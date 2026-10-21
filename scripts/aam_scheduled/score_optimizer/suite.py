#!/usr/bin/env python3
"""Run the four scheduled-AAM vertiport methods as independent experiments."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.aam_repair.matsim_adapter import set_param

METHODS = ("global", "all-vp-k10", "one-vp-k10", "adaptive")


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_route_complete_population(project: Path, output: Path, population: Path,
                                     layout_source: Path, config_source: Path,
                                     powershell: str, launcher: Path, memory: str) -> dict:
    """Route the common ground population once before the four independent methods."""
    config_root = ET.parse(config_source).getroot()
    for param in config_root.findall(".//param"):
        name, value = param.get("name", "").lower(), param.get("value", "")
        if not (name.endswith("file") or name.endswith("filename")) or value in ("", "null") or "://" in value:
            continue
        source_path = Path(value)
        param.set("value", str((source_path if source_path.is_absolute()
                                 else (config_source.parent / source_path).resolve())))
    set_param(config_root, "scheduledAam", "innovationEnabled", "false")
    config = output / "route-preparation.config.xml"
    config.write_text(
        '<?xml version="1.0"?><!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'
        + ET.tostring(config_root, encoding="unicode"), encoding="utf-8")
    layout = output / "route-preparation-layout.csv"
    if not layout.exists():
        shutil.copyfile(layout_source, layout)
    run_name = "route-preparation"
    destination = output / run_name
    suffix = 1
    while destination.exists() or Path(str(destination) + "-inputs").exists():
        run_name = f"route-preparation-resume-{suffix:02d}"
        destination = output / run_name
        suffix += 1
    started = time.perf_counter()
    command = [powershell, "-ExecutionPolicy", "Bypass", "-File", str(launcher),
               "-Memory", memory, "-Config", str(config), "-Output", str(destination),
               "-Plans", str(population), "-Vertiports", str(layout),
               "-RunId", "la-aam-scheduled-route-prep", "-FirstIteration", "0",
               "-LastIteration", "0", "-DisableInnovation", "-InnovationFraction", "0",
               "-SkipCompile"]
    console_log = output / f"{run_name}.console.log"
    print(f"  route-preparation console: {console_log}", flush=True)
    with console_log.open("w", encoding="utf-8") as console:
        subprocess.run(command, cwd=project, check=True, stdout=console, stderr=subprocess.STDOUT)
    routed_matches = list(destination.glob("*.output_plans.xml.gz"))
    if len(routed_matches) != 1:
        raise FileNotFoundError(f"Expected one scheduled route-preparation population in {destination}")
    routed = routed_matches[0]
    elapsed = time.perf_counter() - started
    missing = total = 0
    with gzip.open(routed, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            for leg in person.findall("./plan/leg"):
                total += 1
                if leg.find("route") is None:
                    missing += 1
            person.clear()
    if missing:
        raise ValueError(f"Scheduled route preparation left {missing} of {total} plan legs without routes")
    return dict(population=str(routed.resolve()), populationHash=fingerprint(routed),
                basePopulationHash=fingerprint(population), bootstrapIterations=1,
                routingWallSeconds=time.perf_counter() - started, matsimSeconds=elapsed,
                layoutHash=fingerprint(layout_source), configHash=fingerprint(config_source),
                planLegs=total, unroutedPlanLegs=missing,
                startupDiagnostics=str((destination / "aam-choice-set" / "layout" / "ground-routing.csv").resolve()))


def ensure_route_prepared_population(project: Path, output: Path, population: Path,
                                    layout: Path, config: Path, powershell: str,
                                    launcher: Path, memory: str, resume: bool) -> Path:
    record_path = output / "route-preparation.json"
    if record_path.is_file():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        prepared = Path(record["population"])
        if (record.get("basePopulationHash") != fingerprint(population)
                or record.get("layoutHash") != fingerprint(layout)
                or record.get("configHash") != fingerprint(config)
                or not prepared.is_file() or fingerprint(prepared) != record.get("populationHash")):
            raise ValueError("Scheduled shared route-prepared population is missing or changed")
        return prepared
    if resume and any((output / method).exists() for method in METHODS):
        raise ValueError("Existing scheduled methods lack a shared route-preparation record; start a fresh suite output")
    record = prepare_route_complete_population(project, output, population, layout, config,
                                              powershell, launcher, memory)
    record_path.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return Path(record["population"])


def write_comparison(root: Path) -> None:
    fields = ("method", "totalIterations", "acceptedSwaps", "finalAamUsers", "selectedAamUsers",
              "selectedAamScoreMean", "finalAamScoreSum", "finalAamScoreMean", "qualifyingAamUsers",
              "selectedPlanScoreSum", "selectedPlanScoreMean", "bestPlanScoreSum", "bestPlanScoreMean",
              "potentialNewAamUsersByStage", "optimizerPopulationScoreBaselineByStage",
              "optimizerPredictedImprovementByStage",
              "matsimSeconds", "resumeRerunMatsimSeconds", "optimizerSeconds", "wallSeconds",
              "finalLayout", "finalPlans")
    rows = []
    for method in METHODS:
        result_path = root / method / "result.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            rows.append({field: result.get(field) for field in fields})
    if rows:
        with (root / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(fields))
            writer.writeheader()
            writer.writerows(rows)
        (root / "comparison.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=project / "run-output/aam-scheduled-vertiport-comparison-v11")
    parser.add_argument("--memory", default="18g")
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--initial-layout", type=Path, default=project / "scenarios/aam-scheduled/vertiports.csv")
    parser.add_argument("--population", type=Path, default=project / "run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz")
    parser.add_argument("--config", type=Path, default=project / "scenarios/aam-scheduled/la-aam-scheduled.config.xml")
    parser.add_argument("--skip-compile", action="store_true")
    args = parser.parse_args()
    powershell = shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")
    if not powershell:
        parser.error("PowerShell was not found")
    args.output.mkdir(parents=True, exist_ok=True)
    launcher = project / "scripts/aam-scheduled/run_scheduled_aam.ps1"
    if not args.skip_compile:
        subprocess.run([powershell, "-ExecutionPolicy", "Bypass", "-File", str(launcher),
                        "-Memory", args.memory, "-CompileOnly"], cwd=project, check=True)
    population = ensure_route_prepared_population(
        project, args.output, args.population.resolve(), args.initial_layout.resolve(),
        args.config.resolve(), powershell, launcher, args.memory,
        resume=any((args.output / method).exists() for method in METHODS))
    for method in args.methods:
        destination = args.output / method
        if (destination / "result.json").is_file():
            print(f"Skipping completed method: {method}")
            write_comparison(args.output)
            continue
        if destination.exists():
            print(f"Recovering partial method: {method}")
            resume = ["--resume"]
        else:
            resume = []
        subprocess.run([sys.executable, "-B", "-m", "scripts.aam_scheduled.score_optimizer.experiment",
                        "--method", method, "--output", str(destination), "--memory", args.memory,
                        "--powershell", powershell, "--initial-layout", str(args.initial_layout.resolve()),
                        "--population", str(population), "--config", str(args.config.resolve()),
                        "--skip-compile", *resume], cwd=project, check=True)
        write_comparison(args.output)
    print(f"Comparison written to {args.output / 'comparison.csv'}")


if __name__ == "__main__":
    main()
