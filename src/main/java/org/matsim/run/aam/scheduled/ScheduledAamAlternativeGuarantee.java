package org.matsim.run.aam.scheduled;

import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

import javax.inject.Inject;
import javax.inject.Named;
import javax.inject.Provider;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.listener.StartupListener;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.RoutingModule;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.router.TripStructureUtils.Trip;
import org.matsim.core.router.PlanRouter;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.Id;
import org.matsim.contrib.drt.run.DrtConfigGroup;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleUtils;

/** Seeds one separate scheduled-AAM choice for each eligible nearby traveler. */
public final class ScheduledAamAlternativeGuarantee implements StartupListener {
    private static final Logger LOG = Logger.getLogger(ScheduledAamAlternativeGuarantee.class);

    private final Scenario scenario;
    private final Map<String, RoutingModule> groundRouters;
    private final Provider<TripRouter> tripRouters;

    @Inject
    public ScheduledAamAlternativeGuarantee(Scenario scenario,
            @Named("car") Provider<RoutingModule> car, @Named("ride") Provider<RoutingModule> ride,
            @Named("ride_taxi") Provider<RoutingModule> taxi, @Named("walk") Provider<RoutingModule> walk,
            @Named("bike") Provider<RoutingModule> bike, Provider<TripRouter> tripRouters) {
        this.scenario = scenario;
        this.groundRouters = ScheduledAamPlanStrategyModule.routers(
                scenario, car, ride, taxi, walk, bike);
        this.tripRouters = tripRouters;
    }

    ScheduledAamAlternativeGuarantee(Scenario scenario) {
        this.scenario = scenario;
        this.groundRouters = null;
        this.tripRouters = null;
    }

    @Override
    public void notifyStartup(StartupEvent event) {
        ScheduledAamConfigGroup config = org.matsim.core.config.ConfigUtils.addOrGetModule(
                scenario.getConfig(), ScheduledAamConfigGroup.class);
        List<Plan> added = config.getSeedAlternativesAtStartup() ? seedAlternatives() : List.of();
        int rerouted = 0;
        if (tripRouters != null) {
            boolean hadLegacyDrt = scenario.getConfig().getModules().containsKey(DrtConfigGroup.GROUP_NAME);
            TripRouter tripRouter = tripRouters.get();
            ScheduledAamPlanStrategyModule.removeRouterAddedLegacyDrt(scenario.getConfig(), hadLegacyDrt);
            org.matsim.run.aam.AamFeederPolicy.ensureGroundAlternatives(scenario,tripRouter);
            rerouted = rerouteStagedAlternatives(tripRouter);
        }
        LOG.info("Guaranteed a separate scheduled-AAM alternative for " + added.size()
                + " eligible travelers near an active vertiport and rerouted " + rerouted
                + " staged or layout-invalidated AAM plans.");
        if (!config.getSeedAlternativesAtStartup()) {
            LOG.info("Scheduled-AAM startup alternative generation disabled for route preparation.");
        }
        try {
            java.nio.file.Path diagnostics = java.nio.file.Paths.get(
                    scenario.getConfig().controler().getOutputDirectory(),
                    "aam-choice-set", "layout", "ground-routing.csv");
            java.nio.file.Files.createDirectories(diagnostics.getParent());
            org.matsim.run.aam.AamGroundRoutingDiagnostics.get(scenario).write(diagnostics);
        } catch (java.io.IOException e) {
            throw new java.io.UncheckedIOException(e);
        }
    }

