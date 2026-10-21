#!/usr/bin/env python3
"""Greedy one-swap optimizer for a frozen AAM vertiport layout.

This is deliberately outside MATSim's final run.  It evaluates demand geometry
with a deterministic generalized-cost proxy, accepts only improving swaps, and
atomically writes the selected layout plus an audit JSON file.  The final Java
runner consumes the resulting CSV without changing sites between iterations.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

MILE = 1609.344


def read_sites(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    required = {"id", "x", "y"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{path} must have columns id,name,x,y")
    seen = set()
    result = []
    for row in rows:
        site_id = row["id"].strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", site_id) or site_id in seen:
            raise ValueError(f"invalid or duplicate candidate id: {site_id!r}")
        seen.add(site_id)
        name = row.get("name", site_id).strip() or site_id
        if "," in name:
            raise ValueError(f"candidate name may not contain a comma: {name!r}")
        x, y = float(row["x"]), float(row["y"])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"non-finite coordinates for {site_id}")
        result.append({"id": site_id, "name": name, "x": x, "y": y})
    return result


def selected_plan_trips(population: Path, minimum_trip_miles: float) -> tuple[np.ndarray, np.ndarray]:
    opener = gzip.open if population.suffix == ".gz" else open
    origins, destinations = [], []
    with opener(population, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag.rsplit("}", 1)[-1] != "person":
                continue
            plans = [e for e in person if e.tag.rsplit("}", 1)[-1] == "plan"]
            subpopulation = next((e.text for e in person.iter()
                                  if e.tag.rsplit("}", 1)[-1] == "attribute"
                                  and e.attrib.get("name") == "subpopulation"), "person")
            if subpopulation != "person":
                person.clear(); continue
            plan = next((p for p in plans if p.attrib.get("selected") == "yes"), plans[0] if plans else None)
            if plan is not None:
                activities = []
                for e in plan:
                    if e.tag.rsplit("}", 1)[-1] not in ("act", "activity") or "interaction" in e.attrib.get("type", "").lower():
                        continue
                    if "x" in e.attrib and "y" in e.attrib:
                        activities.append((float(e.attrib["x"]), float(e.attrib["y"])))
                for origin, destination in zip(activities, activities[1:]):
                    if math.hypot(destination[0]-origin[0], destination[1]-origin[1]) >= minimum_trip_miles*MILE:
                        origins.append(origin); destinations.append(destination)
            person.clear()
    if not origins:
        raise ValueError("no coordinate-based trips met the minimum trip distance")
    return np.asarray(origins), np.asarray(destinations)


def distance_matrix(points: np.ndarray, sites: np.ndarray) -> np.ndarray:
    return np.hypot(points[:, None, 0]-sites[None, :, 0], points[:, None, 1]-sites[None, :, 1])


def layout_cost(active: list[int], origin_distance: np.ndarray, destination_distance: np.ndarray,
                site_distance: np.ndarray, access_radius: float, fare_per_mile: float,
                value_of_time: float, protected_origins: np.ndarray | None = None) -> tuple[float, int]:
    """Return mean generalized minutes and number of origin-covered trips.

    The proxy includes ground access/egress (25 mph with a 1.3 circuity factor),
    flight time (100 mph), and distance fare converted using value of time.  A
    two-hour penalty makes preserving five-mile origin coverage a priority.
    """
    a = np.asarray(active, dtype=int)
    od, dd = origin_distance[:, a], destination_distance[:, a]
    oi, di = np.argmin(od, axis=1), np.argmin(dd, axis=1)
    rows = np.arange(len(od))
    access, egress = od[rows, oi], dd[rows, di]
    flight = site_distance[a[oi], a[di]]
    ground_minutes = (access+egress)*1.3/MILE/25*60
    flight_minutes = flight/MILE/100*60
    fare_minutes = flight/MILE*fare_per_mile/value_of_time*60
    covered = access <= access_radius
    if protected_origins is not None and not np.all(covered[protected_origins]):
        return math.inf, int(np.count_nonzero(covered))
    cost = ground_minutes+flight_minutes+fare_minutes+(~covered)*120.0
    return float(np.mean(cost)), int(np.count_nonzero(covered))


def optimize(candidates: list[dict], initial_ids: list[str], origins: np.ndarray,
             destinations: np.ndarray, max_swaps: int, access_radius_miles: float,
             fare_per_mile: float, value_of_time: float,
             preserve_protected_origins: bool = True,
             require_proxy_improvement: bool = True,
             forbidden_layouts: set[frozenset[str]] | None = None) -> tuple[list[int], list[dict]]:
    index = {s["id"]: i for i, s in enumerate(candidates)}
    missing = [site_id for site_id in initial_ids if site_id not in index]
    if missing:
        raise ValueError(f"initial sites absent from candidate set: {missing}")
    active = [index[site_id] for site_id in initial_ids]
    coords = np.asarray([(s["x"], s["y"]) for s in candidates])
    origin_distance, destination_distance = distance_matrix(origins, coords), distance_matrix(destinations, coords)
    site_distance = distance_matrix(coords, coords)
    radius = access_radius_miles*MILE
    protected_origins = np.min(origin_distance[:, active], axis=1) <= radius if preserve_protected_origins else None
    score, covered = layout_cost(active, origin_distance, destination_distance, site_distance, radius, fare_per_mile, value_of_time)
    audit = [{"swap": 0, "meanGeneralizedMinutes": score, "originCoveredTrips": covered,
              "activeIds": [candidates[i]["id"] for i in active]}]
    for swap_number in range(1, max_swaps+1):
        active_set = set(active); best = (score, covered, None) if require_proxy_improvement else (math.inf, -1, None)
        for position in range(len(active)):
            for candidate in range(len(candidates)):
                if candidate in active_set:
                    continue
                trial = active.copy(); trial[position] = candidate
                if forbidden_layouts and frozenset(candidates[i]["id"] for i in trial) in forbidden_layouts:
                    continue
                trial_score, trial_covered = layout_cost(trial, origin_distance, destination_distance, site_distance, radius, fare_per_mile, value_of_time, protected_origins)
                # Strict score improvement; coverage breaks effectively equal ties.
                if trial_score < best[0]-1e-9 or (abs(trial_score-best[0]) <= 1e-9 and trial_covered > best[1]):
                    best = (trial_score, trial_covered, (position, candidate))
        if best[2] is None:
            break
        position, candidate = best[2]; removed = candidates[active[position]]["id"]
        active[position] = candidate; score, covered = best[0], best[1]
        audit.append({"swap": swap_number, "removed": removed, "added": candidates[candidate]["id"],
                      "proxyImproved": score < audit[-1]["meanGeneralizedMinutes"]-1e-9,
                      "meanGeneralizedMinutes": score, "originCoveredTrips": covered,
                      "activeIds": [candidates[i]["id"] for i in active]})
    return active, audit


def atomic_write_layout(path: Path, sites: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+".", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["id", "name", "x", "y"])
            writer.writeheader(); writer.writerows(sites)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True, help="exactly 100 pre-screened feasible candidate sites")
    parser.add_argument("--initial", type=Path, default=Path("scenarios/aam/active-vertiports.csv"))
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("scenarios/aam/active-vertiports.csv"))
    parser.add_argument("--candidate-count", type=int, default=100)
    parser.add_argument("--active-count", type=int, default=10)
    parser.add_argument("--max-swaps", type=int, default=10)
    parser.add_argument("--access-radius-miles", type=float, default=5.0)
    parser.add_argument("--minimum-trip-miles", type=float, default=3.0)
    parser.add_argument("--fare-per-mile", type=float, default=2.0)
    parser.add_argument("--value-of-time", type=float, default=20.0)
    args = parser.parse_args()
    candidates, initial = read_sites(args.candidates), read_sites(args.initial)
    if len(candidates) != args.candidate_count:
        raise ValueError(f"expected exactly {args.candidate_count} candidates, found {len(candidates)}")
    if len(initial) != args.active_count:
        raise ValueError(f"expected exactly {args.active_count} initial active sites, found {len(initial)}")
    origins, destinations = selected_plan_trips(args.population, args.minimum_trip_miles)
    active, audit = optimize(candidates, [s["id"] for s in initial], origins, destinations,
                             args.max_swaps, args.access_radius_miles, args.fare_per_mile, args.value_of_time)
    selected = [candidates[i] for i in active]
    digest = atomic_write_layout(args.output, selected)
    report = {"objective": "mean approximate AAM generalized minutes (lower is better)",
              "population": str(args.population), "candidates": str(args.candidates),
              "tripCount": len(origins), "sha256": digest, "iterations": audit}
    audit_path = args.output.with_suffix(args.output.suffix+".optimization.json")
    audit_path.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(f"Frozen {len(selected)} sites in {args.output}; {len(audit)-1} improving swaps; sha256={digest}")


if __name__ == "__main__":
    main()
