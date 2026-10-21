"""Render labeled PNG figures for the four scheduled-AAM optimizer results."""

from pathlib import Path
import json
import math
import time
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
GRAPH_DIR = HERE / "graphs"
DATA = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
M = DATA["metrics"]
NAMES = ["Global", "All-VP k10", "One-VP k10", "Adaptive"]
COLORS = ["#526D82", "#007F73", "#C66A2B", "#7A5195"]

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
    "mathtext.fontset": "stix",
})


def style_axis(ax):
    ax.grid(axis="y", alpha=.22, linewidth=.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=10)


def label_bars(ax, bars, labels, dy=3):
    for bar, label in zip(bars, labels):
        ax.annotate(label, (bar.get_x() + bar.get_width()/2, bar.get_height()),
                    xytext=(0, dy), textcoords="offset points", ha="center", va="bottom",
                    fontsize=10, fontweight="bold")


def save_png(fig, path, **kwargs):
    for attempt in range(5):
        try:
            fig.savefig(path, **kwargs)
            return
        except OSError:
            if attempt == 4:
                raise
            time.sleep(.25)


def export_individual_axes(fig, axes, names):
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    flat_axes = list(np.asarray(axes).flat)
    suptitle = getattr(fig, "_suptitle", None)
    if suptitle is not None:
        suptitle.set_visible(False)
    for ax, name in zip(flat_axes, names):
        for other in flat_axes:
            other.set_visible(other is ax)
        original = ax.get_title(loc="left")
        if len(original) > 3 and original[1:3] == ". ":
            ax.set_title(original[3:], loc="left", fontweight="bold")
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        extent = ax.get_tightbbox(renderer).transformed(fig.dpi_scale_trans.inverted()).expanded(1.06, 1.16)
        save_png(fig, GRAPH_DIR / name, dpi=180, bbox_inches=extent, facecolor="white")
        ax.set_title(original, loc="left", fontweight="bold")
    for ax in flat_axes:
        ax.set_visible(True)
    if suptitle is not None:
        suptitle.set_visible(True)


