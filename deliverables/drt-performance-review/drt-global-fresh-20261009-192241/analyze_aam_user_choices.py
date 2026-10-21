"""Analyze executed AAM users, their plan alternatives, feeders, and daily tours."""

from __future__ import annotations

import csv
import gzip
import json
import math
import statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUN = ROOT / "run-output" / "drt-global-fresh-20261009-192241" / "final-convergence"
PREFIX = "la-aam-fare30-scoreopt"


def read_csv(name):
    with gzip.open(RUN / name, "rt", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter=";"))


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] if lo == hi else values[lo] * (hi - pos) + values[hi] * (pos - lo)


def summary(values):
    values = list(values)
    return {
        "mean": statistics.mean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p25": quantile(values, .25),
        "p75": quantile(values, .75),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def is_aam_trip(row):
    modes = set((row.get("modes") or "").split("-"))
    return bool({"aam", "aam_drt"} & modes) or row.get("main_mode") in {"aam", "aam_drt"}


def home(activity):
    return (activity or "").lower().startswith("home")


def plan_has_aam_marker(plan):
    for leg in plan.findall("leg"):
        if leg.get("mode") in {"aam", "aam_drt"}:
            return True
        for attr in leg.findall("./attributes/attribute"):
            if attr.get("name") == "routingMode" and (attr.text or "").strip() == "aam":
                return True
    return False


def plan_has_aircraft(plan):
    return any(leg.get("mode") == "aam_drt" for leg in plan.findall("leg"))


def plan_signature(plan):
    modes = []
    for leg in plan.findall("leg"):
        mode = leg.get("mode") or "unknown"
        if mode in {"aam", "aam_drt"}:
            mode = "aam"
        if mode not in {"walk", "access_egress_pt"} and mode not in modes:
            modes.append(mode)
    return "+".join(modes) if modes else "walk"


def plan_park_mode(plan):
    for attr in plan.findall("./attributes/attribute"):
        if attr.get("name") == "aam_park_mode":
            return (attr.text or "").strip() or None
    return None


def parse_plans(cohort=None):
    records = {}
    path = RUN / f"{PREFIX}.output_plans.xml.gz"
    with gzip.open(path, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            pid = person.get("id")
            if cohort is None or pid in cohort:
                plans = []
                for index, plan in enumerate(person.findall("plan"), 1):
                    has_aircraft = plan_has_aircraft(plan)
                    has_marker = plan_has_aam_marker(plan) or plan.get("type") == "aam"
                    plans.append({
                        "index": index,
                        "score": finite(plan.get("score")),
                        "selected": plan.get("selected") == "yes",
                        "aam": has_aircraft,
                        "aam_marker": has_marker,
                        "category": ("genuine_aam" if has_aircraft else
                                     "aam_marker_ground_fallback" if has_marker else "ground"),
                        "signature": plan_signature(plan),
                        "park_mode": plan_park_mode(plan),
                    })
                records[pid] = plans
            person.clear()
    return records


def main():
    trips = read_csv(f"{PREFIX}.output_trips.csv.gz")
    legs = read_csv(f"{PREFIX}.output_legs.csv.gz")
    persons = {r["person"]: r for r in read_csv(f"{PREFIX}.output_persons.csv.gz")}

    trips_by_person = defaultdict(list)
    for row in trips:
        row["is_aam"] = is_aam_trip(row)
        trips_by_person[row["person"]].append(row)
    for values in trips_by_person.values():
        values.sort(key=lambda r: (int(r["trip_number"]), r["dep_time"]))

    actual_users = {pid for pid, values in trips_by_person.items() if any(r["is_aam"] for r in values)}
    plans_by_person = parse_plans()
    post_selected_aam_users = {
        pid for pid, plans in plans_by_person.items()
        if any(plan["selected"] and plan["aam"] for plan in plans)
    }
    post_selected_aam_marker_users = {
        pid for pid, plans in plans_by_person.items()
        if any(plan["selected"] and plan["aam_marker"] for plan in plans)
    }
    selected_marker_only_users = post_selected_aam_marker_users - post_selected_aam_users
    passenger_users = {pid for pid, row in persons.items() if row.get("subpopulation") == "person"}
    freight_users = set(persons) - passenger_users
    any_marker_users = {pid for pid, plans in plans_by_person.items() if any(p["aam_marker"] for p in plans)}
    any_genuine_aam_users = {pid for pid, plans in plans_by_person.items() if any(p["aam"] for p in plans)}

    # Daily trip counts and modes.
    non_aam_counts, total_counts, aam_counts = [], [], []
    all_modes, non_aam_modes = Counter(), Counter()
    trip_count_rows = []
    aam_direction = Counter()
    homebound_modes = Counter()
    outbound_return_modes = Counter()
    outbound_return_people = set()
    no_later_home = 0
    for pid in sorted(actual_users):
        values = trips_by_person[pid]
        n_aam = sum(r["is_aam"] for r in values)
        n_non = len(values) - n_aam
        total_counts.append(len(values)); aam_counts.append(n_aam); non_aam_counts.append(n_non)
        trip_count_rows.append({"person": pid, "total_trips": len(values), "aam_trips": n_aam,
                                "non_aam_trips": n_non, "executed_score": persons[pid]["executed_score"]})
        for row in values:
            mode = "aam" if row["is_aam"] else row["main_mode"]
            all_modes[mode] += 1
            if not row["is_aam"]:
                non_aam_modes[mode] += 1
            if home(row["end_activity_type"]):
                homebound_modes[mode] += 1
            if row["is_aam"]:
                direction = "home → non-home" if home(row["start_activity_type"]) and not home(row["end_activity_type"]) else (
                    "non-home → home" if not home(row["start_activity_type"]) and home(row["end_activity_type"]) else "non-home → non-home")
                aam_direction[direction] += 1
        # For each AAM departure from home, find the next trip that ends at home.
        for i, row in enumerate(values):
            if not row["is_aam"] or not home(row["start_activity_type"]) or home(row["end_activity_type"]):
                continue
            later = next((candidate for candidate in values[i + 1:] if home(candidate["end_activity_type"])), None)
            if later is None:
                no_later_home += 1
            else:
                mode = "aam" if later["is_aam"] else later["main_mode"]
                outbound_return_modes[mode] += 1
                outbound_return_people.add(pid)

    # Access and egress around the actually executed aircraft leg.
    legs_by_trip = defaultdict(list)
    for leg in legs:
        legs_by_trip[leg["trip_id"]].append(leg)
    access_modes, egress_modes = Counter(), Counter()
    access_sequences, egress_sequences = Counter(), Counter()
    for row in trips:
        if not row["is_aam"]:
            continue
        group = legs_by_trip[row["trip_id"]]
        positions = [i for i, leg in enumerate(group) if leg["mode"] == "aam_drt"]
        if not positions:
            continue
        before, after = group[:positions[0]], group[positions[-1] + 1:]
        def substantive(items):
            result = []
            for leg in items:
                distance = finite(leg.get("distance")) or 0
                if leg["mode"] == "walk" and distance <= .01:
                    continue
                result.append(leg["mode"])
            return result
        a, e = substantive(before), substantive(after)
        access_sequences[" + ".join(a) if a else "none"] += 1
        egress_sequences[" + ".join(e) if e else "none"] += 1
        access_modes.update(a); egress_modes.update(e)

    # Compare scored AAM and ground alternatives for the actual-flyer cohort.
    plan_rows = []
    park_modes = Counter()
    for pid in sorted(actual_users):
        plans = plans_by_person.get(pid, [])
        for p in plans:
            plan_rows.append({"person": pid, **p})
            if p["aam"] and p["park_mode"]:
                park_modes[p["park_mode"]] += 1

    def compare_cohort(cohort, include_executed=False):
        selected_kind, best_ground_signatures = Counter(), Counter()
        best_deltas, selected_deltas, executed_gaps, plan_counts = [], [], [], []
        with_both = 0
        for pid in cohort:
            plans = plans_by_person.get(pid, [])
            plan_counts.append(len(plans))
            selected = next((p for p in plans if p["selected"]), None)
            if selected:
                selected_kind["AAM"] += selected["aam"]
                selected_kind["ground"] += not selected["aam"]
            aam_scored = [p for p in plans if p["aam"] and p["score"] is not None]
            # Marker-only "AAM" plans physically contain no aircraft leg and are
            # therefore treated as ground fallbacks in behavioral comparisons.
            ground_scored = [p for p in plans if not p["aam"] and p["score"] is not None]
            if not aam_scored or not ground_scored:
                continue
            with_both += 1
            best_aam = max(aam_scored, key=lambda p: p["score"])
            best_ground = max(ground_scored, key=lambda p: p["score"])
            best_ground_signatures[best_ground["signature"]] += 1
            best_deltas.append(best_aam["score"] - best_ground["score"])
            if selected and selected["aam"] and selected["score"] is not None:
                selected_deltas.append(selected["score"] - best_ground["score"])
            if include_executed:
                executed = finite(persons[pid]["executed_score"])
                if executed is not None:
                    executed_gaps.append(executed - best_ground["score"])
        return {
            "users": len(cohort),
            "users_with_scored_aam_and_ground_options": with_both,
            "plans_per_user": summary(plan_counts),
            "post_iteration_selected_plan": dict(selected_kind),
            "best_aam_minus_best_ground_score": summary(best_deltas),
            "selected_aam_minus_best_ground_score": summary(selected_deltas),
            "share_best_aam_score_above_best_ground_pct": 100 * sum(x > 0 for x in best_deltas) / len(best_deltas),
            "share_selected_aam_score_above_best_ground_pct": 100 * sum(x > 0 for x in selected_deltas) / len(selected_deltas),
            "executed_score_minus_best_ground_score": summary(executed_gaps) if include_executed else None,
            "best_ground_plan_signatures": best_ground_signatures.most_common(),
        }

    actual_comparison = compare_cohort(actual_users, include_executed=True)
    post_selected_comparison = compare_cohort(post_selected_aam_users)

    metrics = {
        "aam_opportunity_in_final_plan_memory": {
            "all_agents": len(persons),
            "passenger_agents": len(passenger_users),
            "freight_agents_excluded_from_aam_innovation": len(freight_users),
            "passengers_with_any_aam_marker_plan": len(any_marker_users & passenger_users),
            "passengers_with_any_genuine_aircraft_plan": len(any_genuine_aam_users & passenger_users),
            "passengers_with_only_marker_ground_fallbacks": len((any_marker_users - any_genuine_aam_users) & passenger_users),
            "passengers_with_no_aam_marker_plan": len(passenger_users - any_marker_users),
            "share_passengers_with_a_genuine_aircraft_plan_pct": 100 * len(any_genuine_aam_users & passenger_users) / len(passenger_users),
        },
        "state_distinction": {
            "actually_executed_aam_users_iteration_9": len(actual_users),
            "actually_executed_aam_trips_iteration_9": sum(aam_counts),
            "reported_selected_aam_marker_users": len(post_selected_aam_marker_users),
            "selected_plans_with_a_genuine_aircraft_leg": len(post_selected_aam_users),
            "selected_aam_marker_plans_that_are_ground_ride_fallbacks": len(selected_marker_only_users),
            "genuine_air_plan_users_served": len(actual_users & post_selected_aam_users),
            "genuine_air_plan_users_not_served": len(post_selected_aam_users - actual_users),
        },
        "daily_trips_actual_aam_users": {
            "total_trips_per_user": summary(total_counts),
            "aam_trips_per_user": summary(aam_counts),
            "non_aam_trips_per_user": summary(non_aam_counts),
            "non_aam_trip_count_distribution_users": dict(sorted(Counter(non_aam_counts).items())),
            "all_trip_modes": all_modes.most_common(),
            "non_aam_trip_modes": non_aam_modes.most_common(),
        },
        "home_and_return_behavior": {
            "aam_trip_directions": dict(aam_direction),
            "all_homebound_trip_modes_for_aam_users": dict(homebound_modes),
            "next_home_return_after_aam_departure_from_home": dict(outbound_return_modes),
            "people_with_identified_later_home_return": len(outbound_return_people),
            "aam_home_departures_without_later_home_arrival": no_later_home,
        },
        "executed_feeders": {
            "access_leg_modes": dict(access_modes),
            "egress_leg_modes": dict(egress_modes),
            "access_sequences": dict(access_sequences.most_common()),
            "egress_sequences": dict(egress_sequences.most_common()),
        },
        "plan_choice_for_actual_aam_users": {**actual_comparison,
            "aam_plan_private_vehicle_parking_attributes": dict(park_modes)},
        "plan_choice_for_selected_genuine_aam_users": post_selected_comparison,
    }

    with (HERE / "aam_user_trip_counts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=trip_count_rows[0].keys()); writer.writeheader(); writer.writerows(trip_count_rows)
    with (HERE / "aam_user_plan_alternatives.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=plan_rows[0].keys()); writer.writeheader(); writer.writerows(plan_rows)
    (HERE / "aam_user_choice_analysis.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
