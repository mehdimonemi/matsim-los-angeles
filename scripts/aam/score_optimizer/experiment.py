#!/usr/bin/env python3
"""Run one independent 50-iteration score-optimizer experiment."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

from .common import atomic_write_layout, read_sites
from .optimizer import optimize_population, read_aam_users
from .population import best_aam_scores, population_score_metrics, sanitize_population

SEARCH_STAGES = 8
ITERATIONS_PER_STAGE = 5
FINAL_ITERATIONS = 10
ROUTED_CANDIDATE_VERTIPORTS = 3


def find_output_plans(output: Path) -> Path:
    matches = list(output.glob("*.output_plans.xml.gz"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one output plans file in {output}, found {len(matches)}")
    return matches[0]


def run_stage(args, output: Path, plans: Path, layout: Path, waits: Path | None,
              iterations: int, compile_sources: bool, innovation: bool) -> tuple[Path, Path, float]:
    if output.exists() or Path(str(output) + "-inputs").exists():
        raise FileExistsError(f"stage output already exists: {output}")
    command = [args.powershell, "-ExecutionPolicy", "Bypass", "-File", str(args.launcher),
               "-Memory", args.memory, "-Config", str(args.config), "-Output", str(output),
               "-Plans", str(plans), "-Vertiports", str(layout),
               "-RunId", f"la-aam-fare{args.base_fare:g}-scoreopt",
               "-FirstIteration", "0", "-LastIteration", str(iterations - 1),
               "-BaseFare", str(args.base_fare), "-FarePerMile", str(args.fare_per_mile),
               "-ServiceStartTime", str(args.service_start_time),
               "-ServiceEndTime", str(args.service_end_time),
               "-CandidateVertiports", str(args.candidate_vertiports)]
    if innovation:
        command += ["-InnovationFraction", "1", "-MinimumConvergence", "0"]
    else:
        command += ["-DisableInnovation", "-InnovationFraction", "0", "-MinimumConvergence", "1"]
    if waits is not None:
        command += ["-WaitPriors", str(waits)]
    if not compile_sources:
        command.append("-SkipCompile")
    if getattr(args,"classes_directory",None):
        command += ["-ClassesDirectory",str(args.classes_directory)]
    # MATSim's console appender is extremely verbose.  Letting Java inherit the
    # Python/PowerShell console can eventually block the whole JVM when the
    # outer terminal stops draining its output.  Keep each stage's console in a
    # regular file; MATSim's own logfile remains in the output directory.
    console_log = output.parent / f"{output.name}.console.log"
    print(f"  console: {console_log}", flush=True)
    started = time.perf_counter()
    with console_log.open("w", encoding="utf-8") as console:
        subprocess.run(command, cwd=args.project_root, check=True,
                       stdout=console, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    output_plans = find_output_plans(output)
    output_waits = Path(str(output) + "-inputs") / "wait-priors.csv"
    if not output_waits.is_file():
        raise FileNotFoundError(f"stage did not produce wait priors: {output_waits}")
    return output_plans, output_waits, elapsed


def final_metrics(population: Path, minimum_trip_miles: float, candidates: Path) -> dict:
    scored = best_aam_scores(population)
    values = list(scored.values())
    try:
        users = read_aam_users(population, read_sites(candidates), minimum_trip_miles)
        qualifying_users, qualifying_sum, qualifying_mean = (
            len(users.ids), float(users.scores.sum()), float(users.scores.mean()))
    except ValueError as error:
        if "no scored AAM users" not in str(error):
            raise
        qualifying_users, qualifying_sum, qualifying_mean = 0, 0.0, None
    return {**population_score_metrics(population),
            "finalAamUsers": len(scored),
            "finalAamScoreSum": float(sum(values)),
            "finalAamScoreMean": float(sum(values) / len(values)) if values else None,
            "qualifyingAamUsers": qualifying_users,
            "qualifyingAamScoreSum": qualifying_sum,
            "qualifyingAamScoreMean": qualifying_mean}


def main() -> None:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=("global", "all-vp-k10", "one-vp-k10", "adaptive"), required=True)
    parser.add_argument("--population", type=Path, default=project / "run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz")
    parser.add_argument("--candidates", type=Path, default=project / "scenarios/aam/vertiport-candidates-100.csv")
    parser.add_argument("--initial-layout", type=Path, default=project / "scenarios/aam/active-vertiports.csv")
    parser.add_argument("--config", type=Path, default=project / "scenarios/aam/la-aam-fare30-it2.config.xml")
    parser.add_argument("--launcher", type=Path, default=project / "scripts/aam/run_aam_v5.ps1")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--memory", default="18g")
    parser.add_argument("--powershell", default=None)
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--base-fare", type=float, default=30.0)
    parser.add_argument("--fare-per-mile", type=float, default=2.0)
    parser.add_argument("--service-start-time", type=float, default=0.0)
    parser.add_argument("--service-end-time", type=float, default=36 * 3600.0)
    parser.add_argument("--expected-wait-seconds", type=float, default=120.0)
    parser.add_argument("--minimum-trip-miles", type=float, default=3.0)
    parser.add_argument("--candidate-vertiports", type=int, default=ROUTED_CANDIDATE_VERTIPORTS)
    parser.add_argument("--wait-bin-seconds", type=float, default=3600.0)
    parser.add_argument("--maximum-wait-seconds", type=float, default=900.0)
    parser.add_argument("--search-stages", type=int, default=SEARCH_STAGES)
    parser.add_argument("--iterations-per-stage", type=int, default=ITERATIONS_PER_STAGE)
    parser.add_argument("--final-iterations", type=int, default=FINAL_ITERATIONS)
    args = parser.parse_args(); args.project_root = project
    if args.service_end_time < args.service_start_time:
        parser.error("--service-end-time must be >= --service-start-time")
    if args.output is None:
        args.output = project / "run-output/aam-score-optimizer-comparison-v2" / args.method
    if args.powershell is None:
        args.powershell = shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")
    if args.powershell is None:
        parser.error("PowerShell was not found; pass --powershell with its executable path")
    total_iterations = args.search_stages * args.iterations_per_stage + args.final_iterations
    if total_iterations != 50:
        parser.error(f"experiment must total exactly 50 iterations; requested {total_iterations}")
    if args.final_iterations < math.ceil(0.20 * total_iterations):
        parser.error("at least 20% of iterations must be innovation-free convergence")
    if args.output.exists():
        raise FileExistsError(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    if len(read_sites(args.candidates)) != 100 or len(read_sites(args.initial_layout)) != 10:
        raise ValueError("experiment requires 100 candidates and 10 initial active vertiports")
    if args.candidate_vertiports != ROUTED_CANDIDATE_VERTIPORTS:
        parser.error("this comparison is calibrated for three routing candidates per trip")

    started = time.perf_counter()
    current_layout = args.output / "layout-00.csv"
    atomic_write_layout(current_layout, read_sites(args.initial_layout))
    initial_input = args.output / "stage-01-input.xml.gz"
    initial_sanitize = sanitize_population(args.population.resolve(), initial_input)
    checkpoint, waits = initial_input, None
    stage_runtime = optimizer_runtime = 0.0
    history = [{"stage": "initialization", "sanitization": initial_sanitize,
                "layout": str(current_layout)}]

    for stage in range(1, args.search_stages + 1):
        stage_output = args.output / f"stage-{stage:02d}"
        print(f"{args.method}: MATSim search stage {stage}/{args.search_stages} "
              f"({args.iterations_per_stage} iterations)", flush=True)
        checkpoint, waits, elapsed = run_stage(
            args, stage_output, checkpoint, current_layout, waits,
            args.iterations_per_stage, compile_sources=(stage == 1 and not args.skip_compile), innovation=True)
        stage_runtime += elapsed
        next_layout = args.output / f"layout-{stage:02d}.csv"
        try:
            report = optimize_population(
                checkpoint, args.candidates, current_layout, next_layout, args.method,
                base_fare=args.base_fare, fare_per_mile=args.fare_per_mile,
                expected_wait_seconds=args.expected_wait_seconds,
                minimum_trip_miles=args.minimum_trip_miles, wait_priors=waits,
                wait_bin_seconds=args.wait_bin_seconds,
                maximum_wait_seconds=args.maximum_wait_seconds,
                routing_candidate_vertiports=args.candidate_vertiports,
                service_start_time=args.service_start_time,
                service_end_time=args.service_end_time)
        except ValueError as error:
            if "no scored AAM users" not in str(error):
                raise
            atomic_write_layout(next_layout, read_sites(current_layout))
            report = {"method": args.method, "objective": "sum of predicted MATSim AAM plan scores",
                      "currentAamUsers": 0, "movesEvaluated": 0, "accepted": False,
                      "improvement": 0.0, "optimizerSeconds": 0.0,
                      "reason": "no scored AAM users in this stage", "before": [], "after": []}
        optimizer_runtime += report["optimizerSeconds"]
        next_input = args.output / f"stage-{stage + 1:02d}-input.xml.gz"
        sanitization = sanitize_population(checkpoint, next_input)
        history.append({"stage": stage, "matsimIterations": args.iterations_per_stage,
                        "matsimSeconds": elapsed, "optimization": report,
                        "sanitization": sanitization})
        current_layout, checkpoint = next_layout, next_input

    final_output = args.output / "final-convergence"
    print(f"{args.method}: final fixed-layout convergence ({args.final_iterations} iterations)", flush=True)
    final_plans, final_waits, elapsed = run_stage(
        args, final_output, checkpoint, current_layout, waits,
        args.final_iterations, compile_sources=False, innovation=False)
    stage_runtime += elapsed
    metrics = final_metrics(final_plans, args.minimum_trip_miles, args.candidates)
    result = {"method": args.method, "totalIterations": total_iterations,
              "searchIterations": args.search_stages * args.iterations_per_stage,
              "finalInnovationFreeIterations": args.final_iterations,
              "baseFare": args.base_fare, "farePerMile": args.fare_per_mile,
              "serviceStartTime": args.service_start_time, "serviceEndTime": args.service_end_time,
              "routedCandidateVertiports": args.candidate_vertiports,
              "siteSeparationConstraint": False, "minimumTripMiles": args.minimum_trip_miles,
              "initialLayout": str(args.initial_layout.resolve()), "finalLayout": str(current_layout.resolve()),
              "finalPlans": str(final_plans.resolve()), "finalWaitPriors": str(final_waits.resolve()),
              "matsimSeconds": stage_runtime, "optimizerSeconds": optimizer_runtime,
              "wallSeconds": time.perf_counter() - started,
              "acceptedSwaps": sum(1 for row in history[1:] if row["optimization"]["accepted"]),
              "potentialNewAamUsersByStage": [row["optimization"].get("potentialNewAamUsers", 0) for row in history],
              "optimizerPopulationScoreBaselineByStage": [row["optimization"].get("currentPopulationScoreSum") for row in history],
              "optimizerPredictedImprovementByStage": [row["optimization"].get("improvement", 0.0) for row in history],
              **metrics, "history": history}
    result_path = args.output / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("method", "totalIterations", "acceptedSwaps", "finalAamUsers",
                       "selectedAamUsers", "selectedPlanScoreMean", "finalAamScoreMean",
                       "matsimSeconds", "optimizerSeconds", "wallSeconds")}, indent=2))


if __name__ == "__main__":
    main()
