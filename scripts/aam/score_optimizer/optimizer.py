#!/usr/bin/env python3
"""Score-based one-swap vertiport optimizer.

The optimizer includes the selected-score baseline for every passenger. It
uses observed AAM plans when available and derives additional AAM candidates
from the selected ground plans of people who have no AAM plan yet. A candidate
layout adds only predicted AAM gains above the current selected score.

All methods make at most one swap.  They differ only in the neighborhood:
global, ten nearest inactive sites around every active site, ten nearest sites
around one weak active site, or an adaptive 5/10/20/global neighborhood.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .common import MILE, atomic_write_layout, distance_matrix, read_sites
from .mission_profile import MINIMUM_FLIGHT_DISTANCE_METERS, flight_time_seconds
GROUND_SPEED_MPS = 25.0 * MILE / 3600.0
WALK_SPEED_MPS = 1.34
GROUND_CIRCUITY = 1.3
PERFORMING_UTIL_HR = 9.84
AAM_TRAVEL_UTIL_HR = -6.0
WALK_TRAVEL_UTIL_HR = -19.68


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


def _routing_mode(leg: ET.Element) -> str | None:
    for attribute in leg.findall("./attributes/attribute"):
        if attribute.get("name") == "routingMode":
            return attribute.text
    return None


def _is_main_activity(element: ET.Element) -> bool:
    return element.tag in ("act", "activity") and "interaction" not in element.get("type", "").lower()


def _score(plan: ET.Element) -> float:
    try:
        value = float(plan.get("score", "nan"))
        return value if math.isfinite(value) else math.nan
    except ValueError:
        return math.nan


def _money_utility(person: ET.Element) -> float:
    values = {a.get("name"): a.text for a in person.findall("./attributes/attribute")}
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


def _site_id(link: str | None) -> str | None:
    prefix = "aam_loop_"
    return link[len(prefix):] if link and link.startswith(prefix) else None


def _time_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        fields = value.split(":")
        if len(fields) == 3:
            return float(fields[0]) * 3600.0 + float(fields[1]) * 60.0 + float(fields[2])
        return float(value)
    except ValueError:
        return 0.0


def _aam_trips(plan: ET.Element) -> list[tuple[tuple[float, float], tuple[float, float], str | None, str | None, float]]:
    """Return every AAM trip and its surrounding main activities."""
    elements = list(plan)
    candidates = []
    for index, element in enumerate(elements):
        if element.tag != "leg" or element.get("mode") != "aam_drt":
            continue
        route = element.find("route")
        try:
            air_distance = float(route.get("distance", "0")) if route is not None else 0.0
        except ValueError:
            air_distance = 0.0
        before = next((e for e in reversed(elements[:index]) if _is_main_activity(e)), None)
        after = next((e for e in elements[index + 1:] if _is_main_activity(e)), None)
        if before is None or after is None or not all(k in before.attrib and k in after.attrib for k in ("x", "y")):
            continue
        candidates.append((air_distance,
                           (float(before.get("x")), float(before.get("y"))),
                           (float(after.get("x")), float(after.get("y"))),
                           _site_id(route.get("start_link") if route is not None else None),
                           _site_id(route.get("end_link") if route is not None else None),
                           _time_seconds(element.get("dep_time"))))
    return [(origin, destination, origin_site, destination_site, departure)
            for _, origin, destination, origin_site, destination_site, departure in candidates]


def _ground_plan_trips(plan: ET.Element, money_utility: float, minimum_trip_miles: float):
    """Build estimated AAM opportunities from a scored non-AAM plan.

    The observed ground plan score is the traveler-level anchor. Per-trip
    ground disutility is reconstructed from routed leg time, distance, and
    the scenario's mode coefficients so a newly feasible AAM itinerary can be
    compared even when MATSim has never created an AAM plan for this person.
    """
    mode_travel = {"car": 0.0, "ride": 0.0, "ride_taxi": 0.0, "pt": -9.84,
                   "walk": -19.68, "transit_walk": -19.68, "non_network_walk": -19.68,
                   "bike": -39.36, "access_egress_pt": 0.0, "aam_drt": -6.0}
    mode_constant = {"ride": -12.0, "ride_taxi": -2.85, "pt": -2.46,
                     "bike": -9.84, "walk": 0.0, "transit_walk": 0.0}
    mode_money_per_meter = {"car": 0.000104, "ride": 0.000104, "ride_taxi": 0.0025}
    elements = list(plan)
    main = [i for i, element in enumerate(elements)
            if element.tag in ("act", "activity") and "interaction" not in element.get("type", "").lower()]
    result = []
    for start, end in zip(main, main[1:]):
        before, after = elements[start], elements[end]
        if not all(key in before.attrib and key in after.attrib for key in ("x", "y")):
            continue
        origin = (float(before.get("x")), float(before.get("y")))
        destination = (float(after.get("x")), float(after.get("y")))
        if math.dist(origin, destination) < minimum_trip_miles * MILE:
            continue
        legs = [element for element in elements[start + 1:end] if element.tag == "leg"]
        if not legs:
            continue
        first = legs[0]
        departure = _time_seconds(first.get("dep_time"))
        if departure <= 0:
            departure = _time_seconds(before.get("end_time"))
        ground_cost = 0.0
        complete_times = True
        for leg in legs:
            mode = leg.get("mode", "")
            route = leg.find("route")
            travel = _time_seconds(leg.get("trav_time") or (route.get("trav_time") if route is not None else None))
            if travel <= 0:
                complete_times = False
            distance = 0.0
            if route is not None:
                try:
                    distance = float(route.get("distance", "0"))
                except ValueError:
                    pass
            utility = mode_travel.get(mode, -6.0)
            ground_cost += (PERFORMING_UTIL_HR - utility) * travel / 3600.0
            ground_cost -= mode_constant.get(mode, 0.0)
            ground_cost += mode_money_per_meter.get(mode, 0.0) * distance * money_utility
        if not complete_times:
            continue
        result.append((origin, destination, departure, ground_cost))
    return result


def observed_ground_scores(population: Path) -> dict:
    """Latest executed ground scores, kept outside simulation plan scores."""
    result = {}
    opener = gzip.open if population.suffix == '.gz' else open
    with opener(population, 'rb') as stream:
        for _, person in ET.iterparse(stream, events=('end',)):
            if person.tag != 'person':
                continue
            scored = [( _score(p), p) for p in person.findall('plan')
                      if not any(l.get('mode') == 'aam_drt'
                                 for l in p.findall('leg'))]
            scored = [(s, p) for s, p in scored if math.isfinite(s)]
            if scored:
                score, plan = max(scored, key=lambda item: item[0])
                result[person.get('id')] = dict(score=score, source=str(population.resolve()),
                    planXml=ET.tostring(plan, encoding='unicode'))
            person.clear()
    return result


def read_aam_users(population: Path, candidates: list[dict], minimum_trip_miles: float = 3.0) -> UserData:
    """Read AAM options and the selected-score baseline for all passengers."""
    index = {site["id"]: i for i, site in enumerate(candidates)}
    people, trips = [], []
    population_score_sum = 0.0
    population_count = 0
    opener = gzip.open if population.suffix == ".gz" else open
    with opener(population, "rb") as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            best = None
            ground = -math.inf
            finite_scores = []
            selected_score = math.nan
            selected_plan = None
            best_scored_plan = None
            for plan in person.findall("plan"):
                score = _score(plan)
                if not math.isfinite(score):
                    continue
                finite_scores.append(score)
                if plan.get("selected") == "yes":
                    selected_score = score
                    selected_plan = plan
                if best_scored_plan is None or score > best_scored_plan[0]:
                    best_scored_plan = (score, plan)
                plan_trips = _aam_trips(plan)
                if not plan_trips and not any(l.get("mode") == "aam_drt" for l in plan.findall("leg")):
                    ground = max(ground, score)
                elif best is None or score > best[0]:
                    best = (score, plan_trips)
            subpopulation = person.findtext("./attributes/attribute[@name='subpopulation']") or "person"
            if subpopulation == "person" and finite_scores:
                if not math.isfinite(selected_score):
                    selected_score = max(finite_scores)
                population_score_sum += selected_score
                population_count += 1
            if selected_plan is None:selected_plan=best_scored_plan[1] if best_scored_plan else None
            if selected_plan is not None and subpopulation=="person":
                money_utility = _money_utility(person)
                from_aam_plan = False
                score_anchor, plan_trips = (best if best is not None else
                    (selected_score if math.isfinite(selected_score) else best_scored_plan[0], []))
                if best is not None:
                    plan_trips = [trip for trip in best[1]
                                  if math.dist(trip[0], trip[1]) >= minimum_trip_miles * MILE]
                    trip_rows = [(origin, destination, index.get(origin_site, -1),
                                  index.get(destination_site, -1), departure, math.nan)
                                 for origin, destination, origin_site, destination_site, departure in plan_trips]
                    from_aam_plan = bool(trip_rows)
                else:
                    trip_rows = []
                if not trip_rows:
                    score_anchor = selected_score if math.isfinite(selected_score) else best_scored_plan[0]
                    trip_rows = [(origin, destination, -1, -1, departure, ground_cost)
                                 for origin, destination, departure, ground_cost in
                                 _ground_plan_trips(selected_plan, money_utility, minimum_trip_miles)]
                if trip_rows:
                    person_index = len(people)
                    people.append((person.get("id"), score_anchor, money_utility,
                                   ground if math.isfinite(ground) else math.nan, selected_score, from_aam_plan))
                    for origin, destination, origin_site, destination_site, departure, ground_cost in trip_rows:
                        trips.append((person_index, origin, destination, origin_site,
                                      destination_site, departure, ground_cost))
            person.clear()
    if not people:
        raise ValueError("no scored AAM users or eligible AAM opportunities in population plans")
    return UserData(
        ids=[row[0] for row in people],
        origins=np.asarray([row[1] for row in trips], dtype=float),
        destinations=np.asarray([row[2] for row in trips], dtype=float),
        scores=np.asarray([row[1] for row in people], dtype=float),
        money_utility=np.asarray([row[2] for row in people], dtype=float),
        trip_person_index=np.asarray([row[0] for row in trips], dtype=int),
        current_origin_site=np.asarray([row[3] for row in trips], dtype=int),
        current_destination_site=np.asarray([row[4] for row in trips], dtype=int),
        ground_scores=np.asarray([row[3] for row in people], dtype=float),
        departure_seconds=np.asarray([row[5] for row in trips], dtype=float),
        selected_scores=np.asarray([row[4] for row in people], dtype=float),
        population_score_sum=population_score_sum,
        population_count=population_count,
        ground_trip_costs=np.asarray([row[6] for row in trips], dtype=float),
        current_aam_plan_users=sum(bool(row[5]) for row in people),
        potential_new_aam_users=sum(not bool(row[5]) for row in people),
        has_aam_plan_by_person=np.asarray([bool(row[5]) for row in people], dtype=bool),
    )


def read_wait_priors(path: Path | None, candidates: list[dict], departure_seconds: np.ndarray,
                     fallback_seconds: float, bin_seconds: float = 3600.0,
                     maximum_seconds: float = 900.0) -> tuple[np.ndarray, int]:
    """Mirror Java's wait hierarchy; unseen vertiports retain the fallback."""
    if bin_seconds <= 0:
        raise ValueError("wait time bin must be positive")
    site_index = {site["id"]: index for index, site in enumerate(candidates)}
    user_bins = np.maximum(0, np.floor(departure_seconds / bin_seconds).astype(int))
    bins = int(np.max(user_bins)) + 1 if len(user_bins) else 1
    result = np.full((bins, len(candidates), len(candidates)), fallback_seconds, dtype=float)
    observed = 0
    if path is None:
        return result, observed
    if not path.is_file():
        raise FileNotFoundError(f"wait-prior file does not exist: {path}")
    size = len(candidates)
    exact_sum = np.zeros((bins, size, size), dtype=float)
    exact_count = np.zeros((bins, size, size), dtype=float)
    origin_time_sum = np.zeros((bins, size), dtype=float)
    origin_time_count = np.zeros((bins, size), dtype=float)
    global_time_sum = np.zeros(bins, dtype=float)
    global_time_count = np.zeros(bins, dtype=float)
    origin_sum = np.zeros(size, dtype=float)
    origin_count = np.zeros(size, dtype=float)
    global_sum = global_count = 0.0
    observed_sites = np.zeros(size, dtype=bool)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            origin_id, destination_id = _site_id(row.get("from")), _site_id(row.get("to"))
            try:
                time_bin, count, mean_wait = int(row["time_bin"]), float(row["count"]), float(row["mean_wait_s"])
            except (KeyError, TypeError, ValueError):
                continue
            if (origin_id not in site_index or destination_id not in site_index or
                    time_bin < 0 or time_bin >= bins or count <= 0 or not math.isfinite(count) or
                    not math.isfinite(mean_wait) or mean_wait < 0):
                continue
            origin, destination = site_index[origin_id], site_index[destination_id]
            weighted = count * mean_wait
            exact_sum[time_bin, origin, destination] += weighted
            exact_count[time_bin, origin, destination] += count
            origin_time_sum[time_bin, origin] += weighted
            origin_time_count[time_bin, origin] += count
            global_time_sum[time_bin] += weighted
            global_time_count[time_bin] += count
            origin_sum[origin] += weighted
            origin_count[origin] += count
            global_sum += weighted; global_count += count
            observed_sites[origin] = observed_sites[destination] = True
            observed += 1
    for time_bin in range(bins):
        for origin in range(size):
            for destination in range(size):
                if not observed_sites[origin] or not observed_sites[destination]:
                    estimate = fallback_seconds
                elif exact_count[time_bin, origin, destination] > 0:
                    estimate = exact_sum[time_bin, origin, destination] / exact_count[time_bin, origin, destination]
                elif origin_time_count[time_bin, origin] > 0:
                    estimate = origin_time_sum[time_bin, origin] / origin_time_count[time_bin, origin]
                elif global_time_count[time_bin] > 0:
                    estimate = global_time_sum[time_bin] / global_time_count[time_bin]
                elif origin_count[origin] > 0:
                    estimate = origin_sum[origin] / origin_count[origin]
                elif global_count > 0:
                    estimate = global_sum / global_count
                else:
                    estimate = fallback_seconds
                result[time_bin, origin, destination] = min(maximum_seconds, max(0.0, estimate))
    return result, observed


