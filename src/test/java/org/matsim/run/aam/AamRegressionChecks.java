package org.matsim.run.aam;

import java.nio.file.*;
import java.util.*;
import javax.inject.Provider;
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
import org.matsim.vehicles.VehicleUtils;
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
        org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings aamStrategy=input.strategy().getStrategySettings().stream().filter(st->st.getStrategyName().equals("AamInnovation")).findFirst().get();
        check(aamStrategy.getDisableAfter()==-1 && Math.abs(input.strategy().getFractionOfIterationsToDisableInnovation()-0.78)<1e-12,"AAM innovation continues through the configured innovation phase and stops after iteration 39");
        AamConfigGroup shipped=ConfigUtils.addOrGetModule(input,AamConfigGroup.class);
        check(input.qsim().getEndTime().seconds()==129600&&shipped.getServiceStartTime()==25200&&shipped.getServiceEndTime()==68400,"exploration keeps 36-hour QSim and sets AAM service to 07:00-19:00");
        check(shipped.getBaseFare()==0,"shipped AAM configuration has no base fare");
        check(shipped.getMinimumTripDistanceMiles()==0&&shipped.getMaxAccessDistanceMiles()==30&&shipped.getMaxEgressDistanceMiles()==30,"exploration removes minimum trip exclusion and widens both catchments");
        check(shipped.getMaximumRoutedCandidates()==3&&shipped.getMaximumCandidateVertiportPairs()==3&&shipped.getProtectedAlternatives()==3&&shipped.getInitialExplorationFraction()==1,"exploration bounds candidate and port-pair routing while retaining alternatives and initial trials");
        check(shipped.getMinimumInnovationFreeFraction()>=0.2 && 50-(int)(50*input.strategy().getFractionOfIterationsToDisableInnovation())>=11,"at least the final 20 percent of iterations are innovation-free");
        Path frozen=RunDynamicAamLosAngelesScenario.resolveFromConfig("scenarios/aam/la-aam-fare30-it2.config.xml",shipped.getActiveVertiportsFile());
        List<RunDynamicAamLosAngelesScenario.VertiportLocation> frozenSites=RunDynamicAamLosAngelesScenario.readVertiportLocations(frozen,shipped.getActiveVertiportCount());
        check(frozenSites.size()==10 && frozenSites.stream().map(site->site.id).distinct().count()==10,"final runner reads ten unique sites from the frozen vertiport layout");
        check(input.strategy().getPlanSelectorForRemoval().equals("WorstPlanSelector"),"plan removal preserves the last typed AAM alternative");
        Config cleanupConfig=ConfigUtils.createConfig();ConfigUtils.addOrGetModule(cleanupConfig,DrtConfigGroup.class);
        AamAlternativeGuarantee.removeStartupAddedLegacyDrt(cleanupConfig,false);
        check(!cleanupConfig.getModules().containsKey(DrtConfigGroup.GROUP_NAME),"AAM startup removes only a newly introduced legacy single-mode DRT config");
        Config retainedConfig=ConfigUtils.createConfig();ConfigUtils.addOrGetModule(retainedConfig,DrtConfigGroup.class);
        AamAlternativeGuarantee.removeStartupAddedLegacyDrt(retainedConfig,true);
        check(retainedConfig.getModules().containsKey(DrtConfigGroup.GROUP_NAME),"AAM startup preserves a pre-existing legacy single-mode DRT config");
        check(!ConfigUtils.addOrGetModule(input,AamConfigGroup.class).modes().contains("ground_drt"),"no unavailable ground DRT option in AAM config");
        check(Arrays.asList(input.subtourModeChoice().getModes()).contains("ride"),"base LA ride choice retained");
        AamConfigGroup cfg=new AamConfigGroup();MultiModeDrtConfigGroup multi=new MultiModeDrtConfigGroup();DvrpConfigGroup dv=new DvrpConfigGroup();
        Config c=ConfigUtils.createConfig(cfg,multi,dv);c.controler().setLastIteration(0);
        c.global().setNumberOfThreads(3);c.qsim().setNumberOfThreads(2);
        cfg.setBaseFare(37);cfg.setFarePerMile(3);cfg.setMaxWaitTime(800);cfg.setMaxAccessDistanceMiles(4.5);cfg.setMinimumTripDistanceMiles(2.5);cfg.setWaitTimeBin(1800);cfg.setServiceStartTime(25200);cfg.setServiceEndTime(68400);cfg.setMinimumInnovationFreeFraction(0.25);
        c.strategy().setFractionOfIterationsToDisableInnovation(0.95);
        configure(c,multi,dv,"unused-test-output");
        check(c.global().getNumberOfThreads()==3 && c.qsim().getNumberOfThreads()==2,"custom scenario thread counts remain unchanged");
        check(c.controler().getLastIteration()==0,"configured iteration count preserved");
        check(c.strategy().getFractionOfIterationsToDisableInnovation()==0,"single-iteration edge case caps the configured innovation fraction at zero");
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
        check(ConfigUtils.addOrGetModule(loaded,AamConfigGroup.class).getMaxAccessDistanceMiles()==4.5 && ConfigUtils.addOrGetModule(loaded,AamConfigGroup.class).getMinimumTripDistanceMiles()==2.5 && ConfigUtils.addOrGetModule(loaded,AamConfigGroup.class).getWaitTimeBin()==1800,"access radius, minimum trip distance, and wait bin survive config XML round-trip");
        check(ConfigUtils.addOrGetModule(loaded,AamConfigGroup.class).getMinimumInnovationFreeFraction()==0.25 && ConfigUtils.addOrGetModule(loaded,AamConfigGroup.class).getActiveVertiportCount()==10,"frozen-layout and convergence settings survive config XML round-trip");
        check(ConfigUtils.addOrGetModule(loaded,AamConfigGroup.class).getServiceStartTime()==25200 && ConfigUtils.addOrGetModule(loaded,AamConfigGroup.class).getServiceEndTime()==68400,"DRT service window survives config XML round-trip");
        check(AamMultimodalRoutingModule.serviceAwareWait(25200-600,25200,900,120)==600,
                "a pre-opening passenger may wait for service opening when within the configured maximum wait");
        check(!Double.isFinite(AamMultimodalRoutingModule.serviceAwareWait(25200-901,25200,900,120)),
                "a pre-opening passenger beyond the configured maximum wait has no feasible AAM route");
        boolean denied=false;try{cfg.setAccessEgressModes("pt");}catch(IllegalArgumentException e){denied=true;}check(denied,"transit access rejected");
        boolean groundRejected=false;try{cfg.setAccessEgressModes("ground_drt");}catch(IllegalArgumentException e){groundRejected=true;}
        check(groundRejected,"unserved ground DRT cannot be selected");
        cfg.setAccessEgressModes("car,ride,ride_taxi,walk,bike");cfg.setCandidateVertiports(10);
        // Subsequent synthetic routes depart at t=0, unlike the XML-window check above.
        cfg.setServiceStartTime(0);cfg.setServiceEndTime(36*3600);
        for(String m:cfg.modes())c.planCalcScore().addModeParams(new ModeParams(m).setConstant(0).setMarginalUtilityOfTraveling(-6).setMonetaryDistanceRate(0));
        Scenario s=ScenarioUtils.createScenario(c);PopulationFactory pf=s.getPopulation().getFactory();
        List<AamMultimodalRoutingModule.Vertiport> parkingSites=new ArrayList<>();
        for(int i:new int[]{5,2,4,1,3})parkingSites.add(new AamMultimodalRoutingModule.Vertiport("p"+i,new Coord(i*100,0),Id.createLinkId("a"+i),Id.createLinkId("r"+i)));
        AamConfigGroup parkingCfg=new AamConfigGroup();parkingCfg.setCandidateVertiports(3);
        AamPlanStrategyModule parkingSearch=new AamPlanStrategyModule(s,parkingSites,1);
        List<AamMultimodalRoutingModule.Vertiport> nearestParking=parkingSearch.parkingCandidates(new Coord(0,0),parkingCfg);
        check(nearestParking.size()==3&&nearestParking.get(0).id.equals("p1")&&nearestParking.get(2).id.equals("p3"),"private parking search selects only three nearest sites regardless of input order");
        parkingCfg.setMaxEgressDistanceMiles(250/MILE);
        check(parkingSearch.parkingCandidates(new Coord(0,0),parkingCfg).size()==2,"parking shortlist respects return catchment and does not pad with ineligible sites");
        Person p=pf.createPerson(Id.createPersonId("test"));Plan plan=pf.createPlan();plan.addActivity(pf.createActivityFromCoord("home",new Coord(0,0)));p.addPlan(plan);p.setSelectedPlan(plan);
        s.getPopulation().addPerson(p);AamAlternativeGuarantee.ensureVehicleIds(s);
        check(VehicleUtils.getVehicleId(p,"car")!=null&&VehicleUtils.getVehicleId(p,"bike")!=null,"staged restart reconstructs private vehicle IDs before AAM rerouting");
        check(VehicleUtils.getVehicleId(p,"ride")!=null&&VehicleUtils.getVehicleId(p,"ride_taxi")!=null,"startup initializes BOTH passenger feeder vehicle IDs");
        c.plansCalcRoute().setNetworkModes(List.of("car","ride_school_bus","freight"));
        plan.addLeg(pf.createLeg("ride_school_bus"));
        plan.addActivity(pf.createActivityFromCoord("school",new Coord(1000,0)));
        AamAlternativeGuarantee.ensureVehicleIds(s);
        check(s.getVehicles().getVehicles().containsKey(VehicleUtils.getVehicleId(p,"ride_school_bus")),"startup initializes vehicles for ordinary configured school-bus network trips");
        Id<org.matsim.vehicles.Vehicle> schoolVehicle=VehicleUtils.getVehicleId(p,"ride_school_bus");
        AamAlternativeGuarantee.ensureVehicleIds(s);
        check(schoolVehicle.equals(VehicleUtils.getVehicleId(p,"ride_school_bus")),"repeated startup vehicle initialization preserves existing mappings");
        List<AamMultimodalRoutingModule.Vertiport> ports=List.of(
            new AamMultimodalRoutingModule.Vertiport("A",new Coord(0,0),Id.createLinkId("airA"),Id.createLinkId("roadA")),
            new AamMultimodalRoutingModule.Vertiport("B",new Coord(20000,0),Id.createLinkId("airB"),Id.createLinkId("roadB")));
        check(AamMultimodalRoutingModule.isEligible(ports,new Coord(4*MILE,0),new Coord(20000,0),5*MILE),"origin inside five-mile vertiport radius is AAM-eligible");
        check(!AamMultimodalRoutingModule.isEligible(ports,new Coord(6*MILE,0),new Coord(100,0),5*MILE),"origin outside five-mile vertiport radius is not AAM-eligible");
        check(!AamMultimodalRoutingModule.isEligible(ports,new Coord(0,0),new Coord(2*MILE,0),5*MILE,3*MILE),"trips shorter than the configured minimum are not AAM-eligible");
        List<AamMultimodalRoutingModule.Vertiport> closePorts=List.of(
            new AamMultimodalRoutingModule.Vertiport("A",new Coord(0,0),Id.createLinkId("airA"),Id.createLinkId("roadA")),
            new AamMultimodalRoutingModule.Vertiport("C",new Coord(1000,0),Id.createLinkId("airC"),Id.createLinkId("roadC")));
        check(AamMultimodalRoutingModule.isEligible(closePorts,new Coord(0,0),new Coord(1000,0),5*MILE),"short inter-vertiport distance no longer blocks eligibility");
        Person choicePerson=pf.createPerson(Id.createPersonId("choice"));choicePerson.getAttributes().putAttribute("subpopulation","person");
        Plan choicePlan=pf.createPlan();choicePlan.setScore(123.0);Activity choiceHome=pf.createActivityFromCoord("home",new Coord(0,0));choiceHome.setEndTime(3600);choicePlan.addActivity(choiceHome);
        Leg choiceLeg=pf.createLeg("walk");choicePlan.addLeg(choiceLeg);choicePlan.addActivity(pf.createActivityFromCoord("work",new Coord(20000,0)));
        choicePerson.addPlan(choicePlan);choicePerson.setSelectedPlan(choicePlan);s.getPopulation().addPerson(choicePerson);
        TripRouter.Builder seedBuilder=new TripRouter.Builder(c);
        seedBuilder.setRoutingModule("aam",(from,to,time,person)->{Leg l=pf.createLeg(AIR);Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());r.setDistance(20000);r.setTravelTime(500);l.setRoute(r);l.setTravelTime(500);return List.of(l);});
        seedBuilder.setRoutingModule("ride",(from,to,time,person)->{Leg l=pf.createLeg("ride");Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());r.setDistance(20000);r.setTravelTime(1000);l.setRoute(r);l.setTravelTime(1000);return List.of(l);});
        TripRouter seedRouter=seedBuilder.build();
        check(new AamPlanStrategyModule(s,ports,1,()->seedRouter.getRoutingModule("aam")).addAlternative(choicePlan,true),"eligible plan receives an AAM alternative");
        check(choicePlan.getScore()==null && AamPlanStrategyModule.AAM_PLAN_TYPE.equals(choicePlan.getType()),"new AAM alternative explicitly clears copied score and gets protected type");
        Person seeded=pf.createPerson(Id.createPersonId("seeded"));seeded.getAttributes().putAttribute("subpopulation","person");
        Plan base=pf.createPlan();base.setScore(10.0);Activity seedHome=pf.createActivityFromCoord("home",new Coord(0,0));seedHome.setEndTime(3600);base.addActivity(seedHome);
        Leg seedCar=pf.createLeg("ride");seedCar.setDepartureTime(3600);base.addLeg(seedCar);base.addActivity(pf.createActivityFromCoord("work",new Coord(20000,0)));
        seeded.addPlan(base);seeded.setSelectedPlan(base);s.getPopulation().addPerson(seeded);
        List<Plan> guaranteed=new AamAlternativeGuarantee(s,new AamMultimodalRoutingModule.PortSet(ports),()->seedRouter).seedAlternatives();
        check(seeded.getSelectedPlan()==base,"startup preserves the selected ground plan for iteration zero");
        check(guaranteed.size()==1&&seeded.getPlans().size()==2&&AamAlternativeGuarantee.hasAam(seeded),"eligible agent is seeded with a separate AAM choice");
        cfg.setInitialExplorationFraction(1);
        AamAlternativeGuarantee initial=new AamAlternativeGuarantee(s,new AamMultimodalRoutingModule.PortSet(ports),()->seedRouter);
        check(initial.selectInitialExploration()>0&&AamFeederPolicy.hasGenuineAam(seeded.getSelectedPlan()),"enabled initial exploration selects physical AAM before iteration zero");
        seeded.setSelectedPlan(base);
        check(initial.selectInitialExploration()==0&&seeded.getSelectedPlan()==base,"restart never forces already exposed passengers back to AAM");
        cfg.setInitialExplorationFraction(0);
        guaranteed.get(0).setScore(-100.0);for(int i=0;i<4;i++){Plan extra=pf.createPlan();extra.setScore((double)i);seeded.addPlan(extra);}
        check(new org.matsim.core.replanning.selectors.WorstPlanForRemovalSelector().selectPlan(seeded)!=guaranteed.get(0),"last typed AAM choice survives plan-memory removal");
        Person paired=pf.createPerson(Id.createPersonId("paired-infeasible"));paired.getAttributes().putAttribute("subpopulation","person");
        Plan pairedPlan=pf.createPlan();pairedPlan.setScore(5.0);
        Activity pairedHome=pf.createActivityFromCoord("home",new Coord(0,0));pairedHome.setEndTime(6*3600);pairedPlan.addActivity(pairedHome);
        Leg outboundCar=pf.createLeg("car");outboundCar.setDepartureTime(6*3600);pairedPlan.addLeg(outboundCar);
        Activity pairedWork=pf.createActivityFromCoord("work",new Coord(20000,0));pairedWork.setEndTime(16*3600);pairedPlan.addActivity(pairedWork);
        Leg returnCar=pf.createLeg("car");returnCar.setDepartureTime(16*3600);pairedPlan.addLeg(returnCar);
        pairedPlan.addActivity(pf.createActivityFromCoord("home",new Coord(0,0)));
        paired.addPlan(pairedPlan);paired.setSelectedPlan(pairedPlan);s.getPopulation().addPerson(paired);
        Provider<RoutingModule> infeasibleAam=()->(from,to,time,person)->{
            throw new AamMultimodalRoutingModule.InfeasibleAamRouteException("outside service hours");
        };
        check(!new AamPlanStrategyModule(s,ports,1,infeasibleAam).addAlternative(pairedPlan,false),
                "an infeasible leg rejects the whole paired private-vehicle AAM alternative");
        check(pairedPlan.getPlanElements().stream().filter(e->e instanceof Leg).allMatch(e->"car".equals(((Leg)e).getMode()))
                &&pairedPlan.getAttributes().getAttribute("aam_park_mode")==null&&pairedPlan.getScore()==5.0,
                "rejecting an infeasible paired alternative restores the scored ground plan intact");
        AamWaitTimeEstimator waits=new AamWaitTimeEstimator(3600);waits.record("airA","airB",100,220);waits.record("airA","airC",200,500);
        check(waits.estimate(Id.createLinkId("airA"),Id.createLinkId("airB"),300,900,900)==120,"wait estimate uses matching origin-destination and time bin");
        check(waits.estimate(Id.createLinkId("airA"),Id.createLinkId("airB"),4000,900,900)==210,"sparse time bin falls back to observed origin mean");
        check(waits.estimate(Id.createLinkId("airA"),Id.createLinkId("newAir"),300,120,900)==120,"new vertiport pair uses the common fallback wait");
        Path waitPriors=Files.createTempFile("aam-wait-priors-",".csv");waits.write(waitPriors);AamWaitTimeEstimator restoredWaits=new AamWaitTimeEstimator(3600);restoredWaits.read(waitPriors);
        check(restoredWaits.estimate(Id.createLinkId("airA"),Id.createLinkId("airB"),300,900,900)==120,"observed wait priors persist across staged MATSim controllers");
        Map<String,String> parsed=RunDynamicAamLosAngelesScenario.parseOptions(new String[]{"config","out","--plans=x.xml.gz","--run-id=scoreopt","--base-fare=30","--fare-per-mile=2","--service-start-time=25200","--service-end-time=68400","--candidate-vertiports=10","--disable-innovation"},2);
        check(parsed.get("plans").equals("x.xml.gz")&&parsed.get("base-fare").equals("30")
                &&parsed.get("fare-per-mile").equals("2")&&parsed.get("candidate-vertiports").equals("10")
                &&parsed.get("service-start-time").equals("25200")&&parsed.get("service-end-time").equals("68400")
                &&parsed.get("run-id").equals("scoreopt")&&parsed.containsKey("disable-innovation"),
                "staged-run command-line and fare overrides are parsed");
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
        routers.put("ride",(from,to,time,person)->{throw new RuntimeException("Could not retrieve vehicle id from person: "+person.getId());});
        boolean feederFailure=false;
        try{new AamMultimodalRoutingModule(s,ports,routers).calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);}
        catch(IllegalStateException e){feederFailure=e.getMessage().contains("mode=ride")&&e.getMessage().contains("person=test");}
        check(feederFailure,"failed feeder has explicit person/mode diagnostic, never silently disappears");
        routers.put("ride",(from,to,time,person)->{
            Leg l=pf.createLeg("ride");Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());
            r.setDistance(100);r.setTravelTime(1);l.setRoute(r);l.setTravelTime(1);l.setDepartureTime(time);return List.of(l);
        });
        route=new AamMultimodalRoutingModule(s,ports,routers).calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);
        check(((Leg)route.get(0)).getMode().equals("ride"),"baseline ride is usable for vertiport access without DRT vehicles");
        List<? extends PlanElement> outside=new AamMultimodalRoutingModule(s,ports,routers).calcRoute(fac(s,"boundary-link",6*MILE),fac(s,"destination",20000),0,p);
        check(outside.stream().noneMatch(e->e instanceof Leg&&((Leg)e).getMode().equals(AIR)),"actual selected vertiport must satisfy eligibility radius");
        routers.put("ride",(from,to,time,person)->{
            Leg l=pf.createLeg("ride");Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());
            r.setDistance(100);r.setTravelTime(6000);l.setRoute(r);l.setTravelTime(6000);l.setDepartureTime(time);return List.of(l);
        });
        Leg flight=route.stream().filter(e->e instanceof Leg && ((Leg)e).getMode().equals(AIR)).map(e->(Leg)e).findFirst().get();
        DrtRoute initialDrt=(DrtRoute)flight.getRoute();
        check(Math.abs(initialDrt.getMaxTravelTime()-(1.2*initialDrt.getDirectRideTime()+1800))<1e-6
            &&flight.getTravelTime().seconds()<initialDrt.getMaxTravelTime(),"initial AAM route separates expected time from the dispatcher latest-arrival allowance");
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
        plan.getAttributes().putAttribute("aam_park_mode","car");plan.getAttributes().putAttribute("aam_park_vertiport","C");
        AamMultimodalRoutingModule parkingRouter=new AamMultimodalRoutingModule(s,expanded,routers);
        List<? extends PlanElement> parkedOut=parkingRouter.calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);
        List<? extends PlanElement> parkedBack=parkingRouter.calcRoute(fac(s,"origin",20000),fac(s,"destination",0),0,p);
        check(parkedOut.stream().filter(e->e instanceof Leg&&AIR.equals(((Leg)e).getMode())).allMatch(e->((Leg)e).getRoute().getStartLinkId().toString().equals("airC"))
            &&parkedBack.stream().filter(e->e instanceof Leg&&AIR.equals(((Leg)e).getMode())).allMatch(e->((Leg)e).getRoute().getEndLinkId().toString().equals("airC")),"non-nearest parking choice is identical for outbound access and return retrieval");
        plan.getAttributes().removeAttribute("aam_park_mode");plan.getAttributes().removeAttribute("aam_park_vertiport");
        cfg.setAccessEgressModes("walk");
        routers.put("walk",(from,to,time,person)->{
            double tt=to.getLinkId().toString().equals("roadA")?10000:60;
            Leg l=pf.createLeg("walk");Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());r.setDistance(100);r.setTravelTime(tt);l.setRoute(r);l.setTravelTime(tt);l.setDepartureTime(time);return List.of(l);
        });
        route=new AamMultimodalRoutingModule(s,expanded,routers).calcRoute(fac(s,"origin",0),fac(s,"destination",20000),0,p);
        flight=route.stream().filter(e->e instanceof Leg && ((Leg)e).getMode().equals(AIR)).map(e->(Leg)e).findFirst().get();
        check(flight.getRoute().getStartLinkId().toString().equals("airC"),"joint route search can choose a non-nearest vertiport");
        choicePipelineChecks();
        dynamicSmoke();
        longFlightInsertionSmoke(0.5,false);
        longFlightInsertionSmoke(1.0,true);
        System.out.println("ALL "+checks+" CHECKS PASSED");
    }
    static void choicePipelineChecks()throws Exception{
        AamConfigGroup cfg=new AamConfigGroup();cfg.setServiceStartTime(25200);cfg.setServiceEndTime(68400);cfg.setMinimumTripDistanceMiles(0);
        Config config=ConfigUtils.createConfig(cfg);config.qsim().setEndTime(129600);
        Scenario s=ScenarioUtils.createScenario(config);PopulationFactory f=s.getPopulation().getFactory();
        List<AamMultimodalRoutingModule.Vertiport> ports=List.of(
            new AamMultimodalRoutingModule.Vertiport("A",new Coord(0,0),Id.createLinkId("airA"),Id.createLinkId("roadA")),
            new AamMultimodalRoutingModule.Vertiport("B",new Coord(20000,0),Id.createLinkId("airB"),Id.createLinkId("roadB")));
        check(cfg.getMaxEgressDistanceMiles()==cfg.getMaxAccessDistanceMiles(),"unspecified egress radius inherits access radius");
        check(!AamMultimodalRoutingModule.isEligible(ports,new Coord(0,0),new Coord(40000,0),5*MILE),"origin inside five miles and destination outside five miles is ineligible");
        Plan marker=f.createPlan();marker.setType("aam");Leg ride=f.createLeg("ride");TripStructureUtils.setRoutingMode(ride,"aam");marker.addLeg(ride);
        check(!AamFeederPolicy.hasGenuineAam(marker)&&AamFeederPolicy.hasAamMarker(marker),"marker-only ride plan is never genuine AAM");
        Plan unrouted=f.createPlan();unrouted.addLeg(f.createLeg(AIR));
        check(AamAlternativeGuarantee.needsAamRouting(unrouted),"an unrouted physical-air leg is rebuilt before startup choice-set exposure");
        Person person=f.createPerson(Id.createPersonId("screen-all"));person.getAttributes().putAttribute("subpopulation","person");
        Plan plan=f.createPlan();String[] types={"home","work","shopping","recreation","home"};
        double[] xs={0,20000,0,20000,0};
        for(int i=0;i<types.length;i++){Activity a=f.createActivityFromCoord(types[i],new Coord(xs[i],0));if(i<types.length-1)a.setEndTime(30000+i*3600);plan.addActivity(a);if(i<types.length-1)plan.addLeg(f.createLeg("ride"));}
        person.addPlan(plan);person.setSelectedPlan(plan);s.getPopulation().addPerson(person);
        AamCandidateScreen screen=AamCandidateScreen.get(s);List<AamCandidateScreen.Candidate> rows=screen.screen(plan,ports);
        check(rows.size()==4&&rows.stream().allMatch(c->c.temporal),"cheap screening includes all home and non-home trips");
        long passes=screen.screenPasses.get(),distances=screen.distanceCalculations.get();screen.screen(plan,ports);
        check(screen.screenPasses.get()==passes&&screen.distanceCalculations.get()==distances,"unchanged layout and trip signature reuse screening across iterations");
        check(screen.distanceTo(new Coord(123,321),ports.get(0))==AamMultimodalRoutingModule.distance(new Coord(123,321),ports.get(0).coord),"precomputed distance equals direct calculation");
        List<AamMultimodalRoutingModule.Vertiport> distant=List.of(ports.get(0),new AamMultimodalRoutingModule.Vertiport("FAR",new Coord(60000,0),Id.createLinkId("airF"),Id.createLinkId("roadF")));
        check(screen.screen(plan,distant).stream().noneMatch(c->c.temporal),"unresolved candidates survive an infeasible layout");
        check(person.getAttributes().getAttribute("aam_candidates").toString().contains("distance"),"unresolved person metadata retains origin destination departure and reason");
        check(screen.screen(plan,ports).stream().allMatch(c->c.temporal),"candidate can become eligible again after a vertiport swap");
        final int[] attempts={0};Provider<RoutingModule> fail=()->(from,to,time,p)->{attempts[0]++;return List.of(f.createLeg("ride"));};
        check(!new AamPlanStrategyModule(s,ports,1,fail).addAlternative(plan,true)&&attempts[0]==2,"only best two screened candidates receive full routing");
        final int[] successCalls={0};Provider<RoutingModule> nonHome=()->(from,to,time,p)->{
            successCalls[0]++;if(from.getCoord().getX()==0)return List.of(f.createLeg("ride"));
            Leg l=f.createLeg(AIR);Route route=RouteUtils.createGenericRouteImpl(Id.createLinkId("airB"),Id.createLinkId("airA"));route.setDistance(20000);route.setTravelTime(500);l.setRoute(route);l.setTravelTime(500);return List.of(l);
        };
        Plan alternative=f.createPlan();org.matsim.core.population.PopulationUtils.copyFromTo(plan,alternative);person.addPlan(alternative);
        check(new AamPlanStrategyModule(s,ports,1,nonHome).addAlternative(alternative,true)&&successCalls[0]==2,"non-home work to shopping trip receives a genuine alternative after first candidate fails");
        check(person.getSelectedPlan()==plan&&alternative.getScore()==null,"routing an unselected alternative preserves behavioral choice and clears its score");
        config.planCalcScore().addModeParams(new ModeParams(AIR).setMarginalUtilityOfTraveling(-6));
        Plan ranked=f.createPlan();org.matsim.core.population.PopulationUtils.copyFromTo(plan,ranked);person.addPlan(ranked);
        final int[] rankedCalls={0};Provider<RoutingModule> varied=()->(from,to,time,p)->{
            rankedCalls[0]++;Leg l=f.createLeg(AIR);Route r=RouteUtils.createGenericRouteImpl(Id.createLinkId("airA"),Id.createLinkId("airB"));
            r.setDistance(20000);r.setTravelTime(from.getCoord().getX()==0?5000:100);l.setRoute(r);l.setTravelTime(r.getTravelTime().seconds());return List.of(l);
        };
        check(new AamPlanStrategyModule(s,ports,1,varied).addAlternative(ranked,true)&&rankedCalls[0]==2
            &&"1,1".equals(ranked.getAttributes().getAttribute("aam_candidate_indices")),"candidate generation compares feasible routes instead of stopping at the first success");
        cfg.setMaximumRoutedCandidates(8);check(cfg.getMaximumRoutedCandidates()==8,"routing budget accepts more than two candidates");cfg.setMaximumRoutedCandidates(2);
        Plan falseChoice=f.createPlan();falseChoice.setType("aam");falseChoice.setScore(999.);falseChoice.addLeg(f.createLeg("ride"));person.addPlan(falseChoice);alternative.setScore(-999.);
        check(new AamPlanRemovalSelector(s).selectPlan(person)!=alternative,"marker-only competitor cannot cause the last physical AAM alternative to be removed");
        check(config.qsim().getEndTime().seconds()==129600,"36-hour QSim horizon is preserved");
        for(String mode:List.of("car","bike")){
            Person owner=f.createPerson(Id.createPersonId("tour-"+mode));Plan tour=f.createPlan();
            for(int i=0;i<types.length;i++){Activity a=f.createActivityFromCoord(types[i],new Coord(xs[i],0));if(i<types.length-1)a.setEndTime(30000+i*3600);tour.addActivity(a);if(i<types.length-1)tour.addLeg(f.createLeg(mode));}
            ((Activity)tour.getPlanElements().get(tour.getPlanElements().size()-1)).setEndTime(50000);
            tour.addLeg(f.createLeg(mode));Activity local=f.createActivityFromCoord("shopping",new Coord(500,0));local.setEndTime(60000);tour.addActivity(local);
            tour.addLeg(f.createLeg(mode));tour.addActivity(f.createActivityFromCoord("home",new Coord(0,0)));
            owner.addPlan(tour);owner.setSelectedPlan(tour);
            Provider<RoutingModule> air=()->(from,to,time,p)->{Leg l=f.createLeg(AIR);Route r=RouteUtils.createGenericRouteImpl(Id.createLinkId("airA"),Id.createLinkId("airB"));r.setTravelTime(500);r.setDistance(20000);l.setRoute(r);l.setTravelTime(500);return List.of(l);};
            Person startup=f.createPerson(Id.createPersonId("startup-tour-"+mode));startup.getAttributes().putAttribute("subpopulation","person");
            Plan original=f.createPlan();org.matsim.core.population.PopulationUtils.copyFromTo(tour,original);original.setScore(42.);startup.addPlan(original);startup.setSelectedPlan(original);s.getPopulation().addPerson(startup);
            TripRouter.Builder startupBuilder=new TripRouter.Builder(config);startupBuilder.setRoutingModule("aam",air.get());
            for(String groundMode:List.of("car","bike","ride"))startupBuilder.setRoutingModule(groundMode,(from,to,time,p)->{Leg l=f.createLeg(groundMode);Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());r.setTravelTime(100);r.setDistance(500);l.setRoute(r);l.setTravelTime(100);return List.of(l);});
            TripRouter startupRouter=startupBuilder.build();new AamAlternativeGuarantee(s,new AamMultimodalRoutingModule.PortSet(ports),()->startupRouter).seedAlternatives();
            Plan startupAir=startup.getPlans().stream().filter(AamFeederPolicy::hasGenuineAam).findFirst().orElseThrow();
            check("paired_tour".equals(startupAir.getAttributes().getAttribute("aam_alternative_kind")),mode+" startup uses the paired-tour strategy without converting the whole day to ride");
            check(TripStructureUtils.getTrips(startupAir).get(4).getLegsOnly().stream().allMatch(l->mode.equals(l.getMode()))
                &&TripStructureUtils.getTrips(startupAir).get(5).getLegsOnly().stream().allMatch(l->mode.equals(l.getMode())),mode+" startup retains unrelated later private trips");
            check(startup.getSelectedPlan()==original&&original.getScore()==42.&&startupAir.getScore()==null,mode+" startup retains the selected scored ground plan and an unscored alternative");
            check(new AamPlanStrategyModule(s,ports,1,air).addAlternative(tour,true),mode+" home subtour may contain intermediate activities");
            check(TripStructureUtils.getTrips(tour).size()==6&&"paired_tour".equals(tour.getAttributes().getAttribute("aam_alternative_kind"))
                &&TripStructureUtils.getTrips(tour).get(1).getLegsOnly().stream().allMatch(l->"ride".equals(l.getMode())),mode+" parked vehicle is not teleported through intermediate activities");
            check(TripStructureUtils.getTrips(tour).get(4).getLegsOnly().stream().allMatch(l->mode.equals(l.getMode()))
                &&TripStructureUtils.getTrips(tour).get(5).getLegsOnly().stream().allMatch(l->mode.equals(l.getMode())),mode+" unrelated later home tour retains its private vehicle legs");
            Plan failed=f.createPlan();for(int i=0;i<types.length;i++){Activity a=f.createActivityFromCoord(types[i],new Coord(xs[i],0));if(i<types.length-1)a.setEndTime(30000+i*3600);failed.addActivity(a);if(i<types.length-1)failed.addLeg(f.createLeg(mode));}owner.addPlan(failed);
            final int[] halves={0};Provider<RoutingModule> badReturn=()->(from,to,time,p)->{if(++halves[0]==2)throw new AamMultimodalRoutingModule.InfeasibleAamRouteException("return unavailable");return air.get().calcRoute(from,to,time,p);};
            check(!new AamPlanStrategyModule(s,ports,1,badReturn).addAlternative(failed,true)&&failed.getPlanElements().stream().filter(e->e instanceof Leg).allMatch(e->mode.equals(((Leg)e).getMode())),mode+" infeasible return restores the whole original tour");
        }
        Person late=f.createPerson(Id.createPersonId("late-car-return"));Plan latePlan=f.createPlan();
        Activity lh=f.createActivityFromCoord("home",new Coord(0,0));lh.setEndTime(30000);latePlan.addActivity(lh);latePlan.addLeg(f.createLeg("car"));
        Activity lw=f.createActivityFromCoord("work",new Coord(20000,0));lw.setEndTime(76000);latePlan.addActivity(lw);latePlan.addLeg(f.createLeg("car"));latePlan.addActivity(f.createActivityFromCoord("home",new Coord(0,0)));
        late.addPlan(latePlan);late.setSelectedPlan(latePlan);
        Provider<RoutingModule> oneWay=()->(from,to,time,p)->{Leg l=f.createLeg(AIR);Route r=RouteUtils.createGenericRouteImpl(Id.createLinkId("airA"),Id.createLinkId("airB"));r.setDistance(20000);r.setTravelTime(500);l.setRoute(r);l.setTravelTime(500);return List.of(l);};
        check(!new AamPlanStrategyModule(s,ports,1,oneWay).addAlternative(latePlan,true),"car-to-port tour cannot strand the car after AAM service ends");
        cfg.setAllowCarAtHomeAlternatives(true);
        check(new AamPlanStrategyModule(s,ports,1,oneWay).addAlternative(latePlan,true)
            &&"car_at_home_tour".equals(latePlan.getAttributes().getAttribute("aam_alternative_kind"))
            &&TripStructureUtils.getLegs(latePlan).stream().noneMatch(l->"car".equals(l.getMode())),"one-way AAM is feasible with late ground return when private car stays at home");
        cfg.setAllowCarAtHomeAlternatives(false);
        // Compare identical exact-time routes with caching toggled; three ports share access work.
        cfg.setAccessEgressModes("ride");cfg.setCandidateVertiports(3);
        config.planCalcScore().addModeParams(new ModeParams("ride").setMarginalUtilityOfTraveling(-6));config.planCalcScore().addModeParams(new ModeParams(AIR).setMarginalUtilityOfTraveling(-6));
        List<AamMultimodalRoutingModule.Vertiport> three=new ArrayList<>(ports);three.add(new AamMultimodalRoutingModule.Vertiport("C",new Coord(21000,0),Id.createLinkId("airC"),Id.createLinkId("roadC")));
        final int[] feederCalls={0};Map<String,RoutingModule> feeders=Map.of("ride",(from,to,time,p)->{feederCalls[0]++;Leg l=f.createLeg("ride");Route r=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());r.setDistance(100);r.setTravelTime(60);l.setRoute(r);l.setTravelTime(60);l.setDepartureTime(time);return List.of(l);});
        AamMultimodalRoutingModule router=new AamMultimodalRoutingModule(s,three,feeders);
        long start=System.nanoTime();cfg.setCacheFeederRoutes(false);List<? extends PlanElement> uncached=router.calcRoute(fac(s,"from",0),fac(s,"to",20000),30000,person);long uncachedTime=System.nanoTime()-start;int uncachedCalls=feederCalls[0];
        feederCalls[0]=0;start=System.nanoTime();cfg.setCacheFeederRoutes(true);List<? extends PlanElement> cached=router.calcRoute(fac(s,"from",0),fac(s,"to",20000),30000,person);long cachedTime=System.nanoTime()-start;
        check(routeSignature(cached).equals(routeSignature(uncached))&&feederCalls[0]<uncachedCalls,"cached and uncached routing are behaviorally equivalent with fewer feeder calls");
        System.out.println("PERFORMANCE feeder calls uncached="+uncachedCalls+" cached="+feederCalls[0]+" ns uncached="+uncachedTime+" cached="+cachedTime);
        cfg.setAllowPreServiceRequests(false);
        check(router.calcRoute(fac(s,"from",0),fac(s,"to",20000),25000,person).stream().noneMatch(e->e instanceof Leg&&AIR.equals(((Leg)e).getMode())),"pre-service request disabled excludes early access arrival");
        cfg.setAllowPreServiceRequests(true);List<? extends PlanElement> early=router.calcRoute(fac(s,"from",0),fac(s,"to",20000),25000,person);
        Leg flight=early.stream().filter(e->e instanceof Leg&&AIR.equals(((Leg)e).getMode())).map(e->(Leg)e).findFirst().get();
        check(flight.getDepartureTime().seconds()<25200&&flight.getDepartureTime().seconds()+flight.getTravelTime().seconds()>=25200,"pre-service request may wait until opening for flight");
        check(router.calcRoute(fac(s,"from",0),fac(s,"to",20000),68300,person).stream().noneMatch(e->e instanceof Leg&&AIR.equals(((Leg)e).getMode())),"flight completion beyond 19:00 is infeasible");
        plan.getAttributes().putAttribute("aam_park_mode","car");
        List<? extends PlanElement> invalidPrivate=router.calcRoute(fac(s,"from",0),fac(s,"to",20000),68300,person);
        check(invalidPrivate.stream().noneMatch(e->e instanceof Leg&&AIR.equals(((Leg)e).getMode()))
            &&Boolean.TRUE.equals(plan.getAttributes().getAttribute("aam_private_route_infeasible")),"native rerouting flags an infeasible private tour without aborting replanning");
        AamFeederPolicy.invalidateAam(plan);
        check(plan.getAttributes().getAttribute("aam_park_mode")==null&&plan.getAttributes().getAttribute("aam_private_route_infeasible")==null,"invalid private tour normalization clears parking and infeasibility markers");
        Person nativePerson=f.createPerson(Id.createPersonId("native-private-gate"));nativePerson.getAttributes().putAttribute("subpopulation","person");
        Plan outside=f.createPlan();outside.setScore(10.);Activity home=f.createActivityFromCoord("home",new Coord(0,0));home.setEndTime(30000);outside.addActivity(home);
        outside.addLeg(f.createLeg("ride"));Activity work=f.createActivityFromCoord("work",new Coord(20000,0));work.setEndTime(68000);outside.addActivity(work);outside.addLeg(f.createLeg("ride"));outside.addActivity(f.createActivityFromCoord("home",new Coord(0,0)));
        nativePerson.addPlan(outside);Plan broken=f.createPlan();org.matsim.core.population.PopulationUtils.copyFromTo(outside,broken);nativePerson.addPlan(broken);
        TripStructureUtils.Trip first=TripStructureUtils.getTrips(broken).get(0);Leg physical=f.createLeg(AIR);TripStructureUtils.setRoutingMode(physical,"aam");
        TripRouter.insertTrip(broken,first.getOriginActivity(),List.of(physical),first.getDestinationActivity());
        broken.setType("aam");broken.getAttributes().putAttribute("aam_park_mode","car");broken.getAttributes().putAttribute("aam_private_route_infeasible",true);
        nativePerson.setSelectedPlan(broken);s.getPopulation().addPerson(nativePerson);s.addScenarioElement("aamActivePorts",new AamMultimodalRoutingModule.PortSet(ports));
        TripRouter groundRouter=new TripRouter.Builder(config).setRoutingModule("ride",feeders.get("ride")).build();
        new AamSelectedPlanValidator(s,()->groundRouter).notifyBeforeMobsim(null);
        check(nativePerson.getSelectedPlan()==outside&&!AamFeederPolicy.hasGenuineAam(broken)&&broken.getPlanElements().stream().noneMatch(e->e instanceof Leg&&AIR.equals(((Leg)e).getMode())),"pre-QSim gate rejects the whole infeasible private return chain and retains the scored ground choice");
    }
    static String routeSignature(List<? extends PlanElement> route){StringBuilder result=new StringBuilder();for(PlanElement e:route)if(e instanceof Leg){Leg l=(Leg)e;result.append(l.getMode()).append(l.getDepartureTime()).append(l.getTravelTime()).append(l.getRoute().getStartLinkId()).append(l.getRoute().getEndLinkId()).append(l.getRoute().getDistance());}return result.toString();}
    static void longFlightInsertionSmoke(double factor,boolean shouldServe)throws Exception{
        MultiModeDrtConfigGroup multi=new MultiModeDrtConfigGroup();DvrpConfigGroup dv=new DvrpConfigGroup();
        Config c=ConfigUtils.createConfig(multi,dv);c.controler().setLastIteration(0);c.controler().setCreateGraphs(false);
        c.global().setNumberOfThreads(1);c.qsim().setNumberOfThreads(1);c.qsim().setEndTime(36000);
        c.qsim().setSimStarttimeInterpretation(org.matsim.core.config.groups.QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
        c.qsim().setSimEndtimeInterpretation(org.matsim.core.config.groups.QSimConfigGroup.EndtimeInterpretation.onlyUseEndtime);
        Path root=Paths.get("run-output/aam-repair-validation/can012-dispatch-"+factor+"-"+System.currentTimeMillis()).toAbsolutePath();Files.createDirectories(root);
        c.controler().setOutputDirectory(root.resolve("matsim").toString());
        c.planCalcScore().addActivityParams(new ActivityParams("home").setTypicalDuration(3600));
        c.planCalcScore().addActivityParams(new ActivityParams("work").setTypicalDuration(3600));
        c.planCalcScore().addModeParams(new ModeParams(AIR).setMarginalUtilityOfTraveling(-6));
        DrtConfigGroup d=new DrtConfigGroup();d.setMode(AIR);d.setUseModeFilteredSubnetwork(true);d.setMaxWaitTime(900);
        d.setStopDuration(120);d.setMaxTravelTimeAlpha(1.2);d.setMaxTravelTimeBeta(1800);d.setNumberOfThreads(1);
        org.matsim.contrib.drt.optimizer.insertion.SelectiveInsertionSearchParams search=new org.matsim.contrib.drt.optimizer.insertion.SelectiveInsertionSearchParams();search.setRestrictiveBeelineSpeedFactor(factor);d.addParameterSet(search);
        Path fleet=root.resolve("fleet.xml");Files.writeString(fleet,"<?xml version=\"1.0\"?><!DOCTYPE vehicles SYSTEM \"http://matsim.org/files/dtd/dvrp_vehicles_v1.dtd\"><vehicles><vehicle id=\"aam_drt_0000\" start_link=\"aam_loop_CAN012\" t_0=\"25200\" t_1=\"68400\" capacity=\"4\"/></vehicles>");
        d.setVehiclesFile(fleet.toString());multi.addParameterSet(d);dv.setNetworkModes(com.google.common.collect.ImmutableSet.of(AIR));dv.getTravelTimeMatrixParams().setCellSize(500);
        DrtConfigs.adjustMultiModeDrtConfig(multi,c.planCalcScore(),c.plansCalcRoute());
        Scenario s=DrtControlerCreator.createScenarioWithDrtRouteFactory(c);Network n=s.getNetwork();NetworkFactory nf=n.getFactory();
        String[] names={"CAN012","CAN025"};Node[] nodes=new Node[2];
        java.util.Map<String,VertiportLocation> locations=new HashMap<>();
        for(VertiportLocation location:readVertiportLocations(Paths.get("scenarios/aam/vertiport-candidates-100.csv"),100))locations.put(location.id,location);
        for(int i=0;i<2;i++){VertiportLocation location=locations.get(names[i]);nodes[i]=nf.createNode(Id.createNodeId(names[i]),new Coord(location.x,location.y));n.addNode(nodes[i]);}
        for(int i=0;i<2;i++)for(int j=0;j<2;j++){
            Link link=nf.createLink(Id.createLinkId(i==j?"aam_loop_"+names[i]:"aam_air_"+names[i]+"_"+names[j]),nodes[i],nodes[j]);
            link.setLength(Math.max(1,AamMultimodalRoutingModule.distance(nodes[i].getCoord(),nodes[j].getCoord())));link.setFreespeed(AIR_SPEED);link.setCapacity(10000);link.setNumberOfLanes(1);link.setAllowedModes(Set.of(AIR));n.addLink(link);
        }
        PopulationFactory pf=s.getPopulation().getFactory();Person p=pf.createPerson(Id.createPersonId("CAN012_repro"));Plan plan=pf.createPlan();
        Activity home=pf.createActivityFromLinkId("home",Id.createLinkId("aam_loop_CAN012"));home.setEndTime(30000);plan.addActivity(home);plan.addLeg(pf.createLeg(AIR));plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId("aam_loop_CAN025")));p.addPlan(plan);s.getPopulation().addPerson(p);
        Controler ctrl=new Controler(s);ctrl.addOverridingModule(new DvrpModule());ctrl.addOverridingModule(new AamMultiModeDrtModule());ctrl.configureQSimComponents(DvrpQSimComponents.activateAllModes(multi));
        int[] counts={0,0};ctrl.getEvents().addHandler((org.matsim.core.events.handler.BasicEventHandler)e->{if(e.getEventType().equals("passenger dropped off"))counts[0]++;if(e.getEventType().equals("PassengerRequest rejected"))counts[1]++;});
        ctrl.run();check(counts[0]==(shouldServe?1:0)&&counts[1]==(shouldServe?0:1),"CAN012 -> CAN025 factor="+factor+" completed="+counts[0]+" rejected="+counts[1]+" with unchanged passenger constraints");
        Files.writeString(root.resolve("verified.txt"),"factor="+factor+" completed="+counts[0]+" rejected="+counts[1]+"\n");
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
