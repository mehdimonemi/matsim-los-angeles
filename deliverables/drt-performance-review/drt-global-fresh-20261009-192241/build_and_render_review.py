"""Build the 14-graph DRT review for drt-global-fresh-20261009-192241."""

from __future__ import annotations

import csv
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
GRAPH_DIR = HERE / "graphs"
RUN = ROOT / "run-output" / "drt-global-fresh-20261009-192241"
PREFIX = "la-aam-fare30-scoreopt"
COLOR = "#526D82"
ACCENT = "#007F73"
ORANGE = "#C66A2B"
PURPLE = "#7A5195"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
    "mathtext.fontset": "stix",
})


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


def quantile(values, q):
    values = sorted(x for x in values if math.isfinite(x))
    if not values:
        return math.nan
    p = (len(values) - 1) * q
    lo, hi = math.floor(p), math.ceil(p)
    return values[lo] if lo == hi else values[lo] * (hi - p) + values[hi] * (p - lo)


def describe(values, divisor=1):
    clean = [x / divisor for x in values if math.isfinite(x)]
    return {"mean": mean(clean), "median": median(clean), "p95": quantile(clean, .95)} if clean else {"mean": math.nan, "median": math.nan, "p95": math.nan}


def write_csv(path, values):
    if not values:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(values[0]), extrasaction="ignore")
        writer.writeheader(); writer.writerows(values)


