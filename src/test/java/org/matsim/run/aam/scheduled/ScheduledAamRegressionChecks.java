package org.matsim.run.aam.scheduled;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.List;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.run.RunLosAngelesScenario;

/** Dependency-free executable regression checks used by the PowerShell launcher. */
public final class ScheduledAamRegressionChecks {
    private ScheduledAamRegressionChecks() {
    }

    public static void main(String[] args) throws Exception {
        Config shipped = RunLosAngelesScenario.prepareConfig(
                new String[] { "scenarios/aam-scheduled/la-aam-scheduled.config.xml" },
                new ScheduledAamConfigGroup());
        ScheduledAamConfigGroup shippedAam = ConfigUtils.addOrGetModule(shipped, ScheduledAamConfigGroup.class);
        check(shippedAam.getServiceStartTime() == 7 * 3600, "shipped service starts at 07:00");
        check(shippedAam.getServiceEndTime() == 19 * 3600, "shipped service ends at 19:00");
        check(shippedAam.getHeadway() == 1800, "shipped service has 30-minute headways");
        check("vertiports.csv".equals(shippedAam.getVertiportsFile()), "shipped config resolves its separate vertiport input");
        check(shipped.getModule("multiModeDrt") == null, "scheduled scenario has no DRT config module");
        check(!shipped.qsim().getMainModes().contains(ScheduledAamTransitBuilder.AAM_MODE),
                "AAM transit vehicles are not registered as ordinary traveler vehicles");
        check(shippedAam.isInnovationEnabled(), "scheduled-AAM innovation is enabled");
        check(shipped.controler().getLastIteration() >= 2, "scheduled scenario has multiple learning iterations");
        check(shipped.strategy().getStrategySettings().stream()
                .anyMatch(setting -> "ScheduledAamInnovation".equals(setting.getStrategyName())
                        && setting.getWeight() == 0.05),
                "scheduled-AAM innovation strategy is registered at weight 0.05");

        Path directory = Files.createTempDirectory("scheduled-aam-check-");
        Path csv = directory.resolve("vertiports.csv");
        Files.write(csv, ("id,name,x,y\nA,Alpha,0,0\nB,Beta,3000,4000\n").getBytes(StandardCharsets.UTF_8));

        Config config = ConfigUtils.createConfig(new ScheduledAamConfigGroup());
        config.setContext(directory.toUri().toURL());
        config.transit().setUseTransit(true);
        ScheduledAamConfigGroup aam = ConfigUtils.addOrGetModule(config, ScheduledAamConfigGroup.class);
        aam.setVertiportsFile("vertiports.csv");
        aam.setServiceStartTime(0);
        aam.setServiceEndTime(1800);
        aam.setHeadway(900);
        aam.setDwellTime(60);
        aam.setCruiseSpeed(50);
        aam.setSeats(4);

        Scenario scenario = ScenarioUtils.createScenario(config);
        ScheduledAamTransitBuilder.BuildResult result = ScheduledAamTransitBuilder.build(scenario, aam);
        check(result.vertiports == 2, "two vertiports");
        check(result.routes == 2, "one directed route per ordered pair");
        check(result.departures == 6, "inclusive departures at 0, 900, and 1800");
        check(scenario.getTransitSchedule().getFacilities().size() == 2, "two transit stop facilities");
        check(scenario.getTransitSchedule().getTransitLines().size() == 2, "two transit lines");
        check(scenario.getTransitVehicles().getVehicleTypes().size() == 1, "one aircraft type");
        check(scenario.getTransitVehicles().getVehicles().size() == 6, "one aircraft per departure");

        TransitRoute route = scenario.getTransitSchedule().getTransitLines().values().iterator().next().getRoutes().values().iterator().next();
        check(ScheduledAamTransitBuilder.AAM_MODE.equals(route.getTransportMode()), "route mode is aam");
        check(route.getStops().get(1).getArrivalOffset().orElse(-1) == 100, "flight time follows distance / speed");
        check(route.getRoute().getLinkIds().size() == 1, "route contains one flight link between terminal loops");
        Link flight = scenario.getNetwork().getLinks().get(route.getRoute().getLinkIds().get(0));
        check(flight.getAllowedModes().equals(Collections.singleton("aam")), "flight network is AAM-only");
        check(flight.getLength() == 5000, "Euclidean flight distance");

        aam.setMinimumTripDistance(1);
        aam.setMaximumAccessEgressTime(3600);
        Person person = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("candidate"));
        Plan plan = scenario.getPopulation().getFactory().createPlan();
        Activity origin = scenario.getPopulation().getFactory().createActivityFromCoord("home", route.getStops().get(0).getStopFacility().getCoord());
        origin.setLinkId(route.getStops().get(0).getStopFacility().getLinkId());
        origin.setEndTime(100);
        Leg originalLeg = scenario.getPopulation().getFactory().createLeg("walk");
        Activity destination = scenario.getPopulation().getFactory().createActivityFromCoord("work", route.getStops().get(1).getStopFacility().getCoord());
        destination.setLinkId(route.getStops().get(1).getStopFacility().getLinkId());
        plan.addActivity(origin);
        plan.addLeg(originalLeg);
        plan.addActivity(destination);
        person.addPlan(plan);
        scenario.getPopulation().addPerson(person);

        ScheduledAamPlanStrategyModule innovation = new ScheduledAamPlanStrategyModule(scenario);
        innovation.prepareReplanning(null);
        innovation.handlePlan(plan);
        innovation.finishReplanning();
        List<Leg> requestLegs = TripStructureUtils.getLegs(plan);
        check(requestLegs.size() == 1 && ScheduledAamRoutingModule.MODE.equals(requestLegs.get(0).getMode()),
                "innovation creates an explicit scheduled_aam routing request");
        ScheduledAamRoutingModule router = new ScheduledAamRoutingModule(scenario);
        @SuppressWarnings("unchecked")
        List<org.matsim.api.core.v01.population.PlanElement> routed =
                (List<org.matsim.api.core.v01.population.PlanElement>) router.calcRoute(
                        FacilitiesUtils.wrapActivity(origin), FacilitiesUtils.wrapActivity(destination), 100, person);
        List<Leg> candidateLegs = TripStructureUtils.getLegs(routed);
        check(candidateLegs.size() == 3, "innovation creates access, scheduled flight, and egress legs");
        check(candidateLegs.get(1).getRoute() instanceof TransitPassengerRoute,
                "middle passenger leg uses a transit passenger route");
        TransitPassengerRoute passengerRoute = (TransitPassengerRoute) candidateLegs.get(1).getRoute();
        check(passengerRoute.getLineId().toString().startsWith(ScheduledAamTransitBuilder.PREFIX + "line_"),
                "candidate is pinned to a scheduled AAM transit line");
        check("pt".equals(candidateLegs.get(1).getMode()), "AAM passenger leg retains normal pt mode");
        check(ScheduledAamRoutingModule.MODE.equals(TripStructureUtils.getRoutingMode(candidateLegs.get(1))),
                "whole trip retains scheduled_aam routing identity");
        check(ScheduledAamRoutingModule.MODE.equals(
                candidateLegs.get(1).getAttributes().getAttribute("scoringMode")),
                "aircraft leg receives scheduled_aam scoring parameters");
        check(passengerRoute.getBoardingTime().seconds() == 900,
                "candidate boards the first feasible scheduled departure");

        System.out.println("Scheduled AAM regression checks passed: " + result);
    }

    private static void check(boolean condition, String label) {
        if (!condition) {
            throw new AssertionError("FAILED: " + label);
        }
        System.out.println("PASS: " + label);
    }
}
