package org.matsim.run.aam.scheduled;

import java.util.List;

import javax.inject.Inject;
import javax.inject.Provider;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.router.RoutingModule;
import org.matsim.facilities.Facility;

/** Explicit traveler-facing mode whose aircraft leg is scheduled public transit. */
public final class ScheduledAamRoutingModule implements RoutingModule {
    public static final String MODE = "scheduled_aam";

    private final ScheduledAamPlanStrategyModule planner;

    public ScheduledAamRoutingModule(Scenario scenario) {
        this.planner = new ScheduledAamPlanStrategyModule(scenario);
    }

    @Override
    public List<? extends PlanElement> calcRoute(Facility fromFacility, Facility toFacility, double departureTime,
            Person person) {
        ScheduledAamPlanStrategyModule.Candidate candidate = planner.candidateFor(
                fromFacility.getCoord(), toFacility.getCoord(), departureTime);
        if (candidate == null) {
            throw new IllegalArgumentException("No feasible scheduled AAM route for person " + person.getId()
                    + " at time " + departureTime);
        }
        return planner.createTrip(candidate, fromFacility.getLinkId(), toFacility.getLinkId());
    }

    public static final class Factory implements Provider<RoutingModule> {
        @Inject
        Scenario scenario;

        @Override
        public RoutingModule get() {
            return new ScheduledAamRoutingModule(scenario);
        }
    }
}