def ground_disutility(distance: np.ndarray, money_utility: np.ndarray,
                      maximum_walk_distance: float = math.inf, maximum_walk_time: float = math.inf) -> np.ndarray:
    """Approximate the least-cost access/egress mode used by the Java router."""
    routed = distance * GROUND_CIRCUITY
    walk = (PERFORMING_UTIL_HR - WALK_TRAVEL_UTIL_HR) * (routed / WALK_SPEED_MPS) / 3600.0
    walk = np.where((routed<=maximum_walk_distance)&(routed/WALK_SPEED_MPS<=maximum_walk_time),walk,math.inf)
    road_time = (PERFORMING_UTIL_HR * (routed / GROUND_SPEED_MPS) / 3600.0)
    ride = road_time + 12.0 + 0.000104 * routed * money_utility[:, None]
    taxi = road_time + 2.85 + 0.0025 * routed * money_utility[:, None]
    return np.minimum(walk, np.minimum(ride, taxi))


class ScoreObjective:
    def __init__(self, users: UserData, candidates: list[dict], current: list[int],
                 base_fare: float, fare_per_mile: float, expected_wait_seconds: float,
                 wait_priors: Path | None = None, wait_bin_seconds: float = 3600.0,
                 maximum_wait_seconds: float = 900.0,
                 routing_candidate_vertiports: int = 3,
                 service_start_time: float = 25200.0, service_end_time: float = 68400.0,
                 maximum_walk_distance: float = math.inf, maximum_walk_time: float = math.inf,
                 max_access_distance_miles: float = 5.0, max_egress_distance_miles: float | None = None,
                 allow_pre_service_requests: bool = True):
        self.max_access_distance = max_access_distance_miles * MILE
        self.max_egress_distance = (max_access_distance_miles if max_egress_distance_miles is None else max_egress_distance_miles) * MILE
        self.allow_pre_service_requests = allow_pre_service_requests
        self.users, self.candidates, self.current = users, candidates, list(current)
        self.coords = np.asarray([(site["x"], site["y"]) for site in candidates], dtype=float)
        origin_distance = distance_matrix(users.origins, self.coords)
        destination_distance = distance_matrix(users.destinations, self.coords)
        self.origin_distance = origin_distance
        self.destination_distance = destination_distance
        trip_money_utility = users.money_utility[users.trip_person_index]
        self.access = ground_disutility(origin_distance, trip_money_utility,maximum_walk_distance,maximum_walk_time)
        self.egress = ground_disutility(destination_distance, trip_money_utility,maximum_walk_distance,maximum_walk_time)
        self.site_distance = distance_matrix(self.coords, self.coords)
        self.base_fare, self.fare_per_mile = base_fare, fare_per_mile
        self.expected_wait_seconds = expected_wait_seconds
        self.maximum_wait_seconds = maximum_wait_seconds
        self.service_start_time, self.service_end_time = service_start_time, service_end_time
        if routing_candidate_vertiports < 1:
            raise ValueError("routing candidate vertiports must be positive")
        self.routing_candidate_vertiports = routing_candidate_vertiports
        self.wait_bin_seconds = wait_bin_seconds
        self.waits, self.observed_wait_cells = read_wait_priors(
            wait_priors, candidates, users.departure_seconds, expected_wait_seconds,
            wait_bin_seconds, maximum_wait_seconds)
        self.departure_bins = np.clip(np.floor(users.departure_seconds / wait_bin_seconds).astype(int),
                                      0, len(self.waits) - 1)
        # Anchor every prediction on the pair actually used in the scored plan.
        fallback_cost, _ = self.minimum_cost(current)
        oi, di = users.current_origin_site, users.current_destination_site
        valid = (oi >= 0) & (di >= 0) & (oi != di)
        self.anchor_cost = fallback_cost.copy()
        rows = np.flatnonzero(valid)
        if len(rows):
            # A scored route can be feasible in MATSim even when our feeder
            # approximation misses its service window. Anchor by finite cost,
            # then screen proposed pairs separately; never form inf-inf gains.
            self.anchor_cost[rows] = self.pair_cost(rows, oi[rows], di[rows],screen=False)
        potential_rows = np.flatnonzero(~valid)
        if users.ground_trip_costs is not None and len(potential_rows):
            ground_costs = users.ground_trip_costs[potential_rows]
            usable = np.isfinite(ground_costs)
            self.anchor_cost[potential_rows[usable]] = ground_costs[usable]
        if not np.all(np.isfinite(self.anchor_cost)):
            raise ValueError("Missing finite score anchor for an AAM opportunity")

    def pair_cost(self, rows: np.ndarray, origins: np.ndarray, destinations: np.ndarray, screen=True) -> np.ndarray:
        distance = self.site_distance[origins, destinations]
        wait = self.waits[self.departure_bins[rows], origins, destinations]
        air_time = flight_time_seconds(distance)
        feeder_time = np.minimum(self.origin_distance[rows, origins] * GROUND_CIRCUITY / WALK_SPEED_MPS,
                                 self.origin_distance[rows, origins] * GROUND_CIRCUITY / GROUND_SPEED_MPS)
        arrival_at_vertiport = self.users.departure_seconds[rows] + feeder_time
        wait = np.maximum(wait, np.maximum(0.0, self.service_start_time - arrival_at_vertiport))
        boarding = arrival_at_vertiport + wait
        fare = self.base_fare + self.fare_per_mile * distance / MILE
        cost = (self.access[rows, origins] + self.egress[rows, destinations]
                + (PERFORMING_UTIL_HR - AAM_TRAVEL_UTIL_HR) * (wait + air_time) / 3600.0
                + fare * self.users.money_utility[self.users.trip_person_index[rows]])
        operational = ((self.origin_distance[rows, origins] <= self.max_access_distance)
                       & (self.destination_distance[rows, destinations] <= self.max_egress_distance)
                       & (origins != destinations)
                       & (distance >= MINIMUM_FLIGHT_DISTANCE_METERS - 1e-6)
                       & (self.allow_pre_service_requests | (arrival_at_vertiport >= self.service_start_time))
                       & (arrival_at_vertiport <= self.service_end_time)
                       & (boarding <= self.service_end_time)
                       & (boarding + air_time + 120 <= self.service_end_time)
                       & (wait <= self.maximum_wait_seconds))
        return np.where(operational, cost, math.inf) if screen else np.where(
            distance >= MINIMUM_FLIGHT_DISTANCE_METERS - 1e-6, cost, math.inf)

    def minimum_cost(self, active: list[int]) -> tuple[np.ndarray, np.ndarray]:
        active_array = np.asarray(active, dtype=int)
        n = len(self.users.origins)
        best = np.full(n, math.inf)
        best_pair = np.full((n, 2), -1, dtype=int)
        rows = np.arange(n)
        k = min(self.routing_candidate_vertiports, len(active_array))
        origin_choices = active_array[np.argsort(self.origin_distance[:, active_array], axis=1)[:, :k]]
        destination_choices = active_array[np.argsort(self.destination_distance[:, active_array], axis=1)[:, :k]]
        # Mirror the Java router: each trip considers its k nearest origin-side
        # and k nearest destination-side active vertiports, excluding m == n.
        for origin in active_array:
            origin_allowed = np.any(origin_choices == origin, axis=1)
            for destination in active_array:
                if origin == destination:
                    continue
                allowed = origin_allowed & np.any(destination_choices == destination, axis=1)
                if not np.any(allowed):
                    continue
                cost = self.pair_cost(rows, np.full(n, origin), np.full(n, destination))
                improved = allowed & (cost < best)
                best[improved] = cost[improved]
                best_pair[improved, 0] = origin
                best_pair[improved, 1] = destination
        return best, best_pair

    def evaluate(self, active: list[int]) -> dict:
        if len(set(active)) != len(active):
            return {"feasible": False, "objective": -math.inf, "reason": "duplicate site"}
        minimum, pair = self.minimum_cost(active)
        trip_delta = self.anchor_cost - minimum
        plan_delta = np.bincount(self.users.trip_person_index, weights=trip_delta,
                                 minlength=len(self.users.ids))
        selected_scores = self.users.selected_scores if self.users.selected_scores is not None else self.users.scores
        population_score_sum = self.users.population_score_sum if self.users.population_count else float(np.sum(selected_scores))
        population_count = self.users.population_count or len(self.users.ids)
        has_aam = (self.users.has_aam_plan_by_person if self.users.has_aam_plan_by_person is not None
                   else np.ones(len(self.users.ids), dtype=bool))
        predicted_aam = self.users.scores + plan_delta
        per_trip_gain = np.maximum(0.0,trip_delta)
        new_user_gain = np.bincount(self.users.trip_person_index,
                                    weights=np.where(~has_aam[self.users.trip_person_index],per_trip_gain,0.0),
                                    minlength=len(self.users.ids))
        ground=self.users.ground_scores
        if not np.all(np.isfinite(ground)):
            raise ValueError("Every modeled traveler needs a scored ground alternative; missing: "+
                             ",".join(np.asarray(self.users.ids)[~np.isfinite(ground)][:10]))
        # Ground-only travelers may keep individual trips on ground. Existing
        # AAM daily plans need every modeled air trip feasible, or fall back to
        # the scored ground plan. Losses relative to current selection count.
        predicted_aam=np.where(has_aam,predicted_aam,selected_scores+new_user_gain)
        predicted=np.maximum(ground,predicted_aam)
        gains=predicted-selected_scores
        if not np.all(np.isfinite(predicted)):
            raise ValueError("Non-finite predicted traveler score")
        finite_ground = np.isfinite(self.users.ground_scores)
        return {"feasible": True, "objective": population_score_sum + float(np.sum(gains)),
                "currentPopulationScoreSum": population_score_sum,
                "eligibleTravelers": population_count,
                "predictedAamGainSum": float(np.sum(gains)),
                "positiveScoreChangeSum":float(np.maximum(0,gains).sum()),
                "negativeScoreChangeSum":float(np.minimum(0,gains).sum()),
                "travelersWithPredictedLoss":int(np.count_nonzero(gains<0)),
                "meanPredictedAamScore": float(np.mean(predicted)),
                "observedAamScoreSum": float(np.sum(self.users.scores)),
                "observedGroundComparisons": int(np.count_nonzero(finite_ground)),
                "predictedBenefitSumWhereGroundObserved":
                    float(np.sum(predicted[finite_ground] - self.users.ground_scores[finite_ground])) if np.any(finite_ground) else None,
                "pair": pair}