def build_metrics():
    result = json.loads((RUN / "result.json").read_text(encoding="utf-8"))
    final_history = result["history"][-1]
    final_dir = RUN / "final-convergence"

    people, incomes_all = {}, []
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
            groups[row["trip_id"]].append({
                "mode": row.get("mode") or "unknown",
                "duration": seconds(row.get("trav_time")),
                "wait": seconds(row.get("wait_time")),
                "distance": distance,
                "dep": seconds(row.get("dep_time")),
                "start": row.get("start_link") or "",
                "end": row.get("end_link") or "",
            })

    air_trip_ids = {trip for trip, legs in groups.items() if any(leg["mode"] == "aam_drt" for leg in legs)}
    completed, total_trips = [], 0
    with open_text(final_dir / f"{PREFIX}.output_trips.csv.gz") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            total_trips += 1
            if row["trip_id"] in air_trip_ids:
                row["journey_seconds"] = seconds(row.get("trav_time"))
                completed.append(row)

    users = {row["person"] for row in completed}
    incomes_users = [people[p] for p in users if p in people and math.isfinite(people[p])]
    air_wait, air_onboard, air_distance = [], [], []
    ground_duration, ground_distance = [], []
    ground_modes, ground_mode_minutes = Counter(), Counter()
    corridors, hourly_count, hourly_wait = Counter(), Counter(), defaultdict(list)
    fares = []
    for row in completed:
        legs = groups[row["trip_id"]]
        air_positions = [i for i, leg in enumerate(legs) if leg["mode"] == "aam_drt"]
        first_air = min(air_positions)
        ground_s = ground_m = 0.0
        for index, leg in enumerate(legs):
            if leg["mode"] == "aam_drt":
                wait = leg["wait"]
                onboard = leg["duration"] - wait if math.isfinite(leg["duration"]) and math.isfinite(wait) else math.nan
                air_wait.append(wait); air_onboard.append(max(0, onboard) if math.isfinite(onboard) else math.nan)
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
                connector = ((not math.isfinite(leg["distance"]) or leg["distance"] == 0) and
                             (leg["start"].startswith("aam_loop_") or leg["end"].startswith("aam_loop_")))
                if not connector:
                    phase = "access" if index < first_air else "egress"
                    ground_modes[(phase, leg["mode"])] += 1
                    if math.isfinite(leg["duration"]):
                        ground_mode_minutes[(phase, leg["mode"])] += leg["duration"] / 60
                if math.isfinite(leg["duration"]):
                    ground_s += leg["duration"]
                if math.isfinite(leg["distance"]):
                    ground_m += leg["distance"]
        ground_duration.append(ground_s); ground_distance.append(ground_m)

    customer = rows(final_dir / f"{PREFIX}.drt_customer_stats_aam_drt.csv", ";")[-1]
    vehicle = rows(final_dir / f"{PREFIX}.drt_vehicle_stats_aam_drt.csv", ";")[-1]
    rides = int(float(customer["rides"])); rejections = int(float(customer["rejections"]))
    total_km = float(vehicle["totalDistance"]) / 1000; empty_km = float(vehicle["totalEmptyDistance"]) / 1000

    parsed = list(csv.reader((final_dir / f"{PREFIX}.drt_detailed_distanceStats_aam_drt.csv").open(encoding="utf-8"), delimiter=";"))
    occupancy = {pax: float(value) / 1000 for pax, value in enumerate(parsed[-1][2:7])}
    occupancy_total = sum(occupancy.values())

    initial_ids = {row["id"] for row in rows(RUN / "layout-00.csv")}
    final_ids = {row["id"] for row in rows(RUN / "layout-08.csv")}
    stages = []
    for history in result["history"]:
        if history.get("phase") != "search":
            continue
        opt = history["optimization"]
        stages.append({
            "stage": int(history["stage"]),
            "aam_users": int(opt.get("currentAamUsers", 0)),
            "selected_aam_users": int(history["retainedPlanMetrics"].get("selectedAamUsers", 0)),
            "selected_aam_score_mean": float(history["retainedPlanMetrics"].get("selectedAamScoreMean", math.nan)),
            "predicted_improvement": float(opt.get("improvement", 0)),
            "moves_evaluated": int(opt.get("movesEvaluated", 0)),
            "optimizer_seconds": float(opt.get("optimizerSeconds", 0)),
            "accepted": bool(opt.get("accepted")),
        })

    journey = [row["journey_seconds"] for row in completed]
    top3_corridors = sum(v for _, v in corridors.most_common(3))
    retained = final_history["retainedPlanMetrics"]
    metric = {
        "run": RUN.name,
        "completed_users": len(users),
        "completed_trips": len(completed),
        "aam_trip_share_pct": pct(len(completed), total_trips),
        "final_result_users": int(retained["scoredAamAlternativeUsers"]),
        "selected_aam_users": int(retained["selectedAamUsers"]),
        "rides": rides,
        "rejections": rejections,
        # MATSim prints rejectionRate with only two decimal places. Recompute it
        # from the integer counts so a single rejection is not shown as 0%.
        "rejection_rate_pct": pct(rejections, rides + rejections),
        "wait_mean_min": describe(air_wait, 60)["mean"],
        "wait_median_min": describe(air_wait, 60)["median"],
        "wait_p95_min": describe(air_wait, 60)["p95"],
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
        "fleet_vehicles": int(float(vehicle["vehicles"])),
        "fleet_total_km": total_km,
        "fleet_empty_km": empty_km,
        "fleet_empty_ratio_pct": pct(empty_km, total_km),
        "vehicle_km_per_ride": total_km / rides,
        "rides_per_vehicle": rides / float(vehicle["vehicles"]),
        "passenger_km_per_vehicle_km": float(vehicle["d_p/d_t"]),
        **{f"occupancy_{pax}_pct": pct(occupancy[pax], occupancy_total) for pax in range(5)},
        "income_user_median_usd": median(incomes_users),
        "income_population_median_usd": median(incomes_all),
        "income_user_ge_100k_pct": pct(sum(x >= 100000 for x in incomes_users), len(incomes_users)),
        "income_user_lt_50k_pct": pct(sum(x < 50000 for x in incomes_users), len(incomes_users)),
        "corridors_used": len(corridors),
        "top3_corridor_share_pct": pct(top3_corridors, sum(corridors.values())),
        "final_aam_score_mean": float(retained["selectedAamScoreMean"]),
        "population_score_mean": float(retained["selectedPlanScoreMean"]),
        "accepted_swaps": sum(stage["accepted"] for stage in stages),
        "moves_evaluated": sum(stage["moves_evaluated"] for stage in stages),
        "optimizer_seconds": sum(stage["optimizer_seconds"] for stage in stages),
        "matsim_minutes": sum(float(h["matsimSeconds"]) for h in result["history"]) / 60,
        "original_sites_retained": len(initial_ids & final_ids),
        "new_sites": len(final_ids - initial_ids),
    }
    ground = [{"phase": phase, "mode": mode, "legs": count, "minutes": ground_mode_minutes[(phase, mode)]}
              for (phase, mode), count in ground_modes.items()]
    corridor_rows = [{"corridor": name, "passenger_trips": count, "share_pct": pct(count, sum(corridors.values()))}
                     for name, count in corridors.most_common()]
    hours = [{"hour": hour, "air_legs": hourly_count[hour],
              "mean_wait_min": mean(hourly_wait[hour]) if hourly_wait[hour] else math.nan}
             for hour in range(24)]
    occupancy_rows = [{"passengers": pax, "distance_km": km, "distance_share_pct": pct(km, occupancy_total)}
                      for pax, km in occupancy.items()]
    percentiles = sorted(set(range(0, 101, 2)) | {25, 75, 95})
    fares_out = [{"cumulative_share_pct": p, "fare_usd": quantile(fares, p / 100)} for p in percentiles]
    waits_out = [{"cumulative_share_pct": p, "wait_minutes": quantile([x/60 for x in air_wait], p / 100)} for p in percentiles]
    data = {"metrics": metric, "stages": stages, "ground_modes": ground, "corridors": corridor_rows,
            "hours": hours, "occupancy": occupancy_rows, "fare_distribution": fares_out,
            "wait_time_distribution": waits_out}
    write_csv(HERE / "optimizer_metrics.csv", [metric]); write_csv(HERE / "stage_metrics.csv", stages)
    write_csv(HERE / "ground_mode_metrics.csv", ground); write_csv(HERE / "corridor_metrics.csv", corridor_rows)
    write_csv(HERE / "hourly_metrics.csv", hours); write_csv(HERE / "occupancy_metrics.csv", occupancy_rows)
    write_csv(HERE / "fare_distribution.csv", fares_out); write_csv(HERE / "wait_time_distribution.csv", waits_out)
    (HERE / "summary.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def style_axis(ax, grid="y"):
    ax.grid(axis=grid, alpha=.22, linewidth=.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=10)


def save(fig, name):
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(GRAPH_DIR / name, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def box_plot(ax, values, average, color, unit):
    minimum, q1, med, q3, p95, maximum = [values[p] for p in (0, 25, 50, 75, 95, 100)]
    ax.hlines(0, minimum, maximum, color=color, linewidth=2.5)
    ax.hlines(0, q1, q3, color=color, linewidth=12, alpha=.5)
    ax.scatter([minimum, maximum], [0, 0], color=color, marker="|", s=180, linewidths=2.5)
    ax.scatter(med, 0, facecolor="white", edgecolor=color, marker="D", s=75, linewidth=2, zorder=4)
    ax.scatter(average, 0, color=color, marker="o", s=75, zorder=4)
    ax.scatter(p95, 0, color=color, marker="^", s=80, zorder=4)
    for x, label, y in [(minimum, f"Min {minimum:.1f}", -.12), (average, f"Avg {average:.1f}", .14),
                        (med, f"Median {med:.1f}", -.22), (p95, f"P95 {p95:.1f}", .14),
                        (maximum, f"Max {maximum:.1f}", -.12)]:
        ax.text(x, y, label, ha="center", va="center", fontsize=9, fontweight="bold" if x == average else None)
    ax.set_yticks([]); ax.set_xlabel(unit); ax.set_ylim(-.32, .32); style_axis(ax, "x")


def render(data):
    m, stages = data["metrics"], data["stages"]

    fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
    bars = [
        ax.bar([-.18], [m["completed_users"]], .32, color=COLOR, edgecolor=COLOR)[0],
        ax.bar([.18], [m["completed_trips"]], .32, color=COLOR, alpha=.5,
               hatch="//", edgecolor=COLOR)[0],
    ]
    ax.set_xticks([-.18, .18], ["Distinct users", "Completed trips"])
    for bar in bars: ax.text(bar.get_x()+bar.get_width()/2, bar.get_height(), f"{bar.get_height():,.0f}", ha="center", va="bottom", fontweight="bold")
    ax.set_ylabel("Count"); ax.set_title("Completed AAM users and trips", loc="left", fontweight="bold"); style_axis(ax)
    save(fig, "01-completed-users.png")

    fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
    x = [s["selected_aam_users"] for s in stages]; y = [s["selected_aam_score_mean"] for s in stages]
    ax.plot(x, y, color=COLOR, linewidth=2, alpha=.65)
    sc = ax.scatter(x, y, c=[s["stage"] for s in stages], cmap="viridis", s=95, zorder=3)
    for s, xx, yy in zip(stages, x, y): ax.annotate(f"S{s['stage']}", (xx, yy), xytext=(5, 5), textcoords="offset points", fontweight="bold")
    ax.set_xlabel("Selected AAM users"); ax.set_ylabel("Mean selected AAM-plan score")
    ax.set_title("Adoption versus AAM-user score by search stage", loc="left", fontweight="bold"); style_axis(ax)
    save(fig, "02-adoption-vs-score.png")

    fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
    bars = ax.bar([0, 1], [m["rejection_rate_pct"], m["wait_mean_min"]], color=[COLOR, ACCENT], width=.62)
    ax.set_xticks([0, 1], ["Rejected requests (%)", "Mean aircraft wait (min)"])
    for bar, value in zip(bars, [m["rejection_rate_pct"], m["wait_mean_min"]]): ax.text(bar.get_x()+bar.get_width()/2, value, f"{value:.2f}", ha="center", va="bottom", fontweight="bold")
    ax.set_title("Request rejection and aircraft wait", loc="left", fontweight="bold"); style_axis(ax)
    save(fig, "03-rejection-and-wait.png")

    fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    vals = np.array([m["ground_mean_min"], m["wait_mean_min"], m["air_onboard_mean_min"]]) / 60
    colors = ["#2A9D8F", "#E9C46A", "#E76F51"]
    left = 0
    for value, label, color in zip(vals, ["Ground access + egress", "Aircraft wait", "Onboard"], colors):
        ax.barh([0], [value], left=left, color=color, label=label); left += value
    ax.text(left+.04, 0, f"{left:.2f} h total\n{m['ground_distance_mean_miles']:.1f} ground miles", va="center", fontweight="bold")
    ax.set_yticks([0], ["DRT Global Fresh"]); ax.set_xlabel("Mean end-to-end journey time (hours)")
    ax.set_title("Journey composition", loc="left", fontweight="bold"); ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(.5, -.16)); style_axis(ax, "x")
    save(fig, "04-journey-composition.png")

    fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
    bottom = 0; occ_colors = ["#B23A48", "#E9C46A", "#8AB17D", "#2A9D8F", "#176B61"]
    for pax, color in zip(range(5), occ_colors):
        val = m[f"occupancy_{pax}_pct"]; ax.bar([0], [val], bottom=bottom, color=color, label=f"{pax} passenger{'s' if pax != 1 else ''}"); bottom += val
    ax.set_xticks([0], ["DRT Global Fresh"]); ax.set_ylabel("Share of AAM distance (%)")
    ax.set_title("Distance by passenger occupancy", loc="left", fontweight="bold"); ax.legend(frameon=False, ncol=3); style_axis(ax)
    save(fig, "05-aam-distance-by-passenger-count.png")

    fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
    aircraft_miles = m["vehicle_km_per_ride"] * .621371
    bars = ax.bar([0, 1, 2], [aircraft_miles, m["passenger_km_per_vehicle_km"], m["fleet_empty_ratio_pct"]], color=[COLOR, ACCENT, ORANGE])
    ax.set_xticks([0, 1, 2], ["Aircraft miles/trip", "Distance-weighted\noccupancy", "Empty distance (%)"])
    for bar in bars: ax.text(bar.get_x()+bar.get_width()/2, bar.get_height(), f"{bar.get_height():.2f}", ha="center", va="bottom", fontweight="bold")
    ax.set_title("Fleet productivity and pooling", loc="left", fontweight="bold"); style_axis(ax)
    save(fig, "06-fleet-productivity.png")

    fare = {r["cumulative_share_pct"]: r["fare_usd"] for r in data["fare_distribution"]}
    fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True); box_plot(ax, fare, m["fare_mean_usd"], COLOR, "Estimated fare (USD)")
    ax.set_title("Fare box plot", loc="left", fontweight="bold"); save(fig, "07-fare-distribution.png")

    fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
    ax.scatter(m["corridors_used"], m["top3_corridor_share_pct"], s=m["air_distance_mean_miles"]*25, color=COLOR)
    ax.annotate(f"{m['corridors_used']} corridors\nTop 3: {m['top3_corridor_share_pct']:.1f}%\nMean air trip: {m['air_distance_mean_miles']:.1f} mi", (m["corridors_used"], m["top3_corridor_share_pct"]), xytext=(8, 8), textcoords="offset points", fontweight="bold")
    ax.set_xlabel("Distinct used corridors"); ax.set_ylabel("Top-three corridor share (%)")
    ax.set_title("Network diversification", loc="left", fontweight="bold"); ax.margins(.25); style_axis(ax)
    save(fig, "08-network-diversification.png")

    fig, ax = plt.subplots(figsize=(9, 6), constrained_layout=True)
    ax.plot([s["stage"] for s in stages], [s["aam_users"] for s in stages], marker="o", linewidth=2.4, color=COLOR)
    for s in stages: ax.annotate(f"{s['aam_users']:,}", (s["stage"], s["aam_users"]), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=9)
    ax.set_xlabel("Search stage"); ax.set_ylabel("Current scored AAM users")
    ax.set_title("Scored AAM-plan users over eight optimizer stages", loc="left", fontweight="bold"); style_axis(ax)
    save(fig, "09-search-stage-users.png")

    fig, ax = plt.subplots(figsize=(9, 6), constrained_layout=True)
    stage_x = np.arange(1, 9); stage_seconds = [s["optimizer_seconds"] for s in stages]
    bars = ax.bar(stage_x, stage_seconds, color=COLOR)
    for bar, s in zip(bars, stages): ax.text(bar.get_x()+bar.get_width()/2, bar.get_height(), f"{s['moves_evaluated']:,} moves", ha="center", va="bottom", fontsize=8, rotation=45)
    ax.set_xlabel("Search stage"); ax.set_ylabel("Optimizer time (seconds)")
    ax.set_title(f"Search cost — total {m['optimizer_seconds']:.0f}s, {m['moves_evaluated']:,} moves", loc="left", fontweight="bold"); style_axis(ax)
    save(fig, "10-search-cost.png")

    fig, ax = plt.subplots(figsize=(9, 6), constrained_layout=True)
    hourly = [r for r in data["hours"] if math.isfinite(r["mean_wait_min"])]
    ax.plot([r["hour"] for r in hourly], [r["mean_wait_min"] for r in hourly], marker="o", linewidth=2.2, color=COLOR)
    ax.set_xlabel("Aircraft departure hour"); ax.set_ylabel("Mean aircraft wait (minutes)")
    ax.set_title("Wait time by hour", loc="left", fontweight="bold"); style_axis(ax)
    save(fig, "11-wait-by-hour.png")

    fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
    vals = [m["income_user_median_usd"]/1000, m["income_population_median_usd"]/1000]
    bars = ax.bar([0, 1], vals, color=[COLOR, "#999999"])
    ax.set_xticks([0, 1], ["AAM users", "Full population"]); ax.set_ylabel("Median household income ($000)")
    for bar, value in zip(bars, vals): ax.text(bar.get_x()+bar.get_width()/2, value, f"${value:.1f}k", ha="center", va="bottom", fontweight="bold")
    ax.set_title(f"AAM-user income — {m['income_user_ge_100k_pct']:.1f}% at or above $100k", loc="left", fontweight="bold"); style_axis(ax)
    save(fig, "12-user-income.png")

    modes = ["walk", "car", "bike", "ride", "ride_taxi"]
    mode_colors = {"walk":"#2A9D8F", "car":"#C66A2B", "bike":"#E9C46A", "ride":"#526D82", "ride_taxi":"#7A5195"}
    grouped = defaultdict(Counter)
    for r in data["ground_modes"]: grouped[r["phase"]][r["mode"]] += int(r["legs"])
    fig, ax = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    left = np.zeros(2); phases = ["access", "egress"]
    for mode in modes:
        values = np.array([100*grouped[p][mode]/sum(grouped[p].values()) if sum(grouped[p].values()) else 0 for p in phases])
        ax.barh(np.arange(2), values, left=left, color=mode_colors[mode], label=mode.replace("_", " ").title()); left += values
    ax.set_yticks(np.arange(2), ["Access", "Egress"]); ax.invert_yaxis(); ax.set_xlabel("Share of substantive legs (%)")
    ax.set_title("Access and egress mode share", loc="left", fontweight="bold"); ax.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(.5, -.14)); style_axis(ax, "x")
    save(fig, "13-access-egress-modes.png")

    waits = {r["cumulative_share_pct"]: r["wait_minutes"] for r in data["wait_time_distribution"]}
    fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True); box_plot(ax, waits, m["wait_mean_min"], COLOR, "User wait time for aircraft pickup (minutes)")
    ax.set_title("AAM user wait-time box plot", loc="left", fontweight="bold"); save(fig, "14-user-wait-time.png")


def main():
    HERE.mkdir(parents=True, exist_ok=True); GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    data = build_metrics(); render(data)
    print(json.dumps(data["metrics"], indent=2))
    print(f"Rendered 14 graphs in {GRAPH_DIR}")


if __name__ == "__main__":
    main()
