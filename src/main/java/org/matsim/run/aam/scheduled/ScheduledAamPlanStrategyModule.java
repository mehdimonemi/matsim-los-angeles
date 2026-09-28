package org.matsim.run.aam.scheduled;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.replanning.PlanStrategyModule;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.replanning.ReplanningContext;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.router.TripStructureUtils.Trip;
import org.matsim.pt.PtConstants;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.Departure;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitRouteStop;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

/**
 * Creates an explicit scheduled-AAM candidate while leaving its operation to
 * MATSim's ordinary transit engine. The copied source plan remains available
 * for normal score-based choice in later iterations.
 */
public final class ScheduledAamPlanStrategyModule implements PlanStrategyModule {
    private static final Logger LOG = Logger.getLogger(ScheduledAamPlanStrategyModule.class);
    private static final String ACCESS_MODE = "access_egress_pt";
    private static final Set<String> CHAIN_BASED_MODES = new HashSet<>(Arrays.asList("car", "bike", "freight"));

    private final Scenario scenario;
    private final ScheduledAamConfigGroup config;
    private final List<Flight> flights;
    private int created;
    private int ineligible;

    public ScheduledAamPlanStrategyModule(Scenario scenario) {
        this.scenario = scenario;
        this.config = ConfigUtils.addOrGetModule(scenario.getConfig(), ScheduledAamConfigGroup.class);
        this.flights = readFlights(scenario);
        if (flights.isEmpty()) {
            throw new IllegalStateException("ScheduledAamInnovation found no scheduled AAM transit routes");
        }
    }

    @Override
    public void prepareReplanning(ReplanningContext replanningContext) {
        created = 0;
        ineligible = 0;
    }

    @Override
    public void handlePlan(Plan plan) {
        if (!config.isInnovationEnabled() || containsScheduledAam(plan)) {
            ineligible++;
            return;
        }

        Candidate best = null;
        for (Trip trip : new ArrayList<>(TripStructureUtils.getTrips(plan))) {
            Candidate candidate = candidateFor(trip);
            if (candidate != null && (best == null || candidate.totalTravelTime < best.totalTravelTime)) {
                best = candidate;
            }
        }
        if (best == null) {
            ineligible++;
            return;
        }

        Leg request = scenario.getPopulation().getFactory().createLeg(ScheduledAamRoutingModule.MODE);
        request.setDepartureTime(best.tripDeparture);
        TripStructureUtils.setRoutingMode(request, ScheduledAamRoutingModule.MODE);
        TripRouter.insertTrip(plan, best.trip.getOriginActivity(), java.util.Collections.singletonList(request),
                best.trip.getDestinationActivity());
        plan.getAttributes().putAttribute("scheduled_aam_innovation", true);
        plan.getAttributes().putAttribute("scheduled_aam_corridor", best.flight.line.getId().toString());
        created++;
    }

    @Override
    public void finishReplanning() {
        LOG.info("ScheduledAamInnovation created " + created + " candidate plans; " + ineligible
                + " copied plans were already AAM or had no eligible trip");
    }

    private Candidate candidateFor(Trip trip) {
        if (usesChainBasedMode(trip)) {
            return null;
        }
        Coord origin = coordinate(trip.getOriginActivity());
        Coord destination = coordinate(trip.getDestinationActivity());
        if (origin == null || destination == null || distance(origin, destination) < config.getMinimumTripDistance()) {
            return null;
        }
        double tripDeparture = TripStructureUtils.getDepartureTime(trip)
                .orElse(trip.getOriginActivity().getEndTime().orElse(Double.NaN));
        if (!Double.isFinite(tripDeparture)) {
            return null;
        }

        Candidate best = candidateFor(origin, destination, tripDeparture);
        return best == null ? null : best.withTrip(trip);
    }

