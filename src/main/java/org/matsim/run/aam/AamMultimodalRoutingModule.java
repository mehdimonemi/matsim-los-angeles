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
    private final Scenario s;private final List<Vertiport> ports;private final Map<String,RoutingModule> routers;
    public AamMultimodalRoutingModule(Scenario s,List<Vertiport> ports,Map<String,RoutingModule> routers){this.s=s;this.ports=ports;this.routers=routers;}
    public List<? extends PlanElement> calcRoute(Facility from,Facility to,double departure,Person person){
        AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(s.getConfig(),AamConfigGroup.class);
        String parked=(String)person.getSelectedPlan().getAttributes().getAttribute("aam_park_mode");
        Coord home=((Activity)person.getSelectedPlan().getPlanElements().get(0)).getCoord();
        boolean outbound=parked!=null&&distance(from.getCoord(),home)<5;
        boolean inbound=parked!=null&&distance(to.getCoord(),home)<5;
        // A paired car/bike tour must return to the SAME home-side parking location.
        List<Vertiport> origins=outbound?List.of(nearest(ports,home)):candidates(from.getCoord(),cfg.getCandidateVertiports());
        List<Vertiport> destinations=inbound?List.of(nearest(ports,home)):candidates(to.getCoord(),cfg.getCandidateVertiports());
        List<PlanElement> best=null;double bestCost=Double.POSITIVE_INFINITY;
        for(Vertiport o:origins)for(Vertiport d:destinations){
            if(o.id.equals(d.id)||distance(o.coord,d.coord)<5*MILE)continue;
            for(String am:options(cfg,outbound?parked:null)){
                List<? extends PlanElement> a=routers.get(am).calcRoute(from,facility(o,false),departure,person);
                if(a==null)continue;
                double arrival=end(departure,new ArrayList<>(a));
                double flight=distance(o.coord,d.coord)/AIR_SPEED+1;
                double egressDeparture=arrival+cfg.getExpectedWaitTime()+flight;
                for(String em:options(cfg,inbound?parked:null)){
                    List<? extends PlanElement> e=routers.get(em).calcRoute(facility(d,false),to,egressDeparture,person);
                    if(e==null)continue;
                    double cost=groundCost(a,person)+groundCost(e,person)
                        +(s.getConfig().planCalcScore().getPerforming_utils_hr()-s.getConfig().planCalcScore().getModes().get(AIR).getMarginalUtilityOfTraveling())*(cfg.getExpectedWaitTime()+flight)/3600
                        +(cfg.getBaseFare()+cfg.getFarePerMile()*distance(o.coord,d.coord)/MILE)*moneyUtility(person);
                    if(Double.isFinite(cost)&&cost<bestCost){
                        bestCost=cost;best=assemble(o,d,departure,a,e,cfg);
                    }
                }
            }
        }
        if(best==null)throw new IllegalArgumentException("No feasible AAM alternative for person "+person.getId()+"; check candidateVertiports and allowed access/egress modes");
        for(PlanElement e:best)if(e instanceof Leg)TripStructureUtils.setRoutingMode((Leg)e,AAM);
        return best;
    }
    private List<String> options(AamConfigGroup cfg,String parked){
        if(parked!=null)return cfg.modes().contains(parked)?List.of(parked):List.of();
        List<String> r=new ArrayList<>(cfg.modes());r.remove("car");r.remove("bike");return r;
    }
    private List<Vertiport> candidates(Coord c,int k){
        List<Vertiport> r=new ArrayList<>(ports);r.sort(Comparator.comparingDouble(v->distance(c,v.coord)));
        return r.subList(0,Math.min(k,r.size()));
    }
    private List<PlanElement> assemble(Vertiport o,Vertiport d,double departure,List<? extends PlanElement> access,
            List<? extends PlanElement> egress,AamConfigGroup cfg){
        List<PlanElement> result=new ArrayList<>();
        result.addAll(access);double now=end(departure,new ArrayList<>(access));
        result.add(stage(o.roadLink,o.coord));
        result.add(connector(o.roadLink,o.airLink,now));result.add(stage(o.airLink,o.coord));
        Leg air=s.getPopulation().getFactory().createLeg(AIR);double dist=distance(o.coord,d.coord);
        DrtRoute r=new DrtRoute(o.airLink,d.airLink);r.setDistance(dist);r.setDirectRideTime(dist/AIR_SPEED+1);
        r.setMaxWaitTime(cfg.getMaxWaitTime());r.setTravelTime(dist/AIR_SPEED+1+cfg.getExpectedWaitTime());
        air.setRoute(r);air.setDepartureTime(now);air.setTravelTime(r.getTravelTime().seconds());result.add(air);
        now+=cfg.getExpectedWaitTime()+dist/AIR_SPEED+1;result.add(stage(d.airLink,d.coord));
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
    private static double moneyUtility(Person p){try{
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
    public static boolean isEligible(List<Vertiport> ps,Coord a,Coord b){if(a==null||b==null)return false;Vertiport o=nearest(ps,a),d=nearest(ps,b);return o!=d&&distance(o.coord,d.coord)>=5*MILE;}
    private static Vertiport nearest(List<Vertiport> ps,Coord c){return ps.stream().min(Comparator.comparingDouble(v->distance(c,v.coord))).orElseThrow();}
    public static double distance(Coord a,Coord b){return Math.hypot(a.getX()-b.getX(),a.getY()-b.getY());}
    public static final class Vertiport {public final String id;public final Coord coord;public final Id<Link> airLink,roadLink;
        public Vertiport(String id,Coord c,Id<Link> a,Id<Link> r){this.id=id;coord=c;airLink=a;roadLink=r;}}
    public static final class PortSet {public final List<Vertiport> ports;public PortSet(List<Vertiport> p){ports=List.copyOf(p);}}
    public static final class Factory implements Provider<RoutingModule>{
        @Inject Scenario s;@Inject PortSet ports;
        @Inject @Named("car") Provider<RoutingModule> car;
        @Inject @Named("ride") Provider<RoutingModule> ride;
        @Inject @Named("ride_taxi") Provider<RoutingModule> taxi;
        @Inject @Named("walk") Provider<RoutingModule> walk;
        @Inject @Named("bike") Provider<RoutingModule> bike;
        public RoutingModule get(){Map<String,RoutingModule> r=new LinkedHashMap<>();r.put("car",car.get());r.put("ride",ride.get());
            r.put("ride_taxi",taxi.get());r.put("walk",walk.get());r.put("bike",bike.get());return new AamMultimodalRoutingModule(s,ports.ports,r);}
    }
}
