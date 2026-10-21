#!/usr/bin/env python3
"""Run one independent 50-iteration scheduled-AAM vertiport experiment."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.aam.score_optimizer.common import atomic_write_layout, read_sites
from .optimizer import MINIMUM_TRIP_METERS, optimize_population, read_aam_users
from .population import best_aam_scores, population_score_metrics, sanitize_population

SEARCH_STAGES = 8
ITERATIONS_PER_STAGE = 5
FINAL_ITERATIONS = 10


def find_output_plans(output: Path) -> Path:
    matches = list(output.glob("*.output_plans.xml.gz"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one output plans file in {output}, found {len(matches)}")
    return matches[0]


def complete_output_plans(output: Path) -> Path | None:
    """Return a resumable output only when its compressed population XML is intact."""
    try:
        plans = find_output_plans(output)
        with gzip.open(plans, "rb") as stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if element.tag == "person":
                    element.clear()
        return plans
    except (FileNotFoundError, OSError, EOFError, ValueError, ET.ParseError):
        return None


def run_stage(args, output: Path, plans: Path, layout: Path, iterations: int,
              compile_sources: bool, innovation: bool) -> tuple[Path, float]:
    if output.exists() or Path(str(output) + "-inputs").exists():
        raise FileExistsError(f"stage output already exists: {output}")
    command = [args.powershell, "-ExecutionPolicy", "Bypass", "-File", str(args.launcher),
               "-Memory", args.memory, "-Config", str(args.config), "-Output", str(output),
               "-Plans", str(plans), "-Vertiports", str(layout),
               "-RunId", "la-aam-scheduled-scoreopt", "-FirstIteration", "0",
               "-LastIteration", str(iterations - 1)]
    command += (["-InnovationFraction", "1"] if innovation else
                ["-DisableInnovation", "-InnovationFraction", "0"])
    if not compile_sources:
        command.append("-SkipCompile")
    console_log = output.parent / f"{output.name}.console.log"
    print(f"  console: {console_log}", flush=True)
    started = time.perf_counter()
    with console_log.open("w", encoding="utf-8") as console:
        subprocess.run(command, cwd=args.project_root, check=True, stdout=console, stderr=subprocess.STDOUT)
    return find_output_plans(output), time.perf_counter() - started


def final_metrics(population: Path, minimum_trip_meters: float, candidates: Path) -> dict:
    scores = best_aam_scores(population)
    try:
        users = read_aam_users(population, read_sites(candidates), minimum_trip_meters)
        qualifying = {"qualifyingAamUsers": len(users.ids), "qualifyingAamScoreSum": float(users.scores.sum()),
                      "qualifyingAamScoreMean": float(users.scores.mean())}
    except ValueError as error:
        if "no scored scheduled-AAM users" not in str(error):
            raise
        qualifying = {"qualifyingAamUsers": 0, "qualifyingAamScoreSum": 0.0, "qualifyingAamScoreMean": None}
    values = list(scores.values())
    return {**population_score_metrics(population), "finalAamUsers": len(values),
            "finalAamScoreSum": float(sum(values)),
            "finalAamScoreMean": float(sum(values) / len(values)) if values else None, **qualifying}


def resume_completed_search(args, total: int) -> None:
    """Resume from completed stage outputs; retry partial stages in new folders."""
    run_manifest_path = args.output / "run-manifest.json"
    if not run_manifest_path.is_file():
        raise ValueError("Cannot safely resume this scheduled run: run-manifest.json is missing")
    saved = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    expected = {"method": args.method, "populationHash": _fingerprint(args.population),
                "initialLayoutHash": _fingerprint(args.initial_layout),
                "configHash": _fingerprint(args.config)}
    if any(saved.get(key) != value for key, value in expected.items()):
        raise ValueError("Cannot resume scheduled run with changed population, layout, config, or method")

    layout = args.output / "layout-00.csv"
    if not layout.is_file():
        raise ValueError("Cannot resume scheduled run: layout-00.csv is missing")
    history, optimizer_seconds, rerun_matsim_seconds = [], 0.0, 0.0
    reused_stage = False
    previous_plans = None
    for stage in range(1, args.search_stages + 1):
        stage_name = f"stage-{stage:02d}"
        base_output = args.output / stage_name
        scored = None
        prior_outputs = [base_output] + sorted(args.output.glob(stage_name + "-resume-*"), reverse=True)
        for candidate_output in prior_outputs:
            if not candidate_output.is_dir():
                continue
            try:
                scored = complete_output_plans(candidate_output)
                if scored is None:
                    continue
                base_output = candidate_output
                break
            except FileNotFoundError:
                continue
        if scored is None:
            source = args.population if stage == 1 else previous_plans
            if source is None:
                raise ValueError(f"Cannot resume before {stage_name}: prior stage plans are missing")
            checkpoint = _fresh_path(args.output, f"{stage_name}-resume-input.xml.gz")
            sanitization = sanitize_population(source, checkpoint)
            output = base_output
            retry = 1
            while output.exists() or Path(str(output) + "-inputs").exists():
                output = args.output / f"{stage_name}-resume-{retry:02d}"
                retry += 1
            print(f"Resuming scheduled {args.method} at {stage_name} in {output.name}", flush=True)
            scored, elapsed = run_stage(args, output, checkpoint, layout, args.iterations_per_stage,
                                        False, True)
            rerun_matsim_seconds += elapsed
        else:
            elapsed = None
            sanitization = {"recoveredCheckpoint": True}
            reused_stage = True

        next_layout = args.output / f"layout-{stage:02d}.csv"
        report_path = next_layout.with_suffix(next_layout.suffix + ".optimization.json")
        if report_path.is_file() and next_layout.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            report = optimize_population(scored, args.candidates, layout, next_layout, args.method,
                                         args.minimum_trip_meters)
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        optimizer_seconds += report.get("optimizerSeconds", 0.0)
        history.append({"stage": stage, "matsimIterations": args.iterations_per_stage,
                        "matsimSeconds": elapsed, "optimization": report,
                        "sanitization": sanitization})
        previous_plans = scored
        layout = next_layout

    final_layout = args.output / f"layout-{args.search_stages:02d}.csv"
    if previous_plans is None:
        raise ValueError("No completed scheduled search stage was available for convergence")
    checkpoint = _fresh_path(args.output, "final-resume-input.xml.gz")
    sanitize_population(previous_plans, checkpoint)
    final_output = args.output / "final-convergence"
    final_plans = None
    for candidate_output in [final_output] + sorted(args.output.glob("final-convergence-resume-*"), reverse=True):
        if candidate_output.is_dir():
            try:
                final_plans = complete_output_plans(candidate_output)
                if final_plans is None:
                    continue
                final_output = candidate_output
                break
            except FileNotFoundError:
                pass
    if final_plans is None:
        suffix = 1
        while final_output.exists() or Path(str(final_output) + "-inputs").exists():
            final_output = args.output / f"final-convergence-resume-{suffix:02d}"
            suffix += 1
        final_plans, final_elapsed = run_stage(args, final_output, checkpoint, final_layout,
                                               args.final_iterations, False, False)
        rerun_matsim_seconds += final_elapsed
    else:
        final_elapsed = None
        reused_stage = True
    result = {"method": args.method, "model": "fixed-timetable scheduled AAM",
              "totalIterations": total, "searchIterations": args.search_stages * args.iterations_per_stage,
              "finalInnovationFreeIterations": args.final_iterations,
              "initialLayout": str(args.initial_layout.resolve()),
              "finalLayout": str(final_layout.resolve()), "finalPlans": str(final_plans.resolve()),
              "matsimSeconds": None if reused_stage else rerun_matsim_seconds,
              "resumeRerunMatsimSeconds": rerun_matsim_seconds,
              "optimizerSeconds": optimizer_seconds,
              "wallSeconds": None, "recoveredRun": True, "resumeFinalConvergenceSeconds": final_elapsed,
              "acceptedSwaps": sum(1 for item in history if item["optimization"].get("accepted")),
              "history": history, **final_metrics(final_plans, args.minimum_trip_meters, args.candidates)}
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("method", "acceptedSwaps", "finalAamUsers",
                                                    "selectedAamUsers", "recoveredRun")}, indent=2))


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fresh_path(root: Path, name: str) -> Path:
    path = root / name
    if not path.exists() and not Path(str(path) + ".observed-plans.jsonl").exists():
        return path
    stem, suffix = Path(name).stem, Path(name).suffix
    index = 1
    while True:
        candidate = root / f"{stem}-resume-{index:02d}{suffix}"
        if not candidate.exists() and not Path(str(candidate) + ".observed-plans.jsonl").exists():
            return candidate
        index += 1


def main() -> None:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=("global", "all-vp-k10", "one-vp-k10", "adaptive"), required=True)
    parser.add_argument("--population", type=Path, default=project / "run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz")
    parser.add_argument("--candidates", type=Path, default=project / "scenarios/aam/vertiport-candidates-100.csv")
    parser.add_argument("--initial-layout", type=Path, default=project / "scenarios/aam-scheduled/vertiports.csv")
    parser.add_argument("--config", type=Path, default=project / "scenarios/aam-scheduled/la-aam-scheduled.config.xml")
    parser.add_argument("--launcher", type=Path, default=project / "scripts/aam-scheduled/run_scheduled_aam.ps1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--memory", default="18g")
    parser.add_argument("--powershell")
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="reuse eight completed search stages and finish convergence")
    parser.add_argument("--minimum-trip-meters", type=float, default=MINIMUM_TRIP_METERS)
    parser.add_argument("--search-stages", type=int, default=SEARCH_STAGES)
    parser.add_argument("--iterations-per-stage", type=int, default=ITERATIONS_PER_STAGE)
    parser.add_argument("--final-iterations", type=int, default=FINAL_ITERATIONS)
    args = parser.parse_args()
    args.project_root = project
    args.output = args.output or project / "run-output/aam-scheduled-vertiport-comparison-v10" / args.method
    args.powershell = args.powershell or shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")
    if not args.powershell:
        parser.error("PowerShell was not found; pass --powershell")
    total = args.search_stages * args.iterations_per_stage + args.final_iterations
    if total != 50:
        parser.error(f"experiment must total exactly 50 iterations; requested {total}")
    if args.final_iterations < math.ceil(0.20 * total):
        parser.error("at least 20% of iterations must be fixed-layout, innovation-free convergence")
    if args.output.exists():
        if not args.resume:
            raise FileExistsError(f"output already exists: {args.output}")
        resume_completed_search(args, total)
        return
    if len(read_sites(args.candidates)) != 100 or len(read_sites(args.initial_layout)) != 10:
        raise ValueError("experiment requires 100 candidates and 10 initial active vertiports")
    args.output.mkdir(parents=True)

    run_manifest = {"method": args.method, "population": str(args.population.resolve()),
                    "populationHash": _fingerprint(args.population),
                    "initialLayout": str(args.initial_layout.resolve()),
                    "initialLayoutHash": _fingerprint(args.initial_layout),
                    "config": str(args.config.resolve()), "configHash": _fingerprint(args.config),
                    "searchStages": args.search_stages,
                    "iterationsPerStage": args.iterations_per_stage,
                    "finalIterations": args.final_iterations}
    (args.output / "run-manifest.json").write_text(json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8")

    started = time.perf_counter()
    layout = args.output / "layout-00.csv"
    atomic_write_layout(layout, read_sites(args.initial_layout))
    checkpoint = args.output / "stage-01-input.xml.gz"
    initialization = sanitize_population(args.population.resolve(), checkpoint)
    history, matsim_seconds, optimizer_seconds = [], 0.0, 0.0
    for stage in range(1, args.search_stages + 1):
        print(f"{args.method}: scheduled-AAM stage {stage}/{args.search_stages}", flush=True)
        output = args.output / f"stage-{stage:02d}"
        scored, elapsed = run_stage(args, output, checkpoint, layout, args.iterations_per_stage,
                                    compile_sources=(stage == 1 and not args.skip_compile), innovation=True)
        matsim_seconds += elapsed
        next_layout = args.output / f"layout-{stage:02d}.csv"
        try:
            report = optimize_population(scored, args.candidates, layout, next_layout, args.method,
                                         args.minimum_trip_meters)
        except ValueError as error:
            if "no scored scheduled-AAM users" not in str(error):
                raise
            atomic_write_layout(next_layout, read_sites(layout))
            report = {"method": args.method, "accepted": False, "movesEvaluated": 0,
                      "improvement": 0.0, "optimizerSeconds": 0.0, "reason": str(error)}
        optimizer_seconds += report["optimizerSeconds"]
        next_checkpoint = args.output / f"stage-{stage + 1:02d}-input.xml.gz"
        sanitization = sanitize_population(scored, next_checkpoint)
        history.append({"stage": stage, "matsimIterations": args.iterations_per_stage,
                        "matsimSeconds": elapsed, "optimization": report, "sanitization": sanitization})
        layout, checkpoint = next_layout, next_checkpoint

    final_output = args.output / "final-convergence"
    final_plans, elapsed = run_stage(args, final_output, checkpoint, layout, args.final_iterations,
                                     compile_sources=False, innovation=False)
    matsim_seconds += elapsed
    result = {"method": args.method, "model": "fixed-timetable scheduled AAM", "totalIterations": total,
              "searchIterations": args.search_stages * args.iterations_per_stage,
              "finalInnovationFreeIterations": args.final_iterations,
              "initialLayout": str(args.initial_layout.resolve()), "finalLayout": str(layout.resolve()),
              "finalPlans": str(final_plans.resolve()), "matsimSeconds": matsim_seconds,
              "optimizerSeconds": optimizer_seconds, "wallSeconds": time.perf_counter() - started,
              "acceptedSwaps": sum(1 for item in history if item["optimization"]["accepted"]),
              "potentialNewAamUsersByStage": [item["optimization"].get("potentialNewAamUsers", 0) for item in history],
              "optimizerPopulationScoreBaselineByStage": [item["optimization"].get("currentPopulationScoreSum") for item in history],
              "optimizerPredictedImprovementByStage": [item["optimization"].get("improvement", 0.0) for item in history],
              "initialSanitization": initialization, "history": history,
              **final_metrics(final_plans, args.minimum_trip_meters, args.candidates)}
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("method", "acceptedSwaps", "finalAamUsers",
                                                    "selectedAamUsers", "matsimSeconds", "optimizerSeconds")}, indent=2))


if __name__ == "__main__":
    main()