def _nearest_inactive(active: list[int], site_distance: np.ndarray, k: int) -> dict[int, list[int]]:
    inactive = np.asarray(sorted(set(range(len(site_distance))) - set(active)), dtype=int)
    return {site: inactive[np.argsort(site_distance[site, inactive])[:min(k, len(inactive))]].tolist()
            for site in active}


def _weak_site(objective: ScoreObjective, active: list[int], baseline: float) -> tuple[int, dict]:
    losses = {}
    for site in active:
        reduced = [candidate for candidate in active if candidate != site]
        value = objective.evaluate(reduced)["objective"]
        losses[site] = baseline - value
    weak = min(active, key=lambda site: (losses[site], site))
    return weak, {objective.candidates[site]["id"]: losses[site] for site in active}


def optimize_one_swap(objective: ScoreObjective, active: list[int], method: str,
                      minimum_improvement: float = 1e-9) -> tuple[list[int], dict]:
    started = time.perf_counter()
    baseline = objective.evaluate(active)
    if not baseline["feasible"]:
        raise ValueError(f"initial layout is infeasible: {baseline.get('reason')}")
    site_distance = objective.site_distance
    levels: list[tuple[str, list[tuple[int, int]]]] = []
    weak_losses = None
    if method == "global":
        inactive = sorted(set(range(len(objective.candidates))) - set(active))
        levels = [("global", [(old, new) for old in active for new in inactive])]
    elif method == "all-vp-k10":
        nearby = _nearest_inactive(active, site_distance, 10)
        levels = [("k10", [(old, new) for old in active for new in nearby[old]])]
    elif method == "one-vp-k10":
        weak, weak_losses = _weak_site(objective, active, baseline["objective"])
        nearby = _nearest_inactive(active, site_distance, 10)
        levels = [("weak-k10", [(weak, new) for new in nearby[weak]])]
    elif method == "adaptive":
        for k in (5, 10, 20, 90):
            nearby = _nearest_inactive(active, site_distance, k)
            pairs = [(old, new) for old in active for new in nearby[old]]
            levels.append(("global" if k == 90 else f"k{k}", pairs))
    else:
        raise ValueError(f"unknown method: {method}")

    best_value, best_layout, best_move = baseline["objective"], list(active), None
    evaluated: set[tuple[int, int]] = set()
    level_audit = []
    for level_name, moves in levels:
        level_best_before = best_value
        count = feasible = 0
        for removed, added in moves:
            if (removed, added) in evaluated:
                continue
            evaluated.add((removed, added)); count += 1
            trial = list(active); trial[trial.index(removed)] = added
            result = objective.evaluate(trial)
            if not result["feasible"]:
                continue
            feasible += 1
            if result["objective"] > best_value + 1e-10:
                best_value, best_layout, best_move = result["objective"], trial, (removed, added)
        level_audit.append({"level": level_name, "newMovesEvaluated": count,
                            "feasibleMoves": feasible, "bestImprovement": best_value - baseline["objective"]})
        # Adaptive search expands only when its current neighborhood is stuck.
        if method == "adaptive" and best_value > level_best_before + minimum_improvement:
            break

    mathematical_best=best_value
    protection_floor=max(baseline["objective"],baseline.get("currentPopulationScoreSum",baseline["objective"]))
    if best_value-protection_floor<=minimum_improvement:
        best_layout,best_move=list(active),None
        best_value=baseline["objective"]
    elapsed = time.perf_counter() - started
    report = {
        "method": method,
        "objective": "sum of best feasible predicted ground-or-AAM traveler scores; losses count",
        "siteSeparationConstraint": False,
        "shortTripRule": "AAM trips under the configured minimum are excluded; QSim remains authoritative",
        "currentAamUsers": objective.users.current_aam_plan_users if objective.users.current_aam_plan_users >= 0 else len(objective.users.ids),
        "currentAamPlanUsers": objective.users.current_aam_plan_users if objective.users.current_aam_plan_users >= 0 else len(objective.users.ids),
        "potentialNewAamUsers": objective.users.potential_new_aam_users,
        "modeledAamOpportunityUsers": len(objective.users.ids),
        "currentAamTrips": len(objective.users.origins),
        "candidateAamTripOpportunities": len(objective.users.origins),
        "eligibleTravelers": objective.users.population_count or len(objective.users.ids),
        "routingCandidateVertiports": objective.routing_candidate_vertiports,
        "baselineObjective": baseline["objective"],
        "aggregateProtectionFloor":protection_floor,
        "candidateObjective": best_value,
        "modelBestObjective":mathematical_best,
        "bestBound":mathematical_best if method=="global" else None,
        "absoluteGap":0.0 if method=="global" else None,
        "relativeGap":0.0 if method=="global" else None,
        "improvement": best_value - baseline["objective"],
        "accepted": best_move is not None,
        "movesEvaluated": len(evaluated),
        "levels": level_audit,
        "weakSiteRemovalLosses": weak_losses,
        "optimizerSeconds": elapsed,
        "before": [objective.candidates[i]["id"] for i in active],
        "after": [objective.candidates[i]["id"] for i in best_layout],
    }
    if best_move:
        report["removed"], report["added"] = (objective.candidates[best_move[0]]["id"],
                                                objective.candidates[best_move[1]]["id"])
    return best_layout, report


