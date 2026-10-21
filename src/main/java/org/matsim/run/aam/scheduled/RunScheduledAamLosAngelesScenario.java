package org.matsim.run.aam.scheduled;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.LinkedHashMap;
import java.util.Iterator;
import java.util.Map;

import javax.inject.Inject;
import javax.inject.Named;
import javax.inject.Provider;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.ConfigWriter;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.replanning.PlanStrategy;
import org.matsim.core.replanning.PlanStrategyImpl;
import org.matsim.core.replanning.selectors.RandomPlanSelector;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.router.RoutingModule;
import org.matsim.run.RunLosAngelesScenario;

/** Runs Los Angeles with AAM represented as ordinary scheduled public transit. */
public final class RunScheduledAamLosAngelesScenario {
    private static final Logger LOG = Logger.getLogger(RunScheduledAamLosAngelesScenario.class);

    private RunScheduledAamLosAngelesScenario() {
    }

    public static void main(String[] args) throws IOException {
        String configFile = args.length > 0 ? args[0] : "scenarios/aam-scheduled/la-aam-scheduled.config.xml";
        String output = args.length > 1 ? args[1] : "run-output/aam-scheduled";
        Map<String, String> options = parseOptions(args, 2);

        Config config = RunLosAngelesScenario.prepareConfig(
                new String[] { configFile }, new ScheduledAamConfigGroup());
        ScheduledAamConfigGroup aamConfig = ConfigUtils.addOrGetModule(config, ScheduledAamConfigGroup.class);
        if (options.containsKey("plans")) {
            config.plans().setInputFile(Paths.get(options.get("plans")).toAbsolutePath().toString());
        }
        if (options.containsKey("vertiports")) {
            aamConfig.setVertiportsFile(Paths.get(options.get("vertiports")).toAbsolutePath().toString());
        }
        if (options.containsKey("first-iteration")) {
            config.controler().setFirstIteration(Integer.parseInt(options.get("first-iteration")));
        }
        if (options.containsKey("last-iteration")) {
            config.controler().setLastIteration(Integer.parseInt(options.get("last-iteration")));
        }
        if (options.containsKey("innovation-fraction")) {
            config.strategy().setFractionOfIterationsToDisableInnovation(
                    Double.parseDouble(options.get("innovation-fraction")));
        }
        if (options.containsKey("disable-innovation")) {
            aamConfig.setInnovationEnabled(false);
            for (StrategySettings strategy : config.strategy().getStrategySettings()) {
                if (!"ChangeExpBeta".equals(strategy.getStrategyName())) {
                    strategy.setWeight(0);
                }
            }
        }
        config.controler().setOutputDirectory(output);
        // Configure before snapshotting or constructing scoring parameters.
        if(!config.planCalcScore().getModes().containsKey(ScheduledAamRoutingModule.MODE))
            config.planCalcScore().addModeParams(new org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ModeParams(ScheduledAamRoutingModule.MODE));
        config.planCalcScore().getModes().get(ScheduledAamRoutingModule.MODE).setDailyMonetaryConstant(0).setMonetaryDistanceRate(0);
        config.controler().setRunId(options.getOrDefault("run-id", "la-aam-scheduled"));
        config.controler().setOverwriteFileSetting(OutputDirectoryHierarchy.OverwriteFileSetting.failIfDirectoryExists);
        // Preserve the last plan of each routing type so the guaranteed
        // scheduled-AAM choice cannot be removed solely for scoring poorly.
        config.strategy().setPlanSelectorForRemoval("WorstPlanSelector");

        Path inputSnapshot = Paths.get(output + "-inputs").toAbsolutePath();
        if(Files.exists(Paths.get(output))||Files.exists(inputSnapshot))throw new java.nio.file.FileAlreadyExistsException("Preserving existing output or input snapshot: "+output);
        Files.createDirectories(inputSnapshot.getParent());Files.createDirectory(inputSnapshot);
        new ConfigWriter(config).write(inputSnapshot.resolve("effective-scheduled-aam.config.xml").toString());
        Path layout = resolveFromConfig(configFile, aamConfig.getVertiportsFile());
        Files.copy(layout, inputSnapshot.resolve("frozen-vertiports.csv"), StandardCopyOption.REPLACE_EXISTING);

        Scenario scenario = RunLosAngelesScenario.prepareScenario(config, true);
        ScheduledAamTransitBuilder.BuildResult result = ScheduledAamTransitBuilder.build(scenario, aamConfig);
        LOG.info(result);

        if (options.containsKey("validate-only")) {
            LOG.info("Validation-only run completed; controller was not started.");
            return;
        }

        if (options.containsKey("test-persons")) {
            retainPersons(scenario, Integer.parseInt(options.get("test-persons")));
        }

        Controler controler = RunLosAngelesScenario.prepareControler(scenario);
        // Fare events are scored with the existing person-specific money utility.
        ScheduledAamServiceState serviceState=new ScheduledAamServiceState(scenario,controler.getEvents());
        scenario.addScenarioElement("scheduledAamServiceState",serviceState);
        controler.addOverridingModule(new AbstractModule() {
            @Override
            public void install() {
                bind(org.matsim.pt.router.TransitRouter.class).toProvider(GroundOnlyRaptorFactory.class);
                bind(ch.sbb.matsim.routing.pt.raptor.SwissRailRaptor.class).toProvider(GroundOnlyRaptorFactory.class);
                addRoutingModuleBinding(ScheduledAamRoutingModule.MODE).toProvider(ScheduledAamRoutingModule.Factory.class);
                addPlanStrategyBinding("ScheduledAamInnovation").toProvider(ScheduledAamStrategyProvider.class);
                addControlerListenerBinding().to(ScheduledAamAlternativeGuarantee.class);
                addControlerListenerBinding().to(ScheduledAamQueueReplanner.class);
                addControlerListenerBinding().to(org.matsim.run.aam.AamSelectedPlanValidator.class);
                addControlerListenerBinding().toInstance(org.matsim.run.aam.AamFeederDiagnostics.get(scenario));
                addEventHandlerBinding().toInstance(serviceState);
                addControlerListenerBinding().toInstance(serviceState);
            }
        });
        controler.addOverridingQSimModule(new org.matsim.core.mobsim.qsim.AbstractQSimModule(){
            @Override protected void configureQSim(){
                bind(org.matsim.core.mobsim.qsim.pt.TransitQSimEngine.class)
                    .to(ScheduledAamTransitEngine.class).in(javax.inject.Singleton.class);
            }
        });
        controler.run();
    }

