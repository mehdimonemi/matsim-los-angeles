"""Vectorized TR Part D AAM flight-time profile shared by both optimizers."""
from __future__ import annotations

import numpy as np

METERS_PER_NAUTICAL_MILE = 1852.0
CLIMB_DESCENT_SPEED_KNOTS = 56.0
CRUISE_SPEED_KNOTS = 98.0
MIN_CRUISE_ALTITUDE_FEET = 1000.0
MAX_CRUISE_ALTITUDE_FEET = 3000.0
ALTITUDE_STEP_FEET = 500.0
VERTICAL_PHASE_START_FEET = 50.0
CLIMB_RATE_FEET_PER_MINUTE = 1000.0
TRANSITION_AND_CLIMBOUT_SECONDS = 40.0
TRANSITION_HOVER_AND_DESCENT_SECONDS = 70.0


def required_climb_descent_distance_meters(altitude_feet: float) -> float:
    phase_seconds = ((altitude_feet - VERTICAL_PHASE_START_FEET)
                     / CLIMB_RATE_FEET_PER_MINUTE * 60.0)
    distance_nmi = 2.0 * CLIMB_DESCENT_SPEED_KNOTS * phase_seconds / 3600.0
    return distance_nmi * METERS_PER_NAUTICAL_MILE


MINIMUM_FLIGHT_DISTANCE_METERS = required_climb_descent_distance_meters(MIN_CRUISE_ALTITUDE_FEET)


def flight_time_seconds(distance_meters: np.ndarray | float) -> np.ndarray:
    """Return rounded-up flight seconds; infeasible distances return infinity."""
    distance = np.asarray(distance_meters, dtype=float)
    distance_nmi = distance / METERS_PER_NAUTICAL_MILE
    feasible = np.isfinite(distance) & (distance >= MINIMUM_FLIGHT_DISTANCE_METERS - 1e-6)
    altitude = np.full(distance.shape, MIN_CRUISE_ALTITUDE_FEET, dtype=float)
    for tier in np.arange(MIN_CRUISE_ALTITUDE_FEET + ALTITUDE_STEP_FEET,
                         MAX_CRUISE_ALTITUDE_FEET + 1.0, ALTITUDE_STEP_FEET):
        altitude = np.where(distance >= required_climb_descent_distance_meters(tier) - 1e-6,
                            tier, altitude)
    climb_descent_seconds = ((altitude - VERTICAL_PHASE_START_FEET)
                             / CLIMB_RATE_FEET_PER_MINUTE * 60.0)
    one_phase_distance_nmi = CLIMB_DESCENT_SPEED_KNOTS * climb_descent_seconds / 3600.0
    cruise_distance_nmi = np.maximum(0.0, distance_nmi - 2.0 * one_phase_distance_nmi)
    cruise_seconds = cruise_distance_nmi / CRUISE_SPEED_KNOTS * 3600.0
    seconds = np.ceil(TRANSITION_AND_CLIMBOUT_SECONDS + 2.0 * climb_descent_seconds
                     + cruise_seconds + TRANSITION_HOVER_AND_DESCENT_SECONDS)
    return np.where(feasible, seconds, np.inf)
