package org.matsim.run.aam;

import javax.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.replanning.selectors.*;

/** Physical-air protection takes precedence over a stale or misleading plan type. */
public final class AamPlanRemovalSelector implements PlanSelector<Plan,Person> {
    private final int protectedCount;
    @Inject public AamPlanRemovalSelector(Scenario scenario){
        protectedCount=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class).getProtectedAlternatives();
    }
    public Plan selectPlan(HasPlansAndId<Plan,Person> person){
        long genuine=person.getPlans().stream().filter(AamFeederPolicy::hasGenuineAam).count();
        Plan proposed=new WorstPlanForRemovalSelector().selectPlan(person);
        if(proposed==null||!AamFeederPolicy.hasGenuineAam(proposed)||genuine>protectedCount)return proposed;
        // A marker-only plan must not cause the last genuine choice to be evicted.
        return person.getPlans().stream().filter(plan->!AamFeederPolicy.hasGenuineAam(plan)&&AamFeederPolicy.hasAamMarker(plan))
            .min(java.util.Comparator.comparingDouble(plan->plan.getScore()==null?Double.NEGATIVE_INFINITY:plan.getScore())).orElse(null);
    }
}
