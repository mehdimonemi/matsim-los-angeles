"""Analyze scheduled AAM embedded in MATSim public-transit routes."""
import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree.ElementTree import iterparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PREFIX = "aam_sched_"


def open_text(path):
    return gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else open(path, encoding="utf-8")


def seconds(value):
    if not value or value in ("undefined", "null"):
        return math.nan
    if ":" in value:
        h, m, s = value.split(":")
        return float(h) * 3600 + float(m) * 60 + float(s)
    return float(value)


def save_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_trips(path):
    with open_text(path) as stream:
        return list(csv.DictReader(stream, delimiter=";"))


def route_data(leg):
    route = leg.find("route")
    if route is None:
        return {}, None
    text = (route.text or "").strip()
    if route.get("type") == "default_pt" and text.startswith("{"):
        return json.loads(text), route
    return {}, route


def selected_aam_journeys(plans):
    rows = []
    with open_text(plans) as stream:
        for _, person in iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            attributes = {a.get("name"): (a.text or "") for a in person.findall("./attributes/attribute")}
            for plan in person.findall("plan"):
                if plan.get("selected", "yes").lower() not in ("yes", "true", "1"):
                    continue
                groups, legs = [], []
                for element in plan:
                    if element.tag in ("activity", "act") and not element.get("type", "").lower().endswith(" interaction"):
                        if legs:
                            groups.append(legs)
                            legs = []
                    elif element.tag == "leg":
                        data, route = route_data(element)
                        dep = seconds(element.get("dep_time"))
                        duration = seconds(element.get("trav_time") or (route.get("trav_time") if route is not None else None))
                        legs.append({"mode": element.get("mode", ""), "dep": dep, "duration": duration,
                                     "route": data, "is_aam": data.get("transitLineId", "").startswith(PREFIX + "line_")})
                if legs:
                    groups.append(legs)
                for trip_number, group in enumerate(groups, 1):
                    indices = [i for i, leg in enumerate(group) if leg["is_aam"]]
                    if not indices:
                        continue
                    access, egress = group[:indices[0]], group[indices[-1] + 1:]
                    aam_legs = [group[i] for i in indices]
                    def duration(items):
                        return sum(x["duration"] for x in items if math.isfinite(x["duration"])) / 60
                    def modes(items):
                        return "+".join(x["mode"] for x in items) or "(none)"
                    waits = []
                    onboard = []
                    corridors = []
                    for leg in aam_legs:
                        boarding = seconds(leg["route"].get("boardingTime"))
                        wait = max(0, boarding - leg["dep"]) if math.isfinite(boarding) and math.isfinite(leg["dep"]) else math.nan
                        waits.append(wait)
                        onboard.append(max(0, leg["duration"] - wait) if math.isfinite(leg["duration"]) and math.isfinite(wait) else math.nan)
                        corridors.append(leg["route"]["transitLineId"].replace(PREFIX + "line_", ""))
                    rows.append({
                        "person": person.get("id"), "trip_number": str(trip_number), "aam_flight_legs": len(aam_legs),
                        "corridors": "+".join(corridors), "access_modes": modes(access), "egress_modes": modes(egress),
                        "access_minutes_planned": round(duration(access), 3), "egress_minutes_planned": round(duration(egress), 3),
                        "aam_wait_minutes_planned": round(sum(x for x in waits if math.isfinite(x)) / 60, 3),
                        "aam_onboard_minutes_planned": round(sum(x for x in onboard if math.isfinite(x)) / 60, 3),
                        "journey_minutes_planned": round(duration(group), 3), "household_income_usd": attributes.get("hhinc", "")
                    })
            person.clear()
    return rows


def event_operations(events):
    vehicles, drivers, board_time, waiting = {}, set(), {}, {}
    flights, corridor_departures, corridor_boardings = [], Counter(), Counter()
    with open_text(events) as stream:
        for _, event in iterparse(stream, events=("end",)):
            a = event.attrib
            kind = a.get("type")
            if kind == "TransitDriverStarts" and a.get("vehicleId", "").startswith(PREFIX + "vehicle_"):
                vehicle = a["vehicleId"]
                corridor = a["transitLineId"].replace(PREFIX + "line_", "")
                vehicles[vehicle] = corridor
                drivers.add(a["driverId"])
                corridor_departures[corridor] += 1
            elif kind == "waitingForPt":
                waiting[a.get("agent")] = float(a["time"])
            elif kind == "PersonEntersVehicle" and a.get("vehicle") in vehicles and a.get("person") not in drivers:
                key = (a["person"], a["vehicle"])
                board_time[key] = float(a["time"])
                corridor_boardings[vehicles[a["vehicle"]]] += 1
            elif kind == "PersonLeavesVehicle":
                key = (a.get("person"), a.get("vehicle"))
                if key in board_time:
                    entered = board_time.pop(key)
                    flights.append({"person": key[0], "vehicle": key[1], "corridor": vehicles[key[1]],
                                    "board_time": entered, "alight_time": float(a["time"]),
                                    "wait_minutes_observed": round((entered - waiting.get(key[0], entered)) / 60, 3),
                                    "onboard_minutes_observed": round((float(a["time"]) - entered) / 60, 3)})
            event.clear()
    return flights, corridor_departures, corridor_boardings


