#!/usr/bin/env python3
"""Run paired MATSim location epochs, freeze the winner, then converge.

Each outer epoch branches from the same population and wait priors. One branch
keeps the accepted layout; the other replaces one vertiport. The swap is
accepted when the sum of best-AAM-plan scores across all scored AAM users is
higher in the candidate branch. The users need not be paired across branches.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from optimize_vertiports import (atomic_write_layout, optimize, read_sites,
                                  selected_plan_trips)


def routing_mode(leg: ET.Element) -> str | None:
    for attribute in leg.findall("./attributes/attribute"):
        if attribute.get("name") == "routingMode":
            return attribute.text
    return None


def set_routing_mode(leg: ET.Element, mode: str) -> None:
    attributes = leg.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes"); leg.insert(0, attributes)
    attribute = next((a for a in attributes.findall("attribute") if a.get("name") == "routingMode"), None)
    if attribute is None:
        attribute = ET.SubElement(attributes, "attribute", {"name": "routingMode", "class": "java.lang.String"})
    attribute.text = mode


def normalize_ground_routing_modes(elements: list[ET.Element]) -> None:
    legs = [e for e in elements if e.tag == "leg"]
    if not legs:
        return
    substantive = [leg.get("mode") for leg in legs if leg.get("mode") != "walk"]
    existing = [routing_mode(leg) for leg in legs if routing_mode(leg)]
    if "pt" in substantive:
        mode = "pt"
    elif substantive:
        mode = substantive[0]
    elif existing:
        mode = existing[0]
    else:
        mode = "walk"
    for leg in legs:
        set_routing_mode(leg, mode)


def is_aam_segment(elements: list[ET.Element]) -> bool:
    return any(e.tag == "leg" and e.get("mode") in ("aam", "aam_drt")
               for e in elements)


def is_main_activity(element: ET.Element) -> bool:
    return element.tag in ("act", "activity") and "interaction" not in element.get("type", "").lower()


def record_candidate(person, trip_index, origin, destination, segment, reason):
    attributes = person.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes"); person.insert(0, attributes)
    name = f"aam_unresolved_{trip_index}"
    record = next((a for a in attributes if a.get("name") == name), None)
    if record is None:
        record = ET.SubElement(attributes, "attribute", {"name": name, "class": "java.lang.String"})
    departure = origin.get("end_time") or next((e.get("dep_time") for e in segment if e.tag == "leg" and e.get("dep_time")), "unknown")
    record.text = f"person={person.get('id')};trip={trip_index};origin={origin.attrib};destination={destination.attrib};departure={departure};reason={reason}"


def sanitize_population(source: Path, destination: Path) -> dict:
    """Clear scores and collapse old AAM stage chains before a layout restart."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if source.suffix == ".gz" else open
    writer = gzip.open(destination, "wt", encoding="utf-8") if destination.suffix == ".gz" else destination.open("w", encoding="utf-8")
    people = plans = aam_plans = 0
    with opener(source, "rb") as stream, writer as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n<population>\n')
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            people += 1
            for plan in person.findall("plan"):
                plans += 1; plan.attrib.pop("score", None)
                children = list(plan); main = [i for i, e in enumerate(children) if is_main_activity(e)]
                if len(main) < 2:
                    continue
                rebuilt = children[:main[0]+1]; changed = False
                for trip_index, (start, end) in enumerate(zip(main, main[1:])):
                    segment = children[start+1:end]
                    if is_aam_segment(segment):
                        record_candidate(person, trip_index, children[start], children[end], segment, "layout_invalidated")
                        leg = ET.Element("leg", {"mode": "ride"}); set_routing_mode(leg, "ride")
                        rebuilt.append(leg); changed = True
                    else:
                        if any(e.tag == "leg" and routing_mode(e) == "aam" for e in segment) or (plan.get("type") == "aam" and not any(leg.get("mode") in ("aam", "aam_drt") for leg in plan.findall("leg"))):
                            record_candidate(person, trip_index, children[start], children[end], segment, "ground_fallback")
                            mode = next((e.get("mode") for e in segment if e.tag == "leg" and e.get("mode") not in ("walk", "aam")), "ride")
                            segment = [ET.Element("leg", {"mode": mode})]
                        normalize_ground_routing_modes(segment)
                        rebuilt.extend(segment)
                    rebuilt.append(children[end])
                rebuilt.extend(children[main[-1]+1:])
                if changed:
                    aam_plans += 1; plan[:] = rebuilt
                    plan.set("type", "ground")
                else:
                    plan[:] = rebuilt
                    if plan.get("type") == "aam":
                        plan.set("type", "ground")
                if plan.get("type") == "ground":
                    attributes = plan.find("attributes")
                    if attributes is not None:
                        for attribute in list(attributes):
                            if attribute.get("name", "").startswith("aam_"):
                                attributes.remove(attribute)
            out.write(ET.tostring(person, encoding="unicode")); out.write("\n"); person.clear()
        out.write("</population>\n")
    return {"people": people, "plans": plans, "layoutInvalidatedAamPlans": aam_plans}


