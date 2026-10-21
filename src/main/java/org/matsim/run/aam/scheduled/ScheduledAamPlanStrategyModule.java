package org.matsim.run.aam.scheduled;

import java.util.*;
import javax.inject.Provider;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.*;
import org.matsim.api.core.v01.replanning.PlanStrategyModule;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.Config;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ModeParams;
import org.matsim.contrib.drt.run.DrtConfigGroup;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.replanning.ReplanningContext;
import org.matsim.core.router.*;
import org.matsim.core.router.TripStructureUtils.Trip;
import org.matsim.facilities.*;
import org.matsim.pt.PtConstants;
import org.matsim.pt.routes.*;
import org.matsim.pt.transitSchedule.api.*;

/** Scheduled aircraft with AAM-DRT-equivalent feeder and vehicle-continuity rules. */
public final class ScheduledAamPlanStrategyModule implements PlanStrategyModule {
    static final String PLAN_TYPE="scheduled_aam", PARK_MODE="scheduled_aam_park_mode";
    private static final Logger LOG=Logger.getLogger(ScheduledAamPlanStrategyModule.class);
    private final Scenario scenario; private final ScheduledAamConfigGroup config;
    private final List<Flight> flights; private final List<Port> ports;
    private final Map<String,RoutingModule> groundRouters;
    private int created,ineligible;

    /** Test-only constructor; production supplies MATSim's mode-specific routers. */
    ScheduledAamPlanStrategyModule(Scenario scenario){this(scenario,fallbackRouters(scenario));}
    ScheduledAamPlanStrategyModule(Scenario scenario,Map<String,RoutingModule> routers){
        this.scenario=scenario;config=ConfigUtils.addOrGetModule(scenario.getConfig(),ScheduledAamConfigGroup.class);
        groundRouters=new LinkedHashMap<>(routers);ports=readPorts(scenario);flights=readFlights(scenario,ports);
        if(flights.isEmpty()||ports.size()<2)throw new IllegalStateException("No scheduled AAM transit routes");
    }
    static Map<String,RoutingModule> routers(RoutingModule car,RoutingModule ride,RoutingModule taxi,RoutingModule walk,RoutingModule bike){
        Map<String,RoutingModule> r=new LinkedHashMap<>();r.put("car",car);r.put("ride",ride);r.put("ride_taxi",taxi);r.put("walk",walk);r.put("bike",bike);return r;
    }
    /**
     * Resolve the production feeder routers without allowing MATSim's legacy
     * ride_taxi binding to turn this scheduled-transit scenario into a DRT run.
     */
    static Map<String,RoutingModule> routers(Scenario scenario,Provider<RoutingModule> car,
            Provider<RoutingModule> ride,Provider<RoutingModule> taxi,Provider<RoutingModule> walk,
            Provider<RoutingModule> bike){
        Config config=scenario.getConfig();
        boolean hadLegacyDrt=config.getModules().containsKey(DrtConfigGroup.GROUP_NAME);
        try{return routers(car.get(),ride.get(),taxi.get(),walk.get(),bike.get());}
        finally{removeRouterAddedLegacyDrt(config,hadLegacyDrt);}
    }
    static void removeRouterAddedLegacyDrt(Config config,boolean existedBeforeRouterInitialization){
        if(!existedBeforeRouterInitialization&&config.getModules().get(DrtConfigGroup.GROUP_NAME) instanceof DrtConfigGroup)
            config.removeModule(DrtConfigGroup.GROUP_NAME);
    }
    public void prepareReplanning(ReplanningContext context){created=0;ineligible=0;}
    public void handlePlan(Plan plan){if(!config.isInnovationEnabled()||!addAlternative(plan))ineligible++;}
    public void finishReplanning(){LOG.info("ScheduledAamInnovation created "+created+" candidate plans; "+ineligible+" copied plans were already AAM or had no eligible trip");}