    Candidate candidateFor(Coord origin, Coord destination, double tripDeparture) {
        Candidate best = null;
        for (Flight flight : flights) {
            double accessDistance = config.getAccessEgressBeelineFactor() * distance(origin, flight.origin.getCoord());
            double egressDistance = config.getAccessEgressBeelineFactor() * distance(flight.destination.getCoord(), destination);
            double accessTime = accessDistance / config.getAccessEgressSpeed();
            double egressTime = egressDistance / config.getAccessEgressSpeed();
            if (accessTime > config.getMaximumAccessEgressTime() || egressTime > config.getMaximumAccessEgressTime()) {
                continue;
            }

            double arrivalAtVertiport = tripDeparture + accessTime;
            Departure departure = flight.route.getDepartures().values().stream()
                    .filter(value -> value.getDepartureTime() + 1e-6 >= arrivalAtVertiport)
                    .min(Comparator.comparingDouble(Departure::getDepartureTime)).orElse(null);
            if (departure == null) {
                continue;
            }
            double total = accessTime + departure.getDepartureTime() - arrivalAtVertiport
                    + flight.flightTime + egressTime;
            if (best == null || total < best.totalTravelTime) {
                best = new Candidate(null, flight, tripDeparture, accessDistance, accessTime, departure.getDepartureTime(),
                        egressDistance, egressTime, total);
            }
        }
        return best;
    }

    List<PlanElement> createTrip(Candidate candidate,
            org.matsim.api.core.v01.Id<org.matsim.api.core.v01.network.Link> originLink,
            org.matsim.api.core.v01.Id<org.matsim.api.core.v01.network.Link> destinationLink) {
        List<PlanElement> result = new ArrayList<>();

        Leg access = createTeleportedLeg(originLink, candidate.flight.origin.getLinkId(), candidate.tripDeparture,
                candidate.accessDistance, candidate.accessTime);
        result.add(access);
        result.add(createInteraction(candidate.flight.origin));

        Leg aam = scenario.getPopulation().getFactory().createLeg(TransportMode.pt);
        aam.setDepartureTime(candidate.tripDeparture + candidate.accessTime);
        double waitAndFlight = candidate.flightDeparture - aam.getDepartureTime().seconds() + candidate.flight.flightTime;
        aam.setTravelTime(waitAndFlight);
        TripStructureUtils.setRoutingMode(aam, TransportMode.pt);
        DefaultTransitPassengerRoute transitRoute = new DefaultTransitPassengerRoute(candidate.flight.origin,
                candidate.flight.line, candidate.flight.route, candidate.flight.destination);
        transitRoute.setBoardingTime(candidate.flightDeparture);
        transitRoute.setDistance(candidate.flight.distance);
        transitRoute.setTravelTime(waitAndFlight);
        aam.setRoute(transitRoute);
        aam.getAttributes().putAttribute("scoringMode", ScheduledAamRoutingModule.MODE);
        result.add(aam);
        result.add(createInteraction(candidate.flight.destination));

        double egressDeparture = candidate.flightDeparture + candidate.flight.flightTime;
        result.add(createTeleportedLeg(candidate.flight.destination.getLinkId(), destinationLink, egressDeparture,
                candidate.egressDistance, candidate.egressTime));
        for (Leg leg : TripStructureUtils.getLegs(result)) {
            TripStructureUtils.setRoutingMode(leg, ScheduledAamRoutingModule.MODE);
        }
        return result;
    }

    private Leg createTeleportedLeg(org.matsim.api.core.v01.Id<org.matsim.api.core.v01.network.Link> from,
            org.matsim.api.core.v01.Id<org.matsim.api.core.v01.network.Link> to, double departure,
            double routeDistance, double travelTime) {
        Leg leg = scenario.getPopulation().getFactory().createLeg(ACCESS_MODE);
        leg.setDepartureTime(departure);
        leg.setTravelTime(travelTime);
        TripStructureUtils.setRoutingMode(leg, TransportMode.pt);
        org.matsim.api.core.v01.population.Route route = RouteUtils.createGenericRouteImpl(from, to);
        route.setDistance(routeDistance);
        route.setTravelTime(travelTime);
        leg.setRoute(route);
        return leg;
    }

