"""All-passenger diagnostic screen, independent of the optimizer score objective.

Distance matrices cover every daily trip and every candidate site. Layout swaps
reuse these matrices; a full vectorized scan is cheaper and simpler than a
mutable nearest-neighbor index for ten active sites. Feasibility is optimistic
until MATSim supplies actual network routes.
"""
import gzip
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from .common import MILE, distance_matrix
from .optimizer import _is_main_activity, _time_seconds


class TripScreen:
    def __init__(self, population: Path, sites: list[dict], access_miles=5., egress_miles=None,
                 minimum_miles=3., service_start=25200., service_end=68400.):
        started = time.perf_counter()
        self.people, self.trips = [], []
        opener = gzip.open if population.suffix == '.gz' else open
        with opener(population, 'rb') as stream:
            for _, person in ET.iterparse(stream, events=('end',)):
                if person.tag != 'person':
                    continue
                if (person.findtext("./attributes/attribute[@name='subpopulation']") or 'person') != 'person':
                    person.clear(); continue
                self.people.append(person.get('id'))
                plan = next((p for p in person.findall('plan') if p.get('selected') == 'yes'), None)
                if plan is not None:
                    elements = list(plan)
                    main = [i for i, e in enumerate(elements) if _is_main_activity(e)]
                    for index, (a, b) in enumerate(zip(main, main[1:])):
                        origin, destination = elements[a], elements[b]
                        def coord(activity):
                            try: return float(activity.get('x')), float(activity.get('y'))
                            except (TypeError, ValueError): return math.nan, math.nan
                        legs = [e for e in elements[a+1:b] if e.tag == 'leg']
                        departure = _time_seconds(origin.get('end_time') or (legs[0].get('dep_time') if legs else None))
                        direction = ('home_to_non_home' if origin.get('type', '').startswith('home') else
                                     'non_home_to_home' if destination.get('type', '').startswith('home') else 'non_home_to_non_home')
                        self.trips.append((person.get('id'), index, coord(origin), coord(destination), departure, direction))
                person.clear()
        coords = np.asarray([(s['x'], s['y']) for s in sites], dtype=float)
        self.origins = np.asarray([t[2] for t in self.trips], dtype=float).reshape(-1, 2)
        self.destinations = np.asarray([t[3] for t in self.trips], dtype=float).reshape(-1, 2)
        self.origin_distance = distance_matrix(self.origins, coords)
        self.destination_distance = distance_matrix(self.destinations, coords)
        self.site_distance = distance_matrix(coords, coords)
        self.direct = np.linalg.norm(self.origins-self.destinations, axis=1)
        self.departure = np.asarray([t[4] for t in self.trips])
        self.access = access_miles*MILE
        self.egress = (access_miles if egress_miles is None else egress_miles)*MILE
        self.minimum, self.start, self.end = minimum_miles*MILE, service_start, service_end
        self.cache, self.states, self.scans = {}, {}, 0
        self.precompute_seconds = time.perf_counter()-started

    def evaluate(self, active: list[int]) -> dict:
        key = tuple(sorted(active))
        if key in self.cache:
            return self.cache[key]
        started = time.perf_counter(); self.scans += 1
        n = len(self.trips)
        geometric = np.zeros(n, dtype=bool); temporal = geometric.copy()
        proxy = np.full(n, np.inf)
        pair = np.full((n, 2), -1, dtype=int)
        for origin in key:
            for destination in key:
                if origin == destination: continue
                g = ((self.direct >= self.minimum) & (self.origin_distance[:, origin] <= self.access)
                     & (self.destination_distance[:, destination] <= self.egress))
                geometric |= g
                flight = self.site_distance[origin, destination]/(100*MILE/3600)+1
                valid = g & (np.maximum(self.departure, self.start)+flight+120 <= self.end)
                temporal |= valid
                cost = (self.origin_distance[:, origin]+self.destination_distance[:, destination])/13.89+flight
                improved = valid & (cost < proxy)
                proxy[improved] = cost[improved]; pair[improved] = origin, destination
        ranked = {}
        for row in np.flatnonzero(temporal):
            ranked.setdefault(self.trips[row][0], []).append(int(row))
        for person, rows in ranked.items():
            ranked[person] = sorted(rows, key=lambda row: (proxy[row], self.trips[row][1]))[:2]
        origin_min = np.nanmin(self.origin_distance[:, key], axis=1)
        destination_min = np.nanmin(self.destination_distance[:, key], axis=1)
        missing = ~np.isfinite(self.direct)
        short = ~missing & (self.direct < self.minimum)
        outside_access = ~missing & ~short & (origin_min > self.access)
        outside_egress = ~missing & ~short & ~outside_access & (destination_min > self.egress)
        reasons = dict(missing_activity_coordinates=int(missing.sum()), minimum_trip_distance=int(short.sum()),
                       access_distance=int(outside_access.sum()), egress_distance=int(outside_egress.sum()),
                       same_vertiport=int((~geometric & ~missing & ~short & ~outside_access & ~outside_egress).sum()),
                       service_window=int((geometric & ~temporal).sum()), unrouted=int(temporal.sum()))
        self.states[key] = dict(geometric=geometric, temporal=temporal, best_pair=pair, proxy=proxy,
                                nearest_origin=np.asarray(key)[np.argmin(self.origin_distance[:, key], axis=1)],
                                nearest_destination=np.asarray(key)[np.argmin(self.destination_distance[:, key], axis=1)],
                                ranked_candidates=ranked)
        result = dict(passengerAgentsEvaluated=len(self.people), totalTripsEvaluated=n,
                      geometricallyEligibleTrips=int(geometric.sum()), temporallyEligibleTrips=int(temporal.sum()),
                      passengersWithEligibleCandidate=len(ranked), unresolvedCandidates=n,
                      screenedCandidatesForRouting=sum(map(len, ranked.values())),
                      infeasibilityReasons=reasons,
                      precomputeSeconds=self.precompute_seconds, layoutScreenSeconds=time.perf_counter()-started,
                      interpretation='Screened eligibility is a candidate, not network feasibility or adoption.')
        self.cache[key] = result
        return result
