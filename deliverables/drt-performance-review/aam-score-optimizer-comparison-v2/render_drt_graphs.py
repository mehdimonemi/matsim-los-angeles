"""Render labeled PNG figures for the four DRT optimizer results."""

from pathlib import Path
import csv
import json
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
    """Retry transient Windows file-handle errors while replacing generated PNGs."""
    for attempt in range(5):
        try:
            fig.savefig(path, **kwargs)
            return
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.25)


def export_individual_axes(fig, axes, names):
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    flat_axes = list(np.asarray(axes).flat)
    suptitle = getattr(fig, "_suptitle", None)
    if suptitle is not None:
        suptitle.set_visible(False)
    for ax, name in zip(flat_axes, names):
        for other_ax in flat_axes:
            other_ax.set_visible(other_ax is ax)
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
    fig.suptitle("DRT optimizer performance: demand, score, service, and journey time",
                 fontsize=18, fontweight="bold")
    x = np.arange(4)

    ax = axes[0, 0]
    completed = [d["completed_users"] for d in M]
    completed_trips = [d["completed_trips"] for d in M]
    width = .36
    user_bars = ax.bar(x - width/2, completed, width, color=COLORS,
                       label="Completed distinct AAM users")
    trip_bars = ax.bar(x + width/2, completed_trips, width, color=COLORS,
                       alpha=.45, hatch="//", edgecolor=COLORS,
                       label="Completed AAM trips")
    label_bars(ax, user_bars, [f"{value:,}" for value in completed], dy=4)
    label_bars(ax, trip_bars, [f"{value:,}" for value in completed_trips], dy=4)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Users and trips (count)")
    ax.set_title("A. Completed AAM users and trips", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper center",
              bbox_to_anchor=(.5, -.12))
    style_axis(ax)

    ax = axes[0, 1]
    users = [d["completed_users"] for d in M]
    scores = [d["final_aam_score_mean"] for d in M]
    for i, d in enumerate(M):
        ax.scatter(users[i], scores[i], s=150, color=COLORS[i], zorder=3)
        ax.annotate(NAMES[i], (users[i], scores[i]), xytext=(7, 7),
                    textcoords="offset points", fontsize=10, fontweight="bold")
    ax.set_xlabel("Completed distinct AAM users")
    ax.set_ylabel("Mean final AAM-user score (higher is better)")
    ax.set_title("B. Adoption versus AAM-user score", loc="left", fontweight="bold")
    style_axis(ax)

    ax = axes[1, 0]
    rejection = [d["rejection_rate_pct"] for d in M]
    bars = ax.bar(x, rejection, color=COLORS)
    labels = [f"{d['rejection_rate_pct']:.0f}% rejected\nMean aircraft wait: {d['wait_mean_min']:.1f} min"
              for d in M]
    for i, (bar, label) in enumerate(zip(bars, labels)):
        x_offset = -0.10 if i == 1 else (0.10 if i == 2 else 0)
        ax.annotate(label, (bar.get_x() + bar.get_width()/2 + x_offset, bar.get_height()),
                    xytext=(0, 4), textcoords="offset points", ha="center", va="bottom",
                    fontsize=9, fontweight="bold")
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Rejected requests (%)")
    ax.set_ylim(0, max(11, max(rejection) * 1.24))
    ax.set_title("C. Request rejection and aircraft wait", loc="left", fontweight="bold")
    style_axis(ax)

    ax = axes[1, 1]
    ground = np.array([d["ground_mean_min"] for d in M]) / 60
    wait = np.array([d["wait_mean_min"] for d in M]) / 60
    onboard = np.array([d["air_onboard_mean_min"] for d in M]) / 60
    y = np.arange(4)
    ax.barh(y, ground, color="#2A9D8F", label="Ground access + egress")
    ax.barh(y, wait, left=ground, color="#E9C46A", label="Aircraft wait")
    ax.barh(y, onboard, left=ground+wait, color="#E76F51", label="Onboard")
    totals = ground + wait + onboard
    for i, d in enumerate(M):
        ax.text(totals[i]+.08, i, f"{totals[i]:.1f} h total\n{d['ground_distance_mean_miles']:.1f} ground miles",
                va="center", fontsize=10, fontweight="bold")
    ax.set_yticks(y, NAMES)
    ax.invert_yaxis()
    ax.set_ylim(3.45, -0.35)
    ax.set_xlabel("Mean end-to-end journey time (hours)")
    ax.set_title("D. Journey composition: ground travel dominates", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=9, loc="upper left", bbox_to_anchor=(0, -.14), ncol=3)
    ax.grid(axis="x", alpha=.22)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(0, 10.8)

    save(fig, "drt-core-performance.png", axes,
         ["01-completed-users.png", "02-adoption-vs-score.png",
          "03-rejection-and-wait.png", "04-journey-composition.png"])