def save(fig, name, axes, individual_names):
    export_individual_axes(fig, axes, individual_names)
    save_png(fig, HERE / name, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def core_performance():
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), constrained_layout=True)
    fig.suptitle("Scheduled AAM optimizer performance: demand, score, wait, and journey time",
                 fontsize=18, fontweight="bold")
    x = np.arange(4)

    ax = axes[0, 0]
    users = [d["completed_users"] for d in M]
    trips = [d["completed_trips"] for d in M]
    width = .36
    user_bars = ax.bar(x - width/2, users, width, color=COLORS,
                       label="Completed distinct AAM users")
    trip_bars = ax.bar(x + width/2, trips, width, color=COLORS, alpha=.45,
                       hatch="//", edgecolor=COLORS, label="Completed AAM trips")
    label_bars(ax, user_bars, [f"{v:,}" for v in users], dy=4)
    label_bars(ax, trip_bars, [f"{v:,}" for v in trips], dy=4)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Users and trips (count)")
    ax.set_title("A. Completed scheduled-AAM users and trips", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper center", bbox_to_anchor=(.5, -.12))
    style_axis(ax)

    ax = axes[0, 1]
    for i, d in enumerate(M):
        ax.scatter(d["completed_users"], d["final_aam_score_mean"], s=150,
                   color=COLORS[i], alpha=.95)
        ax.annotate(NAMES[i], (d["completed_users"], d["final_aam_score_mean"]),
                    xytext=(7, 5), textcoords="offset points", fontsize=9,
                    fontweight="bold")
    ax.set_xlabel("Completed distinct scheduled-AAM users")
    ax.set_ylabel("Mean final scheduled-AAM user score (higher is better)")
    ax.set_title("B. Adoption versus scheduled-AAM user score", loc="left", fontweight="bold")
    style_axis(ax)

    ax = axes[1, 0]
    long_wait = [d["wait_gt_30_pct"] for d in M]
    bars = ax.bar(x, long_wait, color=COLORS)
    labels = [f"{d['wait_gt_30_pct']:.0f}% >30 min\nMean {d['wait_mean_min']:.0f} min" for d in M]
    label_bars(ax, bars, labels)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("AAM legs waiting over 30 minutes (%)")
    ax.set_ylim(0, max(long_wait) * 1.25)
    ax.set_title("C. Scheduled-service wait exposure", loc="left", fontweight="bold")
    style_axis(ax)

    ax = axes[1, 1]
    ground = np.array([d["ground_mean_min"] / 60 for d in M])
    wait = np.array([d["wait_mean_min"] / 60 for d in M])
    onboard = np.array([d["air_onboard_mean_min"] / 60 for d in M])
    y = np.arange(4)
    ax.barh(y, ground, color="#2A9D8F", label="Ground access + egress")
    ax.barh(y, wait, left=ground, color="#E9C46A", label="Scheduled-AAM wait")
    ax.barh(y, onboard, left=ground+wait, color="#E76F51", label="Onboard")
    for i, d in enumerate(M):
        total = ground[i] + wait[i] + onboard[i]
        ax.text(total + .08, i, f"{total:.1f} h total\n{d['ground_distance_mean_miles']:.1f} ground miles",
                va="center", fontsize=9, fontweight="bold")
    ax.set_yticks(y, NAMES)
    ax.invert_yaxis()
    ax.set_xlabel("Mean end-to-end journey time (hours)")
    ax.set_title("D. Journey composition", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=9, loc="upper left", bbox_to_anchor=(0, -.14), ncol=3)
    ax.grid(axis="x", alpha=.22)
    ax.spines[["top", "right"]].set_visible(False)
    max_total = max(ground + wait + onboard)
    ax.set_xlim(0, max_total * 1.28)

    save(fig, "scheduled-core-performance.png", axes,
         ["01-completed-users.png", "02-adoption-vs-score.png",
          "03-wait-exposure.png", "04-journey-composition.png"])


def fleet_and_market():
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), constrained_layout=True)
    fig.suptitle("Scheduled AAM optimizer performance: aircraft use, productivity, fare, and network",
                 fontsize=18, fontweight="bold")
    x = np.arange(4)

    ax = axes[0, 0]
    bottom = np.zeros(4)
    occ_colors = ["#B23A48", "#E9C46A", "#8AB17D", "#2A9D8F", "#176B61"]
    by_method = defaultdict(dict)
    for row in DATA["occupancy"]:
        by_method[row["method"]][int(row["passengers"])] = row["distance_share_pct"]
    for pax in range(5):
        values = np.array([by_method[d["method"]].get(pax, 0) for d in M])
        ax.bar(x, values, bottom=bottom, color=occ_colors[pax],
               label=f"{pax} passenger{'s' if pax != 1 else ''}")
        bottom += values
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Share of scheduled aircraft distance (%)")
    ax.set_ylim(0, 100)
    ax.set_title("A. Scheduled aircraft distance by passenger count", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8, ncol=5, loc="upper center", bbox_to_anchor=(.5, -.12))
    style_axis(ax)

    ax = axes[0, 1]
    miles_per_trip = [d["aircraft_miles_per_trip"] for d in M]
    bars = ax.bar(x, miles_per_trip, color=COLORS)
    labels = [f"{d['aircraft_miles_per_trip']:.1f} mi/trip\nDWO {d['distance_weighted_occupancy']:.2f}\n{d['occupied_departure_pct']:.0f}% flights used" for d in M]
    label_bars(ax, bars, labels)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Scheduled aircraft miles per completed AAM trip")
    ax.set_xlabel("DWO = passenger-miles traveled ÷ scheduled aircraft miles\n(distance-weighted average passengers onboard)")
    ax.set_ylim(0, max(miles_per_trip) * 1.35)
    ax.set_title("B. Scheduled service productivity", loc="left", fontweight="bold")
    style_axis(ax)

    ax = axes[1, 0]
    ax.set_xlim(0, 1)
    ax.set_ylim(-.5, 3.5)
    ax.set_yticks(np.arange(4), NAMES)
    ax.invert_yaxis()
    for i in range(4):
        ax.hlines(i, .08, .92, color=COLORS[i], linewidth=3, alpha=.4)
        ax.text(.5, i, "No fare modeled", ha="center", va="center",
                fontsize=11, fontweight="bold", color=COLORS[i])
    ax.set_xticks([])
    ax.set_xlabel("The fixed-timetable scheduled-AAM model applies no DRT fare")
    ax.set_ylabel("Optimizer")
    ax.set_title("C. Fare box plot — not applicable", loc="left", fontweight="bold")
    ax.spines[["top", "right", "bottom"]].set_visible(False)

    ax = axes[1, 1]
    corridors = [d["corridors_used"] for d in M]
    top3 = [d["top3_corridor_share_pct"] for d in M]
    sizes = [d["air_distance_mean_miles"] * 18 for d in M]
    for i in range(4):
        ax.scatter(corridors[i], top3[i], s=sizes[i], color=COLORS[i], alpha=.9)
        ax.annotate(f"{NAMES[i]}\n{M[i]['air_distance_mean_miles']:.1f} air mi",
                    (corridors[i], top3[i]), xytext=(7, 5), textcoords="offset points",
                    fontsize=9, fontweight="bold")
    ax.set_xlabel("Distinct used scheduled-AAM corridors")
    ax.set_ylabel("Top-three corridor share (%)")
    ax.set_title("D. Network diversification (right and down is broader)", loc="left", fontweight="bold")
    style_axis(ax)

    save(fig, "scheduled-fleet-network-performance.png", axes,
         ["05-aam-distance-by-passenger-count.png", "06-service-productivity.png",
          "07-fare-not-applicable.png", "08-network-diversification.png"])


