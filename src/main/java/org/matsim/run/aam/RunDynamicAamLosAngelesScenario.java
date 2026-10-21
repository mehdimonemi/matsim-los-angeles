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
    public static final double MILE=1609.344, AIR_SPEED=98*AamMissionProfile.KNOTS_TO_METERS_PER_SECOND, MAX_WAIT=900;
    public static final double AAM_BASE_FARE=0, AAM_PER_MILE=2;
    public static final int AIRCRAFT=100;
    public static final double[][] COORDS={
        {282086.6791630887,-470927.31895150105},{156867.80930025305,-424575.10532179195},
        {239164.36206755522,-474067.19596208027},{115286.23341467915,-415969.8192713326},
        {267147.03224965854,-500499.6440343107},{345023.37350177165,-470242.05700257095},
        {214624.56523925607,-428803.77498400025},{193025.76511600026,-464824.05341277504},
        {172937.29294743025,-456860.64624100365},{282456.85131945845,-470270.778965645}};
    public static void main(String[] args) throws Exception {
        String configFile=args.length>0?args[0]:"scenarios/aam/la-aam-fare30-it2.config.xml";
        String out=args.length>1?args[1]:"run-output/aam-fare0-it2";
        Map<String,String> options=parseOptions(args,2);
        MultiModeDrtConfigGroup modes=new MultiModeDrtConfigGroup();
        DvrpConfigGroup dvrp=new DvrpConfigGroup();
        Config c=RunLosAngelesScenario.prepareConfig(new String[]{configFile},modes,dvrp,new AamConfigGroup());
        AamConfigGroup aamConfig=ConfigUtils.addOrGetModule(c,AamConfigGroup.class);
        if(options.containsKey("plans"))c.plans().setInputFile(Paths.get(options.get("plans")).toAbsolutePath().toString());
        if(options.containsKey("first-iteration"))c.controler().setFirstIteration(Integer.parseInt(options.get("first-iteration")));
        if(options.containsKey("last-iteration"))c.controler().setLastIteration(Integer.parseInt(options.get("last-iteration")));
        if(options.containsKey("vertiports"))aamConfig.setActiveVertiportsFile(Paths.get(options.get("vertiports")).toAbsolutePath().toString());
        if(options.containsKey("base-fare"))aamConfig.setBaseFare(Double.parseDouble(options.get("base-fare")));
        if(options.containsKey("fare-per-mile"))aamConfig.setFarePerMile(Double.parseDouble(options.get("fare-per-mile")));
        if(options.containsKey("candidate-vertiports"))aamConfig.setCandidateVertiports(Integer.parseInt(options.get("candidate-vertiports")));
        if(options.containsKey("service-start-time"))aamConfig.setServiceStartTime(Double.parseDouble(options.get("service-start-time")));
        if(options.containsKey("service-end-time"))aamConfig.setServiceEndTime(Double.parseDouble(options.get("service-end-time")));
        if(options.containsKey("innovation-fraction"))c.strategy().setFractionOfIterationsToDisableInnovation(Double.parseDouble(options.get("innovation-fraction")));
        if(options.containsKey("minimum-convergence"))aamConfig.setMinimumInnovationFreeFraction(Double.parseDouble(options.get("minimum-convergence")));
        configure(c,modes,dvrp,out);
        if(options.containsKey("run-id"))c.controler().setRunId(options.get("run-id"));
        if(options.containsKey("disable-innovation"))for(StrategySettings strategy:c.strategy().getStrategySettings())
            if(!"ChangeExpBeta".equals(strategy.getStrategyName()))strategy.setWeight(0);
        Path frozenLayout=resolveFromConfig(configFile,aamConfig.getActiveVertiportsFile());
        List<VertiportLocation> locations=readVertiportLocations(frozenLayout,aamConfig.getActiveVertiportCount());
        // Keep generated fleet inputs outside the controller's output cleanup.
        Path fleetDir=Paths.get(out+"-inputs").toAbsolutePath();
        if(Files.exists(Paths.get(out))||Files.exists(fleetDir))throw new FileAlreadyExistsException("Preserving existing output or input snapshot: "+out);
        Files.createDirectories(fleetDir.getParent());Files.createDirectory(fleetDir);
        for(DrtConfigGroup d:modes.getModalElements())
            d.setVehiclesFile(fleetDir.resolve(d.getMode()+"-fleet.xml").toUri().toString());
        new ConfigWriter(c).write(fleetDir.resolve("effective-aam.config.xml").toString());
        Files.copy(frozenLayout,fleetDir.resolve("frozen-vertiports.csv"),StandardCopyOption.REPLACE_EXISTING);
        // Register the DRT route factory before the population is read. The
        // standard helper loads the scenario first, which turns serialized
        // `type="drt"` AAM routes into GenericRouteImpl; the passenger engine
        // later casts those routes to DrtRoute when an AAM plan is selected.
        Scenario s=ScenarioUtils.createScenario(c);
        s.getPopulation().getFactory().getRouteFactories().setRouteFactory(DrtRoute.class,new DrtRouteFactory());
        ScenarioUtils.loadScenario(s);
        s.getPopulation().getFactory().getRouteFactories().setRouteFactory(DrtRoute.class,new DrtRouteFactory());
        Network road=NetworkUtils.createNetwork();
        new TransportModeNetworkFilter(s.getNetwork()).filter(road,Collections.singleton("car"));
        new NetworkCleaner().run(road);
        List<AamMultimodalRoutingModule.Vertiport> ports=addAirNetwork(s.getNetwork(),road,locations);
        s.addScenarioElement("aamActivePorts",new AamMultimodalRoutingModule.PortSet(ports));
        writeFleets(ports,fleetDir,aamConfig.getServiceStartTime(),aamConfig.getServiceEndTime());
        // All sample agents retained. --test-persons is an explicit smoke-test-only switch.
        if(options.containsKey("test-persons")) {
            int n=Integer.parseInt(options.get("test-persons"));int k=0;
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
        AamWaitTimeEstimator waits=new AamWaitTimeEstimator(aamConfig.getWaitTimeBin());
        if(options.containsKey("wait-priors"))waits.read(Paths.get(options.get("wait-priors")));
        controler.addOverridingModule(new AbstractModule(){@Override public void install(){
            bind(AamMultimodalRoutingModule.PortSet.class).toInstance(new AamMultimodalRoutingModule.PortSet(ports));
            bind(AamWaitTimeEstimator.class).toInstance(waits);
            addRoutingModuleBinding(AAM).toProvider(AamMultimodalRoutingModule.Factory.class);
            // Keep SwissRailRaptor's MainModeIdentifier and the LA analysis binding.
            // The LA analysis identifier is AAM-aware in this overlay; rebinding either
            // key here conflicts with modules already installed by prepareControler().
            addPlanStrategyBinding("AamInnovation").toProvider(AamStrategyProvider.class);
            bindPlanSelectorForRemoval().to(AamPlanRemovalSelector.class);
            addControlerListenerBinding().to(AamAlternativeGuarantee.class);
            addControlerListenerBinding().to(AamSelectedPlanValidator.class);
            addControlerListenerBinding().toInstance(AamFeederDiagnostics.get(s));
            addEventHandlerBinding().toInstance(waits);addEventHandlerBinding().toInstance(metrics);addControlerListenerBinding().toInstance(metrics);
        }});
        controler.run();
        waits.write(fleetDir.resolve("wait-priors.csv"));
    }
    static Map<String,String> parseOptions(String[] args,int start){Map<String,String> result=new LinkedHashMap<>();for(int i=start;i<args.length;i++){
        String arg=args[i];if(!arg.startsWith("--"))throw new IllegalArgumentException("Unknown positional argument: "+arg);
        int equals=arg.indexOf('=');if(equals<0)result.put(arg.substring(2),"true");else result.put(arg.substring(2,equals),arg.substring(equals+1));
    }return result;}
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
        // Honor the output intervals in the run config. Full-population
        // production runs must be able to write these large files sparsely.
        c.controler().setOutputDirectory(out);c.controler().setRunId("la-aam-fare0");
        c.controler().setOverwriteFileSetting(OutputDirectoryHierarchy.OverwriteFileSetting.failIfDirectoryExists);
        c.planCalcScore().setWriteExperiencedPlans(true);
        // AAM alternatives have their own plan type. This selector preserves
        // the final plan of each type, so the guaranteed AAM choice survives.
        c.strategy().setPlanSelectorForRemoval("WorstPlanSelector");
        // Reserve the tail of every production run for fixed-choice convergence.
        // A lower configured innovation fraction is preserved; a higher one is capped.
        int first=c.controler().getFirstIteration(),last=c.controler().getLastIteration();
        int total=last-first+1;
        int reserved=(int)Math.ceil(total*aam.getMinimumInnovationFreeFraction());
        int latestDisableAfter=last-reserved;
        double latestInnovationFraction=last==first?0:Math.max(0,(latestDisableAfter-first)/(double)(last-first));
        if(c.strategy().getFractionOfIterationsToDisableInnovation()>latestInnovationFraction)
            c.strategy().setFractionOfIterationsToDisableInnovation(latestInnovationFraction);
        addMode(c,AIR,-6,0);addMode(c,AAM,0,0);
        c.planCalcScore().addActivityParams(new ActivityParams("aam interaction").setTypicalDuration(1).setScoringThisActivityAtAll(false));
        // Keep ordinary and AAM innovation active for the configured innovation fraction.
        StrategySettings st=new StrategySettings();st.setStrategyName("AamInnovation");st.setSubpopulation("person");
        st.setWeight(0.10);
        boolean hasAam=false;for(StrategySettings existing:c.strategy().getStrategySettings())if(existing.getStrategyName().equals("AamInnovation"))hasAam=true;
        if(!hasAam)c.strategy().addStrategySettings(st);
        // MATSim 13's hard insertion bound rejects even an origin-stationed
        // aircraft on long LA flight links with a 300 s detour allowance.
        // Keep the 900 s pickup limit; permit 1800 s insertion slack and
        // measure actual in-vehicle time in the event-based output.
        addDrt(modes,AIR,120,1.2,1800,aam.getBaseFare(),aam.getFarePerMile()/MILE);
        for(DrtConfigGroup mode:modes.getModalElements())if(mode.getMode().equals(AIR)){
            mode.setMaxWaitTime(aam.getMaxWaitTime());
            for(org.matsim.core.config.ConfigGroup params:mode.getParameterSets(SelectiveInsertionSearchParams.SET_NAME))
                ((SelectiveInsertionSearchParams)params).setRestrictiveBeelineSpeedFactor(aam.getInsertionEstimateSpeedFactor());
        }
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
        List<VertiportLocation> locations=new ArrayList<>();
        for(int i=0;i<COORDS.length;i++)locations.add(new VertiportLocation(String.format(Locale.ROOT,"VP%02d",i+1),COORDS[i][0],COORDS[i][1]));
        return addAirNetwork(n,road,locations);
    }
    public static List<AamMultimodalRoutingModule.Vertiport> addAirNetwork(Network n,Network road,List<VertiportLocation> locations){
        NetworkFactory f=n.getFactory();List<AamMultimodalRoutingModule.Vertiport> v=new ArrayList<>();List<Node> nodes=new ArrayList<>();
        for(VertiportLocation location:locations){
            String id=location.id;Coord coord=new Coord(location.x,location.y);
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
    static Path resolveFromConfig(String configFile,String configured){
        Path p=Paths.get(configured);if(p.isAbsolute())return p.normalize();
        Path config=Paths.get(configFile).toAbsolutePath().normalize();
        return config.getParent().resolve(p).normalize();
    }
    public static List<VertiportLocation> readVertiportLocations(Path csv,int expected)throws IOException{
        if(!Files.isRegularFile(csv))throw new FileNotFoundException("Frozen vertiport layout not found: "+csv+". Run the external location optimizer first.");
        List<String> lines=Files.readAllLines(csv);List<VertiportLocation> result=new ArrayList<>();Set<String> ids=new HashSet<>();
        for(int lineNo=0;lineNo<lines.size();lineNo++){
            String line=lines.get(lineNo).trim();if(line.isEmpty()||line.startsWith("#")||lineNo==0&&line.toLowerCase(Locale.ROOT).startsWith("id,"))continue;
            String[] f=line.split(",");if(f.length<4)throw new IOException("Invalid frozen vertiport CSV line "+(lineNo+1)+": "+line);
            String id=f[0].trim();double x,y;try{x=Double.parseDouble(f[2].trim());y=Double.parseDouble(f[3].trim());}catch(NumberFormatException e){throw new IOException("Invalid coordinates on frozen vertiport CSV line "+(lineNo+1),e);}
            if(id.isEmpty()||!ids.add(id))throw new IOException("Blank or duplicate vertiport id on line "+(lineNo+1)+": "+id);
            if(!Double.isFinite(x)||!Double.isFinite(y))throw new IOException("Non-finite vertiport coordinate on line "+(lineNo+1));
            result.add(new VertiportLocation(id,x,y));
        }
        if(result.size()!=expected)throw new IOException("Frozen vertiport layout must contain exactly "+expected+" sites, found "+result.size()+" in "+csv);
        return result;
    }
    public static final class VertiportLocation{
        public final String id;public final double x,y;
        VertiportLocation(String id,double x,double y){this.id=id;this.x=x;this.y=y;}
    }
    private static void configureAirLink(Link l,double length){l.setLength(length);l.setFreespeed(AIR_SPEED);
        l.setCapacity(100000);l.setNumberOfLanes(10);l.setAllowedModes(Collections.singleton(AIR));}
    private static void writeFleets(List<AamMultimodalRoutingModule.Vertiport> v,Path dir,double serviceStart,double serviceEnd)throws IOException{
        try(PrintWriter w=new PrintWriter(Files.newBufferedWriter(dir.resolve(AIR+"-fleet.xml")))){
            w.println("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE vehicles SYSTEM \"http://matsim.org/files/dtd/dvrp_vehicles_v1.dtd\">\n<vehicles>");
            for(int i=0;i<AIRCRAFT;i++){
                String link=v.get(i%v.size()).airLink.toString();
                w.printf(Locale.ROOT,"  <vehicle id=\"%s_%04d\" start_link=\"%s\" t_0=\"%.0f\" t_1=\"%.0f\" capacity=\"4\"/>%n",AIR,i,link,serviceStart,serviceEnd);
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
            b.addStrategyModule(new AamPlanStrategyModule(s,ports.ports,SEED,()->router.get().getRoutingModule(AAM),router));
            // Only normalize stale markers here; the AAM module routes the
            // exact ground trips it converted, avoiding a whole-plan scan.
            b.addStrategyModule(new org.matsim.api.core.v01.replanning.PlanStrategyModule(){
                public void prepareReplanning(org.matsim.core.replanning.ReplanningContext context){}
                public void handlePlan(Plan plan){AamFeederPolicy.normalizeGround(plan);}
                public void finishReplanning(){}
            });return b.build();}
    }
}
