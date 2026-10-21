package org.matsim.run.aam;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.nio.file.*;
import java.io.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.router.*;
import org.matsim.core.router.TripStructureUtils.Trip;
import static org.matsim.run.aam.RunDynamicAamLosAngelesScenario.*;

/** Layout-scoped cheap screen. Geometry survives swaps; routing failures do not erase intent.
 * A changed departure/activity signature is rescreened, never reused with stale timing. */
public final class AamCandidateScreen {
    private final Scenario scenario;
    private final Map<String,ProxyMode> proxyModes;
    private final double performingUtilityPerHour;
    private final double airTravelUtility;
    private final ConcurrentMap<String,ConcurrentMap<String,Double>> distances=new ConcurrentHashMap<>();
    private final ConcurrentMap<String,List<Candidate>> screens=new ConcurrentHashMap<>();
    private final ConcurrentNavigableMap<String,List<Candidate>> current=new ConcurrentSkipListMap<>();
    private final ConcurrentMap<String,String> currentKeys=new ConcurrentHashMap<>();
    private final ConcurrentMap<String,Object> personLocks=new ConcurrentHashMap<>();
    public final AtomicLong screenPasses=new AtomicLong(), distanceCalculations=new AtomicLong(), routeAttempts=new AtomicLong(), screenNanos=new AtomicLong(), routingNanos=new AtomicLong();
    private AamCandidateScreen(Scenario scenario){
        this.scenario=scenario;
        this.performingUtilityPerHour=scenario.getConfig().planCalcScore().getPerforming_utils_hr();
        Map<String,ProxyMode> modes=new HashMap<>();
        scenario.getConfig().planCalcScore().getModes().forEach((name,params)->modes.put(name,
            new ProxyMode(params.getMarginalUtilityOfTraveling(),params.getConstant(),
                params.getMonetaryDistanceRate(),params.getMarginalUtilityOfDistance(),proxySpeed(name))));
        this.proxyModes=Map.copyOf(modes);
        ProxyMode air=modes.get(AIR);
        this.airTravelUtility=air==null?-6:air.travelUtility;
    }
    public static AamCandidateScreen get(Scenario s){synchronized(s){
        AamCandidateScreen result=(AamCandidateScreen)s.getScenarioElement("aamCandidateScreen");
        if(result==null){result=new AamCandidateScreen(s);s.addScenarioElement("aamCandidateScreen",result);}return result;
    }}
    private static String point(Coord c){return c==null?"missing":c.getX()+":"+c.getY();}
    double distanceTo(Coord c,AamMultimodalRoutingModule.Vertiport port){
        if(c==null)return Double.POSITIVE_INFINITY;
        ConcurrentMap<String,Double> row=distances.computeIfAbsent(point(c),key->new ConcurrentHashMap<>());
        return row.computeIfAbsent(port.id+":"+point(port.coord),key->{distanceCalculations.incrementAndGet();return AamMultimodalRoutingModule.distance(c,port.coord);});
    }
    public List<Candidate> screen(Plan plan,List<AamMultimodalRoutingModule.Vertiport> ports){
        String person=plan.getPerson()==null?"unattached":plan.getPerson().getId().toString();
        Object lock=personLocks.computeIfAbsent(person,key->new Object());
        synchronized(lock){return screenLocked(plan,ports,person);}
    }
    private List<Candidate> screenLocked(Plan plan,List<AamMultimodalRoutingModule.Vertiport> ports,String person){
        long start=System.nanoTime();
        AamConfigGroup cfg=org.matsim.core.config.ConfigUtils.addOrGetModule(scenario.getConfig(),AamConfigGroup.class);
        List<Trip> trips=TripStructureUtils.getTrips(plan);
        double moneyUtility=AamMultimodalRoutingModule.moneyUtility(plan.getPerson());
        StringBuilder key=new StringBuilder(person);
        ports.stream().sorted(Comparator.comparing(v->v.id)).forEach(v->key.append('|').append(v.id).append(point(v.coord)));
        key.append('|').append(cfg.getMaxAccessDistanceMiles()).append('|').append(cfg.getMaxEgressDistanceMiles())
            .append('|').append(cfg.getMinimumTripDistanceMiles()).append('|').append(cfg.getServiceStartTime())
            .append('|').append(cfg.getServiceEndTime()).append('|').append(cfg.getAllowPreServiceRequests()).append('|').append(cfg.getMaxWaitTime());
        for(Trip trip:trips)key.append('|').append(point(trip.getOriginActivity().getCoord())).append('>')
            .append(point(trip.getDestinationActivity().getCoord())).append('@').append(departure(trip,plan));
        List<Candidate> found=screens.get(key.toString());
        if(found!=null)found=key.toString().equals(currentKeys.get(person))?current.get(person):copy(found);
        if(found==null){
            screenPasses.incrementAndGet();found=new ArrayList<>();int index=0;
            for(Trip trip:trips){
                Candidate candidate=new Candidate(person,index++,trip.getOriginActivity().getCoord(),trip.getDestinationActivity().getCoord(),departure(trip,plan),direction(trip));
                double proxy=Double.POSITIVE_INFINITY;
                double[] accessDistances=new double[ports.size()],egressDistances=new double[ports.size()];
                if(candidate.origin!=null&&candidate.destination!=null){
                    for(int port=0;port<ports.size();port++){accessDistances[port]=distanceTo(candidate.origin,ports.get(port));egressDistances[port]=distanceTo(candidate.destination,ports.get(port));}
                    candidate.access=Arrays.stream(accessDistances).min().orElse(Double.NaN);
                    candidate.egress=Arrays.stream(egressDistances).min().orElse(Double.NaN);
                }
                if(candidate.origin==null||candidate.destination==null)candidate.reason="missing_activity_coordinates";
                else if(AamMultimodalRoutingModule.distance(candidate.origin,candidate.destination)<cfg.getMinimumTripDistanceMiles()*MILE)candidate.reason="minimum_trip_distance";
                else{
                    boolean access=false,egress=false;
                    for(int oi=0;oi<ports.size();oi++){
                        AamMultimodalRoutingModule.Vertiport o=ports.get(oi);double ad=accessDistances[oi];
                        if(ad>cfg.getMaxAccessDistanceMiles()*MILE)continue;access=true;
                        for(int di=0;di<ports.size();di++){
                            AamMultimodalRoutingModule.Vertiport d=ports.get(di);double ed=egressDistances[di];
                            if(ed>cfg.getMaxEgressDistanceMiles()*MILE)continue;egress=true;
                            if(o.id.equals(d.id))continue;
                            candidate.geometric=true;
                            double flight=AamMultimodalRoutingModule.distance(o.coord,d.coord)/AIR_SPEED+1;
                            // Optimistic lower bound, not a network travel-time estimate.
                            // Unknown feeder time cannot exclude an otherwise possible pre-opening request.
                            boolean temporal=Double.isFinite(candidate.departure)&&candidate.departure<=cfg.getServiceEndTime()
                                &&Math.max(candidate.departure,cfg.getServiceStartTime())+flight+120<=cfg.getServiceEndTime();
                            if(temporal){
                                double cost=proxyGround(ad,cfg,moneyUtility)+proxyGround(ed,cfg,moneyUtility)
                                    +(performingUtilityPerHour-airTravelUtility)*(flight+cfg.getExpectedWaitTime())/3600
                                    +(cfg.getBaseFare()+cfg.getFarePerMile()*AamMultimodalRoutingModule.distance(o.coord,d.coord)/MILE)*moneyUtility;
                                if(cost<proxy){proxy=cost;candidate.access=ad;candidate.egress=ed;candidate.originPort=o.id;candidate.destinationPort=d.id;}
                                candidate.temporal=true;
                            }
                        }
                    }
                    candidate.reason=!access?"access_distance":!egress?"egress_distance":!candidate.geometric?"same_vertiport":!candidate.temporal?"service_window":"unrouted";
                }
                candidate.proxy=proxy;found.add(candidate);
            }
            screens.put(key.toString(),copy(found));
        }
        current.put(person,found);currentKeys.put(person,key.toString());screenNanos.addAndGet(System.nanoTime()-start);
        if(plan.getPerson()!=null)persist(plan.getPerson(),found);
        return found;
    }
    private double proxyGround(double distance,AamConfigGroup cfg,double moneyUtility){
        double best=Double.POSITIVE_INFINITY;
        for(String mode:cfg.modes()){
            if(List.of("car","bike").contains(mode)&&cfg.modes().stream().anyMatch(m->!List.of("car","bike").contains(m)))continue;
            ProxyMode mp=proxyModes.get(mode);
            double speed=mp==null?proxySpeed(mode):mp.speed;
            if("walk".equals(mode)&&(distance>cfg.getMaximumWalkDistance()||distance/speed>cfg.getMaximumWalkTime()))continue;
            double cost=mp==null?distance/speed/3600:(performingUtilityPerHour-mp.travelUtility)*distance/speed/3600
                -mp.constant-mp.monetaryDistanceRate*distance*moneyUtility-mp.distanceUtility*distance;
            best=Math.min(best,cost);
        }
        return best;
    }
    private static double proxySpeed(String mode){return "walk".equals(mode)?1.34:"bike".equals(mode)?4.17:13.89;}
    private static final class ProxyMode {
        final double travelUtility,constant,monetaryDistanceRate,distanceUtility,speed;
        ProxyMode(double travelUtility,double constant,double monetaryDistanceRate,double distanceUtility,double speed){
            this.travelUtility=travelUtility;this.constant=constant;this.monetaryDistanceRate=monetaryDistanceRate;
            this.distanceUtility=distanceUtility;this.speed=speed;
        }
    }
    private static List<Candidate> copy(List<Candidate> source){
        List<Candidate> result=new ArrayList<>();for(Candidate c:source){Candidate n=new Candidate(c.person,c.index,c.origin,c.destination,c.departure,c.direction);
            n.access=c.access;n.egress=c.egress;n.proxy=c.proxy;n.geometric=c.geometric;n.temporal=c.temporal;n.originPort=c.originPort;n.destinationPort=c.destinationPort;n.reason=c.reason;result.add(n);}
        return result;
    }
    double departure(Trip trip,Plan plan){try{return PlanRouter.calcEndOfActivity(trip.getOriginActivity(),plan,scenario.getConfig());}catch(RuntimeException e){return Double.NaN;}}
    static String direction(Trip trip){return trip.getOriginActivity().getType().startsWith("home")?"home_to_non_home":trip.getDestinationActivity().getType().startsWith("home")?"non_home_to_home":"non_home_to_non_home";}
    synchronized void outcome(Candidate c,String reason,Person person){c.reason=reason;if(person!=null)persist(person,current.getOrDefault(person.getId().toString(),List.of()));}
    private void persist(Person person,List<Candidate> candidates){
        StringBuilder value=new StringBuilder();for(Candidate c:candidates)value.append(c.index).append('|').append(point(c.origin)).append('|').append(point(c.destination)).append('|').append(c.departure).append('|').append(c.reason).append(';');
        person.getAttributes().putAttribute("aam_candidates",value.toString());
    }
    public synchronized Map<String,Long> metrics(){
        Map<String,Long> result=new LinkedHashMap<>();
        result.put("passengerAgentsEvaluated",(long)current.size());
        result.put("totalTripsEvaluated",current.values().stream().mapToLong(List::size).sum());
        result.put("geometricallyEligibleTrips",current.values().stream().flatMap(List::stream).filter(c->c.geometric).count());
        result.put("temporallyEligibleTrips",current.values().stream().flatMap(List::stream).filter(c->c.temporal).count());
        result.put("passengersWithEligibleCandidate",current.values().stream().filter(cs->cs.stream().anyMatch(c->c.temporal)).count());
        result.put("unresolvedCandidates",current.values().stream().flatMap(List::stream).filter(c->!"routed".equals(c.reason)).count());
        result.put("screenPasses",screenPasses.get());result.put("distanceCalculations",distanceCalculations.get());result.put("fullRoutingAttempts",routeAttempts.get());
        result.put("screeningMilliseconds",screenNanos.get()/1000000);result.put("routingMilliseconds",routingNanos.get()/1000000);
        current.values().stream().flatMap(List::stream).filter(c->!"routed".equals(c.reason)).forEach(c->result.merge("reason_"+c.reason,1L,Long::sum));
        return result;
    }
    public synchronized void write(Path directory)throws IOException{
        write(directory,true);
    }
    public synchronized void write(Path directory,boolean details)throws IOException{
        Files.createDirectories(directory);
        if(details)try(PrintWriter w=new PrintWriter(Files.newBufferedWriter(directory.resolve("candidates.csv")))){
            w.println("person,trip_index,origin_x,origin_y,destination_x,destination_y,departure_s,origin_vertiport,destination_vertiport,access_m,egress_m,geometric,temporal,reason,direction");
            for(List<Candidate> cs:current.values())for(Candidate c:cs)w.println(csv(c.person,c.index,c.origin==null?"":c.origin.getX(),c.origin==null?"":c.origin.getY(),c.destination==null?"":c.destination.getX(),c.destination==null?"":c.destination.getY(),c.departure,c.originPort,c.destinationPort,c.access,c.egress,c.geometric,c.temporal,c.reason,c.direction));
        }
        try(PrintWriter w=new PrintWriter(Files.newBufferedWriter(directory.resolve("screening.csv")))){w.println("metric,value");metrics().forEach((k,v)->w.println(k+","+v));}
        Map<String,Long> distribution=new TreeMap<>();
        for(List<Candidate> cs:current.values())for(Candidate c:cs)for(String side:List.of("access","egress")){
            double miles=("access".equals(side)?c.access:c.egress)/MILE;
            String bin=!Double.isFinite(miles)?"missing":miles>5?"over_5":Math.min(4,(int)miles)+"_to_"+(Math.min(4,(int)miles)+1);
            distribution.merge(side+","+("routed".equals(c.reason)?"routed":"screened_or_unresolved")+","+bin,1L,Long::sum);
        }
        try(PrintWriter w=new PrintWriter(Files.newBufferedWriter(directory.resolve("distance-distribution.csv")))){
            w.println("side,state,miles_bin,trips");distribution.forEach((k,v)->w.println(k+","+v));
        }
    }
    private static String csv(Object... values){StringJoiner row=new StringJoiner(",");for(Object v:values)row.add("\""+Objects.toString(v,"").replace("\"","\"\"")+"\"");return row.toString();}
    public static final class Candidate {
        public final String person,direction;public final int index;public final Coord origin,destination;public final double departure;
        public double access=Double.NaN,egress=Double.NaN,proxy;public boolean geometric,temporal;
        public String originPort="",destinationPort="",reason="unrouted";
        Candidate(String person,int index,Coord origin,Coord destination,double departure,String direction){this.person=person;this.index=index;this.origin=origin;this.destination=destination;this.departure=departure;this.direction=direction;}
    }
}
