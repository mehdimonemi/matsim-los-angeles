package org.matsim.run.aam;

/** Distance-based altitude selection and flight time for the TR Part D mission profile. */
public final class AamMissionProfile {
    public static final double METERS_PER_NAUTICAL_MILE = 1852.0;
    public static final double KNOTS_TO_METERS_PER_SECOND = METERS_PER_NAUTICAL_MILE / 3600.0;
    public static final double MIN_CRUISE_ALTITUDE_FEET = 1000.0;
    public static final double MAX_CRUISE_ALTITUDE_FEET = 3000.0;
    public static final double ALTITUDE_STEP_FEET = 500.0;
    public static final double MINIMUM_FLIGHT_DISTANCE_METERS =
            requiredClimbAndDescentDistanceMeters(MIN_CRUISE_ALTITUDE_FEET);

    private static final double TRANSITION_AND_CLIMBOUT_SECONDS = 40.0;
    private static final double TRANSITION_HOVER_AND_DESCENT_SECONDS = 70.0;
    private static final double VERTICAL_PHASE_START_ALTITUDE_FEET = 50.0;
    private static final double CLIMB_RATE_FEET_PER_MINUTE = 1000.0;
    private static final double CLIMB_AND_DESCENT_SPEED_KNOTS = 56.0;
    private static final double CRUISE_SPEED_KNOTS = 98.0;
    private static final double DISTANCE_TOLERANCE_METERS = 1e-6;

    private AamMissionProfile() { }

    public static boolean isFeasible(double distanceMeters) {
        return Double.isFinite(distanceMeters)
                && distanceMeters + DISTANCE_TOLERANCE_METERS >= MINIMUM_FLIGHT_DISTANCE_METERS;
    }

    /** Select the highest 500-ft altitude tier whose climb and descent fit the flight distance. */
    public static double cruiseAltitudeFeet(double distanceMeters) {
        if (!isFeasible(distanceMeters)) {
            throw new IllegalArgumentException("AAM flight distance is below the 1000-ft mission-profile minimum: "
                    + distanceMeters + " m");
        }
        for (double altitude = MAX_CRUISE_ALTITUDE_FEET;
             altitude >= MIN_CRUISE_ALTITUDE_FEET; altitude -= ALTITUDE_STEP_FEET) {
            if (requiredClimbAndDescentDistanceMeters(altitude)
                    <= distanceMeters + DISTANCE_TOLERANCE_METERS) {
                return altitude;
            }
        }
        return MIN_CRUISE_ALTITUDE_FEET;
    }

    /** Complete airborne time: climb, cruise, descent, and both fixed transition phases. */
    public static double flightTimeSeconds(double distanceMeters) {
        double altitude = cruiseAltitudeFeet(distanceMeters);
        double climbTime = climbOrDescentTimeSeconds(altitude);
        double climbDistanceNauticalMiles = CLIMB_AND_DESCENT_SPEED_KNOTS * climbTime / 3600.0;
        double totalDistanceNauticalMiles = distanceMeters / METERS_PER_NAUTICAL_MILE;
        double cruiseDistanceNauticalMiles = Math.max(0.0,
                totalDistanceNauticalMiles - 2.0 * climbDistanceNauticalMiles);
        double cruiseTime = cruiseDistanceNauticalMiles / CRUISE_SPEED_KNOTS * 3600.0;
        return Math.ceil(TRANSITION_AND_CLIMBOUT_SECONDS + climbTime + climbTime + cruiseTime
                + TRANSITION_HOVER_AND_DESCENT_SECONDS);
    }

    private static double requiredClimbAndDescentDistanceMeters(double altitudeFeet) {
        double distanceNauticalMiles = 2.0 * CLIMB_AND_DESCENT_SPEED_KNOTS
                * climbOrDescentTimeSeconds(altitudeFeet) / 3600.0;
        return distanceNauticalMiles * METERS_PER_NAUTICAL_MILE;
    }

    private static double climbOrDescentTimeSeconds(double altitudeFeet) {
        return (altitudeFeet - VERTICAL_PHASE_START_ALTITUDE_FEET)
                / CLIMB_RATE_FEET_PER_MINUTE * 60.0;
    }
}