def aircraft_seats(vehicles_path):
    with open_text(vehicles_path) as stream:
        for _, element in iterparse(stream, events=("end",)):
            if element.tag.endswith("vehicleType") and element.get("id") == PREFIX + "aircraft":
                capacity = next((x for x in element.iter() if x.tag.endswith("capacity")), None)
                return int(capacity.get("seats"))
            if element.tag.endswith("vehicleType"):
                element.clear()
    raise ValueError("Scheduled AAM aircraft type not found in transit vehicles")


def chart(path, title, labels, values, ylabel):
    fig, ax = plt.subplots(figsize=(max(7, len(labels) * .8), 4.5), layout="constrained")
    ax.bar(labels, values, color="#14828b")
    ax.set(title=title, ylabel=ylabel)
    ax.tick_params(axis="x", rotation=30)
    ax.grid(axis="y", alpha=.2)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trips", type=Path)
    parser.add_argument("plans", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("vehicles", type=Path)
    parser.add_argument("vertiports", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    journeys = selected_aam_journeys(args.plans)
    flights, departures, boardings = event_operations(args.events)
    seats = aircraft_seats(args.vehicles)
    trip_rows = read_trips(args.trips)
    trip_lookup = {(x["person"], x["trip_number"]): x for x in trip_rows}
    aam_trip_keys = {(x["person"], x["trip_number"]) for x in journeys}
    for journey in journeys:
        trip = trip_lookup.get((journey["person"], journey["trip_number"]), {})
        journey["completed_trip_minutes"] = round(seconds(trip.get("trav_time")) / 60, 3) if trip else ""
        journey["analysis_main_mode"] = trip.get("main_mode", "")

    journey_fields = ["person", "trip_number", "aam_flight_legs", "corridors", "access_modes", "egress_modes",
                      "access_minutes_planned", "egress_minutes_planned", "aam_wait_minutes_planned",
                      "aam_onboard_minutes_planned", "journey_minutes_planned", "completed_trip_minutes",
                      "analysis_main_mode", "household_income_usd"]
    save_csv(out / "scheduled_aam_journeys.csv", journeys, journey_fields)
    save_csv(out / "observed_aam_flights.csv", flights,
             ["person", "vehicle", "corridor", "board_time", "alight_time", "wait_minutes_observed", "onboard_minutes_observed"])

    mode_counts = Counter("scheduled_aam" if (x["person"], x["trip_number"]) in aam_trip_keys
                          else (x.get("main_mode") or "unknown") for x in trip_rows)
    save_csv(out / "mode_counts_with_scheduled_aam.csv",
             [{"mode": mode, "completed_trips": count, "share_pct": round(100 * count / len(trip_rows), 4)}
              for mode, count in mode_counts.most_common()], ["mode", "completed_trips", "share_pct"])
    chart(out / "mode_share_with_scheduled_aam.png", "Completed trips (scheduled AAM separated from PT)",
          list(mode_counts), list(mode_counts.values()), "Completed trips")

    corridor_rows = []
    for corridor in sorted(departures):
        dep, pax = departures[corridor], boardings[corridor]
        corridor_rows.append({"corridor": corridor, "scheduled_departures": dep, "passenger_boardings": pax,
                              "seat_capacity": dep * seats, "passenger_load_factor_pct": round(100 * pax / (dep * seats), 4)})
    save_csv(out / "corridor_utilization.csv", corridor_rows,
             ["corridor", "scheduled_departures", "passenger_boardings", "seat_capacity", "passenger_load_factor_pct"])

    matched = []
    if args.baseline:
        baseline = {(x["person"], x["trip_number"]): x for x in read_trips(args.baseline)}
        for journey in journeys:
            old = baseline.get((journey["person"], journey["trip_number"]))
            current = trip_lookup.get((journey["person"], journey["trip_number"]))
            if old and current:
                before, after = seconds(old["trav_time"]) / 60, seconds(current["trav_time"]) / 60
                matched.append({"person": journey["person"], "trip_number": journey["trip_number"],
                                "baseline_mode": old.get("longest_distance_mode", ""), "baseline_minutes": round(before, 3),
                                "scheduled_aam_minutes": round(after, 3), "change_minutes": round(after - before, 3)})
        save_csv(out / "matched_baseline_trips.csv", matched,
                 ["person", "trip_number", "baseline_mode", "baseline_minutes", "scheduled_aam_minutes", "change_minutes"])

    corridor_counts = Counter(f["corridor"] for f in flights)
    if corridor_counts:
        chart(out / "used_aam_corridors.png", "Observed scheduled-AAM passenger boardings by corridor",
              list(corridor_counts), list(corridor_counts.values()), "Passenger boardings")
    if flights:
        fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
        axes[0].hist([f["wait_minutes_observed"] for f in flights], bins=max(1, len(flights)), color="#2476aa")
        axes[0].set(title="Observed AAM wait", xlabel="Minutes", ylabel="Flight legs")
        axes[1].hist([f["onboard_minutes_observed"] for f in flights], bins=max(1, len(flights)), color="#e99535")
        axes[1].set(title="Observed AAM onboard time", xlabel="Minutes", ylabel="Flight legs")
        for axis in axes: axis.grid(axis="y", alpha=.2)
        fig.savefig(out / "aam_wait_and_onboard_time.png", dpi=150)
        plt.close(fig)

    ports = {}
    with args.vertiports.open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream): ports[row["id"]] = (float(row["x"]), float(row["y"]))
    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    for corridor, count in corridor_counts.items():
        origin, destination = corridor.split("_")
        ax.plot(*zip(ports[origin], ports[destination]), color="#00a6a6", linewidth=1 + count, alpha=.65)
    ax.scatter([p[0] for p in ports.values()], [p[1] for p in ports.values()], c="#163a5f", s=55, zorder=3)
    for name, point in ports.items(): ax.annotate(name, point, xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.set_aspect("equal"); ax.set_title("Scheduled-AAM passenger corridors"); ax.set_axis_off()
    fig.savefig(out / "vertiports_and_used_flights.png", dpi=150); plt.close(fig)

    total_departures, total_boardings = sum(departures.values()), len(flights)
    pt_trips = sum(1 for x in trip_rows if (x.get("main_mode") or "").startswith("pt"))
    def mean(field):
        values = [float(x[field]) for x in journeys]
        return round(float(np.mean(values)), 3) if values else None
    summary = {
        "all_completed_journeys": len(trip_rows),
        "scheduled_aam_journeys": len(journeys),
        "scheduled_aam_journey_share_pct": round(100 * len(journeys) / len(trip_rows), 4) if trip_rows else 0,
        "public_transit_journeys_including_aam": pt_trips,
        "scheduled_aam_share_of_public_transit_pct": round(100 * len(journeys) / pt_trips, 4) if pt_trips else 0,
        "scheduled_aam_flight_legs_planned": sum(int(x["aam_flight_legs"]) for x in journeys),
        "observed_passenger_flight_legs": total_boardings,
        "distinct_scheduled_aam_users": len({x["person"] for x in flights}),
        "operated_flights": total_departures,
        "aircraft_seats": seats,
        "offered_seat_capacity": total_departures * seats,
        "passenger_load_factor_pct": round(100 * total_boardings / (total_departures * seats), 4) if total_departures else 0,
        "occupied_flight_share_pct": round(100 * len({x["vehicle"] for x in flights}) / total_departures, 4) if total_departures else 0,
        "mean_observed_wait_minutes": round(float(np.mean([x["wait_minutes_observed"] for x in flights])), 3) if flights else None,
        "mean_observed_onboard_minutes": round(float(np.mean([x["onboard_minutes_observed"] for x in flights])), 3) if flights else None,
        "mean_planned_access_minutes": mean("access_minutes_planned"),
        "mean_planned_egress_minutes": mean("egress_minutes_planned"),
        "mean_completed_aam_journey_minutes": mean("completed_trip_minutes"),
        "matched_baseline_journeys": len(matched)
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "INTERPRETATION.txt").write_text(
        "Scheduled AAM is identified from transitLineId values beginning aam_sched_line_, not from the MATSim leg mode (which remains pt). "
        "A journey is a main-activity-to-main-activity trip; a passenger flight leg is one boarding of an AAM transit vehicle. "
        "Load factor is passenger boardings divided by all offered seats and is not a peak-load statistic. Baseline differences are uncontrolled comparisons.\n",
        encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("Saved outputs in", out)


if __name__ == "__main__":
    main()
