#!/usr/bin/env python3
"""Whole-population score one-swap optimizer for scheduled AAM."""
from __future__ import annotations

import argparse
import gzip
import json
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from scripts.aam.score_optimizer.common import MILE, atomic_write_layout, distance_matrix, read_sites
from .population import PREFIX, is_main_activity, route_data

PERFORMING_UTIL_HR = 9.84
SCHEDULED_AAM_TRAVEL_UTIL_HR = -9.84
ACCESS_TRAVEL_UTIL_HR = 0.0
ACCESS_MONETARY_DISTANCE_RATE = 0.000104
MINIMUM_TRIP_METERS = 3 * MILE
MAXIMUM_GROUND_ACCESS_METERS = 5 * MILE
ROUTED_CANDIDATE_VERTIPORTS = 3


def _seconds(value: str | None) -> float:
    if not value:
        return math.nan
    try:
        fields = value.split(":")
        return (float(fields[0]) * 3600 + float(fields[1]) * 60 + float(fields[2])) if len(fields) == 3 else float(value)
    except ValueError:
        return math.nan


def _score(plan: ET.Element) -> float:
    try:
        value = float(plan.get("score", "nan"))
        return value if math.isfinite(value) else math.nan
    except ValueError:
        return math.nan


def _money_utility(person: ET.Element) -> float:
    values = {item.get("name"): item.text for item in person.findall("./attributes/attribute")}
    try:
        saved = float(values["marginalUtilityOfMoney"])
        if math.isfinite(saved) and saved >= 0:
            return saved
    except (KeyError, TypeError, ValueError):
        pass
    try:
        income, size = float(values["hhinc"]), float(values["hhsize"])
        return 35363.89 / (income / size) if income > 0 and size >= 1 else 1.0
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 1.0


def _stop_site(value: str | None) -> str | None:
    prefix = PREFIX + "stop_"
    return value[len(prefix):] if value and value.startswith(prefix) else None


def _scheduled_trips(plan: ET.Element) -> list[tuple]:
    elements = list(plan)
    result = []
    for index, leg in enumerate(elements):
        if leg.tag != "leg":
            continue
        data = route_data(leg)
        if not data.get("transitLineId", "").startswith(PREFIX + "line_"):
            continue
        before = next((item for item in reversed(elements[:index]) if is_main_activity(item)), None)
        after = next((item for item in elements[index + 1:] if is_main_activity(item)), None)
        if before is None or after is None or not all(key in before.attrib and key in after.attrib for key in ("x", "y")):
            continue
        segment_start = next((i + 1 for i, item in enumerate(elements[:index]) if item is before), index)
        first_leg = next((item for item in elements[segment_start:index + 1] if item.tag == "leg"), leg)
        departure = _seconds(first_leg.get("dep_time"))
        if not math.isfinite(departure):
            departure = _seconds(before.get("end_time"))
        result.append(((float(before.get("x")), float(before.get("y"))),
                       (float(after.get("x")), float(after.get("y"))),
                       _stop_site(data.get("accessFacilityId")), _stop_site(data.get("egressFacilityId")), departure))
    return result


