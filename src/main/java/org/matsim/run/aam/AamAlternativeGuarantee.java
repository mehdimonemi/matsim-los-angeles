package org.matsim.run.aam;

import java.util.*;
import javax.inject.Inject;
import javax.inject.Provider;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.*;
import org.matsim.contrib.drt.run.DrtConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.listener.StartupListener;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.algorithms.ParallelPersonAlgorithmUtils;
import org.matsim.core.router.PlanRouter;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.router.TripStructureUtils.Trip;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleUtils;

/** Seeds one honest, routed AAM choice for every eligible person. */
public final class AamAlternativeGuarantee implements StartupListener {
    private static final Logger LOG=Logger.getLogger(AamAlternativeGuarantee.class);
    private final Scenario scenario;private final List<AamMultimodalRoutingModule.Vertiport> ports;
    private final Provider<TripRouter> routers;
    @Inject public AamAlternativeGuarantee(Scenario scenario,AamMultimodalRoutingModule.PortSet ports,Provider<TripRouter> routers){
        this.scenario=scenario;this.ports=ports.ports;this.routers=routers;
    }
    @Override public void notifyStartup(StartupEvent event){
        // PrepareForSim normally creates these mappings later in controller
        // startup. Staged restarts must reroute protected car/bike AAM plans
        // before then, so reconstruct the same deterministic IDs here.
        ensureVehicleIds(scenario);
        AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class);
        boolean seedAtStartup=cfg.getSeedAlternativesAtStartup();
        boolean hadLegacyDrt=scenario.getConfig().getModules().containsKey(DrtConfigGroup.GROUP_NAME);
        java.util.concurrent.atomic.AtomicInteger rejected=new java.util.concurrent.atomic.AtomicInteger();
        java.util.concurrent.atomic.AtomicInteger restoredGround=new java.util.concurrent.atomic.AtomicInteger();
        List<Plan> added=Collections.synchronizedList(new ArrayList<>());
        int threads=Math.max(1,Math.min(2,scenario.getConfig().global().getNumberOfThreads()));
        // Repair originally unrouted ground plans and seed each person in the
        // same bounded worker. This replaces the serial ~70k-leg routing pass
        // and avoids building a throwaway startup TripRouter.
        ParallelPersonAlgorithmUtils.run(scenario.getPopulation(),threads,()->{
            TripRouter router=routers.get();removeStartupAddedLegacyDrt(scenario.getConfig(),hadLegacyDrt);
            AamPlanStrategyModule innovation=new AamPlanStrategyModule(scenario,ports,RunDynamicAamLosAngelesScenario.SEED,()->router.getRoutingModule("aam"),()->router);
            return person->{
                if(seedAtStartup&&"person".equals(person.getAttributes().getAttribute("subpopulation"))&&person.getSelectedPlan()!=null)
                    AamCandidateScreen.get(scenario).screen(person.getSelectedPlan(),ports);
                if(AamFeederPolicy.ensureGroundAlternative(scenario,person,router))restoredGround.incrementAndGet();
                // Saved layout-invalidated routes are intent, not executable choices.
                // Normalize them and let the same bounded, ranked pipeline rebuild coverage.
                for(Plan plan:new ArrayList<>(person.getPlans())){
                    if(needsAamRouting(plan)&&!Boolean.TRUE.equals(plan.getAttributes().getAttribute("aam_private_route_infeasible"))){
                        Plan selected=person.getSelectedPlan();person.setSelectedPlan(plan);
                        try{new PlanRouter(router).run(plan);plan.setScore(null);}
                        finally{person.setSelectedPlan(selected);}
                    }
                    if(hasStaleAirLinks(plan)||Boolean.TRUE.equals(plan.getAttributes().getAttribute("aam_private_route_infeasible"))){
                        AamCandidateScreen.get(scenario).screen(plan,ports);
                        AamFeederPolicy.invalidateAam(plan);rejected.incrementAndGet();
                    }else AamFeederPolicy.normalizeGround(plan);
                    AamFeederPolicy.routeConvertedGroundTrips(scenario,plan,router);
                    if(AamFeederPolicy.hasGenuineAam(plan))plan.setType("aam");
                }
                if(seedAtStartup)seedAlternatives(person,router,innovation,added);
            };
        });
        LOG.info("Restored passenger-ground outside options for "+restoredGround.get()+" old AAM-only checkpoints; original private-car/bike plans cannot be reconstructed from these checkpoints.");
        int rejectedCount=rejected.get();
        int initiallySelected=seedAtStartup?selectInitialExploration():0;
        try{
            java.nio.file.Path directory=java.nio.file.Paths.get(scenario.getConfig().controler().getOutputDirectory(),"aam-choice-set","layout");
            if(seedAtStartup){
                AamCandidateScreen.get(scenario).write(directory);
                try(java.io.PrintWriter writer=new java.io.PrintWriter(java.nio.file.Files.newBufferedWriter(directory.resolve("funnel.csv")))){
                    writer.println("metric,value");AamFleetMetrics.planFunnel(scenario).forEach((k,v)->writer.println(k+","+v));
                }
            }
            AamGroundRoutingDiagnostics.get(scenario).write(directory.resolve("ground-routing.csv"));
        }
        catch(java.io.IOException e){throw new java.io.UncheckedIOException(e);}
        LOG.info("Initial AAM exploration selected "+initiallySelected+" previously unexposed passengers; these are exploration trials, not equilibrium adoption.");
        LOG.info("Guaranteed "+added.size()+" genuine routed choices; normalized "+rejectedCount+" saved candidate plans before bounded routing.");
        if(!seedAtStartup)LOG.info("AAM startup alternative generation disabled for route preparation.");
        System.gc();
    }
    static void removeStartupAddedLegacyDrt(Config config,boolean existedBeforeRouterInitialization){
        if(!existedBeforeRouterInitialization&&config.getModules().get(DrtConfigGroup.GROUP_NAME) instanceof DrtConfigGroup)
            config.removeModule(DrtConfigGroup.GROUP_NAME);
    }
    private boolean hasStaleAirLinks(Plan plan){
        for(Leg leg:TripStructureUtils.getLegs(plan))if("aam_drt".equals(leg.getMode())&&leg.getRoute()!=null)
            if(!scenario.getNetwork().getLinks().containsKey(leg.getRoute().getStartLinkId())||!scenario.getNetwork().getLinks().containsKey(leg.getRoute().getEndLinkId()))return true;
        return false;
    }
    static void ensureVehicleIds(Scenario scenario){
        AamFeederPolicy.initializeVehicles(scenario);
    }
    List<Plan> seedAlternatives(){return seedAlternatives(routers.get());}
    int selectInitialExploration(){
        AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class);
        int selected=0;
        for(Person person:scenario.getPopulation().getPersons().values()){
            if(!"person".equals(person.getAttributes().getAttribute("subpopulation"))||Boolean.TRUE.equals(person.getAttributes().getAttribute("aam_initial_exploration_done")))continue;
            Plan air=person.getPlans().stream().filter(AamFeederPolicy::hasGenuineAam)
                .min(Comparator.comparingDouble(p->{Object gain=p.getAttributes().getAttribute("aam_predicted_generalized_gain");return gain instanceof Number?-((Number)gain).doubleValue():0;})).orElse(null);
            if(air==null)continue;
            double draw=new Random(scenario.getConfig().global().getRandomSeed() ^ person.getId().toString().hashCode()).nextDouble();
            if(draw<cfg.getInitialExplorationFraction()){
                person.setSelectedPlan(air);person.getAttributes().putAttribute("aam_initial_exploration_done",true);selected++;
            }
        }
        return selected;
    }
    List<Plan> seedAlternatives(TripRouter router){
        List<Plan> added=new ArrayList<>();AamPlanStrategyModule innovation=new AamPlanStrategyModule(scenario,ports,RunDynamicAamLosAngelesScenario.SEED,()->router.getRoutingModule("aam"),()->router);
        for(Person person:scenario.getPopulation().getPersons().values())seedAlternatives(person,router,innovation,added);
        return added;
    }
    private void seedAlternatives(Person person,TripRouter router,AamPlanStrategyModule innovation,List<Plan> added){
            AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class);
            if(!"person".equals(person.getAttributes().getAttribute("subpopulation")))return;
            Plan selectedSource=person.getSelectedPlan();if(selectedSource==null)return;
            Plan source=person.getPlans().stream().map(plan->(Plan)plan).filter(plan->!AamFeederPolicy.hasAir(plan))
                .max(Comparator.comparingDouble(plan->plan.getScore()==null?Double.NEGATIVE_INFINITY:plan.getScore())).orElse(selectedSource);
            AamCandidateScreen.get(scenario).screen(source,ports);
            long count=person.getPlans().stream().filter(AamFeederPolicy::hasGenuineAam).count();
            Set<Integer> excluded=new HashSet<>();
            for(Plan existing:person.getPlans())if(AamFeederPolicy.hasGenuineAam(existing)){
                Object indices=existing.getAttributes().getAttribute("aam_candidate_indices");
                if(indices!=null)for(String index:indices.toString().split(","))excluded.add(Integer.parseInt(index));
            }
            while(count<cfg.getProtectedAlternatives()){
            Plan candidate=scenario.getPopulation().getFactory().createPlan();PopulationUtils.copyFromTo(source,candidate);
            candidate.setScore(null);
            // Preserve the source modes. The strategy pairs private-vehicle
            // home tours and changes only movements within the affected tour.
            person.addPlan(candidate);
            // Startup only needs one feasible trip for this protected plan.
            // Let the strategy compare the bounded site choices for that trip,
            // then continue to the next distinct trip only if this one fails.
            if(innovation.addAlternative(candidate,excluded,true)){
                added.add(candidate);count++;
                if(cfg.getProtectedAlternatives()>1)candidate.setType("aam_alternative_"+count);
                for(String index:candidate.getAttributes().getAttribute("aam_candidate_indices").toString().split(","))excluded.add(Integer.parseInt(index));
            }else{person.removePlan(candidate);person.setSelectedPlan(selectedSource);break;}
            person.setSelectedPlan(selectedSource);
            }
    }
    static boolean hasAam(Person person){return person.getPlans().stream().anyMatch(AamFeederPolicy::hasGenuineAam);}
    static boolean needsAamRouting(Plan plan){for(Leg leg:TripStructureUtils.getLegs(plan))
        if((RunDynamicAamLosAngelesScenario.AAM.equals(leg.getMode())||RunDynamicAamLosAngelesScenario.AIR.equals(leg.getMode())||RunDynamicAamLosAngelesScenario.AAM.equals(TripStructureUtils.getRoutingMode(leg)))&&leg.getRoute()==null)return true;return false;}
}
