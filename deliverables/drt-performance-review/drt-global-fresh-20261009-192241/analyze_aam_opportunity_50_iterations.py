"""Audit AAM opportunity and use across all 50 MATSim iterations."""

from __future__ import annotations

import csv
import gzip
import json
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "run-output" / "drt-global-fresh-20261009-192241"
HERE = Path(__file__).resolve().parent
PREFIX = "la-aam-fare30-scoreopt"
PHASES = [f"stage-{i:02d}" for i in range(1, 9)] + ["final-convergence"]


def marker(leg):
    if leg.get("mode") in {"aam", "aam_drt"}:
        return True
    return any(a.get("name") == "routingMode" and (a.text or "").strip() == "aam"
               for a in leg.findall("./attributes/attribute"))


def plan_memory(path):
    marked, genuine = set(), set()
    with gzip.open(path, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            pid = person.get("id")
            plans = person.findall("plan")
            if any(p.get("type") == "aam" or any(marker(l) for l in p.findall("leg")) for p in plans):
                marked.add(pid)
            if any(any(l.get("mode") == "aam_drt" for l in p.findall("leg")) for p in plans):
                genuine.add(pid)
            person.clear()
    return marked, genuine


def actual_users(path):
    users, trips, requests, pickups, arrivals = set(), 0, [], [], []
    with path.open("r", encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            users.add(row["personId"]); trips += 1
            departure, wait, arrival = float(row["departureTime"]), float(row["waitTime"]), float(row["arrivalTime"])
            requests.append(departure); pickups.append(departure + wait); arrivals.append(arrival)
    return users, trips, requests, pickups, arrivals


def main():
    ever_marker, ever_genuine, ever_actual = set(), set(), set()
    phase_rows, iteration_rows = [], []
    all_requests, all_pickups, all_arrivals = [], [], []
    global_iteration = 0
    for phase in PHASES:
        folder = BASE / phase
        marked, genuine = plan_memory(folder / f"{PREFIX}.output_plans.xml.gz")
        ever_marker |= marked; ever_genuine |= genuine
        phase_actual = set(); phase_trips = 0
        iterations = sorted((folder / "ITERS").glob("it.*"), key=lambda p: int(p.name.split(".")[-1]))
        for iteration in iterations:
            local = int(iteration.name.split(".")[-1])
            trip_file = iteration / f"{PREFIX}.{local}.drt_trips_aam_drt.csv"
            users, trips, requests, pickups, arrivals = actual_users(trip_file)
            all_requests.extend(requests); all_pickups.extend(pickups); all_arrivals.extend(arrivals)
            ever_actual |= users; phase_actual |= users; phase_trips += trips
            iteration_rows.append({"global_iteration": global_iteration, "phase": phase,
                                   "local_iteration": local, "actual_aam_users": len(users),
                                   "actual_aam_trips": trips})
            global_iteration += 1
        phase_rows.append({"phase": phase, "end_plan_marker_users": len(marked),
                           "end_plan_genuine_air_users": len(genuine),
                           "actual_aam_users_union": len(phase_actual),
                           "actual_aam_trips_sum": phase_trips})

    persons_file = BASE / "final-convergence" / f"{PREFIX}.output_persons.csv.gz"
    passengers, freight = set(), set()
    with gzip.open(persons_file, "rt", encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            (passengers if row.get("subpopulation") == "person" else freight).add(row["person"])

    result = {
        "iterations_audited": global_iteration,
        "passenger_agents": len(passengers),
        "freight_agents_excluded": len(freight),
        "ever_had_aam_marker_plan_at_a_phase_end": len(ever_marker & passengers),
        "ever_had_genuine_aircraft_plan_at_a_phase_end": len(ever_genuine & passengers),
        "ever_completed_aam_trip_across_50_iterations": len(ever_actual & passengers),
        "never_had_aam_marker_plan_at_a_phase_end": len(passengers - ever_marker),
        "never_had_genuine_aircraft_plan_at_a_phase_end": len(passengers - ever_genuine),
        "marker_opportunity_share_pct": 100 * len(ever_marker & passengers) / len(passengers),
        "genuine_air_opportunity_share_pct": 100 * len(ever_genuine & passengers) / len(passengers),
        "ever_flew_share_pct": 100 * len(ever_actual & passengers) / len(passengers),
        "aam_time_range_seconds_across_all_served_trips": {
            "earliest_request": min(all_requests), "latest_request": max(all_requests),
            "earliest_pickup": min(all_pickups), "latest_pickup": max(all_pickups),
            "earliest_arrival": min(all_arrivals), "latest_arrival": max(all_arrivals),
        },
        "phase_summary": phase_rows,
        "iteration_summary": iteration_rows,
    }
    (HERE / "aam_opportunity_50_iterations.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for name, rows in (("aam_opportunity_by_phase.csv", phase_rows),
                       ("aam_actual_users_by_iteration.csv", iteration_rows)):
        with (HERE / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