    /** Add the least-generalized-cost eligible trip, or both legs of a private-vehicle tour. */
    boolean addAlternative(Plan plan){
        if(containsScheduledAam(plan))return false;
        List<Trip> trips=new ArrayList<>(TripStructureUtils.getTrips(plan));if(trips.isEmpty())return false;
        Set<String> chains=new HashSet<>();for(Trip t:trips)for(Leg l:t.getLegsOnly())if("car".equals(l.getMode())||"bike".equals(l.getMode()))chains.add(l.getMode());
        if(!chains.isEmpty()){
            if(chains.size()!=1||trips.size()!=2)return false;String parked=chains.iterator().next();
            if(!config.modes().contains(parked)||!tripMainMode(trips.get(0)).equals(parked)||!tripMainMode(trips.get(1)).equals(parked))return false;
            Coord a=coordinate(trips.get(0).getOriginActivity()),b=coordinate(trips.get(1).getDestinationActivity());
            if(a==null||b==null||distance(a,b)>5||!trips.get(0).getOriginActivity().getType().startsWith("home"))return false;
            plan.getAttributes().putAttribute(PARK_MODE,parked);List<Candidate> paired=new ArrayList<>();
            for(Trip t:trips){Candidate c=candidateFor(t,plan,plan.getPerson());if(c==null)return false;c.trip=t;paired.add(c);}for(Candidate c:paired)insert(plan,c);
        }else{
            Candidate best=null;for(Trip t:trips){Candidate c=candidateFor(t,plan,plan.getPerson());if(c!=null&&(best==null||c.generalizedCost<best.generalizedCost)){c.trip=t;best=c;}}
            if(best==null)return false;insert(plan,best);plan.getAttributes().putAttribute("scheduled_aam_corridor",best.flight.line.getId().toString());
        }
        plan.getAttributes().putAttribute("scheduled_aam_innovation",true);plan.setType(PLAN_TYPE);plan.setScore(null);created++;return true;
    }

