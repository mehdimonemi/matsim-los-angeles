package org.matsim.run.aam.scheduled;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.NetworkFactory;
import org.matsim.api.core.v01.network.Node;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.pt.transitSchedule.api.Departure;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitRouteStop;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitScheduleFactory;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.Vehicles;

/** Adds a complete, directed AAM timetable to an existing public-transit scenario. */
public final class ScheduledAamTransitBuilder {
    public static final String AAM_MODE = "aam";
    public static final String PREFIX = "aam_sched_";

    private ScheduledAamTransitBuilder() {
    }

    public static BuildResult build(Scenario scenario, ScheduledAamConfigGroup config) throws IOException {
        if (config.getServiceEndTime() < config.getServiceStartTime()) {
            throw new IllegalArgumentException("serviceEndTime must not precede serviceStartTime");
        }

        URL input = ConfigGroup.getInputFileURL(scenario.getConfig().getContext(), config.getVertiportsFile());
        List<Vertiport> vertiports = readVertiports(input);
        if (vertiports.size() < 2) {
            throw new IllegalArgumentException("At least two vertiports are required: " + input);
        }

        TransitSchedule schedule = scenario.getTransitSchedule();
        Vehicles vehicles = scenario.getTransitVehicles();
        Network network = scenario.getNetwork();
        NetworkFactory networkFactory = network.getFactory();
        TransitScheduleFactory scheduleFactory = schedule.getFactory();

        VehicleType aircraftType = vehicles.getFactory().createVehicleType(Id.create(PREFIX + "aircraft", VehicleType.class));
        aircraftType.setDescription("Scheduled AAM aircraft");
        aircraftType.setNetworkMode(AAM_MODE);
        aircraftType.setLength(8);
        aircraftType.setWidth(4);
        aircraftType.setMaximumVelocity(config.getCruiseSpeed());
        aircraftType.setPcuEquivalents(1);
        aircraftType.getCapacity().setSeats(config.getSeats());
        aircraftType.getCapacity().setStandingRoom(0);
        vehicles.addVehicleType(aircraftType);

        for (Vertiport vertiport : vertiports) {
            Node node = networkFactory.createNode(Id.createNodeId(PREFIX + "node_" + vertiport.id), vertiport.coord);
            network.addNode(node);
            vertiport.node = node;

            Link loop = networkFactory.createLink(Id.createLinkId(PREFIX + "loop_" + vertiport.id), node, node);
            configureAirLink(loop, 1, config.getCruiseSpeed());
            network.addLink(loop);
            vertiport.loop = loop;

            TransitStopFacility stop = scheduleFactory.createTransitStopFacility(
                    Id.create(PREFIX + "stop_" + vertiport.id, TransitStopFacility.class), vertiport.coord, false);
            stop.setName(vertiport.name);
            stop.setLinkId(loop.getId());
            schedule.addStopFacility(stop);
            vertiport.stop = stop;
        }

        int routes = 0;
        int departures = 0;
        for (Vertiport origin : vertiports) {
            for (Vertiport destination : vertiports) {
                if (origin == destination) {
                    continue;
                }
                String pair = origin.id + "_" + destination.id;
                double distance = distance(origin.coord, destination.coord);
                Link flight = networkFactory.createLink(Id.createLinkId(PREFIX + "flight_" + pair), origin.node, destination.node);
                configureAirLink(flight, distance, config.getCruiseSpeed());
                network.addLink(flight);

                double flightTime = Math.ceil(distance / config.getCruiseSpeed());
                List<TransitRouteStop> stops = new ArrayList<>();
                stops.add(scheduleFactory.createTransitRouteStop(origin.stop, 0, 0));
                stops.add(scheduleFactory.createTransitRouteStop(destination.stop, flightTime, flightTime + config.getDwellTime()));
                NetworkRoute networkRoute = RouteUtils.createLinkNetworkRouteImpl(
                        origin.loop.getId(), Collections.singletonList(flight.getId()), destination.loop.getId());

                TransitRoute route = scheduleFactory.createTransitRoute(
                        Id.create(PREFIX + "route_" + pair, TransitRoute.class), networkRoute, stops, AAM_MODE);
                route.setDescription("Scheduled AAM " + origin.name + " to " + destination.name);

                int sequence = 0;
                for (double time = config.getServiceStartTime(); time <= config.getServiceEndTime() + 1e-6; time += config.getHeadway()) {
                    String suffix = String.format(Locale.ROOT, "%04d", sequence++);
                    Id<Vehicle> vehicleId = Id.create(PREFIX + "vehicle_" + pair + "_" + suffix, Vehicle.class);
                    Vehicle aircraft = vehicles.getFactory().createVehicle(vehicleId, aircraftType);
                    vehicles.addVehicle(aircraft);

                    Departure departure = scheduleFactory.createDeparture(
                            Id.create(PREFIX + "departure_" + suffix, Departure.class), time);
                    departure.setVehicleId(vehicleId);
                    route.addDeparture(departure);
                    departures++;
                }

                TransitLine line = scheduleFactory.createTransitLine(Id.create(PREFIX + "line_" + pair, TransitLine.class));
                line.setName("AAM " + origin.id + " - " + destination.id);
                line.addRoute(route);
                schedule.addTransitLine(line);
                routes++;
            }
        }
        return new BuildResult(vertiports.size(), routes, departures);
    }