def _ground_plan_trips(plan: ET.Element, money_utility: float, minimum_trip_meters: float) -> list[tuple]:
    """Estimate ground-trip disutility and expose trips without AAM plans."""
    mode_travel = {"car": 0.0, "ride": 0.0, "ride_taxi": 0.0, "pt": -9.84,
                   "walk": -19.68, "transit_walk": -19.68, "non_network_walk": -19.68,
                   "bike": -39.36, "access_egress_pt": 0.0, "scheduled_aam": -9.84}
    mode_constant = {"ride": -12.0, "ride_taxi": -2.85, "pt": -2.46,
                     "scheduled_aam": -2.46, "bike": -9.84}
    mode_money_per_meter = {"car": 0.000104, "ride": 0.000104,
                            "access_egress_pt": 0.000104, "ride_taxi": 0.0025}
    elements = list(plan)
    main = [i for i, element in enumerate(elements)
            if is_main_activity(element) and "interaction" not in element.get("type", "").lower()]
    result = []
    for start, end in zip(main, main[1:]):
        before, after = elements[start], elements[end]
        if not all(key in before.attrib and key in after.attrib for key in ("x", "y")):
            continue
        origin = (float(before.get("x")), float(before.get("y")))
        destination = (float(after.get("x")), float(after.get("y")))
        if math.dist(origin, destination) < minimum_trip_meters:
            continue
        legs = [item for item in elements[start + 1:end] if item.tag == "leg"]
        if not legs:
            continue
        departure = _seconds(legs[0].get("dep_time"))
        if not math.isfinite(departure):
            departure = _seconds(before.get("end_time"))
        ground_cost = 0.0
        complete_times = True
        for leg in legs:
            mode = leg.get("mode", "")
            route = leg.find("route")
            travel = _seconds(leg.get("trav_time"))
            if not math.isfinite(travel):
                travel = _seconds(route.get("trav_time") if route is not None else None)
            if not math.isfinite(travel):
                travel = 0.0
            if travel <= 0:
                complete_times = False
            try:
                distance = float(route.get("distance", "0")) if route is not None else 0.0
            except (TypeError, ValueError):
                distance = 0.0
            utility = mode_travel.get(mode, -9.84)
            ground_cost += (PERFORMING_UTIL_HR - utility) * travel / 3600.0
            ground_cost -= mode_constant.get(mode, 0.0)
            ground_cost += mode_money_per_meter.get(mode, 0.0) * distance * money_utility
        if not complete_times:
            continue
        result.append((origin, destination, departure, ground_cost))
    return result


@dataclass
class UserData:
    ids: list[str]
    origins: np.ndarray
    destinations: np.ndarray
    scores: np.ndarray
    money_utility: np.ndarray
    trip_person_index: np.ndarray
    current_origin_site: np.ndarray
    current_destination_site: np.ndarray
    ground_scores: np.ndarray
    departure_seconds: np.ndarray
    selected_scores: np.ndarray | None = None
    population_score_sum: float = 0.0
    population_count: int = 0
    ground_trip_costs: np.ndarray | None = None
    current_aam_plan_users: int = -1
    potential_new_aam_users: int = 0
    has_aam_plan_by_person: np.ndarray | None = None