    private Candidate candidateFor(Trip trip,Plan plan,Person person){
        Coord o=coordinate(trip.getOriginActivity()),d=coordinate(trip.getDestinationActivity());if(!eligible(o,d))return null;
        double dep=TripStructureUtils.getDepartureTime(trip).orElse(trip.getOriginActivity().getEndTime().orElse(Double.NaN));if(!Double.isFinite(dep))return null;
        String parked=(String)plan.getAttributes().getAttribute(PARK_MODE);Coord home=coordinate((Activity)plan.getPlanElements().get(0));
        return candidateFor(FacilitiesUtils.toFacility(trip.getOriginActivity(),scenario.getActivityFacilities()),FacilitiesUtils.toFacility(trip.getDestinationActivity(),scenario.getActivityFacilities()),o,d,dep,person,parked,home,parked!=null&&distance(o,home)<5,parked!=null&&distance(d,home)<5);
    }
    Candidate candidateFor(Facility from,Facility to,double departure,Person person){
        Coord o=from.getCoord(),d=to.getCoord();if(!eligible(o,d))return null;Plan p=person.getSelectedPlan();
        String parked=p==null?null:(String)p.getAttributes().getAttribute(PARK_MODE);Coord home=p==null||p.getPlanElements().isEmpty()?null:coordinate((Activity)p.getPlanElements().get(0));
        return candidateFor(from,to,o,d,departure,person,parked,home,parked!=null&&home!=null&&distance(o,home)<5,parked!=null&&home!=null&&distance(d,home)<5);
    }
    private Candidate candidateFor(Facility from,Facility to,Coord o,Coord d,double tripDep,Person person,String parked,Coord home,boolean outbound,boolean inbound){
        List<Port> os=outbound?List.of(nearest(home)):nearest(o,config.getCandidateVertiports()),ds=inbound?List.of(nearest(home)):nearest(d,config.getCandidateVertiports());Candidate best=null;
        for(Port op:os)for(Port dp:ds){if(op==dp||distance(o,op.coord)>config.getMaximumGroundAccessDistanceMiles()*1609.344)continue;Flight f=flight(op,dp);if(f==null)continue;
            for(String am:modes(outbound?parked:null)){List<? extends PlanElement>a=groundRoute(am,from,op.ground,tripDep,person,"access");if(a==null)continue;double arrival=end(tripDep,a);Departure scheduled=nextDeparture(f,arrival);if(scheduled==null)continue;double flightDep=scheduled.getDepartureTime(),egressDep=flightDep+f.flightTime;
                for(String em:modes(inbound?parked:null)){List<? extends PlanElement>e=groundRoute(em,dp.ground,to,egressDep,person,"egress");if(e==null)continue;double cost=groundCost(a,person)+groundCost(e,person)+flightCost(flightDep-arrival,f.flightTime)+(config.getBaseFare()+config.getFarePerMile()*f.distance/1609.344)*moneyUtility(person);if(Double.isFinite(cost)&&(best==null||cost<best.generalizedCost))best=new Candidate(f,tripDep,flightDep,a,e,cost);}}
        }return best;
    }
    private boolean eligible(Coord o,Coord d){return o!=null&&d!=null&&distance(o,d)>=config.getMinimumTripDistance()&&distance(o,nearest(o).coord)<=config.getMaximumGroundAccessDistanceMiles()*1609.344;}
    private List<String> modes(String parked){if(parked!=null)return config.modes().contains(parked)?List.of(parked):List.of();List<String> r=new ArrayList<>(config.modes());r.remove("car");r.remove("bike");return r;}
    private List<? extends PlanElement> groundRoute(String mode,Facility from,Facility to,double dep,Person person,String side){
        RoutingModule r=groundRouters.get(mode);if(r==null)throw new IllegalStateException("Missing scheduled feeder router: "+mode);
        try{List<? extends PlanElement> route=r.calcRoute(from,to,dep,person);
            boolean valid=org.matsim.run.aam.AamFeederPolicy.admissible(route,config.getMaximumWalkDistance(),config.getMaximumWalkTime());
            org.matsim.run.aam.AamFeederDiagnostics.get(scenario).record(mode,side,valid?"admissible":"walking_limit");return valid?route:null;
        }catch(RuntimeException e){org.matsim.run.aam.AamFeederDiagnostics.get(scenario).record(mode,side,"routing_failure");
            throw new IllegalStateException("Scheduled feeder routing failed: person="+person.getId()+", mode="+mode+", time="+dep,e);}
    }
    private double groundCost(List<? extends PlanElement> route,Person person){double cost=0,mu=moneyUtility(person);for(PlanElement e:route)if(e instanceof Leg){Leg l=(Leg)e;ModeParams mp=scenario.getConfig().planCalcScore().getModes().get(l.getMode());if(mp==null)throw new IllegalStateException("Missing scoring parameters for feeder mode "+l.getMode());double tt=l.getTravelTime().orElse(0),dist=l.getRoute()==null?0:l.getRoute().getDistance();if(!Double.isFinite(dist))dist=0;cost+=(scenario.getConfig().planCalcScore().getPerforming_utils_hr()-mp.getMarginalUtilityOfTraveling())*tt/3600-mp.getConstant()-mp.getMonetaryDistanceRate()*dist*mu-mp.getMarginalUtilityOfDistance()*dist;}return cost;}
    private double flightCost(double waiting,double flight){ModeParams mp=scenario.getConfig().planCalcScore().getModes().get(ScheduledAamRoutingModule.MODE);
        double performing=scenario.getConfig().planCalcScore().getPerforming_utils_hr(),travelUtility=mp==null?0:mp.getMarginalUtilityOfTraveling();
        return (performing-travelUtility)*flight/3600+(performing-scenario.getConfig().planCalcScore().getMarginalUtlOfWaitingPt_utils_hr())*waiting/3600-(mp==null?0:mp.getConstant());}
    private static double moneyUtility(Person p){try{Object saved=p.getAttributes().getAttribute("marginalUtilityOfMoney");if(saved instanceof Number&&Double.isFinite(((Number)saved).doubleValue()))return((Number)saved).doubleValue();double inc=Double.parseDouble(p.getAttributes().getAttribute("hhinc").toString()),size=Double.parseDouble(p.getAttributes().getAttribute("hhsize").toString());return inc>0&&size>=1?35363.89/(inc/size):1;}catch(Exception e){return 1;}}