def optimize_population(population: Path, candidates_path: Path, layout_path: Path,
                        output_path: Path, method: str, base_fare: float = 30.0,
                        fare_per_mile: float = 2.0, expected_wait_seconds: float = 120.0,
                        minimum_trip_miles: float = 3.0, wait_priors: Path | None = None,
                        wait_bin_seconds: float = 3600.0,
                        maximum_wait_seconds: float = 900.0,
                        routing_candidate_vertiports: int = 3,
                        service_start_time: float = 25200.0,
                        service_end_time: float = 68400.0,
                        maximum_walk_distance: float = math.inf, maximum_walk_time: float = math.inf,
                        minimum_improvement: float = 1e-9, ground_score_history: dict | None = None,
                        max_access_distance_miles: float = 5.0, max_egress_distance_miles: float | None = None,
                        allow_pre_service_requests: bool = True) -> dict:
    total_started = time.perf_counter()
    candidates, layout = read_sites(candidates_path), read_sites(layout_path)
    if len(candidates) != 100 or len(layout) != 10:
        raise ValueError("score optimizer requires 100 candidates and 10 active vertiports")
    index = {site["id"]: i for i, site in enumerate(candidates)}
    try:
        active = [index[site["id"]] for site in layout]
    except KeyError as error:
        raise ValueError(f"active site is absent from candidate set: {error.args[0]}") from error
    users = read_aam_users(population, candidates, minimum_trip_miles)
    historical_ground = []
    for i, person_id in enumerate(users.ids):
        if not math.isfinite(users.ground_scores[i]) and ground_score_history and person_id in ground_score_history:
            observation = ground_score_history[person_id]
            users.ground_scores[i] = observation['score']
            historical_ground.append(dict(person=person_id, **observation))
    objective = ScoreObjective(users, candidates, active, base_fare, fare_per_mile,
                               expected_wait_seconds, wait_priors, wait_bin_seconds,
                               maximum_wait_seconds, routing_candidate_vertiports,
                               service_start_time, service_end_time,maximum_walk_distance,maximum_walk_time,
                               max_access_distance_miles,max_egress_distance_miles,allow_pre_service_requests)
    selected, report = optimize_one_swap(objective, active, method,minimum_improvement)
    from .screening import TripScreen
    screening = TripScreen(population, candidates, access_miles=max_access_distance_miles,
                           egress_miles=max_egress_distance_miles,minimum_miles=minimum_trip_miles,
                           service_start=service_start_time, service_end=service_end_time)
    report["inputLayoutScreening"] = screening.evaluate(active)
    report["outputLayoutScreening"] = screening.evaluate(selected)
    report['historicalGroundScoreEstimates'] = historical_ground
    report['groundScorePolicy'] = 'Current scored ground option; otherwise last observed ground option as a historical estimate, never a newly simulated score.'
    report["searchSeconds"] = report["optimizerSeconds"]
    report.update({"population": str(population), "inputLayout": str(layout_path),
                   "outputLayout": str(output_path), "baseFare": base_fare,
                   "farePerMile": fare_per_mile, "expectedWaitSeconds": expected_wait_seconds,
                   "minimumTripMiles": minimum_trip_miles,
                   "waitPriors": str(wait_priors) if wait_priors else None,
                   "waitTimeBinSeconds": wait_bin_seconds,
                   "maximumWaitSeconds": maximum_wait_seconds,
                   "routingCandidateVertiports": routing_candidate_vertiports,
                   "observedWaitCellsUsed": objective.observed_wait_cells})
    report["sha256"] = atomic_write_layout(output_path, [candidates[i] for i in selected])
    report["optimizerSeconds"] = time.perf_counter() - total_started
    output_path.with_suffix(output_path.suffix + ".optimization.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, default=project / "scenarios/aam/vertiport-candidates-100.csv")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", choices=("global", "all-vp-k10", "one-vp-k10", "adaptive"), required=True)
    parser.add_argument("--base-fare", type=float, default=30.0)
    parser.add_argument("--fare-per-mile", type=float, default=2.0)
    parser.add_argument("--expected-wait-seconds", type=float, default=120.0)
    parser.add_argument("--minimum-trip-miles", type=float, default=3.0)
    parser.add_argument("--wait-priors", type=Path, default=None)
    parser.add_argument("--wait-bin-seconds", type=float, default=3600.0)
    parser.add_argument("--maximum-wait-seconds", type=float, default=900.0)
    parser.add_argument("--routing-candidate-vertiports", type=int, default=3)
    args = parser.parse_args()
    report = optimize_population(args.population, args.candidates, args.layout, args.output,
                                 args.method, args.base_fare, args.fare_per_mile,
                                 args.expected_wait_seconds, args.minimum_trip_miles,
                                 args.wait_priors, args.wait_bin_seconds,
                                 args.maximum_wait_seconds,
                                 args.routing_candidate_vertiports)
    print(json.dumps({key: report[key] for key in
                      ("method", "currentAamUsers", "movesEvaluated", "accepted", "improvement",
                       "removed", "added", "optimizerSeconds") if key in report}, indent=2))


if __name__ == "__main__":
    main()
