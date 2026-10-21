package org.matsim.run.aam;

import java.util.*;
import javax.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.controler.events.BeforeMobsimEvent;
import org.matsim.core.controler.listener.BeforeMobsimListener;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.run.aam.scheduled.ScheduledAamConfigGroup;

/** Final hard feasibility gate, including AAM discovered through ordinary PT routing. */
public final class AamSelectedPlanValidator implements BeforeMobsimListener {
    private final Scenario scenario;
    private final javax.inject.Provider<org.matsim.core.router.TripRouter> routers;
    @Inject public AamSelectedPlanValidator(Scenario s,javax.inject.Provider<org.matsim.core.router.TripRouter> routers){scenario=s;this.routers=routers;}
    @Override public void notifyBeforeMobsim(BeforeMobsimEvent event){
        boolean scheduled=scenario.getConfig().getModules().get("scheduledAam") instanceof ScheduledAamConfigGroup;
        double distance,time;
        if(scheduled){ScheduledAamConfigGroup c=(ScheduledAamConfigGroup)scenario.getConfig().getModules().get("scheduledAam");distance=c.getMaximumWalkDistance();time=c.getMaximumWalkTime();}
        else{AamConfigGroup c=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class);distance=c.getMaximumWalkDistance();time=c.getMaximumWalkTime();}
        for(Person p:scenario.getPopulation().getPersons().values()){
            if(!scheduled)for(Plan plan:p.getPlans())if(Boolean.TRUE.equals(plan.getAttributes().getAttribute("aam_private_route_infeasible"))){
                if(p.getSelectedPlan()==plan){
                    Plan ground=p.getPlans().stream().filter(candidate->!AamFeederPolicy.hasAir(candidate)&&candidate!=plan)
                        .max(Comparator.comparingDouble(candidate->candidate.getScore()==null?Double.NEGATIVE_INFINITY:candidate.getScore())).orElse(null);
                    if(ground!=null)p.setSelectedPlan(ground);
                }
                AamMultimodalRoutingModule.PortSet active=(AamMultimodalRoutingModule.PortSet)scenario.getScenarioElement("aamActivePorts");
                if(active!=null)for(AamCandidateScreen.Candidate candidate:AamCandidateScreen.get(scenario).screen(plan,active.ports))
                    if(candidate.temporal)AamCandidateScreen.get(scenario).outcome(candidate,"private_return_chain",p);
                AamFeederPolicy.invalidateAam(plan);AamFeederPolicy.routeConvertedGroundTrips(scenario,plan,routers.get());
            }
            if(!scheduled)for(Plan plan:p.getPlans())if(!AamFeederPolicy.hasGenuineAam(plan)&&AamFeederPolicy.hasAamMarker(plan)){
                AamMultimodalRoutingModule.PortSet active=(AamMultimodalRoutingModule.PortSet)scenario.getScenarioElement("aamActivePorts");
                if(active!=null)AamCandidateScreen.get(scenario).screen(plan,active.ports);
                AamFeederPolicy.normalizeGround(plan);AamFeederPolicy.routeConvertedGroundTrips(scenario,plan,routers.get());
            }
            Plan selected=p.getSelectedPlan();if(selected==null||valid(selected,distance,time))continue;
            Plan ground=p.getPlans().stream().filter(plan->!AamFeederPolicy.hasAir(plan))
                .max(Comparator.comparingDouble(plan->plan.getScore()==null?Double.NEGATIVE_INFINITY:plan.getScore())).orElseThrow(()->new IllegalStateException("Prohibited AAM walking for "+p.getId()+" and no ground alternative"));
            p.setSelectedPlan(ground);
            org.apache.log4j.Logger.getLogger(getClass()).warn("Rejected infeasible AAM trip in selected plan; selected preserved ground alternative: person="+p.getId());
        }
    }
    public static boolean valid(Plan plan,double distance,double time){
        for(TripStructureUtils.Trip trip:TripStructureUtils.getTrips(plan)){
            List<PlanElement> elements=new ArrayList<>(trip.getTripElements());int first=-1,last=-1;
            for(int i=0;i<elements.size();i++)if(elements.get(i) instanceof Leg){
                Leg l=(Leg)elements.get(i);boolean air="aam_drt".equals(l.getMode());
                if(l.getRoute() instanceof org.matsim.pt.routes.TransitPassengerRoute){
                    org.matsim.api.core.v01.Id<?> line=((org.matsim.pt.routes.TransitPassengerRoute)l.getRoute()).getLineId();
                    air|=line!=null&&line.toString().startsWith("aam_sched_line_");
                }
                if(air){
                    if(l.getRoute()==null||!AamMissionProfile.isFeasible(l.getRoute().getDistance()))return false;
                    if(first<0)first=i;last=i;
                }
            }
            if(first>=0&&(!AamFeederPolicy.admissible(elements.subList(0,first),distance,time)
                    ||!AamFeederPolicy.admissible(elements.subList(last+1,elements.size()),distance,time)))return false;
        }return true;
    }
}