    private void insert(Plan plan,Candidate c){TripRouter.insertTrip(plan,c.trip.getOriginActivity(),createTrip(c),c.trip.getDestinationActivity());}
    List<PlanElement> createTrip(Candidate c){
        List<PlanElement> r=new ArrayList<>();
        double accessArrival=end(c.tripDeparture,c.access);
        r.addAll(c.access);
        r.add(interaction(c.flight.origin.ground));
        r.add(connector(c.flight.origin.ground.getLinkId(),c.flight.origin.stop.getLinkId(),accessArrival));
        r.add(interaction(c.flight.origin.stop));
        Leg air=scenario.getPopulation().getFactory().createLeg(TransportMode.pt);
        air.setDepartureTime(accessArrival);
        double waitAndFlight=c.flightDeparture-accessArrival+c.flight.flightTime;
        air.setTravelTime(waitAndFlight);
        DefaultTransitPassengerRoute route=new DefaultTransitPassengerRoute(c.flight.origin.stop,c.flight.line,c.flight.route,c.flight.destination.stop);
        route.setBoardingTime(c.flightDeparture);route.setDistance(c.flight.distance);route.setTravelTime(waitAndFlight);
        air.setRoute(route);air.getAttributes().putAttribute("scoringMode",ScheduledAamRoutingModule.MODE);r.add(air);
        double flightArrival=c.flightDeparture+c.flight.flightTime;
        r.add(interaction(c.flight.destination.stop));
        r.add(connector(c.flight.destination.stop.getLinkId(),c.flight.destination.ground.getLinkId(),flightArrival));
        r.add(interaction(c.flight.destination.ground));
        r.addAll(c.egress);
        for(Leg l:TripStructureUtils.getLegs(r))TripStructureUtils.setRoutingMode(l,ScheduledAamRoutingModule.MODE);
        return r;
    }
    private Activity interaction(TransitStopFacility stop){Activity a=scenario.getPopulation().getFactory().createActivityFromCoord(PtConstants.TRANSIT_ACTIVITY_TYPE,stop.getCoord());a.setLinkId(stop.getLinkId());a.setMaximumDuration(0);return a;}
    private Activity interaction(ActivityFacility facility){Activity a=scenario.getPopulation().getFactory().createActivityFromCoord(PtConstants.TRANSIT_ACTIVITY_TYPE,facility.getCoord());a.setLinkId(facility.getLinkId());a.setMaximumDuration(0);return a;}
    private Leg connector(Id<Link> from,Id<Link> to,double departure){Leg leg=scenario.getPopulation().getFactory().createLeg(TransportMode.walk);leg.setDepartureTime(departure);leg.setTravelTime(0);org.matsim.api.core.v01.population.Route route=RouteUtils.createGenericRouteImpl(from,to);route.setDistance(0);route.setTravelTime(0);leg.setRoute(route);return leg;}
    private double end(double t,List<? extends PlanElement> elements){for(PlanElement e:elements)t=TripRouter.calcEndOfPlanElement(t,e,scenario.getConfig());return t;}
    private String tripMainMode(Trip t){for(String m:List.of("car","bike","freight","ride_taxi","ride","pt","walk"))if(t.getLegsOnly().stream().anyMatch(l->m.equals(l.getMode())))return m;return t.getLegsOnly().isEmpty()?"":t.getLegsOnly().get(0).getMode();}
    private Coord coordinate(Activity a){if(a==null)return null;if(a.getCoord()!=null)return a.getCoord();Link l=a.getLinkId()==null?null:scenario.getNetwork().getLinks().get(a.getLinkId());return l==null?null:l.getCoord();}
    private Port nearest(Coord c){return ports.stream().min(Comparator.comparingDouble(p->distance(c,p.coord))).orElseThrow();}
    private List<Port> nearest(Coord c,int k){List<Port> r=new ArrayList<>(ports);r.sort(Comparator.comparingDouble(p->distance(c,p.coord)));return r.subList(0,Math.min(k,r.size()));}
    private Flight flight(Port o,Port d){return flights.stream().filter(f->f.origin==o&&f.destination==d).findFirst().orElse(null);}
    private Departure nextDeparture(Flight f,double arrival){
        ScheduledAamServiceState state=ScheduledAamServiceState.get(scenario);
        double ready=arrival+(state==null?0:state.forecastWait(f.line.getId().toString(),arrival));
        return f.route.getDepartures().values().stream()
            .filter(d->d.getDepartureTime()+1e-6>=ready&&d.getDepartureTime()-arrival<=config.getMaximumPassengerWait()+1e-6)
            .filter(d->state==null||!state.previouslyFull(f.line.getId().toString(),d.getId().toString()))
            .min(Comparator.comparingDouble(Departure::getDepartureTime)).orElse(null);
    }
    static boolean containsScheduledAam(Plan plan){for(Leg l:TripStructureUtils.getLegs(plan)){if(ScheduledAamRoutingModule.MODE.equals(l.getMode())||ScheduledAamRoutingModule.MODE.equals(TripStructureUtils.getRoutingMode(l)))return true;if(l.getRoute() instanceof TransitPassengerRoute){TransitPassengerRoute r=(TransitPassengerRoute)l.getRoute();if(r.getLineId()!=null&&r.getLineId().toString().startsWith(ScheduledAamTransitBuilder.PREFIX+"line_"))return true;}}return false;}

