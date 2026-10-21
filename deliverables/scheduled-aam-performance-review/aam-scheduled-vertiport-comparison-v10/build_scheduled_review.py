"""Extract comparable performance metrics for the four scheduled-AAM optimizers."""

from __future__ import annotations

import csv
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SUITE = ROOT / "run-output" / OUT.name
METHODS = ["global", "all-vp-k10", "one-vp-k10", "adaptive"]
PREFIX = "la-aam-scheduled-scoreopt"
MILE = 1609.344
PERCENTILES = sorted(set(range(0, 101, 2)) | {25, 75, 95})


def open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8")


def rows(path: Path, delimiter=","):
    with open_text(path) as stream:
        return list(csv.DictReader(stream, delimiter=delimiter))


def seconds(value):
    if not value or value in {"null", "undefined"}:
        return math.nan
    if ":" in value:
        h, m, s = value.split(":")
        return float(h) * 3600 + float(m) * 60 + float(s)
    return float(value)


def pct(n, d):
    return 100 * n / d if d else math.nan


def trip_purpose(activity_type):
    """Collapse MATSim duration-specific activity types (for example work_28800)."""
    value = (activity_type or "unknown").strip()
    return re.sub(r"_\d+(?:\.\d+)?$", "", value) or "unknown"


def finite(values):
    return [x for x in values if math.isfinite(x)]


def quantile(values, q):
    values = sorted(finite(values))
    if not values:
        return math.nan
    p = (len(values) - 1) * q
    lo, hi = math.floor(p), math.ceil(p)
    return values[lo] if lo == hi else values[lo] * (hi - p) + values[hi] * (p - lo)


def describe(values, divisor=1):
    values = [x / divisor for x in finite(values)]
    return {
        "mean": mean(values) if values else math.nan,
        "median": median(values) if values else math.nan,
        "p95": quantile(values, .95),
    }


