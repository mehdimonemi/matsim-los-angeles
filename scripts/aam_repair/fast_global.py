"""Shared DRT runner: eight learning stages plus a fixed ten-iteration tail.

Analytical predicted-score acceptance, explicitly requested by the user.
No candidate simulation probes and no paired validation branches.
Global remains the default; all four analytical swap neighborhoods are supported.
"""
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from scripts.aam.score_optimizer.common import read_sites, atomic_write_layout
from scripts.aam.score_optimizer.experiment import run_stage
from scripts.aam.score_optimizer.optimizer import optimize_population, observed_ground_scores
from scripts.aam.score_optimizer.population import sanitize_population, population_score_metrics
from .stages import dump, freeze_runtime
from .production_manifests import validate
from .reporting import funnel
from .matsim_adapter import set_param
from .neighborhoods import METHODS
from .convergence import assess


def run(manifest, output, simulate=run_stage, optimize=optimize_population,resume_stage_one=None,method="global",resume=False):
    if manifest["service"]!="drt":raise ValueError("This launch is DRT only")
    if method not in METHODS:raise ValueError("Unknown DRT optimizer: "+method)
    output.mkdir(parents=True,exist_ok=resume)
    if resume:
        saved_manifest=output/"manifest.json"
        if not saved_manifest.is_file():raise ValueError("Cannot resume: method manifest is missing")
        m=json.loads(saved_manifest.read_text(encoding="utf-8"))
        for key in ("populationHash","scoringHash","supplyFareHash","initialLayout","searchMethod"):
            expected=method if key=="searchMethod" else manifest.get(key)
            if m.get(key)!=expected:raise ValueError("Cannot resume method with mismatched "+key)
    else:
        m=freeze_runtime(manifest,output)
    learning_iterations=m.get('iterationsPerSearchStage',5)
    tail_iterations=m.get('finalIterations',10)
    m.update(searchMethod=method,executionProtocol=f"8x{learning_iterations}-learning-plus-{tail_iterations}-minimum-tail",
             acceptance="predicted improvement only; no paired MATSim validation",
             candidateProbeSimulations=0,searchStages=8,iterationsPerSearchStage=learning_iterations,finalIterations=tail_iterations,
             totalMatsimIterations=8*learning_iterations+tail_iterations,
             objective="best_feasible_ground_or_AAM_scores_with_losses",
             coefficientPolicy="Analytical full-population score surrogate with observed wait priors; uniform feeder approximation remains a limitation.")
    if not resume:dump(output/"manifest.json",m)
    config=ET.parse(m["baseConfig"]).getroot()
    set_param(config,"global","randomSeed",m.get("seeds",[817])[0])
    effective_config=output/"effective.config.xml"
    effective_config.write_text('<?xml version="1.0"?><!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'+ET.tostring(config,encoding="unicode"),encoding="utf-8")
    sites=read_sites(Path(m["candidateCsv"]));by_id={s["id"]:s for s in sites}
    layout=output/"layout-00.csv"
    layout_id=atomic_write_layout(layout,[by_id[i] for i in m["initialLayout"]])
    args=SimpleNamespace(project_root=Path(m["projectRoot"]),powershell=m["launcherCommand"][0],
        launcher=Path(m["launcherCommand"][5]),config=effective_config,memory=m["launcherCommand"][-1],
        base_fare=m["baseFare"],fare_per_mile=m["farePerMile"],service_start_time=m["serviceStart"],
        service_end_time=m["serviceEnd"],candidate_vertiports=m.get("candidateVertiports",3),classes_directory=Path(m["compiledClassesDirectory"]))
    checkpoint=Path(m.get("routePreparedPopulation",m["population"]));waits=None;history=[]
    if m.get("routePreparedPopulation"):
        if not checkpoint.is_file():raise FileNotFoundError("Shared route-prepared population missing: "+str(checkpoint))
        if m.get("routePreparedPopulationHash") and hashlib.sha256(checkpoint.read_bytes()).hexdigest()!=m["routePreparedPopulationHash"]:
            raise ValueError("Shared route-prepared population fingerprint changed")
    ground_history=observed_ground_scores(checkpoint)
    checkpoint_layout_id=m.get("initialLayoutId")
    completed_search_stages=0
    if resume:
        # Recover only contiguous stages with explicit decision records. Their
        # output population, wait priors, and next layout form the checkpoint.
        for candidate_stage in range(1,9):
            decision_path=output/f"stage-{candidate_stage:02d}-decision.json"
            if not decision_path.is_file():break
            completed_search_stages=candidate_stage
        if completed_search_stages:
            history=[json.loads((output/f"stage-{n:02d}-decision.json").read_text(encoding="utf-8"))
                     for n in range(1,completed_search_stages+1)]
            latest=f"stage-{completed_search_stages:02d}"
            plans=list((output/latest).glob("*.output_plans.xml.gz"))
            if len(plans)!=1:raise ValueError(f"Cannot resume: expected one completed population in {output/latest}")
            checkpoint=plans[0]
            waits=output/(latest+"-inputs")/"wait-priors.csv"
            if not waits.is_file():raise ValueError(f"Cannot resume: wait priors missing for {latest}")
            ground_path=output/(latest+"-ground-score-history.json")
            if ground_path.is_file():ground_history=json.loads(ground_path.read_text(encoding="utf-8"))
            checkpoint_layout_id=history[-1]["layoutId"]
            layout=output/f"layout-{completed_search_stages:02d}.csv"
            if not layout.is_file():raise ValueError(f"Cannot resume: next layout missing after {latest}")
            layout_id=hashlib.sha256(layout.read_bytes()).hexdigest()
            print(f"Resuming {method} after {completed_search_stages} completed search stages; next is stage {completed_search_stages+1:02d}",flush=True)
        elif any((output/f"stage-{n:02d}").exists() for n in range(1,9)):
            raise ValueError("Cannot resume: a stage directory exists without a completed stage decision")
    if resume_stage_one is not None:
        resume_stage_one=Path(resume_stage_one).resolve()
        previous=json.loads((resume_stage_one/"manifest.json").read_text())
        for key in ("populationHash","eligibleIdsHash","scoringHash","supplyFareHash","initialLayout"):
            if previous.get(key)!=m.get(key):raise ValueError("Incomparable stage-one continuation: "+key)
        if (resume_stage_one/"stage-02").exists():raise ValueError("Use only a source stopped after stage one")
    for stage in range(completed_search_stages+1,10):
        final=stage==9;iterations=m.get("finalIterations",10) if final else m.get("iterationsPerSearchStage",5)
        name="final-convergence" if final else f"stage-{stage:02d}"
        directory=output/name
        execution_name=name
        clean=output/(name+"-input.xml.gz")
        reused_final=False
        if resume and (directory.exists() or clean.exists()):
            # The OS may have stopped MATSim or population serialization in
            # the middle of a stage. Retain those artifacts and regenerate
            # the input/checkpoint into a fresh retry namespace.
            retry=1
            while True:
                execution_name=f"{name}-resume-{retry:02d}"
                directory=output/execution_name
                clean=output/(execution_name+"-input.xml.gz")
                if not directory.exists() and not clean.exists() and not Path(str(clean)+".observed-plans.jsonl").exists():break
                retry+=1
        if resume and final:
            # MATSim may have completed this pass before the process stopped
            # during post-processing. Reuse its plans and wait priors.
            candidates=sorted(output.glob(name+"-resume-*"),reverse=True)+[output/name]
            for candidate in candidates:
                plans=list(candidate.glob("*.output_plans.xml.gz"))
                experienced=list(candidate.glob("*.output_experienced_plans.xml.gz"))
                events=list(candidate.glob("*.output_events.xml.gz"))
                candidate_waits=Path(str(candidate)+"-inputs")/"wait-priors.csv"
                if len(plans)==1 and len(experienced)==1 and len(events)==1 and candidate_waits.is_file():
                    directory=candidate;checkpoint=plans[0];waits=candidate_waits
                    elapsed=0
                    provenance=dict(reusedCompletedStage=str(candidate.resolve()))
                    reused_final=True
                    print(f"Reusing completed final convergence output: {candidate.name}",flush=True)
                    break
        if stage==1 and resume_stage_one is not None:
            directory=resume_stage_one/"stage-01"
            matches=list(directory.glob("*.output_plans.xml.gz"))
            if len(matches)!=1 or not list(directory.glob("*.output_experienced_plans.xml.gz")):
                raise ValueError("Completed stage-one output required")
            checkpoint=matches[0];waits=resume_stage_one/"stage-01-inputs/wait-priors.csv"
            if not waits.is_file():raise ValueError("Completed stage-one waiting observations required")
            elapsed=0;provenance=dict(reusedCompletedStage=str(directory),sourceLayoutId=layout_id)
            print("Reusing five completed stage-one iterations; recomputing optimizer with corrected objective",flush=True)
        elif reused_final:
            pass
        else:
            if resume and clean.is_file():
                # A restart can occur after deterministic population cleanup
                # but before MATSim creates its stage directory. Verify the
                # archive sidecar points at the exact checkpoint/layout.
                sidecar=Path(str(clean)+".observed-plans.jsonl")
                if not sidecar.is_file():raise ValueError(f"Cannot resume: missing provenance for prepared input {clean}")
                with sidecar.open(encoding="utf-8") as stream:first=json.loads(stream.readline())
                if first.get("source")!=str(checkpoint.resolve()) or first.get("layoutId")!=layout_id:
                    raise ValueError(f"Cannot resume: prepared input provenance does not match checkpoint/layout: {clean}")
                provenance=dict(reusedInterruptedStageInput=True,sourceCheckpoint=str(checkpoint.resolve()),layoutId=layout_id)
            else:
                provenance=sanitize_population(checkpoint,clean,layout_id,
                    preserve_learning=m.get("preserveLearning",True),previous_layout_id=checkpoint_layout_id)
            print(f"DRT {method}: {name}, {iterations} iterations, innovation={not final}",flush=True)
            checkpoint,waits,elapsed=simulate(args,directory,clean,layout,waits,iterations,False,not final)
        checkpoint_layout_id=layout_id
        record=dict(stage=stage,phase="convergence" if final else "search",matsimIterations=iterations,
                    matsimSeconds=elapsed,layoutId=layout_id,layout=str(layout.resolve()),provenance=provenance,
                    simulationOutput=str(directory.resolve()))
        # Use experienced plans for executed selected counts, output plans for
        # retained alternatives/optimizer coefficients. Never conflate snapshots.
        experienced=list(directory.glob("*.output_experienced_plans.xml.gz"))
        events=list(directory.glob("*.output_events.xml.gz"))
        record["retainedPlanMetrics"]=population_score_metrics(checkpoint)
        if len(experienced)==1 and len(events)==1:
            record["journeyMetrics"],_=funnel(events[0],experienced[0],service="drt",passenger_ids=set(m["eligibleIds"]))
        if not final:
            ground_history.update(observed_ground_scores(checkpoint))
            dump(output/(name+'-ground-score-history.json'),ground_history)
            next_layout=output/f"layout-{stage:02d}.csv"
            prediction=optimize(checkpoint,Path(m["candidateCsv"]),layout,next_layout,method,
                base_fare=m["baseFare"],fare_per_mile=m["farePerMile"],wait_priors=waits,
                maximum_wait_seconds=m["maximumWaitSeconds"],service_start_time=m["serviceStart"],service_end_time=m["serviceEnd"],
                maximum_walk_distance=m["maximumWalkMeters"],maximum_walk_time=m["maximumWalkSeconds"],
                minimum_improvement=m["minimumPredictedImprovement"],ground_score_history=ground_history,
                max_access_distance_miles=m.get("maxAccessDistanceMiles",5),
                max_egress_distance_miles=m.get("maxEgressDistanceMiles",m.get("maxAccessDistanceMiles",5)),
                allow_pre_service_requests=m.get("allowPreServiceRequests",True),
                minimum_trip_miles=m.get("minimumTripDistanceMiles",3),
                routing_candidate_vertiports=m.get("candidateVertiports",3))
            if prediction["accepted"] and prediction["improvement"]<=m["minimumPredictedImprovement"]:
                raise ValueError("Optimizer accepted a sub-threshold gain")
            prediction.update(acceptanceRule=m["acceptance"],observedImprovement=None,
                              optimalityScope=f"analytical current-stage surrogate, {method} evaluated swap neighborhood; not MATSim optimality")
            record["optimization"]=prediction
            layout=next_layout;layout_id=hashlib.sha256(layout.read_bytes()).hexdigest()
        decision_name=(directory.name+"-decision.json"
                       if resume and final and directory.name!=name
                       else name+"-decision.json")
        decision_path=output/decision_name
        if not (resume and final and decision_path.is_file()):
            dump(decision_path,record)
        history.append(record)
    convergence=assess(directory)
    tail_done=tail_iterations
    maximum_tail=m.get('maximumConvergenceIterations',tail_iterations)
    if resume:
        # Convergence extensions commit their own decision after MATSim and
        # metric extraction complete. Reuse those checkpoints after a restart
        # so a later interruption does not repeat already committed iterations.
        while tail_done<maximum_tail:
            name=f'convergence-extension-{tail_done:03d}'
            decision_path=output/(name+'-decision.json')
            if not decision_path.is_file():break
            prior=json.loads(decision_path.read_text(encoding='utf-8'))
            recorded_dir=prior.get('simulationOutput')
            extension_dir=Path(recorded_dir) if recorded_dir else output/name
            plans=list(extension_dir.glob('*.output_plans.xml.gz'))
            extension_waits=Path(str(extension_dir)+'-inputs')/'wait-priors.csv'
            if len(plans)!=1 or not extension_waits.is_file():
                raise ValueError(f'Cannot resume: committed convergence output is incomplete for {name}')
            checkpoint=plans[0];waits=extension_waits
            convergence=prior.get('convergence',assess(extension_dir))
            history.append(prior)
            tail_done+=prior.get('matsimIterations',10)
            directory=extension_dir
    while not convergence['stable'] and tail_done<maximum_tail:
        iterations=min(10,maximum_tail-tail_done)
        name=f'convergence-extension-{tail_done:03d}'
        execution_name=name
        directory=output/execution_name
        clean=output/(execution_name+'-input.xml.gz')
        if resume and (directory.exists() or clean.exists() or Path(str(clean)+'.observed-plans.jsonl').exists()):
            # A previous run may have filled the disk mid-iteration. Keep its
            # partial files for diagnosis and retry under a fresh namespace.
            retry=1
            while True:
                execution_name=f'{name}-resume-{retry:02d}'
                directory=output/execution_name
                clean=output/(execution_name+'-input.xml.gz')
                if (not directory.exists() and not clean.exists()
                        and not Path(str(clean)+'.observed-plans.jsonl').exists()):break
                retry+=1
        provenance=sanitize_population(checkpoint,clean,layout_id,preserve_learning=True,previous_layout_id=layout_id)
        checkpoint,waits,elapsed=simulate(args,directory,clean,layout,waits,iterations,False,False)
        tail_done+=iterations
        record=dict(stage=len(history)+1,phase='convergence',matsimIterations=iterations,matsimSeconds=elapsed,
                    layoutId=layout_id,layout=str(layout.resolve()),provenance=provenance,
                    simulationOutput=str(directory.resolve()),retainedPlanMetrics=population_score_metrics(checkpoint))
        experienced=list(directory.glob('*.output_experienced_plans.xml.gz'));events=list(directory.glob('*.output_events.xml.gz'))
        if len(experienced)==1 and len(events)==1:
            record['journeyMetrics'],_=funnel(events[0],experienced[0],service='drt',passenger_ids=set(m['eligibleIds']))
        convergence=assess(directory);record['convergence']=convergence
        dump(output/(name+'-decision.json'),record);history.append(record)
    result=dict(status='observed_tail_stability' if convergence['stable'] else 'iteration_budget_reached_NOT_converged',searchMethod=method,history=history,
                totalMatsimIterations=sum(r["matsimIterations"] for r in history),finalPlans=str(checkpoint),
                finalLayout=str(layout),globalOptimalityClaim=False,simulationConvergenceClaim=False,
                convergence=convergence,convergenceIterations=tail_done,
                note="Stability is assessed from observed score and demand windows; a budget alone is never a convergence claim.")
    dump(output/"result.json",result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("package",type=Path);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--resume-stage-one",type=Path)
    p.add_argument("--method",choices=METHODS,default="global")
    a=p.parse_args();validate(a.package)
    run(json.loads((a.package/"drt-production-manifest.json").read_text()),a.output,resume_stage_one=a.resume_stage_one,method=a.method)
