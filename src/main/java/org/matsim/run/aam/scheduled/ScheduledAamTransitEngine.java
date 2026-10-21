package org.matsim.run.aam.scheduled;

import java.util.*;
import javax.inject.Inject;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.mobsim.qsim.pt.*;
import org.matsim.pt.UmlaufBuilder;

/** Hard wait limit. Failure uses MATSim stuck scoring, never a fabricated arrival.
 * Ground alternatives remain available for subsequent plan selection. */
public final class ScheduledAamTransitEngine extends TransitQSimEngine {
    private final QSim sim;
    private final ScheduledAamConfigGroup config;
    private final Map<Id<Person>,Double> arrivals=new HashMap<>();
    @Inject public ScheduledAamTransitEngine(QSim sim, TransitStopHandlerFactory stops, UmlaufBuilder builder) {
        super(sim,stops,builder); this.sim=sim;
        config=ConfigUtils.addOrGetModule(sim.getScenario().getConfig(),ScheduledAamConfigGroup.class);
    }
    @Override public void doSimStep(double time) {
        Set<Id<Person>> waiting=new HashSet<>();
        getAgentTracker().getAgentsAtStop().forEach((stop,agents)->{
            if(!stop.toString().startsWith("aam_sched_stop_"))return;
            for(PTPassengerAgent passenger:new ArrayList<>(agents)) {
                MobsimAgent agent=(MobsimAgent)passenger;
                waiting.add(agent.getId());
                double arrival=arrivals.computeIfAbsent(agent.getId(),p->time);
                String reason=time>config.getServiceEndTime()+config.getDwellTime()?"service_closed":
                    time-arrival>config.getMaximumPassengerWait()?"maximum_wait_exceeded":null;
                if(reason==null)continue;
                getAgentTracker().removeAgentFromStop(passenger,stop);
                getInternalInterface().unregisterAdditionalAgentOnLink(agent.getId(),agent.getCurrentLinkId());
                sim.getEventsManager().processEvent(new FailureEvent(time,agent.getId().toString(),reason,time-arrival));
                agent.setStateToAbort(time);
                getInternalInterface().arrangeNextAgentState(agent);
            }
        });
        arrivals.keySet().retainAll(waiting);
    }
    private static final class FailureEvent extends Event {
        private final String person,reason; private final double wait;
        FailureEvent(double t,String p,String r,double w){super(t);person=p;reason=r;wait=w;}
        @Override public String getEventType(){return "scheduledAamRejected";}
        @Override public Map<String,String> getAttributes(){Map<String,String> a=super.getAttributes();a.put("person",person);a.put("reason",reason);a.put("passengerWait",Double.toString(wait));return a;}
    }
}
