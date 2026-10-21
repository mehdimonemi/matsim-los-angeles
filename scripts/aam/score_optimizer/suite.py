#!/usr/bin/env python3
"""Run and compare all four independent 50-iteration experiments."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

METHODS = ("global", "all-vp-k10", "one-vp-k10", "adaptive")


def write_comparison(root: Path) -> None:
    rows = []
    for method in METHODS:
        path = root / method / "result.json"
        if not path.is_file():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        rows.append({key: result.get(key) for key in
                     ("method", "totalIterations", "acceptedSwaps", "finalAamUsers",
                      "selectedAamUsers", "selectedAamScoreMean", "finalAamScoreSum",
                      "finalAamScoreMean", "qualifyingAamUsers", "selectedPlanScoreSum",
                      "selectedPlanScoreMean", "bestPlanScoreSum", "bestPlanScoreMean",
                      "potentialNewAamUsersByStage", "optimizerPopulationScoreBaselineByStage",
                      "optimizerPredictedImprovementByStage",
                      "matsimSeconds", "optimizerSeconds", "wallSeconds", "finalLayout", "finalPlans")})
    if not rows:
        return
    with (root / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    (root / "comparison.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=project / "run-output/aam-score-optimizer-comparison-v2")
    parser.add_argument("--memory", default="18g")
    parser.add_argument("--powershell", default=None)
    parser.add_argument("--launcher", type=Path, default=project / "scripts/aam/run_aam_v5.ps1")
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--initial-layout", type=Path, default=project / "scenarios/aam/active-vertiports.csv")
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--service-start-time", type=float, default=0.0)
    parser.add_argument("--service-end-time", type=float, default=36 * 3600.0)
    args = parser.parse_args()
    if args.service_end_time < args.service_start_time:
        parser.error("--service-end-time must be >= --service-start-time")
    args.output.mkdir(parents=True, exist_ok=True)
    powershell = args.powershell or shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")
    if powershell is None:
        parser.error("PowerShell was not found; pass --powershell with its executable path")
    # Compile once outside every method's timer so runtime comparisons are fair.
    if not args.skip_compile:
        subprocess.run([powershell, "-ExecutionPolicy", "Bypass", "-File", str(args.launcher),
                        "-Memory", args.memory, "-CompileOnly"], cwd=project, check=True)
    for method in args.methods:
        method_output = args.output / method
        if (method_output / "result.json").is_file():
            print(f"Skipping completed method: {method}")
            write_comparison(args.output)
            continue
        if method_output.exists():
            raise FileExistsError(f"partial output exists for {method}: {method_output}; "
                                  "preserve it for diagnosis and choose a new --output directory")
        command = [sys.executable, "-B", "-m", "scripts.aam.score_optimizer.experiment",
                   "--method", method, "--output", str(method_output), "--memory", args.memory,
                   "--powershell", powershell, "--skip-compile"]
        command += ["--service-start-time", str(args.service_start_time),
                    "--service-end-time", str(args.service_end_time)]
        command += ["--initial-layout", str(args.initial_layout.resolve())]
        subprocess.run(command, cwd=project, check=True)
        write_comparison(args.output)
    print(f"Comparison written to {args.output / 'comparison.csv'}")


if __name__ == "__main__":
    main()
