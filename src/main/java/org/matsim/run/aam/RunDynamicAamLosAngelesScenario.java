package org.matsim.run.aam;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import javax.inject.Inject;
import javax.inject.Provider;
import com.google.inject.name.Named;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.contrib.drt.fare.DrtFareParams;
import org.matsim.contrib.drt.routing.*;
import org.matsim.contrib.drt.run.*;
import org.matsim.contrib.drt.optimizer.insertion.SelectiveInsertionSearchParams;
import org.matsim.contrib.dvrp.run.*;
import org.matsim.core.config.*;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.*;
import org.matsim.core.config.groups.QSimConfigGroup.*;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.network.algorithms.*;
import org.matsim.core.replanning.*;
import org.matsim.core.replanning.modules.ReRoute;
import org.matsim.core.replanning.selectors.RandomPlanSelector;
import org.matsim.core.router.*;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.run.RunLosAngelesScenario;

/** MATSim 13, dynamic AAM aircraft and original LA ground modes. No base-runner edits. */
public final class RunDynamicAamLosAngelesScenario {
    public static final long SEED=20260909L;
    public static final String AIR="aam_drt", AAM="aam";
    public static final double MILE=1609.344, AIR_SPEED=100*MILE/3600, MAX_WAIT=900;
    public static final double AAM_BASE_FARE=30, AAM_PER_MILE=2;
    public static final int AIRCRAFT=100;
    public static final double[][] COORDS={
        {282086.6791630887,-470927.31895150105},{156867.80930025305,-424575.10532179195},
        {239164.36206755522,-474067.19596208027},{115286.23341467915,-415969.8192713326},
        {267147.03224965854,-500499.6440343107},{345023.37350177165,-470242.05700257095},
        {214624.56523925607,-428803.77498400025},{193025.76511600026,-464824.05341277504},
        {172937.29294743025,-456860.64624100365},{282456.85131945845,-470270.778965645}};
    public static void main(String[] args) throws Exception {
        String configFile=args.length>0?args[0]:"scenarios/aam/la-aam-fare30-it2.config.xml";
        String out=args.length>1?args[1]:"run-output/aam-fare30-it2";
        MultiModeDrtConfigGroup modes=new MultiModeDrtConfigGroup();
        DvrpConfigGroup dvrp=new DvrpConfigGroup();
        Config c=RunLosAngelesScenario.prepareConfig(new String[]{configFile},modes,dvrp,new AamConfigGroup());
        configure(c,modes,dvrp,out);
        // Keep generated fleet inputs outside the controller's output cleanup.
        Path fleetDir=Paths.get(out+"-inputs").toAbsolutePath();Files.createDirectories(fleetDir);
        for(DrtConfigGroup d:modes.getModalElements())
            d.setVehiclesFile(fleetDir.resolve(d.getMode()+"-fleet.xml").toUri().toString());
        new ConfigWriter(c).write(fleetDir.resolve("effective-aam.config.xml").toString());
        Scenario s=RunLosAngelesScenario.prepareScenario(c);
        s.getPopulation().getFactory().getRouteFactories().setRouteFactory(DrtRoute.class,new DrtRouteFactory());
        Network road=NetworkUtils.createNetwork();
        new TransportModeNetworkFilter(s.getNetwork()).filter(road,Collections.singleton("car"));
        new NetworkCleaner().run(road);
        List<AamMultimodalRoutingModule.Vertiport> ports=addAirNetwork(s.getNetwork(),road);
        writeFleets(ports,fleetDir);
        // All sample agents retained. --test-persons is an explicit smoke-test-only switch.
        if(args.length>2 && args[2].startsWith("--test-persons=")) {
            int n=Integer.parseInt(args[2].substring(15));int k=0;
            Iterator<? extends Person> it=s.getPopulation().getPersons().values().iterator();
            while(it.hasNext()){it.next();if(k++>=n)it.remove();}
        }
        Controler controler=RunLosAngelesScenario.prepareControler(s);
        // The standard MultiModeDrtModule conflicts with SwissRailRaptor over
        // MainModeIdentifier in MATSim 13. This equivalent installs each DRT
        // service while retaining Raptor's single global identifier binding.
        controler.addOverridingModule(new AamMultiModeDrtModule());
        controler.addOverridingModule(new DvrpModule());
        controler.configureQSimComponents(DvrpQSimComponents.activateAllModes(modes));
        AamFleetMetrics metrics=new AamFleetMetrics(s,AIRCRAFT);
        controler.addOverridingModule(new AbstractModule(){@Override public void install(){
            bind(AamMultimodalRoutingModule.PortSet.class).toInstance(new AamMultimodalRoutingModule.PortSet(ports));
            addRoutingModuleBinding(AAM).toProvider(AamMultimodalRoutingModule.Factory.class);
            // Keep SwissRailRaptor's MainModeIdentifier and the LA analysis binding.
            // The LA analysis identifier is AAM-aware in this overlay; rebinding either
            // key here conflicts with modules already installed by prepareControler().
            addPlanStrategyBinding("AamInnovation").toProvider(AamStrategyProvider.class);
            addEventHandlerBinding().toInstance(metrics);addControlerListenerBinding().toInstance(metrics);
        }});
        controler.run();
    }
    static void configure(Config c,MultiModeDrtConfigGroup modes,DvrpConfigGroup dvrp,String out){
        AamConfigGroup aam=ConfigUtils.addOrGetModule(c,AamConfigGroup.class);
        if(!modes.getModalElements().isEmpty())throw new IllegalArgumentException("This runner generates multiModeDrt from the aam module; remove duplicate multiModeDrt input settings.");
        c.global().setRandomSeed(SEED);
        // Keep the LA configuration's routing and QSim thread counts.
        // Preserve the LA baseline's FastAStarLandmarks road routing. With
        // regional ground DRT removed, the slower FastDijkstra workaround is
        // unnecessary for ordinary LA trip preparation and replanning.
        c.qsim().setSimStarttimeInterpretation(StarttimeInterpretation.onlyUseStarttime);
        c.qsim().setSimEndtimeInterpretation(EndtimeInterpretation.onlyUseEndtime);
        c.qsim().setRemoveStuckVehicles(false);
        c.parallelEventHandling().setSynchronizeOnSimSteps(true);
        // Keep the input configuration's iteration range.
        c.controler().setWriteEventsInterval(1);c.controler().setWritePlansInterval(1);
        c.controler().setOutputDirectory(out);c.controler().setRunId("la-aam-fare30");
        c.controler().setOverwriteFileSetting(OutputDirectoryHierarchy.OverwriteFileSetting.failIfDirectoryExists);
        c.planCalcScore().setWriteExperiencedPlans(true);
        addMode(c,AIR,-6,0);addMode(c,AAM,0,0);
        c.planCalcScore().addActivityParams(new ActivityParams("aam interaction").setTypicalDuration(1).setScoringThisActivityAtAll(false));
        // Keep the normal LA ride and ride_taxi alternatives unchanged.
        // Offer new alternatives in the first replanning round. Final round tests score-based retention.
        for(StrategySettings st:c.strategy().getStrategySettings())
            if(!st.getStrategyName().equals("ChangeExpBeta"))st.setDisableAfter(1);
        c.strategy().setFractionOfIterationsToDisableInnovation(1.0);
        StrategySettings st=new StrategySettings();st.setStrategyName("AamInnovation");st.setSubpopulation("person");
        st.setWeight(0.10);st.setDisableAfter(1);
        boolean hasAam=false;for(StrategySettings existing:c.strategy().getStrategySettings())if(existing.getStrategyName().equals("AamInnovation"))hasAam=true;
        if(!hasAam)c.strategy().addStrategySettings(st);
        // MATSim 13's hard insertion bound rejects even an origin-stationed
        // aircraft on long LA flight links with a 300 s detour allowance.
        // Keep the 900 s pickup limit; permit 1800 s insertion slack and
        // measure actual in-vehicle time in the event-based output.
        addDrt(modes,AIR,120,1.2,1800,aam.getBaseFare(),aam.getFarePerMile()/MILE);
        for(DrtConfigGroup mode:modes.getModalElements())if(mode.getMode().equals(AIR))mode.setMaxWaitTime(aam.getMaxWaitTime());
        // The DVRP matrix and vehicle router need only the 10-vertiport air
        // graph. Do not build insertion estimates over the regional road graph.
        dvrp.setNetworkModes(com.google.common.collect.ImmutableSet.of(AIR));
        dvrp.getTravelTimeMatrixParams().setCellSize(aam.getDrtMatrixCellSize());
        DrtConfigs.adjustMultiModeDrtConfig(modes,c.planCalcScore(),c.plansCalcRoute());
    }
    private static void addMode(Config c,String m,double t,double constant){
        if(c.planCalcScore().getModes().containsKey(m))return;
        c.planCalcScore().addModeParams(new ModeParams(m).setMarginalUtilityOfTraveling(t).setConstant(constant)
                .setMarginalUtilityOfDistance(0).setMonetaryDistanceRate(0));
    }
    private static void addDrt(MultiModeDrtConfigGroup multi,String mode,double stop,double alpha,double beta,double base,double rate){
        DrtConfigGroup d=new DrtConfigGroup();d.setMode(mode);d.setUseModeFilteredSubnetwork(true);
        d.setOperationalScheme(DrtConfigGroup.OperationalScheme.door2door);d.setMaxWaitTime(MAX_WAIT);
        d.setMaxTravelTimeAlpha(alpha);d.setMaxTravelTimeBeta(beta);d.setStopDuration(stop);d.setNumberOfThreads(1);
        d.setRejectRequestIfMaxWaitOrTravelTimeViolated(true);d.setChangeStartLinkToLastLinkInSchedule(false);
        d.addParameterSet(new SelectiveInsertionSearchParams());
        DrtFareParams f=new DrtFareParams();f.setBasefare(base);f.setDistanceFare_m(rate);f.setMinFarePerTrip(base);
        f.setTimeFare_h(0);f.setDailySubscriptionFee(0);d.addParameterSet(f);multi.addParameterSet(d);
    }
    public static List<AamMultimodalRoutingModule.Vertiport> addAirNetwork(Network n,Network road){
        NetworkFactory f=n.getFactory();List<AamMultimodalRoutingModule.Vertiport> v=new ArrayList<>();List<Node> nodes=new ArrayList<>();
        for(int i=0;i<COORDS.length;i++){
            String id=String.format(Locale.ROOT,"VP%02d",i+1);Coord coord=new Coord(COORDS[i][0],COORDS[i][1]);
            Node node=f.createNode(Id.createNodeId("aam_node_"+id),coord);n.addNode(node);nodes.add(node);
            Link loop=f.createLink(Id.createLinkId("aam_loop_"+id),node,node);configureAirLink(loop,1);n.addLink(loop);
            Link ground=NetworkUtils.getNearestLinkExactly(road,coord);
            v.add(new AamMultimodalRoutingModule.Vertiport(id,coord,loop.getId(),ground.getId()));
        }
        for(int i=0;i<v.size();i++)for(int j=0;j<v.size();j++)if(i!=j){
            Link l=f.createLink(Id.createLinkId("aam_air_"+v.get(i).id+"_"+v.get(j).id),nodes.get(i),nodes.get(j));
            configureAirLink(l,AamMultimodalRoutingModule.distance(v.get(i).coord,v.get(j).coord));n.addLink(l);
        }
        return v;
    }
    private static void configureAirLink(Link l,double length){l.setLength(length);l.setFreespeed(AIR_SPEED);
        l.setCapacity(100000);l.setNumberOfLanes(10);l.setAllowedModes(Collections.singleton(AIR));}
    private static void writeFleets(List<AamMultimodalRoutingModule.Vertiport> v,Path dir)throws IOException{
        try(PrintWriter w=new PrintWriter(Files.newBufferedWriter(dir.resolve(AIR+"-fleet.xml")))){
            w.println("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE vehicles SYSTEM \"http://matsim.org/files/dtd/dvrp_vehicles_v1.dtd\">\n<vehicles>");
            for(int i=0;i<AIRCRAFT;i++){
                String link=v.get(i%v.size()).airLink.toString();
                w.printf(Locale.ROOT,"  <vehicle id=\"%s_%04d\" start_link=\"%s\" t_0=\"0\" t_1=\"129600\" capacity=\"4\"/>%n",AIR,i,link);
            }
            w.println("</vehicles>");
        }
        try(PrintWriter w=new PrintWriter(Files.newBufferedWriter(dir.resolve("vertiports.csv")))){
            w.println("vertiport,x_epsg3310,y_epsg3310,air_link,road_link");
            for(AamMultimodalRoutingModule.Vertiport vp:v)w.printf(Locale.ROOT,"%s,%.6f,%.6f,%s,%s%n",vp.id,vp.coord.getX(),vp.coord.getY(),vp.airLink,vp.roadLink);
        }
    }
    public static final class AamStrategyProvider implements Provider<PlanStrategy>{
        @Inject Scenario s;@Inject Provider<TripRouter> router;@Inject AamMultimodalRoutingModule.PortSet ports;
        public PlanStrategy get(){PlanStrategyImpl.Builder b=new PlanStrategyImpl.Builder(new RandomPlanSelector<>());
            b.addStrategyModule(new AamPlanStrategyModule(s,ports.ports,SEED));b.addStrategyModule(new ReRoute(s,router));return b.build();}
    }
}