    static List<Vertiport> readVertiports(URL input) throws IOException {
        List<Vertiport> result = new ArrayList<>();
        Set<String> ids = new HashSet<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input.openStream(), StandardCharsets.UTF_8))) {
            String line;
            int lineNumber = 0;
            while ((line = reader.readLine()) != null) {
                lineNumber++;
                String trimmed = line.trim();
                if (trimmed.isEmpty() || trimmed.startsWith("#") || (lineNumber == 1 && trimmed.toLowerCase(Locale.ROOT).startsWith("id,"))) {
                    continue;
                }
                String[] columns = trimmed.split(",", -1);
                if (columns.length != 4) {
                    throw new IllegalArgumentException("Expected id,name,x,y at " + input + ":" + lineNumber);
                }
                String id = columns[0].trim();
                String name = columns[1].trim();
                if (!id.matches("[A-Za-z0-9_-]+") || !ids.add(id)) {
                    throw new IllegalArgumentException("Invalid or duplicate vertiport id at " + input + ":" + lineNumber + ": " + id);
                }
                try {
                    result.add(new Vertiport(id, name, new Coord(
                            Double.parseDouble(columns[2].trim()), Double.parseDouble(columns[3].trim()))));
                } catch (NumberFormatException error) {
                    throw new IllegalArgumentException("Invalid coordinate at " + input + ":" + lineNumber, error);
                }
            }
        }
        return result;
    }

    private static void configureAirLink(Link link, double length, double speed) {
        link.setLength(Math.max(1, length));
        link.setFreespeed(speed);
        link.setCapacity(100000);
        link.setNumberOfLanes(10);
        link.setAllowedModes(Collections.singleton(AAM_MODE));
    }

    private static double distance(Coord first, Coord second) {
        return Math.hypot(first.getX() - second.getX(), first.getY() - second.getY());
    }

    static final class Vertiport {
        final String id;
        final String name;
        final Coord coord;
        Node node;
        Link loop;
        TransitStopFacility stop;

        Vertiport(String id, String name, Coord coord) {
            this.id = id;
            this.name = name;
            this.coord = coord;
        }
    }

    public static final class BuildResult {
        public final int vertiports;
        public final int routes;
        public final int departures;

        BuildResult(int vertiports, int routes, int departures) {
            this.vertiports = vertiports;
            this.routes = routes;
            this.departures = departures;
        }

        @Override
        public String toString() {
            return "Scheduled AAM: " + vertiports + " vertiports, " + routes + " directed routes, "
                    + departures + " departures";
        }
    }
}
