package org.matsim.run.aam.scheduled;

import java.util.List;

import javax.inject.Inject;
import javax.inject.Provider;

import javax.inject.Named;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.router.RoutingModule;
import org.matsim.facilities.Facility;

/** Explicit traveler-facing mode whose aircraft leg is scheduled public transit. */
public final class ScheduledAamRoutingModule implements RoutingModule {
    public static final String MODE = "scheduled_aam";
    private static final Logger LOG = Logger.getLogger(ScheduledAamRoutingModule.class);

    private final ScheduledAamPlanStrategyModule planner;
    private final RoutingModule fallback;

    public ScheduledAamRoutingModule(Scenario scenario) {
        this.planner = new ScheduledAamPlanStrategyModule(scenario);
        this.fallback = null;
    }

    ScheduledAamRoutingModule(Scenario scenario, RoutingModule fallback,
            java.util.Map<String, RoutingModule> groundRouters) {
        this.planner = new ScheduledAamPlanStrategyModule(scenario, groundRouters);
        // An invalidated AAM request must still have a road-ground outside option.
        // Ordinary PT can be unavailable (including an empty ground schedule).
        // Paired private tours are handled transactionally by the startup listener.
        this.fallback = groundRouters.getOrDefault("ride", fallback);
    }

    ScheduledAamRoutingModule(Scenario scenario, RoutingModule fallback) {
        this(scenario, fallback, ScheduledAamPlanStrategyModule.routers(fallback, fallback, fallback, fallback, fallback));
    }

    @Override
    public List<? extends PlanElement> calcRoute(Facility fromFacility, Facility toFacility, double departureTime,
            Person person) {
        ScheduledAamPlanStrategyModule.Candidate candidate = planner.candidateFor(
                fromFacility, toFacility, departureTime, person);
        if (candidate == null) {
            if (fallback != null) {
                LOG.warn("No feasible direct scheduled-AAM route for person " + person.getId() + " at time "
                        + departureTime + "; falling back to passenger ground travel for this carried-over alternative");
                return fallback.calcRoute(fromFacility, toFacility, departureTime, person);
            }
            throw new IllegalArgumentException("No feasible scheduled AAM route for person " + person.getId()
                    + " at time " + departureTime);
        }
        return planner.createTrip(candidate);
    }

    public static final class Factory implements Provider<RoutingModule> {
        @Inject
        Scenario scenario;

        @Inject
        @Named(TransportMode.pt)
        Provider<RoutingModule> pt;
        @Inject @Named("car") Provider<RoutingModule> car;
        @Inject @Named("ride") Provider<RoutingModule> ride;
        @Inject @Named("ride_taxi") Provider<RoutingModule> taxi;
        @Inject @Named("walk") Provider<RoutingModule> walk;
        @Inject @Named("bike") Provider<RoutingModule> bike;

        @Override
        public RoutingModule get() {
            return new ScheduledAamRoutingModule(scenario, pt.get(),
                    ScheduledAamPlanStrategyModule.routers(scenario, car, ride, taxi, walk, bike));
        }
    }
}
