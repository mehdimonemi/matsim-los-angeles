"""Opt-in stage protocol: estimate -> solve -> paired MATSim validation -> accept.

Evaluator/estimator commands are explicit adapters, not hidden proxy optimizers.
They receive a JSON request path and an output path as final command arguments.
The evaluator must actually run MATSim and return all eligible persons' scores.
This module never launches the regional model without --allow-large-population.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import shutil
import time
from .stage_model import Alternative, solve, paired_acceptance
from .neighborhoods import optimize


def dump(path, value):
    with path.open("x",encoding="utf-8") as f:json.dump(value,f,indent=2,allow_nan=False)


def freeze_runtime(manifest, output):
    """One immutable build per experiment; trials take private copies of it."""
    m=dict(manifest)
    if "projectRoot" in m and "service" in m:
        original=Path(m.get("compiledClassesDirectory",Path(m["projectRoot"])/"target"/
                           ("aam-scheduled-classes" if m["service"]=="scheduled" else "aam-v5-classes")))
        destination=output/"runtime-classes"
        shutil.copytree(original,destination)
        if not (destination/"org/matsim/run/aam/AamFeederPolicy.class").is_file():raise ValueError("Compile complete runtime before starting experiment")
        m["compiledClassesDirectory"]=str(destination.resolve())
    return m


def adapter(command, request, directory, name):
    request_file=directory/(name+"-request.json");output=directory/(name+"-result.json")
    dump(request_file,request)
    with (directory/(name+".log")).open("x",encoding="utf-8") as log:
        subprocess.run([*command,str(request_file.resolve()),str(output.resolve())],check=True,stdout=log,stderr=subprocess.STDOUT)
    return json.loads(output.read_text(encoding="utf-8"))


def alternatives_from_estimate(estimate, manifest, stage):
    for key in ("populationHash","scoringHash","supplyFareHash","eligibleIdsHash"):
        if estimate.get(key)!=manifest[key]:raise ValueError("Estimate mismatch: "+key)
    if estimate.get("stage")!=stage:raise ValueError("Stale coefficients from a different stage")
    if set(estimate["eligibleIds"])!=set(manifest["eligibleIds"]):raise ValueError("Eligible population changed")
    result=[]
    for row in estimate["alternatives"]:
        sites=frozenset(row["sites"])
        if row["person"] not in manifest["eligibleIds"]:raise ValueError("Unexpected traveler")
        if sites:
            required=("feederModes","accessWalkMeters","egressWalkMeters","accessWalkSeconds","egressWalkSeconds",
                      "serviceFeasible","continuityFeasible","expectedWaitSeconds","rejectionProbability",
                      "successScore","rejectionScore","fare","flightMeters","capacityEvidence","routeEvidence")
            if any(k not in row for k in required):raise ValueError("Incomplete routed/service/scoring evidence for AAM coefficient")
            if not row["capacityEvidence"] or not row["routeEvidence"]:raise ValueError("Missing route/capacity provenance")
            if not set(row["feederModes"])<=set(manifest["feederModes"]):raise ValueError("Unavailable feeder mode in optimizer")
            if not 0<=row["rejectionProbability"]<=1:raise ValueError("Invalid rejection probability")
            expected_fare=manifest["baseFare"]*row.get("flightCount",1)+manifest["farePerMile"]*row["flightMeters"]/1609.344
            if not math.isclose(row["fare"],expected_fare,abs_tol=1e-6):raise ValueError("Optimizer/simulation fare mismatch")
            feasible=(row["serviceFeasible"] and row["continuityFeasible"]
                      and all(0<=row[k]<=manifest["maximumWalkMeters"] for k in ("accessWalkMeters","egressWalkMeters"))
                      and all(0<=row[k]<=manifest["maximumWalkSeconds"] for k in ("accessWalkSeconds","egressWalkSeconds"))
                      and 0<=row["expectedWaitSeconds"]<=manifest["maximumWaitSeconds"])
            score=(row["score"] if row.get("scoreKind")=="observedPlanMean" else
                   (1-row["rejectionProbability"])*row["successScore"]+row["rejectionProbability"]*row["rejectionScore"])
        else:feasible=True;score=row["score"]
        result.append(Alternative(row["person"],sites,score,feasible,row["planId"]))
    if {r.person for r in result}!=set(manifest["eligibleIds"]):raise ValueError("Missing eligible travelers")
    return result


def simulation_stable(runs, tolerance, window=3):
    for r in runs:
        series=r.get("populationObjectiveByIteration",[])
        if len(series)<window or not r.get("allCompetingPlansRescored",False):return False
        tail=series[-window:]
        if any(not math.isfinite(v) for v in tail) or max(tail)-min(tail)>tolerance:return False
    return True


def run(manifest, output, evaluate=adapter, estimate_adapter=adapter, allow_large_population=False):
    if len(manifest["eligibleIds"])>100 and not allow_large_population:
        raise ValueError("Large-population execution disabled; small reproducible validation only")
    if len(manifest["seeds"])<5 or len(set(manifest["seeds"]))!=len(manifest["seeds"]):raise ValueError("Need >=5 distinct paired seeds")
    output.mkdir(parents=True,exist_ok=False);manifest=freeze_runtime(manifest,output);dump(output/"manifest.json",manifest)
    incumbent=list(manifest["initialLayout"]);checkpoint=manifest["population"];checkpoint_layout_id=manifest.get("initialLayoutId");history=[];observations=[];stable_stages=0
    status="safety_budget_reached_NOT_converged"
    for stage in range(manifest["maximumStages"]):
        directory=output/f"stage-{stage:03d}";directory.mkdir()
        estimation_started=time.monotonic()
        estimates=estimate_adapter(manifest["estimatorCommand"],{
            "manifest":manifest,"stage":stage,"incumbent":incumbent,"checkpoint":checkpoint,"checkpointLayoutId":checkpoint_layout_id,
            "observations":observations,"includeRejectedProposals":True},directory,"estimates")
        rows=alternatives_from_estimate(estimates,manifest,stage)
        estimation_seconds=time.monotonic()-estimation_started
        objective_name=manifest.get("objective","eligible_population_with_ground")
        if objective_name not in ("eligible_population_with_ground","legacy_current_aam_users"):raise ValueError("Unknown objective")
        optimization_started=time.monotonic()
        prediction=optimize(rows,manifest,incumbent,
                            set(estimates["legacyCurrentUsers"]) if objective_name=="legacy_current_aam_users" else None)
        optimization_seconds=time.monotonic()-optimization_started
        validation_started=time.monotonic()
        proposal=prediction["proposal"]
        old_runs=[];new_runs=[]
        for seed in manifest["seeds"]:
            common={"manifest":manifest,"stage":stage,"seed":seed,
                    "checkpoint":checkpoint,"checkpointLayoutId":checkpoint_layout_id,"preserveAlternatives":True,
                    "rerouteAndRescoreModifiedPlans":True}
            old=evaluate(manifest["evaluatorCommand"],{**common,"layout":incumbent},directory,f"incumbent-{seed}")
            if old.get("engine")!="MATSim":raise ValueError("Layout validation must be MATSim, not a proxy")
            old_runs.append(old)
            if proposal!=incumbent:
                new=evaluate(manifest["evaluatorCommand"],{**common,"layout":proposal},directory,f"proposal-{seed}")
                if new.get("engine")!="MATSim":raise ValueError("Layout validation must be MATSim")
                new_runs.append(new)
        if new_runs:
            decision=paired_acceptance(old_runs,new_runs,manifest["minimumObservedImprovement"],manifest.get("criticalValue",2.776))
            if not all(r.get("allCompetingPlansRescored",False) for r in old_runs+new_runs):
                decision.update(accepted=False,reason="Unscored competing alternatives; extend small evaluation before accepting")
            # Update estimation data even on rejection. Never advance checkpoint/layout on failed validation.
            observations.extend([{"layout":incumbent,"runs":old_runs},
                                 {"layout":proposal,"runs":new_runs,"proposalRejected":not decision["accepted"],
                                  "pairedDifferences":decision["pairedDifferences"]}])
            if decision["accepted"]:incumbent=proposal
            checkpoint=(new_runs if decision["accepted"] else old_runs)[0]["checkpoint"]
            checkpoint_layout_id=(new_runs if decision["accepted"] else old_runs)[0].get("layoutId")
        else:
            decision={"accepted":False,"realizedImprovement":0,"reason":"no qualifying predicted improvement"}
            observations.append({"layout":incumbent,"runs":old_runs})
            checkpoint=old_runs[0]["checkpoint"]
            checkpoint_layout_id=old_runs[0].get("layoutId")
        converged=(not prediction["proposeChange"] and prediction["status"]=="optimal" and estimates.get("coefficientCoverageComplete",False)
                   and simulation_stable(old_runs,manifest["simulationTolerance"]))
        stable_stages=stable_stages+1 if converged else 0
        record={"stage":stage,"optimization":prediction,"validation":decision,
                "estimationSeconds":estimation_seconds,"optimizationSeconds":optimization_seconds,
                "validationSeconds":time.monotonic()-validation_started,
                "acceptedLayout":incumbent,"simulationStable":simulation_stable(old_runs,manifest["simulationTolerance"])}
        dump(directory/"estimation-feedback.json",{"nextCheckpoint":checkpoint,"nextCheckpointLayoutId":checkpoint_layout_id,
                                                "observations":observations})
        dump(directory/"decision.json",record);history.append(record)
        # A single no-improvement stage is insufficient: fresh scores and
        # queues can change the next estimate. Stop once the configured number
        # of consecutive fully covered, solved, stable stages has been met.
        if stable_stages>=manifest.get("stableStages",2):
            status="stage_model_and_simulation_converged"
            break
    result={"status":status,"acceptedLayout":incumbent,"history":history,
            "searchMethod":manifest.get("searchMethod","global"),
            "convergenceScope":"observed plan catalog, configured coefficient coverage, selected search neighborhood and simulation stability",
            "globalOptimalityClaim":False}
    dump(output/"result.json",result);return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("manifest",type=Path);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--allow-large-population",action="store_true")
    a=p.parse_args();run(json.loads(a.manifest.read_text()),a.output,allow_large_population=a.allow_large_population)