def best_aam_scores(path: Path) -> dict[str, float]:
    result = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            scores = []
            for plan in person.findall("plan"):
                is_aam = any(leg.get("mode") == "aam_drt" for leg in plan.findall("leg"))
                try:
                    score = float(plan.get("score", "nan"))
                except ValueError:
                    score = math.nan
                if is_aam and math.isfinite(score):
                    scores.append(score)
            if scores:
                result[person.get("id")] = max(scores)
            person.clear()
    return result


def compare_aam_score_sums(baseline: Path, candidate: Path) -> dict:
    base, trial = best_aam_scores(baseline), best_aam_scores(candidate)
    common = sorted(base.keys() & trial.keys())
    deltas = np.asarray([trial[p]-base[p] for p in common], dtype=float)
    baseline_sum = float(sum(base.values()))
    candidate_sum = float(sum(trial.values()))
    baseline_average = float(np.mean(list(base.values()))) if base else None
    candidate_average = float(np.mean(list(trial.values()))) if trial else None
    return {"baselineAamAgents": len(base), "candidateAamAgents": len(trial),
            "totalBestAamScoreBaseline": baseline_sum,
            "totalBestAamScoreCandidate": candidate_sum,
            "totalAamScoreChange": candidate_sum-baseline_sum,
            "averageBestAamScoreBaseline": baseline_average,
            "averageBestAamScoreCandidate": candidate_average,
            "averageAamScoreChange": (candidate_average-baseline_average
                                      if baseline_average is not None and candidate_average is not None else None),
            "pairedAgents": len(common),
            "meanBestAamScoreBaseline": float(np.mean([base[p] for p in common])) if common else None,
            "meanBestAamScoreCandidate": float(np.mean([trial[p] for p in common])) if common else None,
            "meanPairedScoreChange": float(np.mean(deltas)) if common else None,
            "medianPairedScoreChange": float(np.median(deltas)) if common else None,
            "candidateBetterShare": float(np.mean(deltas > 0)) if common else None}


def evaluate_candidate(comparison: dict, minimum_aam_users: int,
                       minimum_total_improvement: float = 0.0,
                       minimum_mean_improvement: float = 0.0,
                       minimum_better_share: float = 0.5) -> dict:
    """Apply five AAM votes after enforcing a minimum valid sample size."""
    criteria = {
        "totalAamScoreImproves": comparison["totalAamScoreChange"] > minimum_total_improvement,
        "averageAamScoreImproves": comparison["averageAamScoreChange"] is not None
                                   and comparison["averageAamScoreChange"] > minimum_mean_improvement,
        "pairedMeanAamScoreImproves": comparison["meanPairedScoreChange"] is not None
                                      and comparison["meanPairedScoreChange"] > minimum_mean_improvement,
        "pairedMajorityImproves": comparison["candidateBetterShare"] is not None
                                  and comparison["candidateBetterShare"] > minimum_better_share,
        "aamUserCountRetained": comparison["candidateAamAgents"] >= comparison["baselineAamAgents"],
    }
    passed = sum(criteria.values())
    sample_valid = min(comparison["baselineAamAgents"], comparison["candidateAamAgents"]) >= minimum_aam_users
    return {"criteria": criteria, "passedCriteria": passed, "requiredCriteria": 3,
            "sampleSizeValid": sample_valid, "accepted": sample_valid and passed >= 3}


def run_stage(args, output: Path, plans: Path, layout: Path, waits: Path | None,
              iterations: int, compile_sources: bool, disable_innovation: bool = False) -> tuple[Path, Path]:
    if output.exists() or Path(str(output)+"-inputs").exists():
        raise FileExistsError(f"stage output already exists: {output}")
    command = [args.powershell, "-ExecutionPolicy", "Bypass", "-File", str(args.launcher),
               "-Memory", args.memory, "-Config", str(args.config), "-Output", str(output),
               "-Plans", str(plans), "-Vertiports", str(layout),
               "-FirstIteration", "0", "-LastIteration", str(iterations-1)]
    if disable_innovation:
        command += ["-DisableInnovation", "-InnovationFraction", "0", "-MinimumConvergence", "1"]
    else:
        command += ["-InnovationFraction", "1", "-MinimumConvergence", "0"]
    if waits is not None:
        command += ["-WaitPriors", str(waits)]
    if not compile_sources:
        command.append("-SkipCompile")
    subprocess.run(command, cwd=args.project_root, check=True)
    output_plans = output/"la-aam-fare0.output_plans.xml.gz"
    output_waits = Path(str(output)+"-inputs")/"wait-priors.csv"
    if not output_plans.is_file() or not output_waits.is_file():
        raise FileNotFoundError(f"stage did not produce plans and wait priors: {output}")
    return output_plans, output_waits