def read_aam_users(population: Path, candidates: list[dict], minimum_trip_meters: float = MINIMUM_TRIP_METERS,
                   maximum_ground_access_meters: float = MAXIMUM_GROUND_ACCESS_METERS) -> UserData:
    """Read routed AAM options and the selected-score baseline for passengers."""
    index = {site["id"]: i for i, site in enumerate(candidates)}
    people, trips = [], []
    population_score_sum, population_count = 0.0, 0
    opener = gzip.open if population.suffix == ".gz" else open
    with opener(population, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            best, ground = None, -math.inf
            finite_scores, selected_score = [], math.nan
            selected_plan = None
            best_scored_plan = None
            for plan in person.findall("plan"):
                score, plan_trips = _score(plan), _scheduled_trips(plan)
                if not math.isfinite(score):
                    continue
                finite_scores.append(score)
                if plan.get("selected") == "yes":
                    selected_score = score
                    selected_plan = plan
                if best_scored_plan is None or score > best_scored_plan[0]:
                    best_scored_plan = (score, plan)
                if not plan_trips:
                    ground = max(ground, score)
                elif best is None or score > best[0]:
                    best = (score, plan_trips)
            subpopulation = person.findtext("./attributes/attribute[@name='subpopulation']") or "person"
            if subpopulation == "person" and finite_scores:
                if not math.isfinite(selected_score):
                    selected_score = max(finite_scores)
                population_score_sum += selected_score
                population_count += 1
            selected_plan = selected_plan or (best_scored_plan[1] if best_scored_plan else None)
            if selected_plan is not None:
                money_utility = _money_utility(person)
                from_aam_plan = False
                score_anchor = best[0] if best is not None else (
                    selected_score if math.isfinite(selected_score) else best_scored_plan[0])
                qualifying = []
                if best is not None:
                    qualifying = [trip for trip in best[1]
                                  if math.dist(trip[0], trip[1]) >= minimum_trip_meters
                                  and trip[2] in index
                                  and math.dist(trip[0], (candidates[index[trip[2]]]["x"],
                                                         candidates[index[trip[2]]]["y"])) <= maximum_ground_access_meters]
                trip_rows = [(origin, destination, index.get(origin_site, -1),
                              index.get(destination_site, -1), departure, math.nan)
                             for origin, destination, origin_site, destination_site, departure in qualifying]
                from_aam_plan = bool(trip_rows)
                if not trip_rows:
                    score_anchor = selected_score if math.isfinite(selected_score) else best_scored_plan[0]
                    trip_rows = [(origin, destination, -1, -1, departure, ground_cost)
                                 for origin, destination, departure, ground_cost in
                                 _ground_plan_trips(selected_plan, money_utility, minimum_trip_meters)]
                if trip_rows:
                    person_index = len(people)
                    people.append((person.get("id"), score_anchor, money_utility,
                                   ground if math.isfinite(ground) else math.nan, selected_score, from_aam_plan))
                    for origin, destination, origin_site, destination_site, departure, ground_cost in trip_rows:
                        trips.append((person_index, origin, destination, origin_site,
                                      destination_site, departure, ground_cost))
            person.clear()
    if not people:
        raise ValueError("no scored scheduled-AAM users or eligible AAM opportunities in population plans")
    return UserData([row[0] for row in people], np.asarray([row[1] for row in trips]),
                    np.asarray([row[2] for row in trips]), np.asarray([row[1] for row in people]),
                    np.asarray([row[2] for row in people]), np.asarray([row[0] for row in trips], dtype=int),
                    np.asarray([row[3] for row in trips], dtype=int), np.asarray([row[4] for row in trips], dtype=int),
                    np.asarray([row[3] for row in people]), np.asarray([row[5] for row in trips]),
                    np.asarray([row[4] for row in people]), population_score_sum, population_count,
                    np.asarray([row[6] for row in trips], dtype=float),
                    sum(bool(row[5]) for row in people), sum(not bool(row[5]) for row in people),
                    np.asarray([bool(row[5]) for row in people], dtype=bool))


class ScheduledScoreObjective:
    def __init__(self, users: UserData, candidates: list[dict], current: list[int], *,
                 service_start: float = 25200, service_end: float = 68400, headway: float = 1800,
                 base_fare: float = 30.0, fare_per_mile: float = 2.0,
                 maximum_wait_seconds: float = 1800.0,
                 cruise_speed: float = 44.704, access_speed: float = 13.89,
                 access_beeline_factor: float = 1.4,
                 maximum_ground_access_distance: float = MAXIMUM_GROUND_ACCESS_METERS,
                 routed_candidate_vertiports: int = ROUTED_CANDIDATE_VERTIPORTS):
        self.users, self.candidates = users, candidates
        self.coords = np.asarray([(site["x"], site["y"]) for site in candidates])
        self.origin_beeline = distance_matrix(users.origins, self.coords)
        self.origin_distance = self.origin_beeline * access_beeline_factor
        self.destination_distance = distance_matrix(users.destinations, self.coords) * access_beeline_factor
        self.site_distance = distance_matrix(self.coords, self.coords)
        self.service_start, self.service_end, self.headway = service_start, service_end, headway
        self.base_fare, self.fare_per_mile = base_fare, fare_per_mile
        self.maximum_wait_seconds = maximum_wait_seconds
        self.cruise_speed, self.access_speed = cruise_speed, access_speed
        self.maximum_ground_access_distance = maximum_ground_access_distance
        self.routed_candidate_vertiports = routed_candidate_vertiports
        fallback, _ = self.minimum_cost(current)
        oi, di = users.current_origin_site, users.current_destination_site
        valid = (oi >= 0) & (di >= 0) & (oi != di)
        self.anchor_cost = fallback.copy()
        rows = np.flatnonzero(valid)
        if len(rows):
            self.anchor_cost[rows] = self.pair_cost(rows, oi[rows], di[rows], True)
        potential_rows = np.flatnonzero(~valid)
        if users.ground_trip_costs is not None and len(potential_rows):
            ground_costs = users.ground_trip_costs[potential_rows]
            usable = np.isfinite(ground_costs)
            self.anchor_cost[potential_rows[usable]] = ground_costs[usable]

    def pair_cost(self, rows: np.ndarray, origins: np.ndarray, destinations: np.ndarray,
                  trust_observed_feasibility: bool = False) -> np.ndarray:
        access_distance = self.origin_distance[rows, origins]
        egress_distance = self.destination_distance[rows, destinations]
        access_time, egress_time = access_distance / self.access_speed, egress_distance / self.access_speed
        arrival = self.users.departure_seconds[rows] + access_time
        departure = self.service_start + np.ceil(np.maximum(0, arrival - self.service_start) / self.headway) * self.headway
        wait = departure - arrival
        flight = np.ceil(self.site_distance[origins, destinations] / self.cruise_speed)
        money = self.users.money_utility[self.users.trip_person_index[rows]]
        result = ((PERFORMING_UTIL_HR - ACCESS_TRAVEL_UTIL_HR) * (access_time + egress_time) / 3600
                  + ACCESS_MONETARY_DISTANCE_RATE * (access_distance + egress_distance) * money
                  + (PERFORMING_UTIL_HR - SCHEDULED_AAM_TRAVEL_UTIL_HR) * (wait + flight) / 3600
                  + (self.base_fare + self.fare_per_mile * self.site_distance[origins, destinations] / MILE) * money)
        feasible = ((origins != destinations)
                    & (self.origin_beeline[rows, origins] <= self.maximum_ground_access_distance)
                    & (departure <= self.service_end + 1e-6)
                    & (wait <= self.maximum_wait_seconds + 1e-6))
        # An observed MATSim route is stronger feasibility evidence than this
        # deliberately simple feeder-speed approximation.  In particular, a
        # real taxi/car feeder can catch the last flight when the surrogate's
        # uniform access speed predicts an arrival a few seconds too late.
        if trust_observed_feasibility:
            feasible = origins != destinations
        return np.where(feasible, result, math.inf)

    def minimum_cost(self, active: list[int]) -> tuple[np.ndarray, np.ndarray]:
        rows = np.arange(len(self.users.origins))
        best, pair = np.full(len(rows), math.inf), np.full((len(rows), 2), -1, dtype=int)
        active_array = np.asarray(active, dtype=int)
        origin_candidates = active_array[np.argsort(self.origin_beeline[:, active_array], axis=1)[:, :self.routed_candidate_vertiports]]
        destination_candidates = active_array[np.argsort(self.destination_distance[:, active_array], axis=1)[:, :self.routed_candidate_vertiports]]
        for origin_rank in range(origin_candidates.shape[1]):
            for destination_rank in range(destination_candidates.shape[1]):
                origins = origin_candidates[:, origin_rank]
                destinations = destination_candidates[:, destination_rank]
                cost = self.pair_cost(rows, origins, destinations)
                improved = cost < best
                best[improved,], pair[improved] = cost[improved], np.column_stack((origins[improved], destinations[improved]))
        # Keep each successfully simulated current pair available when both of
        # its sites remain active. Proposed pairs still use strict feasibility.
        oi, di = self.users.current_origin_site, self.users.current_destination_site
        active_set = set(active)
        observed = np.asarray([o in active_set and d in active_set and o != d for o, d in zip(oi, di)])
        observed_rows = np.flatnonzero(observed)
        if len(observed_rows):
            observed_cost = self.pair_cost(observed_rows, oi[observed_rows], di[observed_rows], True)
            improved = observed_cost < best[observed_rows]
            chosen = observed_rows[improved]
            best[chosen] = observed_cost[improved]
            pair[chosen] = np.column_stack((oi[chosen], di[chosen]))
        return best, pair

    def evaluate(self, active: list[int]) -> dict:
        if len(set(active)) != len(active):
            return {"feasible": False, "objective": -math.inf, "reason": "duplicate site"}
        minimum, pair = self.minimum_cost(active)
        delta = self.anchor_cost - minimum
        selected_scores = self.users.selected_scores if self.users.selected_scores is not None else self.users.scores
        population_score_sum = self.users.population_score_sum if self.users.population_count else float(np.sum(selected_scores))
        population_count = self.users.population_count or len(self.users.ids)
        predicted_aam = self.users.scores + np.bincount(self.users.trip_person_index, weights=delta, minlength=len(self.users.ids))
        has_aam = (self.users.has_aam_plan_by_person if self.users.has_aam_plan_by_person is not None
                   else np.ones(len(self.users.ids), dtype=bool))
        existing_gain = np.maximum(0.0, np.nan_to_num(predicted_aam - selected_scores,
                                    nan=-math.inf, posinf=math.inf, neginf=-math.inf))
        per_trip_gain = np.maximum(0.0, np.nan_to_num(delta, nan=-math.inf,
                                   posinf=math.inf, neginf=-math.inf))
        new_user_gain = np.bincount(self.users.trip_person_index,
                                    weights=per_trip_gain * (~has_aam[self.users.trip_person_index]),
                                    minlength=len(self.users.ids))
        gains = np.where(has_aam, existing_gain, new_user_gain)
        predicted = selected_scores + gains
        ground = np.isfinite(self.users.ground_scores)
        return {"feasible": True, "objective": population_score_sum + float(np.sum(gains)),
                "currentPopulationScoreSum": population_score_sum,
                "eligibleTravelers": population_count,
                "predictedAamGainSum": float(np.sum(gains)), "pair": pair,
                "meanPredictedAamScore": float(np.mean(predicted)),
                "observedGroundComparisons": int(np.count_nonzero(ground)),
                "predictedBenefitSumWhereGroundObserved": float(np.sum(predicted[ground] - self.users.ground_scores[ground])) if np.any(ground) else None}


def _nearest(active: list[int], distance: np.ndarray, k: int) -> dict[int, list[int]]:
    inactive = np.asarray(sorted(set(range(len(distance))) - set(active)), dtype=int)
    return {site: inactive[np.argsort(distance[site, inactive])[:min(k, len(inactive))]].tolist() for site in active}


def optimize_one_swap(objective, active: list[int], method: str, minimum_improvement: float = 1e-9):
    started, baseline = time.perf_counter(), objective.evaluate(active)
    if not baseline["feasible"]:
        raise ValueError(f"initial layout is infeasible: {baseline.get('reason')}")
    inactive = sorted(set(range(len(objective.candidates))) - set(active))
    weak_losses = None
    if method == "global":
        levels = [("global", [(old, new) for old in active for new in inactive])]
    elif method == "all-vp-k10":
        nearby = _nearest(active, objective.site_distance, 10)
        levels = [("k10", [(old, new) for old in active for new in nearby[old]])]
    elif method == "one-vp-k10":
        losses = {site: baseline["objective"] - objective.evaluate([x for x in active if x != site])["objective"] for site in active}
        weak = min(active, key=lambda site: (losses[site], site))
        weak_losses = {objective.candidates[site]["id"]: losses[site] for site in active}
        levels = [("weak-k10", [(weak, new) for new in _nearest(active, objective.site_distance, 10)[weak]])]
    elif method == "adaptive":
        levels = []
        for k in (5, 10, 20, 90):
            nearby = _nearest(active, objective.site_distance, k)
            levels.append(("global" if k == 90 else f"k{k}", [(old, new) for old in active for new in nearby[old]]))
    else:
        raise ValueError(f"unknown method: {method}")
    best_value, best_layout, move, evaluated, audit = baseline["objective"], list(active), None, set(), []
    for name, moves in levels:
        before, feasible = best_value, 0
        for removed, added in moves:
            if (removed, added) in evaluated:
                continue
            evaluated.add((removed, added))
            trial = list(active)
            trial[trial.index(removed)] = added
            result = objective.evaluate(trial)
            feasible += int(result["feasible"])
            if result["feasible"] and result["objective"] > best_value + minimum_improvement:
                best_value, best_layout, move = result["objective"], trial, (removed, added)
        audit.append({"level": name, "newMovesEvaluated": len(evaluated) - sum(x["newMovesEvaluated"] for x in audit),
                      "feasibleMoves": feasible, "bestImprovement": best_value - baseline["objective"]})
        if method == "adaptive" and best_value > before + minimum_improvement:
            break
    report = {"method": method,
              "objective": "all passenger current selected scores plus positive gains from a higher-scoring feasible AAM alternative",
              "currentAamUsers": objective.users.current_aam_plan_users if objective.users.current_aam_plan_users >= 0 else len(objective.users.ids),
              "currentAamTrips": len(objective.users.origins),
              "currentAamPlanUsers": objective.users.current_aam_plan_users if objective.users.current_aam_plan_users >= 0 else len(objective.users.ids),
              "potentialNewAamUsers": objective.users.potential_new_aam_users,
              "modeledAamOpportunityUsers": len(objective.users.ids),
              "candidateAamTripOpportunities": len(objective.users.origins),
              "eligibleTravelers": objective.users.population_count or len(objective.users.ids),
              "baselineObjective": baseline["objective"], "candidateObjective": best_value,
              "improvement": best_value - baseline["objective"], "accepted": move is not None,
              "movesEvaluated": len(evaluated), "levels": audit, "weakSiteRemovalLosses": weak_losses,
              "optimizerSeconds": time.perf_counter() - started,
              "baseFare": objective.base_fare, "farePerMile": objective.fare_per_mile,
              "maximumWaitSeconds": objective.maximum_wait_seconds,
              "before": [objective.candidates[i]["id"] for i in active],
              "after": [objective.candidates[i]["id"] for i in best_layout], "siteSeparationConstraint": False}
    if move:
        report.update(removed=objective.candidates[move[0]]["id"], added=objective.candidates[move[1]]["id"])
    return best_layout, report


def optimize_population(population: Path, candidates_path: Path, layout_path: Path, output_path: Path,
                        method: str, minimum_trip_meters: float = MINIMUM_TRIP_METERS, **schedule) -> dict:
    started = time.perf_counter()
    candidates, layout = read_sites(candidates_path), read_sites(layout_path)
    if len(candidates) != 100 or len(layout) != 10:
        raise ValueError("scheduled score optimizer requires 100 candidates and 10 active vertiports")
    index = {site["id"]: i for i, site in enumerate(candidates)}
    try:
        active = [index[site["id"]] for site in layout]
    except KeyError as error:
        raise ValueError(f"active site is absent from candidate set: {error.args[0]}") from error
    users = read_aam_users(population, candidates, minimum_trip_meters)
    selected, report = optimize_one_swap(ScheduledScoreObjective(users, candidates, active, **schedule), active, method)
    report.update(population=str(population), inputLayout=str(layout_path), outputLayout=str(output_path),
                  minimumTripMeters=minimum_trip_meters, schedule=schedule)
    report["sha256"] = atomic_write_layout(output_path, [candidates[i] for i in selected])
    report["optimizerSeconds"] = time.perf_counter() - started
    output_path.with_suffix(output_path.suffix + ".optimization.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, default=project / "scenarios/aam/vertiport-candidates-100.csv")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", choices=("global", "all-vp-k10", "one-vp-k10", "adaptive"), required=True)
    parser.add_argument("--minimum-trip-meters", type=float, default=MINIMUM_TRIP_METERS)
    args = parser.parse_args()
    print(json.dumps(optimize_population(args.population, args.candidates, args.layout, args.output,
                                         args.method, args.minimum_trip_meters), indent=2))


if __name__ == "__main__":
    main()
