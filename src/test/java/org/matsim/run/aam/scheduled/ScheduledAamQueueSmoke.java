package org.matsim.run.aam.scheduled;

import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.*;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.*;

/** Seven-person QSim, not a regional run: capacity, timeout, closure, actual fares. */
public final class ScheduledAamQueueSmoke {
    public static void main(String[] args) throws Exception {
        Path root=Paths.get("run-output/aam-repair-validation/queue-"+System.currentTimeMillis()).toAbsolutePath();
        Files.createDirectories(root);
        Path ports=root.resolve("ports.csv");
        Files.writeString(ports,"id,name,x,y\nVP08,Origin,0,0\nVP09,Destination,5000,0\n");
        Config c=ConfigUtils.createConfig(new ScheduledAamConfigGroup());
        c.controler().setOutputDirectory(root.resolve("matsim").toString());
        c.controler().setLastIteration(0); c.controler().setCreateGraphs(false);
        c.qsim().setEndTime(2400); c.qsim().setNumberOfThreads(1);
        c.transit().setUseTransit(true);
        c.planCalcScore().addActivityParams(new ActivityParams("home").setTypicalDuration(3600));
        c.planCalcScore().addActivityParams(new ActivityParams("work").setTypicalDuration(3600));
        ScheduledAamConfigGroup a=ConfigUtils.addOrGetModule(c,ScheduledAamConfigGroup.class);
        a.setVertiportsFile(ports.toString()); a.setServiceStartTime(0);a.setServiceEndTime(1800);
        a.setHeadway(1800);a.setCruiseSpeed(50);a.setSeats(4);a.setMaximumPassengerWait(1800);
        Scenario s=ScenarioUtils.createScenario(c);ScheduledAamTransitBuilder.build(s,a);
        TransitLine line=s.getTransitSchedule().getTransitLines().get(Id.create("aam_sched_line_VP08_VP09",TransitLine.class));
        TransitRoute route=line.getRoutes().values().iterator().next();
        TransitStopFacility from=route.getStops().get(0).getStopFacility(),to=route.getStops().get(1).getStopFacility();
        for(int i=0;i<7;i++) {
            Person person=s.getPopulation().getFactory().createPerson(Id.createPersonId("queue_"+i));
            Plan p=s.getPopulation().getFactory().createPlan();
            Activity h=s.getPopulation().getFactory().createActivityFromLinkId("home",from.getLinkId());h.setEndTime(i==6?2200:20);
            Leg leg=s.getPopulation().getFactory().createLeg("pt");
            DefaultTransitPassengerRoute r=new DefaultTransitPassengerRoute(from,line,route,to);
            r.setDistance(5000);r.setTravelTime(1900);r.setBoardingTime(1800);leg.setRoute(r);leg.setTravelTime(1900);
            p.addActivity(h);p.addLeg(leg);p.addActivity(s.getPopulation().getFactory().createActivityFromLinkId("work",to.getLinkId()));
            person.addPlan(p);s.getPopulation().addPerson(person);
        }
        Controler controler=new Controler(s);
        ScheduledAamServiceState state=new ScheduledAamServiceState(s,controler.getEvents());
        s.addScenarioElement("scheduledAamServiceState",state);
        Map<String,Integer> counts=new HashMap<>();double[] fares={0};
        controler.addOverridingModule(new AbstractModule(){@Override public void install(){
            addEventHandlerBinding().toInstance(state);
            addEventHandlerBinding().toInstance((BasicEventHandler)e->{
                Map<String,String> x=e.getAttributes();
                if("scheduledAamRejected".equals(e.getEventType()))counts.merge(x.get("reason"),1,Integer::sum);
                if("personMoney".equals(e.getEventType())&&"scheduledAamFare".equals(x.get("purpose"))){counts.merge("fares",1,Integer::sum);fares[0]+=Double.parseDouble(x.get("amount"));}
            });
        }});
        controler.addOverridingQSimModule(new org.matsim.core.mobsim.qsim.AbstractQSimModule(){@Override protected void configureQSim(){
            bind(org.matsim.core.mobsim.qsim.pt.TransitQSimEngine.class).to(ScheduledAamTransitEngine.class).in(javax.inject.Singleton.class);
        }});
        controler.run();
        if(counts.getOrDefault("fares",0)!=4)throw new AssertionError("Exactly four boarding fares: "+counts);
        if(counts.getOrDefault("maximum_wait_exceeded",0)!=2)throw new AssertionError("Two capacity timeout failures: "+counts);
        if(counts.getOrDefault("service_closed",0)!=1)throw new AssertionError("One missed final service: "+counts);
        if(Math.abs(fares[0]+4*(30+2*5000/1609.344))>1e-6)throw new AssertionError("Wrong charged fares: "+fares[0]);
        Files.writeString(root.resolve("verified.txt"),counts+"\ncharged="+fares[0]+"\n");
        System.out.println("PASS: saturated VP08 -> VP09 QSim and fare events: "+root);
    }
}