    private Activity createInteraction(TransitStopFacility stop) {
        Activity interaction = scenario.getPopulation().getFactory().createActivityFromCoord(
                PtConstants.TRANSIT_ACTIVITY_TYPE, stop.getCoord());
        interaction.setLinkId(stop.getLinkId());
        interaction.setMaximumDuration(0);
        return interaction;
    }

    private Coord coordinate(Activity activity) {
        if (activity.getCoord() != null) {
            return activity.getCoord();
        }
        if (activity.getLinkId() == null || scenario.getNetwork().getLinks().get(activity.getLinkId()) == null) {
            return null;
        }
        return scenario.getNetwork().getLinks().get(activity.getLinkId()).getCoord();
    }

    private static boolean usesChainBasedMode(Trip trip) {
        return trip.getLegsOnly().stream().anyMatch(leg -> CHAIN_BASED_MODES.contains(leg.getMode()));
    }

    private static boolean containsScheduledAam(Plan plan) {
        for (Leg leg : TripStructureUtils.getLegs(plan)) {
            if (leg.getRoute() instanceof TransitPassengerRoute) {
                TransitPassengerRoute route = (TransitPassengerRoute) leg.getRoute();
                if (route.getLineId() != null
                        && route.getLineId().toString().startsWith(ScheduledAamTransitBuilder.PREFIX + "line_")) {
                    return true;
                }
            }
        }
        return false;
    }

    private static List<Flight> readFlights(Scenario scenario) {
        List<Flight> result = new ArrayList<>();
        for (TransitLine line : scenario.getTransitSchedule().getTransitLines().values()) {
            if (!line.getId().toString().startsWith(ScheduledAamTransitBuilder.PREFIX + "line_")) {
                continue;
            }
            for (TransitRoute route : line.getRoutes().values()) {
                if (!ScheduledAamTransitBuilder.AAM_MODE.equals(route.getTransportMode()) || route.getStops().size() < 2) {
                    continue;
                }
                TransitRouteStop first = route.getStops().get(0);
                TransitRouteStop last = route.getStops().get(route.getStops().size() - 1);
                double flightTime = last.getArrivalOffset().seconds() - first.getDepartureOffset().seconds();
                double flightDistance = RouteUtils.calcDistance(route, first.getStopFacility(), last.getStopFacility(),
                        scenario.getNetwork());
                result.add(new Flight(line, route, first.getStopFacility(), last.getStopFacility(), flightTime,
                        flightDistance));
            }
        }
        return result;
    }

    private static double distance(Coord first, Coord second) {
        return Math.hypot(first.getX() - second.getX(), first.getY() - second.getY());
    }

    private static final class Flight {
        final TransitLine line;
        final TransitRoute route;
        final TransitStopFacility origin;
        final TransitStopFacility destination;
        final double flightTime;
        final double distance;

        Flight(TransitLine line, TransitRoute route, TransitStopFacility origin, TransitStopFacility destination,
                double flightTime, double distance) {
            this.line = line;
            this.route = route;
            this.origin = origin;
            this.destination = destination;
            this.flightTime = flightTime;
            this.distance = distance;
        }
    }

    static final class Candidate {
        final Trip trip;
        final Flight flight;
        final double tripDeparture;
        final double accessDistance;
        final double accessTime;
        final double flightDeparture;
        final double egressDistance;
        final double egressTime;
        final double totalTravelTime;

        Candidate(Trip trip, Flight flight, double tripDeparture, double accessDistance, double accessTime,
                double flightDeparture, double egressDistance, double egressTime, double totalTravelTime) {
            this.trip = trip;
            this.flight = flight;
            this.tripDeparture = tripDeparture;
            this.accessDistance = accessDistance;
            this.accessTime = accessTime;
            this.flightDeparture = flightDeparture;
            this.egressDistance = egressDistance;
            this.egressTime = egressTime;
            this.totalTravelTime = totalTravelTime;
        }

        Candidate withTrip(Trip value) {
            return new Candidate(value, flight, tripDeparture, accessDistance, accessTime, flightDeparture,
                    egressDistance, egressTime, totalTravelTime);
        }
    }
}