def write_csv(path, values, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(values)


def layout_ids(path):
    return {r["id"] for r in rows(path)}


def scheduled_supply(final_dir):
    lengths = {}
    link_pattern = re.compile(r'<link id="(aam_sched_flight_[^"]+)".*?length="([^"]+)"')
    network = final_dir / f"{PREFIX}.output_network.xml.gz"
    with open_text(network) as stream:
        for line in stream:
            match = link_pattern.search(line)
            if match:
                line_id = match.group(1).replace("aam_sched_flight_", "aam_sched_line_", 1)
                lengths[line_id] = float(match.group(2))

    departures = defaultdict(list)
    line_pattern = re.compile(r'<transitLine id="(aam_sched_line_[^"]+)"')
    departure_pattern = re.compile(r'<departure .*?departureTime="([^"]+)"')
    current = None
    schedule = final_dir / f"{PREFIX}.output_transitSchedule.xml.gz"
    with open_text(schedule) as stream:
        for line in stream:
            match = line_pattern.search(line)
            if match:
                current = match.group(1)
            if current:
                match = departure_pattern.search(line)
                if match:
                    departures[current].append(seconds(match.group(1)))
            if current and "</transitLine>" in line:
                current = None
    return lengths, departures


def analyze_method(method):
    method_dir = SUITE / method
    final_dir = method_dir / "final-convergence"
    result = json.loads((method_dir / "result.json").read_text(encoding="utf-8"))
    line_lengths, departure_times = scheduled_supply(final_dir)

    people = {}
    incomes_all = []
    with open_text(final_dir / f"{PREFIX}.output_persons.csv.gz") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            try:
                income = float(row.get("hhinc") or "nan")
            except ValueError:
                income = math.nan
            people[row["person"]] = income
            if math.isfinite(income):
                incomes_all.append(income)

    groups = defaultdict(list)
    with open_text(final_dir / f"{PREFIX}.output_legs.csv.gz") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            try:
                distance = float(row.get("distance") or "nan")
            except ValueError:
                distance = math.nan
            transit_line = row.get("transit_line") or ""
            groups[row["trip_id"]].append({
                "mode": row.get("mode") or "unknown",
                "duration": seconds(row.get("trav_time")),
                "wait": seconds(row.get("wait_time")),
                "distance": distance,
                "dep": seconds(row.get("dep_time")),
                "start": row.get("start_link") or "",
                "end": row.get("end_link") or "",
                "line": transit_line,
                "is_aam": transit_line.startswith("aam_sched_line_"),
            })

    air_trip_ids = {trip_id for trip_id, legs in groups.items() if any(x["is_aam"] for x in legs)}
    completed = []
    total_trips = 0
    window_total_trips = 0
    window_completed_trips = 0
    purposes = Counter()
    with open_text(final_dir / f"{PREFIX}.output_trips.csv.gz") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            total_trips += 1
            departure = seconds(row.get("dep_time"))
            in_window = math.isfinite(departure) and 7 * 3600 <= departure < 19 * 3600
            window_total_trips += in_window
            if row["trip_id"] in air_trip_ids:
                row["journey_seconds"] = seconds(row.get("trav_time"))
                completed.append(row)
                window_completed_trips += in_window
                purposes[trip_purpose(row.get("end_activity_type"))] += 1

    users = {r["person"] for r in completed}
    incomes_users = [people[p] for p in users if p in people and math.isfinite(people[p])]
    air_wait, air_onboard, air_distance = [], [], []
    ground_duration, ground_distance = [], []
    ground_modes = Counter()
    ground_mode_minutes = Counter()
    corridors = Counter()
    hourly_count = Counter()
    hourly_wait = defaultdict(list)
    boarded = Counter()

    for trip in completed:
        legs = groups[trip["trip_id"]]
        air_positions = [i for i, leg in enumerate(legs) if leg["is_aam"]]
        first_air, last_air = min(air_positions), max(air_positions)
        ground_s = 0
        ground_m = 0
        for leg_index, leg in enumerate(legs):
            if leg["is_aam"]:
                wait = leg["wait"]
                onboard = leg["duration"] - wait if math.isfinite(leg["duration"]) and math.isfinite(wait) else math.nan
                air_wait.append(wait)
                air_onboard.append(max(0, onboard) if math.isfinite(onboard) else math.nan)
                air_distance.append(leg["distance"])
                line = leg["line"]
                parts = line.replace("aam_sched_line_", "", 1).split("_", 1)
                if len(parts) == 2:
                    corridors[f"{parts[0]} → {parts[1]}"] += 1
                if math.isfinite(leg["dep"]):
                    hour = int(leg["dep"] // 3600) % 24
                    hourly_count[hour] += 1
                    if math.isfinite(wait):
                        hourly_wait[hour].append(wait / 60)
                board_time = leg["dep"] + wait
                available = departure_times.get(line, [])
                if available and math.isfinite(board_time):
                    nearest = min(available, key=lambda t: abs(t - board_time))
                    boarded[(line, nearest)] += 1
            else:
                is_stage_connector = ((not math.isfinite(leg["distance"]) or leg["distance"] == 0)
                                      and (leg["start"].startswith("aam_sched_loop_")
                                           or leg["end"].startswith("aam_sched_loop_")))
                substantive = not is_stage_connector
                if substantive:
                    phase = "access" if leg_index < first_air else "egress"
                    ground_modes[(phase, leg["mode"])] += 1
                if math.isfinite(leg["duration"]):
                    ground_s += leg["duration"]
                    if substantive:
                        ground_mode_minutes[(phase, leg["mode"])] += leg["duration"] / 60
                if math.isfinite(leg["distance"]):
                    ground_m += leg["distance"]
        ground_duration.append(ground_s)
        ground_distance.append(ground_m)

    occupancy_distance = Counter({pax: 0.0 for pax in range(5)})
    total_aircraft_m = 0.0
    scheduled_departures = 0
    occupied_departures = 0
    max_observed_occupancy = 0
    for line, times in departure_times.items():
        distance = line_lengths.get(line, 0.0)
        for departure in times:
            occupancy = boarded[(line, departure)]
            max_observed_occupancy = max(max_observed_occupancy, occupancy)
            occupancy_distance[min(4, occupancy)] += distance
            total_aircraft_m += distance
            scheduled_departures += 1
            occupied_departures += occupancy > 0

    initial = layout_ids(method_dir / "layout-00.csv")
    final = layout_ids(method_dir / "layout-08.csv")
    stage_rows = []
    for history in result["history"]:
        if not isinstance(history.get("stage"), int):
            continue
        opt = history["optimization"]
        stage_rows.append({
            "method": method,
            "stage": history["stage"],
            "aam_users": opt.get("currentAamUsers"),
            "aam_trips": opt.get("currentAamTrips"),
            "predicted_improvement": opt.get("improvement", 0),
            "accepted": bool(opt.get("accepted")),
            "moves_evaluated": opt.get("movesEvaluated", 0),
            "optimizer_seconds": opt.get("optimizerSeconds", 0),
        })

    top3 = sum(v for _, v in corridors.most_common(3))
    journey = [r["journey_seconds"] for r in completed]
    passenger_m = sum(finite(air_distance))
    total_aircraft_miles = total_aircraft_m / MILE
    metric = {
        "method": method,
        "completed_users": len(users),
        "completed_trips": len(completed),
        "aam_trip_share_pct": pct(len(completed), total_trips),
        "final_result_users": result["finalAamUsers"],
        "completion_ratio_pct": pct(len(users), result["finalAamUsers"]),
        "wait_mean_min": describe(air_wait, 60)["mean"],
        "wait_median_min": describe(air_wait, 60)["median"],
        "wait_p95_min": describe(air_wait, 60)["p95"],
        "wait_gt_30_pct": pct(sum(x > 1800 for x in finite(air_wait)), len(finite(air_wait))),
        "air_onboard_mean_min": describe(air_onboard, 60)["mean"],
        "air_distance_mean_miles": describe(air_distance, MILE)["mean"],
        "ground_mean_min": describe(ground_duration, 60)["mean"],
        "ground_median_min": describe(ground_duration, 60)["median"],
        "ground_distance_mean_miles": describe(ground_distance, MILE)["mean"],
        "journey_mean_min": describe(journey, 60)["mean"],
        "journey_median_min": describe(journey, 60)["median"],
        "journey_gt_6h_pct": pct(sum(x > 21600 for x in finite(journey)), len(finite(journey))),
        "scheduled_departures": scheduled_departures,
        "occupied_departure_pct": pct(occupied_departures, scheduled_departures),
        "scheduled_aircraft_miles": total_aircraft_miles,
        "aircraft_miles_per_trip": total_aircraft_miles / len(completed),
        "trips_per_departure": len(air_distance) / scheduled_departures,
        "distance_weighted_occupancy": passenger_m / total_aircraft_m if total_aircraft_m else math.nan,
        "max_observed_occupancy": max_observed_occupancy,
        "income_user_median_usd": median(incomes_users),
        "income_population_median_usd": median(incomes_all),
        "income_user_ge_100k_pct": pct(sum(x >= 100000 for x in incomes_users), len(incomes_users)),
        "income_user_lt_50k_pct": pct(sum(x < 50000 for x in incomes_users), len(incomes_users)),
        "corridors_used": len(corridors),
        "top3_corridor_share_pct": pct(top3, sum(corridors.values())),
        "final_aam_score_mean": result["finalAamScoreMean"],
        "population_score_mean": result["selectedPlanScoreMean"],
        "accepted_swaps": result["acceptedSwaps"],
        "moves_evaluated": sum(s["moves_evaluated"] for s in stage_rows),
        "optimizer_seconds": result["optimizerSeconds"],
        "wall_minutes": float(result.get("wallSeconds") or math.nan) / 60,
        "original_sites_retained": len(initial & final),
        "new_sites": len(final - initial),
    }

    ground_rows = [{"method": method, "phase": phase, "mode": mode, "legs": count,
                    "minutes": ground_mode_minutes[(phase, mode)]}
                   for (phase, mode), count in ground_modes.most_common()]
    corridor_rows = [{"method": method, "corridor": name, "passenger_trips": count,
                      "share_pct": pct(count, sum(corridors.values()))}
                     for name, count in corridors.most_common()]
    hour_rows = [{"method": method, "hour": hour, "air_legs": hourly_count[hour],
                  "mean_wait_min": mean(hourly_wait[hour]) if hourly_wait[hour] else math.nan}
                 for hour in range(24)]
    occupancy_total = sum(occupancy_distance.values())
    occupancy_rows = [{"method": method, "passengers": pax,
                       "distance_miles": distance / MILE,
                       "distance_share_pct": pct(distance, occupancy_total)}
                      for pax, distance in occupancy_distance.items()]
    wait_minutes = [value / 60 for value in finite(air_wait)]
    wait_rows = [{"method": method, "cumulative_share_pct": percentile,
                  "wait_minutes": quantile(wait_minutes, percentile / 100)}
                 for percentile in PERCENTILES]
    share_rows = [
        {"method": method, "scope": "All trips", "aam_trips": len(completed),
         "total_trips": total_trips, "aam_share_pct": pct(len(completed), total_trips)},
        {"method": method, "scope": "07:00–19:00", "aam_trips": window_completed_trips,
         "total_trips": window_total_trips,
         "aam_share_pct": pct(window_completed_trips, window_total_trips)},
    ]
    purpose_rows = [
        {"method": method, "purpose": purpose, "aam_trips": count,
         "share_pct": pct(count, len(completed))}
        for purpose, count in purposes.most_common()
    ]
    return (metric, stage_rows, ground_rows, corridor_rows, hour_rows,
            occupancy_rows, wait_rows, share_rows, purpose_rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    metrics, stages, ground, corridors, hours, occupancy, waits = [], [], [], [], [], [], []
    shares, purposes = [], []
    for method in METHODS:
        result = analyze_method(method)
        metrics.append(result[0]); stages.extend(result[1]); ground.extend(result[2])
        corridors.extend(result[3]); hours.extend(result[4]); occupancy.extend(result[5])
        waits.extend(result[6])
        shares.extend(result[7])
        purposes.extend(result[8])
    write_csv(OUT / "optimizer_metrics.csv", metrics, list(metrics[0]))
    write_csv(OUT / "stage_metrics.csv", stages, list(stages[0]))
    write_csv(OUT / "ground_mode_metrics.csv", ground, list(ground[0]))
    write_csv(OUT / "corridor_metrics.csv", corridors, list(corridors[0]))
    write_csv(OUT / "hourly_metrics.csv", hours, list(hours[0]))
    write_csv(OUT / "occupancy_metrics.csv", occupancy, list(occupancy[0]))
    write_csv(OUT / "wait_time_distribution.csv", waits, list(waits[0]))
    write_csv(OUT / "aam_share_by_time_window.csv", shares, list(shares[0]))
    write_csv(OUT / "aam_trip_purposes.csv", purposes, list(purposes[0]))
    (OUT / "summary.json").write_text(json.dumps({
        "metrics": metrics, "stages": stages, "ground_modes": ground,
        "corridors": corridors, "hours": hours, "occupancy": occupancy,
        "wait_time_distribution": waits, "aam_share_by_time_window": shares,
        "aam_trip_purposes": purposes,
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
