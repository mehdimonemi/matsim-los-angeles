#!/usr/bin/env python3
"""Generate reproducible demand-centered analytical vertiport candidates."""
from __future__ import annotations

import argparse
import gzip
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from optimize_vertiports import atomic_write_layout, read_sites


def person_activity_origins(population: Path) -> np.ndarray:
    """Return main-activity trip origins for the original person population."""
    opener = gzip.open if population.suffix == ".gz" else open
    result = []
    with opener(population, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag.rsplit("}", 1)[-1] != "person":
                continue
            subpopulation = next((e.text for e in person.iter()
                                  if e.tag.rsplit("}", 1)[-1] == "attribute"
                                  and e.attrib.get("name") == "subpopulation"), "person")
            plans = [e for e in person if e.tag.rsplit("}", 1)[-1] == "plan"]
            plan = next((p for p in plans if p.attrib.get("selected") == "yes"), plans[0] if plans else None)
            if subpopulation == "person" and plan is not None:
                activities = [(float(e.attrib["x"]), float(e.attrib["y"])) for e in plan
                              if e.tag.rsplit("}", 1)[-1] in ("act", "activity")
                              and "interaction" not in e.attrib.get("type", "").lower()
                              and "x" in e.attrib and "y" in e.attrib]
                result.extend(activities[:-1])
            person.clear()
    if not result:
        raise ValueError("no person activity origins with coordinates were found")
    return np.asarray(result, dtype=float)


def kmeans_plus_plus(points: np.ndarray, count: int, seed: int) -> np.ndarray:
    """Seeded k-means++, followed by Lloyd updates and snapping to demand points."""
    if count > len(points):
        raise ValueError("candidate count exceeds the number of activity origins")
    rng = np.random.default_rng(seed)
    centers = np.empty((count, 2), dtype=float)
    centers[0] = points[rng.integers(len(points))]
    closest_sq = np.sum((points-centers[0])**2, axis=1)
    for index in range(1, count):
        total = float(np.sum(closest_sq))
        selected = rng.integers(len(points)) if total == 0 else rng.choice(len(points), p=closest_sq/total)
        centers[index] = points[selected]
        closest_sq = np.minimum(closest_sq, np.sum((points-centers[index])**2, axis=1))
    for _ in range(30):
        distances = np.sum((points[:, None, :]-centers[None, :, :])**2, axis=2)
        labels = np.argmin(distances, axis=1)
        updated = centers.copy()
        for index in range(count):
            members = points[labels == index]
            if len(members):
                updated[index] = np.mean(members, axis=0)
        if np.max(np.hypot(*(updated-centers).T)) < 1.0:
            centers = updated; break
        centers = updated
    # Candidate sites are observed demand coordinates nearest to each center,
    # not unconstrained points that may fall in an obviously empty location.
    unique_points = np.unique(points, axis=0); snapped = []; used = set()
    for center in centers:
        order = np.argsort(np.sum((unique_points-center)**2, axis=1))
        chosen = next(int(i) for i in order if int(i) not in used)
        used.add(chosen); snapped.append(unique_points[chosen])
    return np.asarray(snapped)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--current", type=Path, default=Path("scenarios/aam/active-vertiports.csv"))
    parser.add_argument("--output", type=Path, default=Path("scenarios/aam/vertiport-candidates-100.csv"))
    parser.add_argument("--candidate-count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260909)
    args = parser.parse_args()
    current = read_sites(args.current)
    if len(current) >= args.candidate_count:
        raise ValueError("candidate count must exceed the current active-site count")
    origins = person_activity_origins(args.population)
    generated = kmeans_plus_plus(origins, args.candidate_count-len(current), args.seed)
    sites = list(current)
    for offset, (x, y) in enumerate(generated, start=len(current)+1):
        sites.append({"id": f"CAN{offset:03d}", "name": f"Demand center {offset:03d}",
                      "x": float(x), "y": float(y)})
    digest = atomic_write_layout(args.output, sites)
    print(f"Wrote {len(sites)} candidates from {len(origins)} activity origins to {args.output}; sha256={digest}")


if __name__ == "__main__":
    main()