def search_and_time():
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), constrained_layout=True)
    fig.suptitle("Scheduled AAM optimizer performance: search, time of day, and user income",
                 fontsize=18, fontweight="bold")
    x = np.arange(4)

    ax = axes[0, 0]
    grouped = defaultdict(list)
    for row in DATA["stages"]:
        grouped[row["method"]].append(row)
    for i, d in enumerate(M):
        values = sorted(grouped[d["method"]], key=lambda r: r["stage"])
        ax.plot([r["stage"] for r in values], [r["aam_users"] for r in values],
                marker="o", linewidth=2.3, color=COLORS[i], label=NAMES[i])
        ax.text(8.08, values[-1]["aam_users"], f"{NAMES[i]} {values[-1]['aam_users']:,}",
                va="center", fontsize=9, fontweight="bold")
    ax.set_xlabel("")
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.set_ylabel("Scored scheduled-AAM-plan users")
    ax.set_title("A. Scored scheduled-AAM-plan users over eight optimizer stages", loc="left", fontweight="bold")
    ax.set_xlim(.8, 9.5)
    style_axis(ax)

    ax = axes[0, 1]
    seconds = [d["optimizer_seconds"] for d in M]
    bars = ax.bar(x, seconds, color=COLORS)
    labels = [f"{d['optimizer_seconds']:.0f}s\n{d['moves_evaluated']:,} moves\n{d['new_sites']} new sites" for d in M]
    label_bars(ax, bars, labels)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Optimizer time (seconds)")
    ax.set_title("B. Search cost and layout turnover", loc="left", fontweight="bold")
    ax.set_ylim(0, max(seconds) * 1.35)
    style_axis(ax)

    ax = axes[1, 0]
    by_method = defaultdict(list)
    for row in DATA["hours"]:
        by_method[row["method"]].append(row)
    for i, d in enumerate(M):
        values = sorted(by_method[d["method"]], key=lambda r: r["hour"])
        hours = [r["hour"] for r in values if math.isfinite(r["mean_wait_min"])]
        waits = [r["mean_wait_min"] for r in values if math.isfinite(r["mean_wait_min"])]
        ax.plot(hours, waits, marker="o", linewidth=2.0, color=COLORS[i], label=NAMES[i])
    ax.set_xlabel("User arrival hour at scheduled-AAM stop")
    ax.set_ylabel("Mean scheduled-AAM wait (minutes)")
    ax.set_title("C. User wait time by arrival hour", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=9, ncol=2)
    style_axis(ax)

    ax = axes[1, 1]
    incomes = [d["income_user_median_usd"] / 1000 for d in M]
    bars = ax.bar(x, incomes, color=COLORS)
    population_median = M[0]["income_population_median_usd"] / 1000
    ax.axhline(population_median, color="black", linestyle="--", linewidth=1.5,
               label=f"Population median ${population_median:.1f}k")
    labels = [f"${d['income_user_median_usd']/1000:.1f}k\n{d['income_user_ge_100k_pct']:.0f}% ≥$100k" for d in M]
    label_bars(ax, bars, labels)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Median household income ($000)")
    ax.set_ylim(0, max(incomes + [population_median]) * 1.18)
    ax.set_title("D. Scheduled-AAM user income", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=9)
    style_axis(ax)

    save(fig, "scheduled-search-time-equity.png", axes,
         ["09-search-stage-users.png", "10-search-cost.png",
          "11-wait-by-hour.png", "12-user-income.png"])


