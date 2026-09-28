package org.matsim.run.aam;

import java.nio.file.*;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.contrib.drt.routing.*;
import org.matsim.contrib.drt.run.*;
import org.matsim.contrib.dvrp.run.*;
import org.matsim.core.config.*;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.*;
import org.matsim.core.controler.Controler;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.*;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.facilities.*;
import static org.matsim.run.aam.RunDynamicAamLosAngelesScenario.*;

/** Executable checks without JUnit; fails with nonzero exit on any broken invariant. */
public final class AamRegressionChecks {
    private static int checks=0;
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);checks++;System.out.println("PASS: "+message);}
    static ActivityFacility fac(Scenario s,String id,double x){
        ActivityFacility f=s.getActivityFacilities().getFactory().createActivityFacility(Id.create(id,ActivityFacility.class),new Coord(x,0));
        ((ActivityFacilityImpl)f).setLinkId(Id.createLinkId(id));return f;
    }
    public static void main(String[] args)throws Exception{
        MultiModeDrtConfigGroup inputDrt=new MultiModeDrtConfigGroup();DvrpConfigGroup inputDv=new DvrpConfigGroup();
        Config input=org.matsim.run.RunLosAngelesScenario.prepareConfig(new String[]{"scenarios/aam/la-aam-fare30-it2.config.xml"},new AamConfigGroup(),inputDrt,inputDv);
        configure(input,inputDrt,inputDv,"unused-config-check");
        check(inputDv.getTravelTimeMatrixParams().getCellSize()==500,"shipped air-only routing matrix uses 500 m cells");
        check(input.global().getNumberOfThreads()==8 && input.qsim().getNumberOfThreads()==8,"AAM preserves baseline LA routing and QSim thread counts");
        check(input.controler().getRoutingAlgorithmType()==org.matsim.core.config.groups.ControlerConfigGroup.RoutingAlgorithmType.FastAStarLandmarks,"AAM preserves baseline LA A-star road routing");
        check(input.planCalcScore().getModes().containsKey(AAM) && input.planCalcScore().getModes().containsKey(AIR),"shipped LA XML registers AAM scoring");
        check(input.strategy().getStrategySettings().stream().filter(st->st.getStrategyName().equals("AamInnovation")).count()==1,"shipped XML registers AAM strategy exactly once");
        check(!ConfigUtils.addOrGetModule(input,AamConfigGroup.class).modes().contains("ground_drt"),"no unavailable ground DRT option in AAM config");
        check(Arrays.asList(input.subtourModeChoice().getModes()).contains("ride"),"base LA ride choice retained");
        AamConfigGroup cfg=new AamConfigGroup();MultiModeDrtConfigGroup multi=new MultiModeDrtConfigGroup();DvrpConfigGroup dv=new DvrpConfigGroup();
        Config c=ConfigUtils.createConfig(cfg,multi,dv);c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(3);c.qsim().setNumberOfThreads(2);
        cfg.setBaseFare(37);cfg.setFarePerMile(3);cfg.setMaxWaitTime(800);
        configure(c,multi,dv,"unused-test-output");
        check(c.global().getNumberOfThreads()==3 && c.qsim().getNumberOfThreads()==2,"custom scenario thread counts remain unchanged");
        check(c.controler().getLastIteration()==0,"configured iteration count preserved");
        check(multi.getModalElements().size()==1 && multi.getModalElements().stream().allMatch(d->AIR.equals(d.getMode())),"only aircraft fleet registered");
        DrtConfigGroup air=multi.getModalElements().stream().filter(d->d.getMode().equals(AIR)).findFirst().get();
        check(air.getMaxWaitTime()==800,"AAM max wait reaches DRT dispatcher");
        check(dv.getTravelTimeMatrixParams().getCellSize()==5000,"explicit matrix cell size is preserved");
        check(dv.getNetworkModes().equals(Set.of(AIR)),"DVRP matrix excludes the regional road network");
        check(air.getMaxTravelTimeBeta()==1800,"flight insertion allowance matches ten-vertiport dispatch test");
        check(multi.getModalElements().stream().allMatch(d->d.isUseModeFilteredSubnetwork()),"air uses a filtered network");
        org.matsim.contrib.drt.fare.DrtFareParams fare=air.getDrtFareParams().get();
        check(fare.getBasefare()==37 && Math.abs(fare.getDistanceFare_m()-3/MILE)<1e-12,"XML fares reach aircraft fare handler");
        Path roundtrip=Files.createTempFile("aam-config-check-",".xml");new ConfigWriter(c).write(roundtrip.toString());
        Config loaded=ConfigUtils.loadConfig(roundtrip.toString(),new AamConfigGroup(),new MultiModeDrtConfigGroup(),new DvrpConfigGroup());
        check(ConfigUtils.addOrGetModule(loaded,AamConfigGroup.class).getBaseFare()==37,"AAM config XML round-trip");
        boolean denied=false;try{cfg.setAccessEgressModes("pt");}catch(IllegalArgumentException e){denied=true;}check(denied,"transit access rejected");
        boolean groundRejected=false;try{cfg.setAccessEgressModes("ground_drt");}catch(IllegalArgumentException e){groundRejected=true;}
        check(groundRejected,"unserved ground DRT cannot be selected");
        cfg.setAccessEgressModes("car,ride,ride_taxi,walk,bike");cfg.setCandidateVertiports(10);
        for(String m:cfg.modes())c.planCalcScore().addModeParams(new ModeParams(m).setConstant(0).setMarginalUtilityOfTraveling(-6).setMonetaryDistanceRate(0));
        Scenario s=ScenarioUtils.createScenario(c);PopulationFactory pf=s.getPopulation().getFactory();
        Person p=pf.createPerson(Id.createPersonId("test"));Plan plan=pf.createPlan();plan.addActivity(pf.createActivityFromCoord("home",new Coord(0,0)));p.addPlan(plan);p.setSelectedPlan(plan);
        List<AamMultimodalRoutingModule.Vertiport> ports=List.of(
            new AamMultimodalRoutingModule.Vertiport("A",new Coord(0,0),Id.createLinkId("airA"),Id.createLinkId("roadA")),
            new AamMultimodalRoutingModule.Vertiport("B",new Coord(20000,0),Id.createLinkId("airB"),Id.createLinkId("roadB")));
        Map<String,RoutingModule> routers=new HashMap<>();
        for(String mode:cfg.modes())routers.put(mode,(from,to,time,person)->{
            boolean access=from.getLinkId().toString().equals("origin");
            double tt=mode.equals(access?"ride_taxi":"walk")?60:6000;
            Leg l=pf.createLeg(mode);Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());r.setDistance(100);r.setTravelTime(tt);
            l.setRoute(r);l.setTravelTime(tt);l.setDepartureTime(time);return List.of(l);
        });
        AamMultimodalRoutingModule router=new AamMultimodalRoutingModule(s,ports,routers);
        List<? extends PlanElement> route=router.calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);
        check(((Leg)route.get(0)).getMode().equals("ride_taxi"),"lowest-cost access mode selected");
        check(((Leg)route.get(route.size()-1)).getMode().equals("walk"),"lowest-cost egress mode selected independently");
        routers.put("ride",(from,to,time,person)->{
            Leg l=pf.createLeg("ride");Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());
            r.setDistance(100);r.setTravelTime(1);l.setRoute(r);l.setTravelTime(1);l.setDepartureTime(time);return List.of(l);
        });
        route=new AamMultimodalRoutingModule(s,ports,routers).calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);
        check(((Leg)route.get(0)).getMode().equals("ride"),"baseline ride is usable for vertiport access without DRT vehicles");
        routers.put("ride",(from,to,time,person)->{
            Leg l=pf.createLeg("ride");Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());
            r.setDistance(100);r.setTravelTime(6000);l.setRoute(r);l.setTravelTime(6000);l.setDepartureTime(time);return List.of(l);
        });
        Leg flight=route.stream().filter(e->e instanceof Leg && ((Leg)e).getMode().equals(AIR)).map(e->(Leg)e).findFirst().get();
        check(!flight.getRoute().getStartLinkId().equals(flight.getRoute().getEndLinkId()),"same-vertiport flights excluded");
        check(new AamMainModeIdentifier().identifyMainMode(route).equals(AAM),"whole chain identified as AAM");
        check(new org.matsim.run.LosAngelesIntermodalPtDrtRouterAnalysisModeIdentifier().identifyMainMode(route).equals(AAM),"LA analysis binding counts intermodal chain as AAM");
        check(route.stream().filter(e->e instanceof Leg).allMatch(e->AAM.equals(TripStructureUtils.getRoutingMode((Leg)e))),"all legs preserve AAM routing mode");
        plan.getAttributes().putAttribute("aam_park_mode","car");
        route=router.calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);
        check(((Leg)route.get(0)).getMode().equals("car"),"private car access retained for paired parking tour");
        route=router.calcRoute(fac(s,"origin",20000),fac(s,"destination",0),0,p);
        check(((Leg)route.get(route.size()-1)).getMode().equals("car"),"return egress retrieves parked car");
        plan.getAttributes().putAttribute("aam_park_mode","bike");
        route=router.calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);
        check(((Leg)route.get(0)).getMode().equals("bike"),"private bike access supported");
        plan.getAttributes().removeAttribute("aam_park_mode");
        List<AamMultimodalRoutingModule.Vertiport> expanded=new ArrayList<>(ports);
        expanded.add(new AamMultimodalRoutingModule.Vertiport("C",new Coord(1000,0),Id.createLinkId("airC"),Id.createLinkId("roadC")));
        cfg.setAccessEgressModes("walk");
        routers.put("walk",(from,to,time,person)->{
            double tt=to.getLinkId().toString().equals("roadA")?10000:60;
            Leg l=pf.createLeg("walk");Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());r.setDistance(100);r.setTravelTime(tt);l.setRoute(r);l.setTravelTime(tt);l.setDepartureTime(time);return List.of(l);
        });
        route=new AamMultimodalRoutingModule(s,expanded,routers).calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);
        flight=route.stream().filter(e->e instanceof Leg && ((Leg)e).getMode().equals(AIR)).map(e->(Leg)e).findFirst().get();
        check(flight.getRoute().getStartLinkId().toString().equals("airC"),"joint route search can choose a non-nearest vertiport");
        dynamicSmoke();
        System.out.println("ALL "+checks+" CHECKS PASSED");
    }
    static void dynamicSmoke()throws Exception{
        MultiModeDrtConfigGroup multi=new MultiModeDrtConfigGroup();DvrpConfigGroup dv=new DvrpConfigGroup();
        Config c=ConfigUtils.createConfig(multi,dv);c.controler().setLastIteration(0);c.qsim().setEndTime(12000);
        c.qsim().setSimStarttimeInterpretation(org.matsim.core.config.groups.QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
        c.qsim().setSimEndtimeInterpretation(org.matsim.core.config.groups.QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        Path root=Files.createTempDirectory("aam-dynamic-check-");c.controler().setOutputDirectory(root.resolve("output").toString());
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);
        c.planCalcScore().addActivityParams(new ActivityParams("home").setTypicalDuration(3600));
        c.planCalcScore().addActivityParams(new ActivityParams("work").setTypicalDuration(3600));
        c.planCalcScore().addModeParams(new ModeParams(AIR).setMarginalUtilityOfTraveling(-6));
        DrtConfigGroup d=new DrtConfigGroup();d.setMode(AIR);d.setUseModeFilteredSubnetwork(true);d.setMaxWaitTime(900);d.setStopDuration(120);d.setMaxTravelTimeAlpha(1.2);d.setMaxTravelTimeBeta(1800);
        d.setNumberOfThreads(1);d.addParameterSet(new org.matsim.contrib.drt.optimizer.insertion.SelectiveInsertionSearchParams());
        Path fleet=root.resolve("fleet.xml");
        StringBuilder fleetXml=new StringBuilder("<?xml version=\"1.0\"?><!DOCTYPE vehicles SYSTEM \"http://matsim.org/files/dtd/dvrp_vehicles_v1.dtd\"><vehicles>");
        for(int i=0;i<100;i++)fleetXml.append("<vehicle id=\"aam_drt_").append(String.format("%04d",i)).append("\" start_link=\"aam_loop_VP").append(String.format("%02d",i%10+1)).append("\" t_0=\"0\" t_1=\"129600\" capacity=\"4\"/>");
        Files.writeString(fleet,fleetXml.append("</vehicles>").toString());
        d.setVehiclesFile(fleet.toString());multi.addParameterSet(d);dv.setNetworkModes(com.google.common.collect.ImmutableSet.of(AIR));
        dv.getTravelTimeMatrixParams().setCellSize(500);
        DrtConfigs.adjustMultiModeDrtConfig(multi,c.planCalcScore(),c.plansCalcRoute());
        Scenario s=DrtControlerCreator.createScenarioWithDrtRouteFactory(c);Network n=s.getNetwork();NetworkFactory nf=n.getFactory();
        Node[] airNodes=new Node[10];
        for(int i=0;i<10;i++){
            String port=String.format("VP%02d",i+1);
            Coord position=new Coord(COORDS[i][0],COORDS[i][1]);
            airNodes[i]=nf.createNode(Id.createNodeId("aam_node_"+port),position);n.addNode(airNodes[i]);
            Link loop=nf.createLink(Id.createLinkId("aam_loop_"+port),airNodes[i],airNodes[i]);
            loop.setLength(1);loop.setFreespeed(AIR_SPEED);loop.setCapacity(10000);loop.setNumberOfLanes(1);loop.setAllowedModes(Set.of(AIR));n.addLink(loop);
        }
        for(int i=0;i<10;i++)for(int j=0;j<10;j++)if(i!=j){
            Link flight=nf.createLink(Id.createLinkId("aam_air_"+String.format("VP%02d",i+1)+"_"+String.format("VP%02d",j+1)),airNodes[i],airNodes[j]);
            flight.setLength(AamMultimodalRoutingModule.distance(airNodes[i].getCoord(),airNodes[j].getCoord()));
            flight.setFreespeed(AIR_SPEED);flight.setCapacity(10000);flight.setNumberOfLanes(1);flight.setAllowedModes(Set.of(AIR));n.addLink(flight);
        }
        Node roadA=nf.createNode(Id.createNodeId("roadA"),new Coord(COORDS[7][0],COORDS[7][1]+500));
        Node roadB=nf.createNode(Id.createNodeId("roadB"),new Coord(COORDS[0][0],COORDS[0][1]+500));
        n.addNode(roadA);n.addNode(roadB);
        Link roadLink=nf.createLink(Id.createLinkId("road"),roadA,roadB);
        roadLink.setLength(10000);roadLink.setFreespeed(15);roadLink.setCapacity(10000);roadLink.setNumberOfLanes(1);roadLink.setAllowedModes(Set.of("car"));n.addLink(roadLink);
        for(int i=0;i<2;i++){PopulationFactory pf=s.getPopulation().getFactory();Person p=pf.createPerson(Id.createPersonId("p"+i));Plan plan=pf.createPlan();
            Activity home=pf.createActivityFromLinkId("home",Id.createLinkId("aam_loop_VP08"));home.setEndTime(100);plan.addActivity(home);plan.addLeg(pf.createLeg(AIR));plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId("aam_loop_VP01")));p.addPlan(plan);s.getPopulation().addPerson(p);}
        Controler ctrl=new Controler(s);ctrl.addOverridingModule(new DvrpModule());ctrl.addOverridingModule(new AamMultiModeDrtModule());
        ctrl.configureQSimComponents(DvrpQSimComponents.activateAllModes(multi));
        final int[] pickups={0},dropoffs={0},rejections={0};
        final double[] pickupTime={Double.NaN},dropoffTime={Double.NaN};
        ctrl.getEvents().addHandler((org.matsim.core.events.handler.BasicEventHandler)e->{
            if(e.getEventType().equals("passenger picked up")){pickups[0]++;pickupTime[0]=e.getTime();}
            if(e.getEventType().equals("passenger dropped off")){dropoffs[0]++;dropoffTime[0]=e.getTime();}
            if(e.getEventType().equals("PassengerRequest rejected"))rejections[0]++;
        });
        ctrl.run();check(pickups[0]==2 && dropoffs[0]==2 && rejections[0]==0,"ten-port mixed-network requests picked up and dropped off, without rejection");
        check(pickupTime[0]-100<=900 && dropoffTime[0]-pickupTime[0]<2300,"observed aircraft wait and flight time remain within expected range");
        check(ctrl.getInjector().getInstance(com.google.inject.Key.get(Network.class,com.google.inject.name.Names.named("dvrp_routing"))).getLinks().size()==100,"DVRP routing network contains only 10 loops and 90 flight links");
        check(ctrl.getInjector().getInstance(org.matsim.contrib.dvrp.run.DvrpModes.key(Network.class,AIR)).getLinks().containsKey(Id.createLinkId("aam_air_VP08_VP01")),"modal aircraft network retains flight corridor");
    }
}
