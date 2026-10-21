package org.matsim.run.aam.scheduled;

import java.nio.file.*;
import java.util.*;
import javax.inject.*;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.controler.events.BeforeMobsimEvent;
import org.matsim.core.controler.listener.BeforeMobsimListener;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.*;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.run.aam.AamFeederPolicy;

/** Rebook selected AAM journeys against actual seats, even with innovation off.
 * This is a deterministic-seed day-ahead estimate, not a seat guarantee in QSim.
 * Late arrival and unexpected boarding delays still use the hard runtime policy. */
public final class ScheduledAamQueueReplanner implements BeforeMobsimListener {
    private final Scenario s;private final ScheduledAamPlanStrategyModule planner;
    @Inject public ScheduledAamQueueReplanner(Scenario s,@Named("car") Provider<RoutingModule> car,
            @Named("ride") Provider<RoutingModule> ride,@Named("ride_taxi") Provider<RoutingModule> taxi,
            @Named("walk") Provider<RoutingModule> walk,@Named("bike") Provider<RoutingModule> bike){
        this.s=s;planner=new ScheduledAamPlanStrategyModule(s,ScheduledAamPlanStrategyModule.routers(s,car,ride,taxi,walk,bike));
    }
    @Override public void notifyBeforeMobsim(BeforeMobsimEvent event){
        ScheduledAamServiceState state=ScheduledAamServiceState.get(s);state.beginReservations();
        // Exact pre-modification plans/scores are retained, not attached to new routes.
        Path archive=Paths.get(s.getConfig().controler().getOutputDirectory(),"queue-plan-provenance","before-"+event.getIteration()+".xml.gz");
        try{Files.createDirectories(archive.getParent());if(Files.exists(archive))throw new IllegalStateException("Refusing to overwrite "+archive);
            new PopulationWriter(s.getPopulation()).write(archive.toString());
        }catch(java.io.IOException e){throw new java.io.UncheckedIOException(e);}
        List<Person> people=new ArrayList<>(s.getPopulation().getPersons().values());
        Collections.shuffle(people,new Random(s.getConfig().global().getRandomSeed()+event.getIteration()));
        try{for(Person person:people){
            Plan old=person.getSelectedPlan();if(old==null||!AamFeederPolicy.hasAir(old))continue;
            Plan candidate=s.getPopulation().getFactory().createPlan();PopulationUtils.copyFromTo(old,candidate);
            person.addPlan(candidate);person.setSelectedPlan(candidate);candidate.setScore(null);boolean feasible=true;
            for(TripStructureUtils.Trip trip:new ArrayList<>(TripStructureUtils.getTrips(candidate))){
                if(!trip.getLegsOnly().stream().anyMatch(l->l.getRoute() instanceof org.matsim.pt.routes.TransitPassengerRoute
                        && ((org.matsim.pt.routes.TransitPassengerRoute)l.getRoute()).getLineId()!=null
                        && ((org.matsim.pt.routes.TransitPassengerRoute)l.getRoute()).getLineId().toString().startsWith("aam_sched_line_")))continue;
                ScheduledAamPlanStrategyModule.Candidate choice=planner.candidateFor(
                    FacilitiesUtils.toFacility(trip.getOriginActivity(),s.getActivityFacilities()),
                    FacilitiesUtils.toFacility(trip.getDestinationActivity(),s.getActivityFacilities()),
                    PlanRouter.calcEndOfActivity(trip.getOriginActivity(),candidate,s.getConfig()),person);
                if(choice==null){feasible=false;break;}
                TripRouter.insertTrip(candidate,trip.getOriginActivity(),planner.createTrip(choice),trip.getDestinationActivity());
            }
            if(feasible){person.removePlan(old);state.reserve(candidate);}
            else{person.removePlan(candidate);Plan ground=person.getPlans().stream().filter(p->!AamFeederPolicy.hasAir(p))
                    .max(Comparator.comparingDouble(p->p.getScore()==null?Double.NEGATIVE_INFINITY:p.getScore()))
                    .orElseThrow(()->new IllegalStateException("No feasible ground alternative for full/closed scheduled service: "+person.getId()));
                person.setSelectedPlan(ground);
                org.apache.log4j.Logger.getLogger(getClass()).info("Full/closed/unreachable scheduled service: selected ground plan for "+person.getId());}
        }}finally{state.endReservations();}
    }
}
