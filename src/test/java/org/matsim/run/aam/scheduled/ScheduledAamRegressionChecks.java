package org.matsim.run.aam.scheduled;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.List;
import java.util.Map;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ModeParams;
import org.matsim.contrib.drt.run.DrtConfigGroup;
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
        check(shippedAam.getMinimumTripDistance() == 3 * 1609.344,
                "scheduled AAM uses the same three-mile minimum trip as AAM DRT");
        check(shippedAam.getMaximumGroundAccessDistanceMiles() == 5,
                "scheduled AAM uses the same five-mile origin radius as AAM DRT");
        check(shippedAam.getCandidateVertiports() == 3,
                "scheduled AAM jointly searches three origin- and destination-side vertiports");
        check("vertiports.csv".equals(shippedAam.getVertiportsFile()), "shipped config resolves its separate vertiport input");
        check(shipped.getModule("multiModeDrt") == null, "scheduled scenario has no DRT config module");
        Config cleanupConfig = ConfigUtils.createConfig();
        ConfigUtils.addOrGetModule(cleanupConfig, DrtConfigGroup.class);
        ScheduledAamPlanStrategyModule.removeRouterAddedLegacyDrt(cleanupConfig, false);
        check(!cleanupConfig.getModules().containsKey(DrtConfigGroup.GROUP_NAME),
                "scheduled feeder initialization removes a newly introduced legacy DRT config");
        Config retainedConfig = ConfigUtils.createConfig();
        ConfigUtils.addOrGetModule(retainedConfig, DrtConfigGroup.class);
        ScheduledAamPlanStrategyModule.removeRouterAddedLegacyDrt(retainedConfig, true);
        check(retainedConfig.getModules().containsKey(DrtConfigGroup.GROUP_NAME),
                "scheduled feeder initialization preserves an explicitly configured legacy DRT module");
        check(!shipped.qsim().getMainModes().contains(ScheduledAamTransitBuilder.AAM_MODE),
                "AAM transit vehicles are not registered as ordinary traveler vehicles");
        check(shippedAam.isInnovationEnabled(), "scheduled-AAM innovation is enabled");
        check(shipped.controler().getLastIteration() >= 2, "scheduled scenario has multiple learning iterations");
        check(shipped.strategy().getStrategySettings().stream()
                .anyMatch(setting -> "ScheduledAamInnovation".equals(setting.getStrategyName())
                        && setting.getWeight() == 0.05),
                "scheduled-AAM innovation strategy is registered at weight 0.05");
        Map<String, String> options = RunScheduledAamLosAngelesScenario.parseOptions(
                new String[] { "config.xml", "output", "--plans=checkpoint.xml.gz", "--disable-innovation" }, 2);
        check("checkpoint.xml.gz".equals(options.get("plans")), "staged runner accepts a plans checkpoint");
        check(options.containsKey("disable-innovation"), "staged runner accepts fixed-layout convergence mode");

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
        aam.setAccessEgressModes("walk");

        Scenario scenario = ScenarioUtils.createScenario(config);
        org.matsim.api.core.v01.network.Node roadA = scenario.getNetwork().getFactory().createNode(
                Id.createNodeId("roadA"), new org.matsim.api.core.v01.Coord(0, 0));
        org.matsim.api.core.v01.network.Node roadB = scenario.getNetwork().getFactory().createNode(
                Id.createNodeId("roadB"), new org.matsim.api.core.v01.Coord(3000, 4000));
        scenario.getNetwork().addNode(roadA);
        scenario.getNetwork().addNode(roadB);
        Link road = scenario.getNetwork().getFactory().createLink(Id.createLinkId("road"), roadA, roadB);
        road.setLength(5000);
        road.setFreespeed(20);
        road.setCapacity(1000);
        road.setNumberOfLanes(1);
        road.setAllowedModes(new java.util.HashSet<>(java.util.Arrays.asList("car", "ride", "ride_taxi", "bike")));
        scenario.getNetwork().addLink(road);
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
        Person person = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("candidate"));
        person.getAttributes().putAttribute("subpopulation", "person");
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

        Person farPerson = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("far-candidate"));
        farPerson.getAttributes().putAttribute("subpopulation", "person");
        Plan farPlan = scenario.getPopulation().getFactory().createPlan();
        Activity farOrigin = scenario.getPopulation().getFactory().createActivityFromCoord("home", new org.matsim.api.core.v01.Coord(20000, 0));
        farOrigin.setLinkId(route.getStops().get(0).getStopFacility().getLinkId());
        farOrigin.setEndTime(100);
        Activity farDestination = scenario.getPopulation().getFactory().createActivityFromCoord("work", new org.matsim.api.core.v01.Coord(0, 0));
        farDestination.setLinkId(route.getStops().get(1).getStopFacility().getLinkId());
        farPlan.addActivity(farOrigin);
        farPlan.addLeg(scenario.getPopulation().getFactory().createLeg("walk"));
        farPlan.addActivity(farDestination);
        farPerson.addPlan(farPlan);
        scenario.getPopulation().addPerson(farPerson);

        Person complexCarPerson = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("complex-car-tour"));
        complexCarPerson.getAttributes().putAttribute("subpopulation", "person");
        Plan complexCarPlan = scenario.getPopulation().getFactory().createPlan();
        Activity complexHome = scenario.getPopulation().getFactory().createActivityFromCoord("home", roadA.getCoord());
        complexHome.setLinkId(road.getId()); complexHome.setEndTime(100);
        Activity complexWork = scenario.getPopulation().getFactory().createActivityFromCoord("work", roadB.getCoord());
        complexWork.setLinkId(road.getId()); complexWork.setEndTime(700);
        Activity complexShop = scenario.getPopulation().getFactory().createActivityFromCoord("shop", roadA.getCoord());
        complexShop.setLinkId(road.getId()); complexShop.setEndTime(1300);
        Activity complexReturn = scenario.getPopulation().getFactory().createActivityFromCoord("home", roadB.getCoord());
        complexReturn.setLinkId(road.getId());
        complexCarPlan.addActivity(complexHome);
        complexCarPlan.addLeg(scenario.getPopulation().getFactory().createLeg("car"));
        complexCarPlan.addActivity(complexWork);
        complexCarPlan.addLeg(scenario.getPopulation().getFactory().createLeg("car"));
        complexCarPlan.addActivity(complexShop);
        complexCarPlan.addLeg(scenario.getPopulation().getFactory().createLeg("car"));
        complexCarPlan.addActivity(complexReturn);
        complexCarPerson.addPlan(complexCarPlan);
        scenario.getPopulation().addPerson(complexCarPerson);

        List<Plan> guaranteed = new ScheduledAamAlternativeGuarantee(scenario).seedAlternatives();
        check(guaranteed.size() == 2 && person.getPlans().size() == 2
                        && ScheduledAamAlternativeGuarantee.hasScheduledAam(person),
                "nearby eligible traveler receives one separate scheduled-AAM alternative");
        check(farPerson.getPlans().size() == 1 && !ScheduledAamAlternativeGuarantee.hasScheduledAam(farPerson),
                "traveler outside the five-mile origin radius is not guaranteed an AAM plan");
        Plan complexAamPlan = complexCarPerson.getPlans().stream()
                .filter(ScheduledAamPlanStrategyModule::containsScheduledAam).findFirst().orElseThrow();
        check(complexCarPerson.getPlans().size() == 2
                        && TripStructureUtils.getLegs(complexCarPlan).stream().allMatch(leg -> "car".equals(leg.getMode()))
                        && TripStructureUtils.getLegs(complexAamPlan).stream()
                        .noneMatch(leg -> "car".equals(leg.getMode()) || "bike".equals(leg.getMode())),
                "guaranteed complex car tour keeps its original and uses passenger ride in the AAM clone");

        ScheduledAamPlanStrategyModule innovation = new ScheduledAamPlanStrategyModule(scenario);
        innovation.prepareReplanning(null);
        innovation.handlePlan(plan);
        innovation.finishReplanning();
        List<Leg> innovationLegs = TripStructureUtils.getLegs(plan);
        check(innovationLegs.size() == 5 && innovationLegs.get(2).getRoute() instanceof TransitPassengerRoute,
                "innovation directly creates a complete scheduled-AAM trip");
        ScheduledAamRoutingModule router = new ScheduledAamRoutingModule(scenario);
        @SuppressWarnings("unchecked")
        List<org.matsim.api.core.v01.population.PlanElement> routed =
                (List<org.matsim.api.core.v01.population.PlanElement>) router.calcRoute(
                        FacilitiesUtils.wrapActivity(origin), FacilitiesUtils.wrapActivity(destination), 100, person);
        List<Leg> candidateLegs = TripStructureUtils.getLegs(routed);
        check(candidateLegs.size() == 5, "innovation creates access, airside connectors, scheduled flight, and egress legs");
        check(candidateLegs.get(2).getRoute() instanceof TransitPassengerRoute,
                "middle passenger leg uses a transit passenger route");
        check(candidateLegs.get(1).getRoute().getEndLinkId().equals(
                        route.getStops().get(0).getStopFacility().getLinkId())
                        && candidateLegs.get(3).getRoute().getStartLinkId().equals(
                        route.getStops().get(1).getStopFacility().getLinkId()),
                "connector legs place the traveler on each AAM stop link before and after flight");
        TransitPassengerRoute passengerRoute = (TransitPassengerRoute) candidateLegs.get(2).getRoute();
        check(passengerRoute.getLineId().toString().startsWith(ScheduledAamTransitBuilder.PREFIX + "line_"),
                "candidate is pinned to a scheduled AAM transit line");
        check("pt".equals(candidateLegs.get(2).getMode()), "AAM passenger leg retains normal pt mode");
        check(ScheduledAamRoutingModule.MODE.equals(TripStructureUtils.getRoutingMode(candidateLegs.get(2))),
                "whole trip retains scheduled_aam routing identity");
        check(ScheduledAamRoutingModule.MODE.equals(
                candidateLegs.get(2).getAttributes().getAttribute("scoringMode")),
                "aircraft leg receives scheduled_aam scoring parameters");
        check(passengerRoute.getBoardingTime().seconds() == 900,
                "candidate boards the first feasible scheduled departure");

        aam.setAccessEgressModes("car,ride");
        config.planCalcScore().addModeParams(new ModeParams("ride").setConstant(0)
                .setMarginalUtilityOfTraveling(-6).setMonetaryDistanceRate(0));
        Person tourPerson = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("paired-tour"));
        Plan tour = scenario.getPopulation().getFactory().createPlan();
        Activity tourHome = scenario.getPopulation().getFactory().createActivityFromCoord("home", new org.matsim.api.core.v01.Coord(0, 0));
        tourHome.setLinkId(road.getId()); tourHome.setEndTime(100);
        Activity tourWork = scenario.getPopulation().getFactory().createActivityFromCoord("work", new org.matsim.api.core.v01.Coord(3000, 4000));
        tourWork.setLinkId(road.getId()); tourWork.setEndTime(1000);
        Activity tourReturn = scenario.getPopulation().getFactory().createActivityFromCoord("home", new org.matsim.api.core.v01.Coord(0, 0));
        tourReturn.setLinkId(road.getId());
        tour.addActivity(tourHome); tour.addLeg(scenario.getPopulation().getFactory().createLeg("car"));
        tour.addActivity(tourWork); tour.addLeg(scenario.getPopulation().getFactory().createLeg("car"));
        tour.addActivity(tourReturn); tourPerson.addPlan(tour); scenario.getPopulation().addPerson(tourPerson);
        check(new ScheduledAamPlanStrategyModule(scenario).addAlternative(tour),
                "eligible private-car tour receives a paired scheduled-AAM alternative");
        long pairedFlights = TripStructureUtils.getLegs(tour).stream()
                .filter(leg -> leg.getRoute() instanceof TransitPassengerRoute).count();
        check(pairedFlights == 2 && "car".equals(tour.getAttributes().getAttribute(
                        ScheduledAamPlanStrategyModule.PARK_MODE)),
                "outbound and return flights preserve the home-side parked car");

        Plan staged = scenario.getPopulation().getFactory().createPlan();
        staged.addActivity(tourHome);
        Leg stagedRequest = scenario.getPopulation().getFactory().createLeg(ScheduledAamRoutingModule.MODE);
        TripStructureUtils.setRoutingMode(stagedRequest, ScheduledAamRoutingModule.MODE);
        staged.addLeg(stagedRequest);
        staged.addActivity(tourWork);
        check(ScheduledAamAlternativeGuarantee.needsScheduledAamRouting(staged),
                "staged scheduled-AAM requests are detected for layout-aware startup rerouting");

        ScheduledAamRoutingModule withFallback = new ScheduledAamRoutingModule(scenario,
                (from, to, departure, routedPerson) -> Collections.singletonList(
                        scenario.getPopulation().getFactory().createLeg(TransportMode.walk)));
        List<? extends org.matsim.api.core.v01.population.PlanElement> fallback = withFallback.calcRoute(
                FacilitiesUtils.wrapActivity(origin), FacilitiesUtils.wrapActivity(destination), 1900, person);
        check(fallback.size() == 1 && TransportMode.walk.equals(((Leg) fallback.get(0)).getMode()),
                "infeasible carried-over AAM request safely falls back instead of crashing");
        org.matsim.core.router.RoutingModule emptyTransit = (from,to,time,p) -> {throw new AssertionError("Unavailable ground transit must not be used as AAM fallback");};
        org.matsim.core.router.RoutingModule availableRide = (from,to,time,p) -> Collections.singletonList(scenario.getPopulation().getFactory().createLeg("ride"));
        ScheduledAamRoutingModule emptyTransitSafe = new ScheduledAamRoutingModule(scenario,emptyTransit,
            ScheduledAamPlanStrategyModule.routers(availableRide,availableRide,availableRide,availableRide,availableRide));
        List<? extends org.matsim.api.core.v01.population.PlanElement> roadFallback=emptyTransitSafe.calcRoute(
            FacilitiesUtils.wrapActivity(origin),FacilitiesUtils.wrapActivity(destination),1900,person);
        check("ride".equals(((Leg)roadFallback.get(0)).getMode()),"layout restart can use road outside option with no ground transit");

        // Historic observed walking segments: both ends must fail independently.
        for(double[] trace:new double[][]{{8624,8170},{21226,20108},{10457,9907},{32354,30651}}){
            Leg walk=scenario.getPopulation().getFactory().createLeg("walk");
            org.matsim.api.core.v01.population.Route wr=org.matsim.core.population.routes.RouteUtils.createGenericRouteImpl(road.getId(),road.getId());
            wr.setDistance(trace[0]);wr.setTravelTime(trace[1]);walk.setRoute(wr);walk.setTravelTime(trace[1]);
            check(!org.matsim.run.aam.AamFeederPolicy.admissible(List.of(walk),1000,1200),
                "historical 10096817/10092375 access or egress is prohibited: "+trace[0]+" m");
        }
        Leg cleanedWalk=scenario.getPopulation().getFactory().createLeg("walk");
        org.matsim.api.core.v01.population.Route cleanRoute=org.matsim.core.population.routes.RouteUtils.createGenericRouteImpl(road.getId(),road.getId());
        cleanRoute.setDistance(100);cleanRoute.setTravelTime(100);cleanedWalk.setRoute(cleanRoute);
        check(org.matsim.run.aam.AamFeederPolicy.admissible(List.of(cleanedWalk),1000,1200),
            "VspPlansCleaner clearing leg time does not invalidate a valid routed feeder");
        Path restart=directory.resolve("restart.xml");
        Files.writeString(restart,"<?xml version=\"1.0\"?><!DOCTYPE population SYSTEM \"http://www.matsim.org/files/dtd/population_v6.dtd\"><population><person id=\"restart\"><plan selected=\"yes\" score=\"10\"><activity type=\"home\" x=\"0\" y=\"0\"/></plan><plan selected=\"no\" score=\"9\"><activity type=\"home\" x=\"0\" y=\"0\"/></plan></person></population>");
        Config restartConfig=ConfigUtils.createConfig();restartConfig.plans().setInputFile(restart.toString());
        Scenario restarted=RunLosAngelesScenario.prepareScenario(restartConfig,true);
        check(restarted.getPopulation().getPersons().get(Id.createPersonId("restart")).getPlans().size()==2,
            "real scenario startup retains BOTH scored plans across a stage restart");
        check(restarted.getPopulation().getPersons().get(Id.createPersonId("restart")).getPlans().get(1).getScore()==9,
            "unchanged loaded plans keep their score until layout rerouting invalidates it");
        Path allocation=directory.resolve("frequencies.csv");
        Files.writeString(allocation,"origin,destination,departures\nA,B,5\nB,A,1\n");
        Config frequencyConfig=ConfigUtils.createConfig(new ScheduledAamConfigGroup());
        frequencyConfig.setContext(directory.toUri().toURL());frequencyConfig.transit().setUseTransit(true);
        ScheduledAamConfigGroup frequency=ConfigUtils.addOrGetModule(frequencyConfig,ScheduledAamConfigGroup.class);
        frequency.setVertiportsFile(csv.toString());frequency.setFrequencyAllocationFile(allocation.toString());
        frequency.setServiceStartTime(0);frequency.setServiceEndTime(1800);
        Scenario frequencyScenario=ScenarioUtils.createScenario(frequencyConfig);
        ScheduledAamTransitBuilder.build(frequencyScenario,frequency);
        int[] counts=frequencyScenario.getTransitSchedule().getTransitLines().values().stream()
            .flatMap(line->line.getRoutes().values().stream()).mapToInt(frequencyRoute->frequencyRoute.getDepartures().size()).sorted().toArray();
        check(java.util.Arrays.equals(counts,new int[]{1,5}),"separate frequency allocation respects corridor departure counts");
        check(frequencyScenario.getTransitVehicles().getVehicles().size()==6,"frequency comparison retains explicit one-aircraft-per-departure supply");
        System.out.println("Scheduled AAM regression checks passed: " + result);
    }

    private static void check(boolean condition, String label) {
        if (!condition) {
            throw new AssertionError("FAILED: " + label);
        }
        System.out.println("PASS: " + label);
    }
}