def access_egress_modes():
    rows = DATA["ground_modes"]
    methods = [d["method"] for d in M]
    phases = ["access", "egress"]
    preferred = ["walk", "car", "bike", "ride", "ride_taxi", "pt", "access_egress_pt"]
    present = {r["mode"] for r in rows}
    modes = [mode for mode in preferred if mode in present]
    modes.extend(sorted(present - set(modes)))
    mode_colors = {"walk": "#2A9D8F", "car": "#C66A2B", "bike": "#E9C46A",
                   "ride": "#526D82", "ride_taxi": "#7A5195", "pt": "#B23A48",
                   "access_egress_pt": "#8AB17D"}
    grouped = defaultdict(dict)
    for row in rows:
        grouped[(row["method"], row["phase"])][row["mode"]] = int(row["legs"])
    labels, row_values = [], []
    for method, display in zip(methods, NAMES):
        for phase in phases:
            counts = grouped[(method, phase)]
            total = sum(counts.values())
            row_values.append({mode: (100 * counts.get(mode, 0) / total if total else 0) for mode in modes})
            labels.append(f"{display} — {phase}")
    fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)
    y = np.arange(len(labels))
    left = np.zeros(len(y))
    for mode in modes:
        values = np.array([row[mode] for row in row_values])
        ax.barh(y, values, left=left, color=mode_colors.get(mode, "#999999"),
                label=mode.replace("_", " ").title())
        left += values
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of substantive access/egress legs (%)")
    ax.set_title("Scheduled-AAM access and egress mode share", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=max(1, min(4, len(modes))), loc="upper center",
              bbox_to_anchor=(.5, -.10))
    ax.grid(axis="x", alpha=.22)
    ax.spines[["top", "right"]].set_visible(False)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    save_png(fig, GRAPH_DIR / "13-access-egress-modes.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    save_png(fig, HERE / "scheduled-access-egress-modes.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    plt.close(fig)


def user_wait_time():
    wait_by_method = defaultdict(dict)
    for row in DATA["wait_time_distribution"]:
        wait_by_method[row["method"]][row["cumulative_share_pct"]] = row["wait_minutes"]
    fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)
    y = np.arange(4) * 1.35
    for i, d in enumerate(M):
        values = wait_by_method[d["method"]]
        minimum, q1, median_value = values[0], values[25], values[50]
        q3, p95, maximum = values[75], values[95], values[100]
        average = d["wait_mean_min"]
        ax.hlines(y[i], minimum, maximum, color=COLORS[i], linewidth=2.5)
        ax.hlines(y[i], q1, q3, color=COLORS[i], linewidth=10, alpha=.55)
        ax.scatter([minimum, maximum], [y[i], y[i]], color=COLORS[i],
                   marker="|", s=180, linewidths=2.5, zorder=3)
        ax.scatter(median_value, y[i], facecolor="white", edgecolor=COLORS[i],
                   marker="D", s=65, linewidth=2, zorder=4)
        ax.scatter(average, y[i], color=COLORS[i], marker="o", s=65, zorder=4)
        ax.scatter(p95, y[i], color=COLORS[i], marker="^", s=70, zorder=4)
        ax.annotate(f"Min {minimum:.0f}", (minimum, y[i]), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", fontsize=8)
        ax.annotate(f"Avg {average:.0f}", (average, y[i]), xytext=(0, 8),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=9, fontweight="bold")
        ax.annotate(f"P95 {p95:.0f}", (p95, y[i]), xytext=(0, 8),
                    textcoords="offset points", ha="center", va="bottom", fontsize=8)
        ax.annotate(f"Max {maximum:.0f}", (maximum, y[i]), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", fontsize=8)
    ax.set_yticks(y, NAMES)
    ax.invert_yaxis()
    ax.set_ylim(y[-1] + .55, -.35)
    ax.set_xlabel("Scheduled-AAM user wait time (minutes)")
    ax.set_ylabel("Optimizer")
    maximum_wait = max(values[100] for values in wait_by_method.values())
    ax.set_xlim(-.03 * maximum_wait, 1.06 * maximum_wait)
    ax.set_title("Scheduled-AAM user wait-time box plot", loc="left", fontweight="bold")
    ax.grid(axis="x", alpha=.22, linewidth=.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=10)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    save_png(fig, GRAPH_DIR / "14-user-wait-time.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    save_png(fig, HERE / "scheduled-user-wait-time.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    plt.close(fig)


def aam_share_time_window():
    grouped = defaultdict(dict)
    for row in DATA["aam_share_by_time_window"]:
        grouped[row["method"]][row["scope"]] = row
    methods = [d["method"] for d in M]
    x = np.arange(len(methods))
    width = .36
    fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)
    for offset, scope, alpha, hatch in [
        (-width / 2, "All trips", 1.0, None),
        (width / 2, "07:00–19:00", .45, "//"),
    ]:
        selected = [grouped[method][scope] for method in methods]
        values = [row["aam_share_pct"] for row in selected]
        bars = ax.bar(x + offset, values, width, color=COLORS, alpha=alpha,
                      hatch=hatch, edgecolor=COLORS, label=scope)
        labels = [f'{value:.2f}%\n({int(row["aam_trips"]):,}/{int(row["total_trips"]):,})'
                  for value, row in zip(values, selected)]
        label_bars(ax, bars, labels, dy=4)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Completed scheduled-AAM trips as share of person trips (%)")
    ax.set_title("Scheduled-AAM trip share: full day versus 07:00–19:00 departures",
                 loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(.5, -.10))
    ax.set_ylim(0, max(row["aam_share_pct"] for row in DATA["aam_share_by_time_window"]) * 1.23)
    style_axis(ax)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    save_png(fig, GRAPH_DIR / "15-aam-share-all-vs-0700-1900.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    save_png(fig, HERE / "scheduled-aam-share-all-vs-0700-1900.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    plt.close(fig)


def aam_trip_purposes():
    methods = [d["method"] for d in M]
    rows = DATA["aam_trip_purposes"]
    totals = defaultdict(int)
    by_method = defaultdict(dict)
    for row in rows:
        count = int(row["aam_trips"])
        totals[row["purpose"]] += count
        by_method[row["method"]][row["purpose"]] = count
    purposes = [purpose for purpose, _ in sorted(totals.items(), key=lambda item: -item[1])[:8]]
    categories = purposes + ["Other"]
    purpose_labels = {"HHmaintenance": "Household maintenance",
                      "personalmaintenance": "Personal maintenance",
                      "non-schoolescort": "Non-school escort"}
    palette = list(plt.get_cmap("tab20").colors[:len(categories)])
    fig, ax = plt.subplots(figsize=(13, 7), constrained_layout=True)
    y = np.arange(len(methods))
    left = np.zeros(len(methods))
    sample_sizes = []
    for method in methods:
        sample_sizes.append(sum(by_method[method].values()))
    for category, color in zip(categories, palette):
        values = []
        for method, denominator in zip(methods, sample_sizes):
            count = (sum(v for p, v in by_method[method].items() if p not in purposes)
                     if category == "Other" else by_method[method].get(category, 0))
            values.append(100 * count / denominator if denominator else 0)
        bars = ax.barh(y, values, left=left, color=color,
                       label=purpose_labels.get(category, category.title()))
        for i, (bar, value) in enumerate(zip(bars, values)):
            if value >= 4:
                ax.text(left[i] + value / 2, bar.get_y() + bar.get_height() / 2,
                        f"{value:.1f}%", ha="center", va="center", fontsize=8,
                        fontweight="bold")
        left += values
    ax.set_yticks(y, [f"{name}  (n={n:,})" for name, n in zip(NAMES, sample_sizes)])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of completed scheduled-AAM trips (%)")
    ax.set_title("Destination purposes of completed scheduled-AAM trips",
                 loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(.5, -.12))
    ax.grid(axis="x", alpha=.22)
    ax.spines[["top", "right"]].set_visible(False)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    save_png(fig, GRAPH_DIR / "16-aam-trip-purposes.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    save_png(fig, HERE / "scheduled-aam-trip-purposes.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    core_performance()
    fleet_and_market()
    search_and_time()
    access_egress_modes()
    user_wait_time()
    aam_share_time_window()
    aam_trip_purposes()
    print("Rendered seven overview figures and sixteen separate graphs in", HERE)
