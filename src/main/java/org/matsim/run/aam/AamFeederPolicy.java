package org.matsim.run.aam;

import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.vehicles.*;

/** Shared feeder invariants. Startup routing precedes MATSim PrepareForSim. */
public final class AamFeederPolicy {
    private AamFeederPolicy() { }
    public static boolean hasGenuineAam(Plan plan){
        return plan!=null&&!Boolean.TRUE.equals(plan.getAttributes().getAttribute("aam_private_route_infeasible"))
            &&plan.getPlanElements().stream().anyMatch(e->e instanceof Leg&&"aam_drt".equals(((Leg)e).getMode()));
    }
    public static boolean hasAamMarker(Plan plan){
        return "aam".equals(plan.getType())||plan.getPlanElements().stream().anyMatch(e->e instanceof Leg&&
            ("aam".equals(((Leg)e).getMode())||"aam".equals(org.matsim.core.router.TripStructureUtils.getRoutingMode((Leg)e))));
    }
    /** Remove false classification without removing the separately stored candidate. */
    public static void normalizeGround(Plan plan){
        boolean genuine=hasGenuineAam(plan);
        boolean changed=!genuine&&hasAamMarker(plan);
        for(org.matsim.core.router.TripStructureUtils.Trip trip:new ArrayList<>(org.matsim.core.router.TripStructureUtils.getTrips(plan))){
            if(genuine&&trip.getLegsOnly().stream().anyMatch(l->"aam_drt".equals(l.getMode())))continue;
            if(!trip.getLegsOnly().stream().anyMatch(l->"aam".equals(l.getMode())||"aam".equals(org.matsim.core.router.TripStructureUtils.getRoutingMode(l)))
                &&trip.getTripElements().stream().noneMatch(e->e instanceof Activity&&((Activity)e).getType().equals("aam interaction")))continue;
            String mode=trip.getLegsOnly().stream().map(Leg::getMode).filter(m->!List.of("aam","aam_drt","walk","non_network_walk").contains(m)).findFirst().orElse("ride");
            // Collapse obsolete AAM interactions/connectors; route the normal trip afresh.
            Leg ground=org.matsim.core.population.PopulationUtils.createLeg(mode);
            org.matsim.core.router.TripStructureUtils.setRoutingMode(ground,mode);
            org.matsim.core.router.TripRouter.insertTrip(plan,trip.getOriginActivity(),List.of(ground),trip.getDestinationActivity());
            changed=true;
        }
        if(!genuine)for(String key:new ArrayList<>(plan.getAttributes().getAsMap().keySet()))if(key.startsWith("aam_")&&!key.equals("aam_ground_fallback"))plan.getAttributes().removeAttribute(key);
        if(changed){if(!genuine)plan.setType("ground");plan.setScore(null);plan.getAttributes().putAttribute("aam_ground_fallback",true);}
    }
    public static void invalidateAam(Plan plan){
        for(org.matsim.core.router.TripStructureUtils.Trip trip:new ArrayList<>(org.matsim.core.router.TripStructureUtils.getTrips(plan)))
            if(trip.getLegsOnly().stream().anyMatch(l->List.of("aam","aam_drt").contains(l.getMode())||"aam".equals(org.matsim.core.router.TripStructureUtils.getRoutingMode(l)))){
                Leg ground=org.matsim.core.population.PopulationUtils.createLeg("ride");
                org.matsim.core.router.TripStructureUtils.setRoutingMode(ground,"ride");
                org.matsim.core.router.TripRouter.insertTrip(plan,trip.getOriginActivity(),List.of(ground),trip.getDestinationActivity());
            }
        plan.setType("aam");normalizeGround(plan);
    }
    public static boolean hasAir(Plan plan){
        for(PlanElement e:plan.getPlanElements())if(e instanceof Leg){Leg l=(Leg)e;
            if(Arrays.asList("aam","aam_drt","scheduled_aam").contains(l.getMode()))return true;
            if(l.getRoute() instanceof org.matsim.pt.routes.TransitPassengerRoute){
                Id<?> line=((org.matsim.pt.routes.TransitPassengerRoute)l.getRoute()).getLineId();
                if(line!=null&&line.toString().startsWith("aam_sched_line_"))return true;
            }
        }return false;
    }
    /** Salvage old single-AAM checkpoints without inventing a private vehicle location. */
    public static int ensureGroundAlternatives(Scenario s,org.matsim.core.router.TripRouter router){
        int added=0;
        for(Person person:s.getPopulation().getPersons().values())if(ensureGroundAlternative(s,person,router))added++;
        org.apache.log4j.Logger.getLogger(AamFeederPolicy.class).info("Restored passenger-ground outside options for "+added+" old AAM-only checkpoints; original private-car/bike plans cannot be reconstructed from these checkpoints.");
        return added;
    }
    /** Restore one legacy ground outside option using the caller's person-local router. */
    public static boolean ensureGroundAlternative(Scenario s,Person person,org.matsim.core.router.TripRouter router){
        if(person.getPlans().isEmpty()||person.getPlans().stream().anyMatch(p->!hasAir(p))||person.getSelectedPlan()==null)return false;
        Plan ground=s.getPopulation().getFactory().createPlan();
        org.matsim.core.population.PopulationUtils.copyFromTo(person.getSelectedPlan(),ground);
        person.addPlan(ground);ground.setScore(null);ground.setType("aam_ground_outside_option");
        ground.getAttributes().removeAttribute("aam_park_mode");ground.getAttributes().removeAttribute("scheduled_aam_park_mode");
        for(org.matsim.core.router.TripStructureUtils.Trip trip:new ArrayList<>(org.matsim.core.router.TripStructureUtils.getTrips(ground))){
            List<? extends PlanElement> route=router.calcRoute("ride",
                org.matsim.facilities.FacilitiesUtils.toFacility(trip.getOriginActivity(),s.getActivityFacilities()),
                org.matsim.facilities.FacilitiesUtils.toFacility(trip.getDestinationActivity(),s.getActivityFacilities()),
                org.matsim.core.router.PlanRouter.calcEndOfActivity(trip.getOriginActivity(),ground,s.getConfig()),person);
            org.matsim.core.router.TripRouter.insertTrip(ground,trip.getOriginActivity(),route,trip.getDestinationActivity());
        }
        return true;
    }
    public static void routeConvertedGroundTrips(Scenario s,Plan plan,org.matsim.core.router.TripRouter router){
        for(org.matsim.core.router.TripStructureUtils.Trip trip:new ArrayList<>(org.matsim.core.router.TripStructureUtils.getTrips(plan))){
            if(trip.getLegsOnly().stream().noneMatch(l->l.getRoute()==null))continue;
            // Only whole ground trips, never replace the ride feeder of an AAM chain.
            if(trip.getLegsOnly().stream().anyMatch(l->Arrays.asList("aam","aam_drt","scheduled_aam").contains(org.matsim.core.router.TripStructureUtils.getRoutingMode(l))))continue;
            routeGroundTrip(s,plan,trip.getOriginActivity(),trip.getDestinationActivity(),router,"startup_existing_plan");
        }
    }
    /** Route one known converted trip without scanning/routing the rest of an AAM candidate. */
    public static void routeConvertedGroundTrip(Scenario s,Plan plan,Activity origin,Activity destination,
            org.matsim.core.router.TripRouter router,String context){
        for(org.matsim.core.router.TripStructureUtils.Trip trip:org.matsim.core.router.TripStructureUtils.getTrips(plan))
            if(trip.getOriginActivity()==origin&&trip.getDestinationActivity()==destination){
                if(trip.getLegsOnly().stream().noneMatch(l->l.getRoute()==null)
                    ||trip.getLegsOnly().stream().anyMatch(l->Arrays.asList("aam","aam_drt","scheduled_aam").contains(org.matsim.core.router.TripStructureUtils.getRoutingMode(l))))return;
                routeGroundTrip(s,plan,origin,destination,router,context);return;
            }
    }
    private static void routeGroundTrip(Scenario s,Plan plan,Activity origin,Activity destination,
            org.matsim.core.router.TripRouter router,String context){
        org.matsim.core.router.TripStructureUtils.Trip trip=org.matsim.core.router.TripStructureUtils.getTrips(plan).stream()
            .filter(t->t.getOriginActivity()==origin&&t.getDestinationActivity()==destination).findFirst().orElseThrow();
        String mode=trip.getLegsOnly().stream().map(Leg::getMode).filter(m->!List.of("walk","non_network_walk","transit_walk").contains(m)).findFirst().orElse("walk");
        long started=System.nanoTime();
        try{
            List<? extends PlanElement> routed=router.calcRoute(mode,
                org.matsim.facilities.FacilitiesUtils.toFacility(origin,s.getActivityFacilities()),
                org.matsim.facilities.FacilitiesUtils.toFacility(destination,s.getActivityFacilities()),
                org.matsim.core.router.PlanRouter.calcEndOfActivity(origin,plan,s.getConfig()),plan.getPerson());
            org.matsim.core.router.TripRouter.insertTrip(plan,origin,routed,destination);plan.setScore(null);
        }finally{AamGroundRoutingDiagnostics.get(s).record(context,System.nanoTime()-started);}
    }
    public static void initializeVehicles(Scenario s) {
        for (Person p : s.getPopulation().getPersons().values()) {
            Map<String,Id<Vehicle>> ids=new LinkedHashMap<>();
            if(p.getAttributes().getAttribute("vehicles")!=null)ids.putAll(VehicleUtils.getVehicleIds(p));
            Set<String> modes=new LinkedHashSet<>(List.of("car","bike","ride","ride_taxi"));
            // Startup reroutes ordinary trips before PrepareForSim creates
            // their mappings, including school-bus rides and freight.
            for(Plan plan:p.getPlans())for(PlanElement element:plan.getPlanElements())if(element instanceof Leg){
                String mode=((Leg)element).getMode();
                if(s.getConfig().plansCalcRoute().getNetworkModes().contains(mode)
                        &&!List.of("aam","aam_drt","scheduled_aam").contains(mode))modes.add(mode);
            }
            for(String mode:modes) {
                Id<Vehicle> id=ids.get(mode);
                if(id==null)id="car".equals(mode)&&s.getConfig().qsim().getUsePersonIdForMissingVehicleId()
                        ? Id.createVehicleId(p.getId()) : VehicleUtils.createVehicleId(p,mode);
                ids.put(mode,id);
                Id<VehicleType> typeId=Id.create(mode,VehicleType.class);
                VehicleType type=s.getVehicles().getVehicleTypes().get(typeId);
                if(type==null){type=VehicleUtils.createVehicleType(typeId);type.setNetworkMode(mode);s.getVehicles().addVehicleType(type);}
                if(!s.getVehicles().getVehicles().containsKey(id))s.getVehicles().addVehicle(VehicleUtils.getFactory().createVehicle(id,type));
            }
            VehicleUtils.insertVehicleIdsIntoAttributes(p,ids);
        }
    }
    /** Apply to the TOTAL walking within each feeder, including road connectors. */
    public static boolean admissible(List<? extends PlanElement> elements,double meters,double seconds) {
        double distance=0,time=0;
        for(PlanElement e:elements)if(e instanceof Leg){Leg leg=(Leg)e;
            if(List.of("walk","transit_walk","non_network_walk").contains(leg.getMode())){
                if(leg.getRoute()==null)return false;
                // VspPlansCleaner clears Leg.travelTime before QSim, but keeps
                // the routed travel time. Missing leg time is not infeasibility.
                double d=leg.getRoute().getDistance(),t=leg.getTravelTime().orElse(leg.getRoute().getTravelTime().orElse(Double.NaN));
                if(!Double.isFinite(d)||!Double.isFinite(t)||d<0||t<0)return false;
                distance+=d;time+=t;
            }
        }
        return distance<=meters+1e-6&&time<=seconds+1e-6;
    }
}
