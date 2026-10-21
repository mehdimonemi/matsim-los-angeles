package org.matsim.run.aam;
import java.util.*;
import javax.inject.Inject;
import javax.inject.Provider;
import javax.inject.Named;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.*;
import org.matsim.contrib.drt.routing.DrtRoute;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ModeParams;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.*;
import org.matsim.facilities.*;
import static org.matsim.run.aam.RunDynamicAamLosAngelesScenario.*;

/** Ground access follows base LA ride, ride_taxi, walk and bike routing. */
public final class AamMultimodalRoutingModule implements RoutingModule {
    private final Scenario s;private final List<Vertiport> ports;private final Map<String,RoutingModule> routers;private final AamWaitTimeEstimator waits;
    public AamMultimodalRoutingModule(Scenario s,List<Vertiport> ports,Map<String,RoutingModule> routers){this(s,ports,routers,new AamWaitTimeEstimator());}
    public AamMultimodalRoutingModule(Scenario s,List<Vertiport> ports,Map<String,RoutingModule> routers,AamWaitTimeEstimator waits){this.s=s;this.ports=ports;this.routers=routers;this.waits=waits;}
    public List<? extends PlanElement> calcRoute(Facility from,Facility to,double departure,Person person){
        AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(s.getConfig(),AamConfigGroup.class);
        String parked=(String)person.getSelectedPlan().getAttributes().getAttribute("aam_park_mode");
        Coord home=((Activity)person.getSelectedPlan().getPlanElements().get(0)).getCoord();
        Object hx=person.getSelectedPlan().getAttributes().getAttribute("aam_park_home_x"),hy=person.getSelectedPlan().getAttributes().getAttribute("aam_park_home_y");
        if(hx instanceof Number&&hy instanceof Number)home=new Coord(((Number)hx).doubleValue(),((Number)hy).doubleValue());
        Coord origin=from.getCoord(),destination=to.getCoord();
        // Activity coordinates define the radius, even when the road link is displaced.
        double closest=Double.POSITIVE_INFINITY;
        for(TripStructureUtils.Trip trip:TripStructureUtils.getTrips(person.getSelectedPlan())){
            if(!Objects.equals(from.getLinkId(),trip.getOriginActivity().getLinkId())||!Objects.equals(to.getLinkId(),trip.getDestinationActivity().getLinkId())||from.getLinkId()==null)continue;
            double delta=Math.abs(PlanRouter.calcEndOfActivity(trip.getOriginActivity(),person.getSelectedPlan(),s.getConfig())-departure);
            if(delta<closest){closest=delta;origin=trip.getOriginActivity().getCoord();destination=trip.getDestinationActivity().getCoord();}
        }
        if(origin==null||destination==null)return groundFallback(from,to,departure,person,parked);
        if(distance(origin,destination)<cfg.getMinimumTripDistanceMiles()*MILE)return groundFallback(from,to,departure,person,parked);
        Map<String,List<? extends PlanElement>> feederCache=new HashMap<>();
        boolean outbound=parked!=null&&home!=null&&distance(origin,home)<5;
        boolean inbound=parked!=null&&home!=null&&distance(destination,home)<5;
        // A paired car/bike tour must return to the SAME home-side parking location.
        // Eligibility already applies the access radius to the activity coordinate.
        // Do not apply it again to the routed link/facility coordinate: those can
        // differ near the boundary and would turn a valid innovation into no route.
        Object parkingId=person.getSelectedPlan().getAttributes().getAttribute("aam_park_vertiport");
        Vertiport parking=!(outbound||inbound)?null:parkingId==null?nearest(ports,home):ports.stream().filter(v->v.id.equals(parkingId.toString())).findFirst().orElse(null);
        if((outbound||inbound)&&parking==null)return groundFallback(from,to,departure,person,parked);
        List<Vertiport> origins=outbound?List.of(parking):candidates(origin,cfg.getCandidateVertiports());
        List<Vertiport> destinations=inbound?List.of(parking):candidates(destination,cfg.getCandidateVertiports());
        List<PortPair> pairs=new ArrayList<>();
        for(Vertiport o:origins)for(Vertiport d:destinations)
            if(!o.id.equals(d.id)&&distance(origin,o.coord)<=cfg.getMaxAccessDistanceMiles()*MILE
                    &&distance(destination,d.coord)<=cfg.getMaxEgressDistanceMiles()*MILE)
                pairs.add(new PortPair(o,d,distance(origin,o.coord)+distance(destination,d.coord)+distance(o.coord,d.coord)));
        pairs.sort(Comparator.comparingDouble((PortPair p)->p.proxy).thenComparing(p->p.origin.id).thenComparing(p->p.destination.id));
        if(pairs.size()>cfg.getMaximumCandidateVertiportPairs())pairs=new ArrayList<>(pairs.subList(0,cfg.getMaximumCandidateVertiportPairs()));
        List<PlanElement> best=null;double bestCost=Double.POSITIVE_INFINITY;
        for(PortPair pair:pairs){Vertiport o=pair.origin,d=pair.destination;
            for(String am:options(cfg,outbound?parked:null)){
                List<? extends PlanElement> a=groundRoute(am,from,facility(o,false),departure,person,"access",feederCache);
                if(a==null)continue;
                double arrival=end(departure,new ArrayList<>(a));
                if(!cfg.getAllowPreServiceRequests()&&arrival<cfg.getServiceStartTime())continue;
                double flight=distance(o.coord,d.coord)/AIR_SPEED+1;
                double wait=serviceAwareWait(arrival,cfg.getServiceStartTime(),cfg.getMaxWaitTime(),
                        waits.estimate(o.airLink,d.airLink,arrival,cfg.getExpectedWaitTime(),cfg.getMaxWaitTime()));
                if(!Double.isFinite(wait)||arrival+wait+flight+120>cfg.getServiceEndTime())continue;
                double egressDeparture=arrival+wait+flight;
                for(String em:options(cfg,inbound?parked:null)){
                    List<? extends PlanElement> e=groundRoute(em,facility(d,false),to,egressDeparture,person,"egress",feederCache);
                    if(e==null)continue;
                    double cost=groundCost(a,person)+groundCost(e,person)
                        +(s.getConfig().planCalcScore().getPerforming_utils_hr()-s.getConfig().planCalcScore().getModes().get(AIR).getMarginalUtilityOfTraveling())*(wait+flight)/3600
                        +(cfg.getBaseFare()+cfg.getFarePerMile()*distance(o.coord,d.coord)/MILE)*moneyUtility(person);
                    if(Double.isFinite(cost)&&cost<bestCost){
                        bestCost=cost;best=assemble(o,d,departure,a,e,cfg,wait);
                        for(PlanElement element:best)if(element instanceof Leg&&AIR.equals(((Leg)element).getMode())){
                            Leg leg=(Leg)element;
                            leg.getAttributes().putAttribute("aam_access_distance_m",distance(origin,o.coord));
                            leg.getAttributes().putAttribute("aam_egress_distance_m",distance(destination,d.coord));
                            leg.getAttributes().putAttribute("aam_origin_vertiport",o.id);leg.getAttributes().putAttribute("aam_destination_vertiport",d.id);
                        }
                    }
                }
            }
        }
        if(best==null){
            org.apache.log4j.Logger.getLogger(getClass()).debug("AAM infeasible; ground fallback for person="+person.getId()+" departure="+departure);
            return groundFallback(from,to,departure,person,parked);
        }
        for(PlanElement e:best)if(e instanceof Leg)TripStructureUtils.setRoutingMode((Leg)e,AAM);
        return best;
    }
    private List<? extends PlanElement> groundFallback(Facility from,Facility to,double departure,Person person,String parked){
        // Native MATSim ReRoute may refresh a saved paired plan after a time
        // mutation. Flag the whole tour for the pre-QSim gate instead of letting
        // one infeasible half abort parallel replanning or teleport its vehicle.
        if(parked!=null)person.getSelectedPlan().getAttributes().putAttribute("aam_private_route_infeasible",true);
        List<? extends PlanElement> route=routers.get("ride").calcRoute(from,to,departure,person);
        for(PlanElement element:route)if(element instanceof Leg)TripStructureUtils.setRoutingMode((Leg)element,"ride");
        return route;
    }
    // Exact-time, request-local cache: no reuse across changing network travel times,
    // people, vehicle IDs or time bins; no cached elements escape into another plan.
    private List<? extends PlanElement> groundRoute(String mode,Facility from,Facility to,double departure,Person person,String side,Map<String,List<? extends PlanElement>> cache){
        String key=mode+"|"+side+"|"+from.getLinkId()+"|"+from.getCoord()+"|"+to.getLinkId()+"|"+to.getCoord()+"|"+departure;
        boolean cached=org.matsim.core.config.ConfigUtils.addOrGetModule(s.getConfig(),AamConfigGroup.class).getCacheFeederRoutes();
        if(cached&&cache.containsKey(key))return cache.get(key);
        try{List<? extends PlanElement> route=routers.get(mode).calcRoute(from,to,departure,person);
            AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(s.getConfig(),AamConfigGroup.class);
            boolean valid=AamFeederPolicy.admissible(route,cfg.getMaximumWalkDistance(),cfg.getMaximumWalkTime());
            AamFeederDiagnostics.get(s).record(mode,side,valid?"admissible":"walking_limit");if(cached)cache.put(key,valid?route:null);return valid?route:null;}
        catch(RuntimeException e){
            AamFeederDiagnostics.get(s).record(mode,side,"routing_failure");
            throw new IllegalStateException("AAM feeder routing failed: person="+person.getId()+", mode="+mode+", time="+departure,e);
        }
    }
    private List<String> options(AamConfigGroup cfg,String parked){
        if(parked!=null)return cfg.modes().contains(parked)?List.of(parked):List.of();
        List<String> r=new ArrayList<>(cfg.modes());r.remove("car");r.remove("bike");return r;
    }
    static double serviceAwareWait(double arrival,double serviceStart,double maximumWait,double observedWait){
        double wait=Math.max(Math.max(0,observedWait),Math.max(0,serviceStart-arrival));
        return Double.isFinite(wait)&&wait<=maximumWait?wait:Double.NaN;
    }
    private List<Vertiport> candidates(Coord c,int k){
        List<Vertiport> r=new ArrayList<>(ports);r.sort(Comparator.comparingDouble(v->distance(c,v.coord)));
        return r.subList(0,Math.min(k,r.size()));
    }
    private List<PlanElement> assemble(Vertiport o,Vertiport d,double departure,List<? extends PlanElement> access,
            List<? extends PlanElement> egress,AamConfigGroup cfg,double wait){
        List<PlanElement> result=new ArrayList<>();
        result.addAll(access);double now=end(departure,new ArrayList<>(access));
        result.add(stage(o.roadLink,o.coord));
        result.add(connector(o.roadLink,o.airLink,now));result.add(stage(o.airLink,o.coord));
        Leg air=s.getPopulation().getFactory().createLeg(AIR);double dist=distance(o.coord,d.coord);
        DrtRoute r=new DrtRoute(o.airLink,d.airLink);r.setDistance(dist);r.setDirectRideTime(dist/AIR_SPEED+1);
        // MATSim 13 interprets DrtRoute.travelTime as the hard latest-arrival
        // allowance, NOT an expected time. Keep the expectation on the Leg.
        double alpha=1.2,beta=1800;
        org.matsim.core.config.ConfigGroup multi=s.getConfig().getModules().get("multiModeDrt");
        if(multi instanceof org.matsim.contrib.drt.run.MultiModeDrtConfigGroup)
            for(org.matsim.contrib.drt.run.DrtConfigGroup drt:((org.matsim.contrib.drt.run.MultiModeDrtConfigGroup)multi).getModalElements())
                if(AIR.equals(drt.getMode())){alpha=drt.getMaxTravelTimeAlpha();beta=drt.getMaxTravelTimeBeta();}
        r.setMaxWaitTime(cfg.getMaxWaitTime());r.setTravelTime(alpha*r.getDirectRideTime()+beta);
        air.setRoute(r);air.setDepartureTime(now);air.setTravelTime(r.getDirectRideTime()+wait);result.add(air);
        now+=wait+dist/AIR_SPEED+1;result.add(stage(d.airLink,d.coord));
        result.add(connector(d.airLink,d.roadLink,now));result.add(stage(d.roadLink,d.coord));
        result.addAll(egress);
        return result;
    }
    private double groundCost(List<? extends PlanElement> route,Person p){
            double cost=0;double mu=moneyUtility(p);
            for(PlanElement e:route)if(e instanceof Leg){
                Leg l=(Leg)e;String m=l.getMode();ModeParams mp=s.getConfig().planCalcScore().getModes().get(m);
                double tt=l.getTravelTime().orElse(0),dist=l.getRoute()==null?0:l.getRoute().getDistance();
                if(!Double.isFinite(dist))dist=0;
                if(mp==null)throw new IllegalStateException("Missing scoring parameters: "+m);
                cost+=(s.getConfig().planCalcScore().getPerforming_utils_hr()-mp.getMarginalUtilityOfTraveling())*tt/3600
                    -mp.getConstant()-mp.getMonetaryDistanceRate()*dist*mu-mp.getMarginalUtilityOfDistance()*dist;
            }
            return cost;
    }
    static double moneyUtility(Person p){try{
        Object saved=p.getAttributes().getAttribute("marginalUtilityOfMoney");
        if(saved instanceof Number && Double.isFinite(((Number)saved).doubleValue()))return ((Number)saved).doubleValue();
        double inc=Double.parseDouble(p.getAttributes().getAttribute("hhinc").toString());
        double size=Double.parseDouble(p.getAttributes().getAttribute("hhsize").toString());
        return inc>0&&size>=1?35363.89/(inc/size):1;
    }catch(Exception e){return 1;}}
    private double end(double t,List<PlanElement> es){for(PlanElement e:es)t=TripRouter.calcEndOfPlanElement(t,e,s.getConfig());return t;}
    private Activity stage(Id<Link> id,Coord c){Activity a=s.getPopulation().getFactory().createActivityFromLinkId("aam interaction",id);a.setCoord(c);a.setMaximumDuration(0);return a;}
    private Leg connector(Id<Link> from,Id<Link> to,double t){Leg l=s.getPopulation().getFactory().createLeg("walk");
        Route r=RouteUtils.createGenericRouteImpl(from,to);r.setDistance(0);r.setTravelTime(0);l.setRoute(r);l.setDepartureTime(t);l.setTravelTime(0);return l;}
    private Facility facility(Vertiport p,boolean air){ActivityFacility f=s.getActivityFacilities().getFactory().createActivityFacility(Id.create("aam_fac_"+p.id,ActivityFacility.class),p.coord);
        ((ActivityFacilityImpl)f).setLinkId(air?p.airLink:p.roadLink);return f;}
    public static boolean isEligible(List<Vertiport> ps,Coord a,Coord b,double maxAccessDistance){
        return isEligible(ps,a,b,maxAccessDistance,0);
    }
    public static boolean isEligible(List<Vertiport> ps,Coord a,Coord b,double maxAccessDistance,double minimumTripDistance){
        return isEligible(ps,a,b,maxAccessDistance,maxAccessDistance,minimumTripDistance);
    }
    public static boolean isEligible(List<Vertiport> ps,Coord a,Coord b,double access,double egress,double minimum){
        if(a==null||b==null||distance(a,b)<minimum)return false;
        for(Vertiport o:ps)if(distance(a,o.coord)<=access)
            for(Vertiport d:ps)if(!o.id.equals(d.id)&&distance(b,d.coord)<=egress)return true;
        return false;
    }
    private static Vertiport nearest(List<Vertiport> ps,Coord c){return ps.stream().min(Comparator.comparingDouble(v->distance(c,v.coord))).orElseThrow();}
    private static final class PortPair{final Vertiport origin,destination;final double proxy;
        PortPair(Vertiport o,Vertiport d,double proxy){origin=o;destination=d;this.proxy=proxy;}}
    public static double distance(Coord a,Coord b){return Math.hypot(a.getX()-b.getX(),a.getY()-b.getY());}
    public static final class Vertiport {public final String id;public final Coord coord;public final Id<Link> airLink,roadLink;
        public Vertiport(String id,Coord c,Id<Link> a,Id<Link> r){this.id=id;coord=c;airLink=a;roadLink=r;}}
    public static final class PortSet {public final List<Vertiport> ports;public PortSet(List<Vertiport> p){ports=List.copyOf(p);}}
    public static final class InfeasibleAamRouteException extends IllegalStateException {
        public InfeasibleAamRouteException(String message){super(message);}
    }
    public static final class Factory implements Provider<RoutingModule>{
        @Inject Scenario s;@Inject PortSet ports;@Inject AamWaitTimeEstimator waits;
        @Inject @Named("car") Provider<RoutingModule> car;
        @Inject @Named("ride") Provider<RoutingModule> ride;
        @Inject @Named("ride_taxi") Provider<RoutingModule> taxi;
        @Inject @Named("walk") Provider<RoutingModule> walk;
        @Inject @Named("bike") Provider<RoutingModule> bike;
        public RoutingModule get(){Map<String,RoutingModule> r=new LinkedHashMap<>();r.put("car",car.get());r.put("ride",ride.get());
            r.put("ride_taxi",taxi.get());r.put("walk",walk.get());r.put("bike",bike.get());return new AamMultimodalRoutingModule(s,ports.ports,r,waits);}
    }
}