def main() -> None:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=Path, default=project/"run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz")
    parser.add_argument("--initial-wait-priors", type=Path, default=None)
    parser.add_argument("--skip-bootstrap", action="store_true", help="population already contains protected AAM alternatives")
    parser.add_argument("--candidates", type=Path, default=project/"scenarios/aam/vertiport-candidates-100.csv")
    parser.add_argument("--initial-layout", type=Path, default=project/"scenarios/aam/active-vertiports.csv")
    parser.add_argument("--frozen-layout", type=Path, default=project/"scenarios/aam/active-vertiports.csv")
    parser.add_argument("--config", type=Path, default=project/"scenarios/aam/la-aam-fare30-it2.config.xml")
    parser.add_argument("--launcher", type=Path, default=project/"scripts/aam/run_aam_v5.ps1")
    parser.add_argument("--work-dir", type=Path, default=project/"run-output/aam-adaptive-location-search")
    parser.add_argument("--final-output", type=Path, default=project/"run-output/aam-adaptive-final")
    parser.add_argument("--epochs", type=int, default=47)
    parser.add_argument("--bootstrap-iterations", type=int, default=5)
    parser.add_argument("--iterations-per-epoch", type=int, default=5)
    parser.add_argument("--final-iterations", type=int, default=60)
    parser.add_argument("--minimum-aam-users", "--minimum-paired-agents",
                        dest="minimum_aam_users", type=int, default=100,
                        help="minimum number of scored AAM users required in each branch")
    parser.add_argument("--minimum-score-improvement", type=float, default=0.0)
    parser.add_argument("--minimum-mean-score-improvement", type=float, default=0.0)
    parser.add_argument("--minimum-better-share", type=float, default=0.5)
    parser.add_argument("--memory", default="18g")
    parser.add_argument("--powershell", default=None, help="PowerShell executable; auto-detected when omitted")
    parser.add_argument("--access-radius-miles", type=float, default=5.0)
    parser.add_argument("--minimum-trip-miles", type=float, default=3.0)
    parser.add_argument("--fare-per-mile", type=float, default=2.0)
    parser.add_argument("--value-of-time", type=float, default=20.0)
    args = parser.parse_args(); args.project_root = project
    if args.powershell is None:
        args.powershell = shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")
    if args.powershell is None:
        parser.error("PowerShell was not found; pass --powershell with its executable path")
    if args.epochs < 0 or args.bootstrap_iterations < 1 or args.iterations_per_epoch < 1 or args.final_iterations < 1:
        parser.error("epochs must be nonnegative and stage iteration counts positive")
    accepted_path_iterations=(0 if args.skip_bootstrap else args.bootstrap_iterations)+args.epochs*args.iterations_per_epoch+args.final_iterations
    if args.final_iterations/accepted_path_iterations < 0.20:
        parser.error("final-iterations must be at least 20% of the accepted-path iteration budget")
    if args.work_dir.exists() or args.final_output.exists():
        raise FileExistsError("work-dir and final-output must not already exist")
    args.work_dir.mkdir(parents=True)
    candidates = read_sites(args.candidates); active_sites = read_sites(args.initial_layout)
    if len(candidates) != 100 or len(active_sites) != 10:
        raise ValueError("adaptive search requires 100 candidates and 10 active sites")
    current_layout = args.work_dir/"accepted-layout-00.csv"
    atomic_write_layout(current_layout, active_sites)
    if args.skip_bootstrap:
        checkpoint=args.population.resolve();waits=args.initial_wait_priors.resolve() if args.initial_wait_priors else None
        if not checkpoint.is_file() or waits is not None and not waits.is_file():
            raise FileNotFoundError("resume population or initial wait-prior file does not exist")
        compiled=False;audit=[{"stage":"resumed-after-bootstrap","population":str(checkpoint),"waitPriors":str(waits) if waits else None}]
    else:
        # Bootstrap once on the original layout. This seeds the protected AAM
        # plan before any site is moved; typed plans then survive every restart.
        bootstrap_input = args.work_dir/"bootstrap-input.xml.gz"
        bootstrap_sanitized = sanitize_population(args.population.resolve(), bootstrap_input)
        bootstrap_output = args.work_dir/"bootstrap-current-layout"
        print(f"BOOTSTRAP: running {args.bootstrap_iterations} iteration(s) with {current_layout}",flush=True)
        checkpoint, waits = run_stage(args, bootstrap_output, bootstrap_input, current_layout, None,
                                      args.bootstrap_iterations, True)
        compiled = True
        audit = [{"stage": "bootstrap", "iterations": args.bootstrap_iterations,
                  "layout": str(current_layout), "sanitized": bootstrap_sanitized}]
    rejected_layouts=set()
    for epoch in range(1, args.epochs+1):
        stage_input = args.work_dir/f"epoch-{epoch:02d}-input.xml.gz"
        sanitized = sanitize_population(checkpoint, stage_input)
        origins, destinations = selected_plan_trips(stage_input, args.minimum_trip_miles)
        active_ids = [s["id"] for s in read_sites(current_layout)]
        chosen, proxy = optimize(candidates, active_ids, origins, destinations, 1,
                                 args.access_radius_miles, args.fare_per_mile, args.value_of_time,
                                 preserve_protected_origins=False, require_proxy_improvement=False,
                                 forbidden_layouts=rejected_layouts)
        if len(proxy) == 1:
            raise RuntimeError("candidate pool contains no alternative one-site layout")
        proposed_layout = args.work_dir/f"proposed-layout-{epoch:02d}.csv"
        atomic_write_layout(proposed_layout, [candidates[i] for i in chosen])
        print(f"EPOCH {epoch}/{args.epochs}: proposing {proxy[-1]['removed']} -> {proxy[-1]['added']}",flush=True)
        baseline_out = args.work_dir/f"epoch-{epoch:02d}-baseline"
        candidate_out = args.work_dir/f"epoch-{epoch:02d}-candidate"
        print(f"EPOCH {epoch}: baseline MATSim iteration",flush=True)
        baseline_plans, baseline_waits = run_stage(args, baseline_out, stage_input, current_layout, waits,
                                                   args.iterations_per_epoch, not compiled)
        compiled = True
        print(f"EPOCH {epoch}: candidate MATSim iteration with changed vertiport",flush=True)
        candidate_plans, candidate_waits = run_stage(args, candidate_out, stage_input, proposed_layout, waits,
                                                      args.iterations_per_epoch, False)
        comparison = compare_aam_score_sums(baseline_plans, candidate_plans)
        decision = evaluate_candidate(comparison, args.minimum_aam_users, args.minimum_score_improvement,
                                      args.minimum_mean_score_improvement, args.minimum_better_share)
        accepted = decision["accepted"]
        if accepted:
            checkpoint, waits = candidate_plans, candidate_waits
            current_layout = args.work_dir/f"accepted-layout-{epoch:02d}.csv"
            shutil.copy2(proposed_layout, current_layout)
        else:
            checkpoint, waits = baseline_plans, baseline_waits
            rejected_layouts.add(frozenset(site["id"] for site in read_sites(proposed_layout)))
        print(f"EPOCH {epoch}: {'ACCEPTED' if accepted else 'REJECTED'}; votes={decision['passedCriteria']}/5; sampleSizeValid={decision['sampleSizeValid']}; baselineAamUsers={comparison['baselineAamAgents']}; candidateAamUsers={comparison['candidateAamAgents']}; totalAamScoreChange={comparison['totalAamScoreChange']}",flush=True)
        audit.append({"epoch": epoch, "status": "accepted" if accepted else "rejected",
                      "swap": proxy[-1], "comparison": comparison, "decision": decision, "sanitized": sanitized,
                      "acceptedLayout": str(current_layout)})
        (args.work_dir/"adaptive-search.json").write_text(json.dumps(audit, indent=2)+"\n", encoding="utf-8")
    final_input = args.work_dir/"final-convergence-input.xml.gz"
    sanitize_population(checkpoint, final_input)
    print(f"FINAL: locations frozen for {args.final_iterations} innovation-free iterations",flush=True)
    final_plans, final_waits = run_stage(args, args.final_output, final_input, current_layout, waits,
                                         args.final_iterations, not compiled, disable_innovation=True)
    frozen_sites = read_sites(current_layout)
    digest = atomic_write_layout(args.frozen_layout, frozen_sites)
    result = {"acceptedEpochs": sum(a.get("status") == "accepted" for a in audit),
              "locationEpochsEvaluated": sum(a.get("status") in ("accepted", "rejected") for a in audit),
              "frozenLayout": str(args.frozen_layout), "frozenLayoutSha256": digest,
              "finalOutput": str(args.final_output), "finalPlans": str(final_plans),
              "finalWaitPriors": str(final_waits), "innovationFreeFinalIterations": args.final_iterations,
              "bootstrapIterations": 0 if args.skip_bootstrap else args.bootstrap_iterations, "history": audit}
    (args.work_dir/"adaptive-search.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ADAPTIVE LOCATION SEARCH FAILED: {error}", file=sys.stderr)
        raise
