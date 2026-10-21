"""Extract multi-factor performance metrics for the four completed DRT optimizers."""

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
PREFIX = "la-aam-fare30-scoreopt"


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


def quantile(values, q):
    values = sorted(x for x in values if math.isfinite(x))
    if not values:
        return math.nan
    p = (len(values) - 1) * q
    lo, hi = math.floor(p), math.ceil(p)
    return values[lo] if lo == hi else values[lo] * (hi - p) + values[hi] * (p - lo)


def describe(values, divisor=1):
    values = [x / divisor for x in values if math.isfinite(x)]
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


def analyze_method(method):
    method_dir = SUITE / method
    final_dir = method_dir / "final-convergence"
    result = json.loads((method_dir / "result.json").read_text(encoding="utf-8"))

    people = {}
    incomes_all = []
    with open_text(final_dir / f"{PREFIX}.output_persons.csv.gz") as stream:
        for r in csv.DictReader(stream, delimiter=";"):
            try:
                income = float(r.get("hhinc") or "nan")
            except ValueError:
                income = math.nan
            people[r["person"]] = income
            if math.isfinite(income):
                incomes_all.append(income)

    groups = defaultdict(list)
    with open_text(final_dir / f"{PREFIX}.output_legs.csv.gz") as stream:
        for r in csv.DictReader(stream, delimiter=";"):
            duration = seconds(r.get("trav_time"))
            wait = seconds(r.get("wait_time"))
            try:
                distance = float(r.get("distance") or "nan")
            except ValueError:
                distance = math.nan
            groups[r["trip_id"]].append({
                "mode": r.get("mode") or "unknown",
                "duration": duration,
                "wait": wait,
                "distance": distance,
                "dep": seconds(r.get("dep_time")),
                "start": r.get("start_link") or "",
                "end": r.get("end_link") or "",
            })

    air_trip_ids = {trip_id for trip_id, legs in groups.items() if any(x["mode"] == "aam_drt" for x in legs)}
    completed = []
    total_trips = 0
    window_total_trips = 0
    window_completed_trips = 0
    purposes = Counter()
    with open_text(final_dir / f"{PREFIX}.output_trips.csv.gz") as stream:
        for r in csv.DictReader(stream, delimiter=";"):
            total_trips += 1
            departure = seconds(r.get("dep_time"))
            in_window = math.isfinite(departure) and 7 * 3600 <= departure < 19 * 3600
            window_total_trips += in_window
            if r["trip_id"] in air_trip_ids:
                r["journey_seconds"] = seconds(r.get("trav_time"))
                completed.append(r)
                window_completed_trips += in_window
                purposes[trip_purpose(r.get("end_activity_type"))] += 1

    users = {r["person"] for r in completed}
    incomes_users = [people[p] for p in users if p in people and math.isfinite(people[p])]
    air_wait, air_onboard, air_distance = [], [], []
    ground_duration, ground_distance = [], []
    ground_modes = Counter()
    ground_mode_minutes = Counter()
    corridors = Counter()
    hourly_count = Counter()
    hourly_wait = defaultdict(list)
    fares = []
    for r in completed:
        legs = groups[r["trip_id"]]
        air_positions = [i for i, leg in enumerate(legs) if leg["mode"] == "aam_drt"]
        first_air, last_air = min(air_positions), max(air_positions)
        ground_s = 0
        ground_m = 0
        for leg_index, leg in enumerate(legs):
            if leg["mode"] == "aam_drt":
                wait = leg["wait"]
                onboard = leg["duration"] - wait if math.isfinite(leg["duration"]) and math.isfinite(wait) else math.nan
                air_wait.append(wait)
                air_onboard.append(max(0, onboard) if math.isfinite(onboard) else math.nan)
                air_distance.append(leg["distance"])
                if math.isfinite(leg["distance"]):
                    fares.append(30 + 2 * leg["distance"] / 1609.344)
                origin = leg["start"].replace("aam_loop_", "")
                destination = leg["end"].replace("aam_loop_", "")
                corridors[f"{origin} → {destination}"] += 1
                if math.isfinite(leg["dep"]):
                    hour = int(leg["dep"] // 3600) % 24
                    hourly_count[hour] += 1
                    if math.isfinite(wait):
                        hourly_wait[hour].append(wait / 60)
            else:
                # Exclude zero-time/zero-distance stage connectors from the
                # access/egress mode counts while retaining their harmless
                # zero values in total ground time and distance.
                is_stage_connector = ((not math.isfinite(leg["distance"]) or leg["distance"] == 0)
                                      and (leg["start"].startswith("aam_loop_")
                                           or leg["end"].startswith("aam_loop_")))
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

    customer = rows(final_dir / f"{PREFIX}.drt_customer_stats_aam_drt.csv", ";")[-1]
    vehicle = rows(final_dir / f"{PREFIX}.drt_vehicle_stats_aam_drt.csv", ";")[-1]
    rides = int(float(customer["rides"]))
    rejections = int(float(customer["rejections"]))
    total_km = float(vehicle["totalDistance"]) / 1000
    empty_km = float(vehicle["totalEmptyDistance"]) / 1000

    occupancy = {}
    distance_file = final_dir / f"{PREFIX}.drt_detailed_distanceStats_aam_drt.csv"
    with distance_file.open(encoding="utf-8") as stream:
        parsed = list(csv.reader(stream, delimiter=";"))
    last = parsed[-1]
    # Columns 2..6 are distance driven with 0..4 passengers.
    for pax, value in enumerate(last[2:7]):
        occupancy[pax] = float(value) / 1000
    occupancy_total = sum(occupancy.values())

    initial = layout_ids(method_dir / "layout-00.csv")
    final = layout_ids(method_dir / "layout-08.csv")
    stage_rows = []
    for h in result["history"]:
        if not isinstance(h.get("stage"), int):
            continue
        opt = h["optimization"]
        stage_rows.append({
            "method": method,
            "stage": h["stage"],
            "aam_users": opt.get("currentAamUsers"),
            "aam_trips": opt.get("currentAamTrips"),
            "predicted_improvement": opt.get("improvement", 0),
            "accepted": bool(opt.get("accepted")),
            "moves_evaluated": opt.get("movesEvaluated", 0),
            "optimizer_seconds": opt.get("optimizerSeconds", 0),
        })

    top3_corridors = sum(v for _, v in corridors.most_common(3))
    journey = [r["journey_seconds"] for r in completed]
    metric = {
        "method": method,
        "completed_users": len(users),
        "completed_trips": len(completed),
        "aam_trip_share_pct": pct(len(completed), total_trips),
        "final_result_users": result["finalAamUsers"],
        "completion_ratio_pct": pct(len(users), result["finalAamUsers"]),
        "rides": rides,
        "rejections": rejections,
        "rejection_rate_pct": 100 * float(customer["rejectionRate"]),
        "wait_mean_min": describe(air_wait, 60)["mean"],
        "wait_median_min": describe(air_wait, 60)["median"],
        "wait_p95_min": describe(air_wait, 60)["p95"],
        "wait_le_10_pct": pct(sum(x <= 600 for x in air_wait), len(air_wait)),
        "wait_le_15_pct": pct(sum(x <= 900 for x in air_wait), len(air_wait)),
        "air_onboard_mean_min": describe(air_onboard, 60)["mean"],
        "air_distance_mean_miles": describe(air_distance, 1609.344)["mean"],
        "fare_mean_usd": mean(fares),
        "fare_p95_usd": quantile(fares, .95),
        "ground_mean_min": describe(ground_duration, 60)["mean"],
        "ground_median_min": describe(ground_duration, 60)["median"],
        "ground_distance_mean_miles": describe(ground_distance, 1609.344)["mean"],
        "journey_mean_min": describe(journey, 60)["mean"],
        "journey_median_min": describe(journey, 60)["median"],
        "journey_p95_min": describe(journey, 60)["p95"],
        "journey_gt_6h_pct": pct(sum(x > 21600 for x in journey), len(journey)),
        "fleet_vehicles": int(float(vehicle["vehicles"])),
        "fleet_total_km": total_km,
        "fleet_empty_km": empty_km,
        "fleet_empty_ratio_pct": 100 * float(vehicle["emptyRatio"]),
        "vehicle_km_per_ride": total_km / rides,
        "rides_per_vehicle": rides / float(vehicle["vehicles"]),
        "passenger_km_per_vehicle_km": float(vehicle["d_p/d_t"]),
        "occupancy_0_pct": pct(occupancy[0], occupancy_total),
        "occupancy_1_pct": pct(occupancy[1], occupancy_total),
        "occupancy_2_pct": pct(occupancy[2], occupancy_total),
        "occupancy_3_pct": pct(occupancy[3], occupancy_total),
        "occupancy_4_pct": pct(occupancy[4], occupancy_total),
        "income_user_median_usd": median(incomes_users),
        "income_population_median_usd": median(incomes_all),
        "income_user_ge_100k_pct": pct(sum(x >= 100000 for x in incomes_users), len(incomes_users)),
        "income_user_lt_50k_pct": pct(sum(x < 50000 for x in incomes_users), len(incomes_users)),
        "corridors_used": len(corridors),
        "top3_corridor_share_pct": pct(top3_corridors, sum(corridors.values())),
        "final_aam_score_mean": result["finalAamScoreMean"],
        "population_score_mean": result["selectedPlanScoreMean"],
        "accepted_swaps": result["acceptedSwaps"],
        "moves_evaluated": sum(s["moves_evaluated"] for s in stage_rows),
        "optimizer_seconds": result["optimizerSeconds"],
        "wall_minutes": result["wallSeconds"] / 60,
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
    occupancy_rows = [{"method": method, "passengers": pax, "distance_km": km,
                       "distance_share_pct": pct(km, occupancy_total)}
                      for pax, km in occupancy.items()]
    fare_percentiles = sorted(set(range(0, 101, 2)) | {25, 75, 95})
    fare_rows = [{"method": method, "cumulative_share_pct": percentile,
                  "fare_usd": quantile(fares, percentile / 100)}
                 for percentile in fare_percentiles]
    wait_minutes = [value / 60 for value in air_wait if math.isfinite(value)]
    wait_rows = [{"method": method, "cumulative_share_pct": percentile,
                  "wait_minutes": quantile(wait_minutes, percentile / 100)}
                 for percentile in fare_percentiles]
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
            occupancy_rows, fare_rows, wait_rows, share_rows, purpose_rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    metrics, stages, ground, corridors, hours, occupancy, fares, waits = [], [], [], [], [], [], [], []
    shares, purposes = [], []
    for method in METHODS:
        result = analyze_method(method)
        metrics.append(result[0]); stages.extend(result[1]); ground.extend(result[2])
        corridors.extend(result[3]); hours.extend(result[4]); occupancy.extend(result[5])
        fares.extend(result[6])
        waits.extend(result[7])
        shares.extend(result[8])
        purposes.extend(result[9])
    write_csv(OUT / "optimizer_metrics.csv", metrics, list(metrics[0]))
    write_csv(OUT / "stage_metrics.csv", stages, list(stages[0]))
    write_csv(OUT / "ground_mode_metrics.csv", ground, list(ground[0]))
    write_csv(OUT / "corridor_metrics.csv", corridors, list(corridors[0]))
    write_csv(OUT / "hourly_metrics.csv", hours, list(hours[0]))
    write_csv(OUT / "occupancy_metrics.csv", occupancy, list(occupancy[0]))
    write_csv(OUT / "fare_distribution.csv", fares, list(fares[0]))
    write_csv(OUT / "wait_time_distribution.csv", waits, list(waits[0]))
    write_csv(OUT / "aam_share_by_time_window.csv", shares, list(shares[0]))
    write_csv(OUT / "aam_trip_purposes.csv", purposes, list(purposes[0]))
    (OUT / "summary.json").write_text(json.dumps({"metrics": metrics, "stages": stages,
        "ground_modes": ground, "corridors": corridors, "hours": hours,
        "occupancy": occupancy, "fare_distribution": fares,
        "wait_time_distribution": waits, "aam_share_by_time_window": shares,
        "aam_trip_purposes": purposes}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