    List<Plan> seedAlternatives() {
        List<Plan> added = new ArrayList<>();
        ensureVehicleIds();
        ScheduledAamPlanStrategyModule planner = groundRouters == null
                ? new ScheduledAamPlanStrategyModule(scenario)
                : new ScheduledAamPlanStrategyModule(scenario, groundRouters);
        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (!"person".equals(person.getAttributes().getAttribute("subpopulation")) || hasScheduledAam(person)) {
                continue;
            }
            Plan source = person.getSelectedPlan();
            if (source == null) {
                continue;
            }
            Plan candidate = scenario.getPopulation().getFactory().createPlan();
            PopulationUtils.copyFromTo(source, candidate);
            candidate.setScore(null);
            // The guaranteed comparison is a passenger-based counterfactual:
            // the person's private car/bike remains at home for the whole day.
            // This lets complex tours receive one feasible AAM alternative
            // without teleporting a private vehicle between activities.
            replacePrivateVehicleLegsWithRide(candidate);
            person.addPlan(candidate);
            if (planner.addAlternative(candidate)) {
                added.add(candidate);
            } else {
                person.removePlan(candidate);
            }
        }
        return added;
    }

    static void replacePrivateVehicleLegsWithRide(Plan plan) {
        for (Trip trip : TripStructureUtils.getTrips(plan)) {
            boolean converted = false;
            for (PlanElement element : trip.getTripElements()) {
                if (element instanceof Leg) {
                    Leg leg = (Leg) element;
                    if ("car".equals(leg.getMode()) || "bike".equals(leg.getMode())) {
                        leg.setMode("ride");
                        leg.setRoute(null);
                        converted = true;
                    }
                }
            }
            if (converted) {
                for (PlanElement element : trip.getTripElements()) {
                    if (element instanceof Leg) {
                        TripStructureUtils.setRoutingMode((Leg) element, "ride");
                    }
                }
            }
        }
    }

    static boolean hasScheduledAam(Person person) {
        return person.getPlans().stream().anyMatch(ScheduledAamPlanStrategyModule::containsScheduledAam);
    }

    private int rerouteStagedAlternatives(TripRouter router) {
        int routedPlans = 0;
        for (Person person : scenario.getPopulation().getPersons().values()) {
            for (Plan plan : person.getPlans()) {
                org.matsim.run.aam.AamFeederPolicy.routeConvertedGroundTrips(scenario,plan,router);
                if (!needsScheduledAamRouting(plan)) {
                    continue;
                }
                Plan selected = person.getSelectedPlan();
                if (selected != plan) {
                    person.setSelectedPlan(plan);
                }
                try {
                    plan.setScore(null);
                    for (Trip trip : new ArrayList<>(TripStructureUtils.getTrips(plan))) {
                        if (!isUnroutedScheduledAamTrip(trip)) {
                            continue;
                        }
                        List<? extends PlanElement> route = router.calcRoute(ScheduledAamRoutingModule.MODE,
                                FacilitiesUtils.toFacility(trip.getOriginActivity(), scenario.getActivityFacilities()),
                                FacilitiesUtils.toFacility(trip.getDestinationActivity(), scenario.getActivityFacilities()),
                                PlanRouter.calcEndOfActivity(trip.getOriginActivity(), plan, scenario.getConfig()), person);
                        if (plan.getAttributes().getAttribute(ScheduledAamPlanStrategyModule.PARK_MODE) != null
                                && route.stream().filter(e -> e instanceof Leg).map(e -> (Leg)e)
                                    .noneMatch(l -> l.getRoute() instanceof org.matsim.pt.routes.TransitPassengerRoute
                                        && l.getRoute().getRouteDescription().contains("aam_sched_line_"))) {
                            // A partial ground fallback could strand the private vehicle.
                            // Replace the entire daily alternative, never just one tour leg.
                            Plan ground = person.getPlans().stream().filter(p -> p != plan
                                && !org.matsim.run.aam.AamFeederPolicy.hasAir(p)).findFirst()
                                .orElseThrow(() -> new IllegalStateException("No whole-day ground fallback for paired tour " + person.getId()));
                            PopulationUtils.copyFromTo(ground, plan);
                            plan.setScore(null);
                            LOG.warn("Invalidated paired AAM tour for " + person.getId() + "; restored whole-day ground alternative");
                            break;
                        }
                        TripRouter.insertTrip(plan, trip.getOriginActivity(), route, trip.getDestinationActivity());
                    }
                    routedPlans++;
                } finally {
                    if (selected != plan) {
                        person.setSelectedPlan(selected);
                    }
                }
            }
        }
        return routedPlans;
    }

    static boolean needsScheduledAamRouting(Plan plan) {
        return TripStructureUtils.getTrips(plan).stream().anyMatch(ScheduledAamAlternativeGuarantee::isUnroutedScheduledAamTrip);
    }

    private static boolean isUnroutedScheduledAamTrip(Trip trip) {
        for (Leg leg : trip.getLegsOnly()) {
            if ((ScheduledAamRoutingModule.MODE.equals(leg.getMode())
                    || ScheduledAamRoutingModule.MODE.equals(TripStructureUtils.getRoutingMode(leg)))
                    && leg.getRoute() == null) {
                return true;
            }
        }
        return false;
    }

    private void ensureVehicleIds() {
        org.matsim.run.aam.AamFeederPolicy.initializeVehicles(scenario);
    }
}
