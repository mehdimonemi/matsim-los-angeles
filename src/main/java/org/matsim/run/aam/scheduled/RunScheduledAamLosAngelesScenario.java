package org.matsim.run.aam.scheduled;

import java.io.IOException;
import java.util.Iterator;

import javax.inject.Inject;
import javax.inject.Provider;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.replanning.PlanStrategy;
import org.matsim.core.replanning.PlanStrategyImpl;
import org.matsim.core.replanning.selectors.RandomPlanSelector;
import org.matsim.core.replanning.modules.ReRoute;
import org.matsim.core.router.TripRouter;
import org.matsim.run.RunLosAngelesScenario;

/** Runs Los Angeles with AAM represented as ordinary scheduled public transit. */
public final class RunScheduledAamLosAngelesScenario {
    private static final Logger LOG = Logger.getLogger(RunScheduledAamLosAngelesScenario.class);

    private RunScheduledAamLosAngelesScenario() {
    }

    public static void main(String[] args) throws IOException {
        String configFile = args.length > 0 ? args[0] : "scenarios/aam-scheduled/la-aam-scheduled.config.xml";
        String output = args.length > 1 ? args[1] : "run-output/aam-scheduled";

        Config config = RunLosAngelesScenario.prepareConfig(
                new String[] { configFile }, new ScheduledAamConfigGroup());
        config.controler().setOutputDirectory(output);
        config.controler().setRunId("la-aam-scheduled");
        config.controler().setOverwriteFileSetting(OutputDirectoryHierarchy.OverwriteFileSetting.failIfDirectoryExists);

        Scenario scenario = RunLosAngelesScenario.prepareScenario(config);
        ScheduledAamConfigGroup aamConfig = ConfigUtils.addOrGetModule(config, ScheduledAamConfigGroup.class);
        ScheduledAamTransitBuilder.BuildResult result = ScheduledAamTransitBuilder.build(scenario, aamConfig);
        LOG.info(result);

        if (args.length > 2 && "--validate-only".equals(args[2])) {
            LOG.info("Validation-only run completed; controller was not started.");
            return;
        }

        if (args.length > 2 && args[2].startsWith("--test-persons=")) {
            retainPersons(scenario, Integer.parseInt(args[2].substring("--test-persons=".length())));
        }

        Controler controler = RunLosAngelesScenario.prepareControler(scenario);
        controler.addOverridingModule(new AbstractModule() {
            @Override
            public void install() {
                addRoutingModuleBinding(ScheduledAamRoutingModule.MODE).toProvider(ScheduledAamRoutingModule.Factory.class);
                addPlanStrategyBinding("ScheduledAamInnovation").toProvider(ScheduledAamStrategyProvider.class);
            }
        });
        controler.run();
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

        @Inject
        Provider<TripRouter> tripRouter;

        @Override
        public PlanStrategy get() {
            PlanStrategyImpl.Builder builder = new PlanStrategyImpl.Builder(new RandomPlanSelector<>());
            builder.addStrategyModule(new ScheduledAamPlanStrategyModule(scenario));
            builder.addStrategyModule(new ReRoute(scenario, tripRouter));
            return builder.build();
        }
    }
}