    static Map<String, String> parseOptions(String[] args, int start) {
        Map<String, String> result = new LinkedHashMap<>();
        for (int index = start; index < args.length; index++) {
            String argument = args[index];
            if (!argument.startsWith("--")) {
                throw new IllegalArgumentException("Unknown positional argument: " + argument);
            }
            int equals = argument.indexOf('=');
            if (equals < 0) {
                result.put(argument.substring(2), "true");
            } else {
                result.put(argument.substring(2, equals), argument.substring(equals + 1));
            }
        }
        return result;
    }

    private static Path resolveFromConfig(String configFile, String configured) {
        Path path = Paths.get(configured);
        if (path.isAbsolute()) {
            return path.normalize();
        }
        return Paths.get(configFile).toAbsolutePath().normalize().getParent().resolve(path).normalize();
    }

    private static void retainPersons(Scenario scenario, int maximum) {
        int retained = 0;
        Iterator<? extends Person> iterator = scenario.getPopulation().getPersons().values().iterator();
        while (iterator.hasNext()) {
            iterator.next();
            if (retained++ >= maximum) {
                iterator.remove();
            }
        }
    }

    public static final class ScheduledAamStrategyProvider implements Provider<PlanStrategy> {
        @Inject
        Scenario scenario;
        @Inject @Named("car") Provider<RoutingModule> car;
        @Inject @Named("ride") Provider<RoutingModule> ride;
        @Inject @Named("ride_taxi") Provider<RoutingModule> taxi;
        @Inject @Named("walk") Provider<RoutingModule> walk;
        @Inject @Named("bike") Provider<RoutingModule> bike;

        @Override
        public PlanStrategy get() {
            PlanStrategyImpl.Builder builder = new PlanStrategyImpl.Builder(new RandomPlanSelector<>());
            builder.addStrategyModule(new ScheduledAamPlanStrategyModule(scenario,
                    ScheduledAamPlanStrategyModule.routers(scenario, car, ride, taxi, walk, bike)));
            return builder.build();
        }
    }
}