    private static List<Port> readPorts(Scenario s){List<Port> r=new ArrayList<>();for(TransitStopFacility stop:s.getTransitSchedule().getFacilities().values())if(stop.getId().toString().startsWith(ScheduledAamTransitBuilder.PREFIX+"stop_")){Link link=s.getNetwork().getLinks().values().stream().filter(l->!l.getId().toString().startsWith(ScheduledAamTransitBuilder.PREFIX)&&l.getAllowedModes().stream().anyMatch(m->List.of("car","ride","ride_taxi","bike").contains(m))).min(Comparator.comparingDouble(l->distance(stop.getCoord(),l.getCoord()))).orElseThrow();ActivityFacility f=s.getActivityFacilities().getFactory().createActivityFacility(Id.create("scheduled_aam_ground_"+stop.getId(),ActivityFacility.class),stop.getCoord());((ActivityFacilityImpl)f).setLinkId(link.getId());r.add(new Port(stop,stop.getCoord(),f));}return r;}
    private static List<Flight> readFlights(Scenario s,List<Port> ports){Map<Id<TransitStopFacility>,Port> by=new LinkedHashMap<>();for(Port p:ports)by.put(p.stop.getId(),p);List<Flight> r=new ArrayList<>();for(TransitLine line:s.getTransitSchedule().getTransitLines().values())if(line.getId().toString().startsWith(ScheduledAamTransitBuilder.PREFIX+"line_"))for(TransitRoute route:line.getRoutes().values())if(ScheduledAamTransitBuilder.AAM_MODE.equals(route.getTransportMode())&&route.getStops().size()>=2){TransitRouteStop first=route.getStops().get(0),last=route.getStops().get(route.getStops().size()-1);double time=last.getArrivalOffset().seconds()-first.getDepartureOffset().seconds(),dist=RouteUtils.calcDistance(route,first.getStopFacility(),last.getStopFacility(),s.getNetwork());r.add(new Flight(line,route,by.get(first.getStopFacility().getId()),by.get(last.getStopFacility().getId()),time,dist));}return r;}
    private static Map<String,RoutingModule> fallbackRouters(Scenario s){Map<String,RoutingModule> r=new LinkedHashMap<>();for(String mode:List.of("car","ride","ride_taxi","walk","bike"))r.put(mode,(from,to,dep,person)->{Leg l=s.getPopulation().getFactory().createLeg(mode);l.setDepartureTime(dep);double speed="walk".equals(mode)?1.05:"bike".equals(mode)?3.14:13.89,dist=1.4*distance(from.getCoord(),to.getCoord()),tt=dist/speed;l.setTravelTime(tt);org.matsim.api.core.v01.population.Route route=RouteUtils.createGenericRouteImpl(from.getLinkId(),to.getLinkId());route.setDistance(dist);route.setTravelTime(tt);l.setRoute(route);return List.of(l);});return r;}
    private static double distance(Coord a,Coord b){return a==null||b==null?Double.POSITIVE_INFINITY:Math.hypot(a.getX()-b.getX(),a.getY()-b.getY());}
    private static final class Port{final TransitStopFacility stop;final Coord coord;final ActivityFacility ground;Port(TransitStopFacility s,Coord c,ActivityFacility g){stop=s;coord=c;ground=g;}}
    private static final class Flight{final TransitLine line;final TransitRoute route;final Port origin,destination;final double flightTime,distance;Flight(TransitLine l,TransitRoute r,Port o,Port d,double t,double x){line=l;route=r;origin=o;destination=d;flightTime=t;distance=x;}}
    static final class Candidate{Trip trip;final Flight flight;final double tripDeparture,flightDeparture,generalizedCost;final List<? extends PlanElement> access,egress;Candidate(Flight f,double td,double fd,List<? extends PlanElement>a,List<? extends PlanElement>e,double c){flight=f;tripDeparture=td;flightDeparture=fd;access=a;egress=e;generalizedCost=c;}}
}