def fleet_and_market():
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), constrained_layout=True)
    fig.suptitle("DRT optimizer performance: aircraft use, productivity, fare, and network",
                 fontsize=18, fontweight="bold")
    x = np.arange(4)

    ax = axes[0, 0]
    bottom = np.zeros(4)
    occ_colors = ["#B23A48", "#E9C46A", "#8AB17D", "#2A9D8F", "#176B61"]
    for pax in range(5):
        vals = np.array([d[f"occupancy_{pax}_pct"] for d in M])
        ax.bar(x, vals, bottom=bottom, color=occ_colors[pax], label=f"{pax} passenger{'s' if pax != 1 else ''}")
        bottom += vals
    for i, d in enumerate(M):
        ax.text(i, 102, f"{d['occupancy_4_pct']:.0f}% full", ha="center", fontsize=10, fontweight="bold")
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Share of AAM distance (%)")
    ax.set_ylim(0, 110)
    ax.set_title("A. Distance by passenger occupancy", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8, ncol=5, loc="upper center",
              bbox_to_anchor=(.5, -.12))
    style_axis(ax)

    ax = axes[0, 1]
    miles_ride = [d["vehicle_km_per_ride"] * 0.621371 for d in M]
    bars = ax.bar(x, miles_ride, color=COLORS)
    labels = [f"{d['vehicle_km_per_ride'] * 0.621371:.1f} aircraft miles / trip\nDWO: {d['passenger_km_per_vehicle_km']:.2f}\nEmpty flight distance: {d['fleet_empty_ratio_pct']:.0f}%"
              for d in M]
    for i, (bar, label) in enumerate(zip(bars, labels)):
        offset = 22 if i == 0 else (-18 if i == 3 else 0)
        ax.annotate(label, (bar.get_x() + bar.get_width()/2, bar.get_height()),
                    xytext=(offset, 4), textcoords="offset points", ha="center", va="bottom",
                    fontsize=9, fontweight="bold")
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Aircraft miles flown per completed passenger trip")
    ax.set_xlabel("DWO = passenger-miles traveled ÷ aircraft miles flown\n(distance-weighted average passengers onboard)")
    ax.set_ylim(0, 6.5)
    ax.set_title("B. Fleet productivity and pooling", loc="left", fontweight="bold")
    style_axis(ax)

    ax = axes[1, 0]
    means = [d["fare_mean_usd"] for d in M]
    fare_by_method = defaultdict(dict)
    for row in DATA["fare_distribution"]:
        fare_by_method[row["method"]][row["cumulative_share_pct"]] = row["fare_usd"]
    minimums = [fare_by_method[d["method"]][0] for d in M]
    maximums = [fare_by_method[d["method"]][100] for d in M]
    y = np.arange(4) * 1.35
    for i, value in enumerate(means):
        values = fare_by_method[M[i]["method"]]
        q1, median_value, q3, p95 = values[25], values[50], values[75], values[95]
        ax.hlines(y[i], minimums[i], maximums[i], color=COLORS[i], linewidth=2.5)
        ax.hlines(y[i], q1, q3, color=COLORS[i], linewidth=10, alpha=.55)
        ax.scatter([minimums[i], maximums[i]], [y[i], y[i]], color=COLORS[i],
                   marker="|", s=180, linewidths=2.5, zorder=3)
        ax.scatter(median_value, y[i], facecolor="white", edgecolor=COLORS[i],
                   marker="D", s=65, linewidth=2, zorder=4)
        ax.scatter(value, y[i], color=COLORS[i], marker="o", s=65, zorder=4)
        ax.scatter(p95, y[i], color=COLORS[i], marker="^", s=70, zorder=4)
        ax.annotate(f"Min ${minimums[i]:.0f}", (minimums[i], y[i]), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", fontsize=8)
        ax.annotate(f"Avg ${value:.0f}", (value, y[i]), xytext=(0, 8),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=9, fontweight="bold")
        ax.annotate(f"P95 ${p95:.0f}", (p95, y[i]), xytext=(0, 8),
                    textcoords="offset points", ha="center", va="bottom", fontsize=8)
        ax.annotate(f"Max ${maximums[i]:.0f}", (maximums[i], y[i]), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", fontsize=8)
    ax.set_yticks(y, NAMES)
    ax.invert_yaxis()
    ax.set_ylim(y[-1] + .55, -.35)
    ax.set_xlabel("Estimated fare (USD)")
    ax.set_ylabel("Optimizer")
    fare_span = max(maximums) - min(minimums)
    ax.set_xlim(min(minimums) - .04 * fare_span, max(maximums) + .04 * fare_span)
    ax.set_title("C. Fare box plot", loc="left", fontweight="bold")
    ax.grid(axis="x", alpha=.22, linewidth=.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=10)

    ax = axes[1, 1]
    corridors = [d["corridors_used"] for d in M]
    top3 = [d["top3_corridor_share_pct"] for d in M]
    sizes = [d["air_distance_mean_miles"]*18 for d in M]
    for i in range(4):
        ax.scatter(corridors[i], top3[i], s=sizes[i], color=COLORS[i], alpha=.9)
        yoff = -25 if NAMES[i] == "One-VP k10" else 5
        ax.annotate(f"{NAMES[i]}\n{M[i]['air_distance_mean_miles']:.1f} air mi",
                    (corridors[i], top3[i]), xytext=(7, yoff), textcoords="offset points",
                    fontsize=9, fontweight="bold")
    ax.set_xlabel("Distinct used corridors")
    ax.set_ylabel("Top-three corridor share (%)")
    ax.set_title("D. Network diversification (right and down is broader)", loc="left", fontweight="bold")
    ax.set_ylim(25.5, 47.2)
    style_axis(ax)

    save(fig, "drt-fleet-network-performance.png", axes,
         ["05-aam-distance-by-passenger-count.png", "06-fleet-productivity.png",
          "07-fare-distribution.png", "08-network-diversification.png"])


def search_and_time():
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), constrained_layout=True)
    fig.suptitle("DRT optimizer performance: search behavior, time of day, and user income",
                 fontsize=18, fontweight="bold")
    x = np.arange(4)

    ax = axes[0, 0]
    grouped = {method: [] for method in [d["method"] for d in M]}
    for r in DATA["stages"]:
        grouped[r["method"]].append(r)
    for i, d in enumerate(M):
        values = sorted(grouped[d["method"]], key=lambda r:r["stage"])
        ax.plot([r["stage"] for r in values], [r["aam_users"] for r in values],
                marker="o", linewidth=2.3, color=COLORS[i], label=NAMES[i])
        ax.text(8.08, values[-1]["aam_users"], f"{NAMES[i]} {values[-1]['aam_users']:,}",
                va="center", fontsize=9, fontweight="bold")
    ax.set_xlabel("")
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.set_ylabel("Scored AAM-plan users (not completed users)")
    ax.set_title("A. Scored AAM-plan users over eight optimizer stages", loc="left", fontweight="bold")
    ax.set_xlim(.8, 9.4)
    style_axis(ax)

    ax = axes[0, 1]
    seconds = [d["optimizer_seconds"] for d in M]
    bars = ax.bar(x, seconds, color=COLORS)
    labels = [f"{d['optimizer_seconds']:.0f}s\n{d['moves_evaluated']:,} moves\n{d['new_sites']} new sites" for d in M]
    label_bars(ax, bars, labels)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Optimizer time (seconds)")
    ax.set_title("B. Search cost and layout turnover", loc="left", fontweight="bold")
    ax.set_ylim(0, 235)
    style_axis(ax)

    ax = axes[1, 0]
    by_method = defaultdict(list)
    for r in DATA["hours"]:
        by_method[r["method"]].append(r)
    for i, d in enumerate(M):
        values = sorted(by_method[d["method"]], key=lambda r:r["hour"])
        ax.plot([r["hour"] for r in values], [r["mean_wait_min"] for r in values],
                linewidth=2.0, color=COLORS[i], label=NAMES[i])
    ax.set_xlabel("Aircraft departure hour")
    ax.set_ylabel("Mean aircraft wait (minutes)")
    ax.set_title("C. Wait time by hour", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=9, ncol=2)
    style_axis(ax)

    ax = axes[1, 1]
    incomes = [d["income_user_median_usd"]/1000 for d in M]
    bars = ax.bar(x, incomes, color=COLORS)
    ax.axhline(M[0]["income_population_median_usd"]/1000, color="black", linestyle="--", linewidth=1.5,
               label="Population median $65.6k")
    labels = [f"${d['income_user_median_usd']/1000:.1f}k\n{d['income_user_ge_100k_pct']:.0f}% ≥$100k" for d in M]
    label_bars(ax, bars, labels)
    ax.set_xticks(x, NAMES)
    ax.set_ylabel("Median household income ($000)")
    ax.set_ylim(0, 78)
    ax.set_title("D. AAM-user income", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=9)
    style_axis(ax)

    save(fig, "drt-search-time-equity.png", axes,
         ["09-search-stage-users.png", "10-search-cost.png",
          "11-wait-by-hour.png", "12-user-income.png"])


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
        ax.annotate(f"Min {minimum:.1f}", (minimum, y[i]), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", fontsize=8)
        ax.annotate(f"Avg {average:.1f}", (average, y[i]), xytext=(0, 8),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=9, fontweight="bold")
        ax.annotate(f"P95 {p95:.1f}", (p95, y[i]), xytext=(0, 8),
                    textcoords="offset points", ha="center", va="bottom", fontsize=8)
        ax.annotate(f"Max {maximum:.1f}", (maximum, y[i]), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", fontsize=8)
    ax.set_yticks(y, NAMES)
    ax.invert_yaxis()
    ax.set_ylim(y[-1] + .55, -.35)
    ax.set_xlabel("User wait time for aircraft pickup (minutes)")
    ax.set_ylabel("Optimizer")
    wait_span = max(values[100] for values in wait_by_method.values())
    ax.set_xlim(-.04 * wait_span, 1.06 * wait_span)
    ax.set_title("AAM user wait-time box plot", loc="left", fontweight="bold")
    ax.grid(axis="x", alpha=.22, linewidth=.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=10)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    save_png(fig, GRAPH_DIR / "14-user-wait-time.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    save_png(fig, HERE / "drt-user-wait-time.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    plt.close(fig)


def access_egress_modes():
    rows = DATA["ground_modes"]
    methods = [d["method"] for d in M]
    phases = ["access", "egress"]
    preferred_modes = ["walk", "car", "bike", "ride", "ride_taxi"]
    present_modes = {r["mode"] for r in rows}
    modes = [mode for mode in preferred_modes if mode in present_modes]
    modes.extend(sorted(present_modes - set(modes)))
    mode_colors = {
        "walk": "#2A9D8F", "car": "#C66A2B", "bike": "#E9C46A",
        "ride": "#526D82", "ride_taxi": "#7A5195",
    }
    grouped = defaultdict(dict)
    for r in rows:
        grouped[(r["method"], r["phase"])][r["mode"]] = int(r["legs"])

    fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)
    y = np.arange(len(methods) * len(phases))
    labels = []
    left = np.zeros(len(y))
    row_values = []
    for method, display_name in zip(methods, NAMES):
        for phase in phases:
            counts = grouped[(method, phase)]
            total = sum(counts.values())
            shares = {mode: (100 * counts.get(mode, 0) / total if total else 0) for mode in modes}
            row_values.append(shares)
            labels.append(f"{display_name} — {phase}")
    for mode in modes:
        values = np.array([row[mode] for row in row_values])
        ax.barh(y, values, left=left, color=mode_colors.get(mode, "#999999"),
                label=mode.replace("_", " ").title())
        left += values
    for i, shares in enumerate(row_values):
        def share_label(mode, share):
            value = "<0.1%" if 0 < share < 0.05 else f"{share:.1f}%"
            return f"{mode.replace('_', ' ').title()} {value}"
        summary = " · ".join(share_label(mode, share)
                             for mode, share in shares.items() if share > 0)
        ax.text(101, i, summary, va="center", fontsize=9, fontweight="bold")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 142)
    ax.set_xlabel("Share of substantive access/egress legs (%)")
    ax.set_title("Access and egress mode share", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=max(1, len(modes)), loc="upper center",
              bbox_to_anchor=(.5, -.10))
    ax.grid(axis="x", alpha=.22)
    ax.spines[["top", "right"]].set_visible(False)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    save_png(fig, GRAPH_DIR / "13-access-egress-modes.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    save_png(fig, HERE / "drt-access-egress-modes.png", dpi=180,
             bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    core_performance()
    fleet_and_market()
    search_and_time()
    access_egress_modes()
    user_wait_time()
    print("Rendered five overview figures and fourteen separate graphs in", HERE)
