package org.matsim.run.aam;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.stream.Collectors;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.controler.events.IterationEndsEvent;
import org.matsim.core.controler.listener.IterationEndsListener;
import static org.matsim.run.aam.RunDynamicAamLosAngelesScenario.*;

/** Event-based fleet audit. Passenger pickup/dropoff events exclude the vehicle driver. */
public final class AamFleetMetrics implements BasicEventHandler,IterationEndsListener {
    private final Scenario scenario;private final int aircraft;
    private final Map<String,V> vehicles=new TreeMap<>();
    private final Map<String,R> requests=new LinkedHashMap<>();
    private final Map<String,R> activeRequest=new HashMap<>();
    private final List<String> trajectories=new ArrayList<>();
    public AamFleetMetrics(Scenario s,int air){scenario=s;aircraft=air;reset(0);}
    public void reset(int iteration){vehicles.clear();requests.clear();activeRequest.clear();trajectories.clear();
        for(int i=0;i<aircraft;i++){
            String id=String.format(Locale.ROOT,"%s_%04d",AIR,i);vehicles.put(id,new V(id,AIR));}}
    public void handleEvent(Event e){
        String type=e.getEventType();
        if(!List.of("DrtRequest submitted","PassengerRequest rejected","passenger picked up","passenger dropped off",
                "personMoney","vehicle enters traffic","vehicle leaves traffic","entered link","left link").contains(type))return;
        Map<String,String> a=e.getAttributes();String mode=a.get("mode"),rid=a.get("request");
        if(type.equals("DrtRequest submitted") && AIR.equals(mode)){
            R r=new R();r.mode=mode;r.id=rid;r.person=a.get("person");r.submitted=e.getTime();
            r.from=a.get("fromLink");r.to=a.get("toLink");r.directDistance=num(a,"unsharedRideDistance",0);r.directTime=num(a,"unsharedRideTime",0);
            requests.put(mode+":"+rid,r);activeRequest.put(mode+":"+r.person,r);return;
        }
        if(type.equals("PassengerRequest rejected")){R r=requests.get(mode+":"+rid);if(r!=null){r.rejected=true;r.cause=a.get("cause");}return;}
        if(type.equals("personMoney")){
            R r=activeRequest.get(a.get("transactionPartner")+":"+a.get("person"));
            if(r!=null&&"drtFare".equals(a.get("purpose")))r.fare-=num(a,"amount",0);return;
        }
        V v=vehicles.get(a.get("vehicle"));if(v==null)return;
        if(type.equals("passenger picked up")){
            v.occupancy++;v.maxOccupancy=Math.max(v.maxOccupancy,v.occupancy);v.pickups++;
            R r=requests.get(mode+":"+rid);if(r!=null){r.pickup=e.getTime();r.vehicle=v.id;}return;
        }
        if(type.equals("passenger dropped off")){
            v.occupancy--;if(v.occupancy<0)throw new IllegalStateException("Negative passenger load "+v.id);
            R r=requests.get(mode+":"+rid);if(r!=null)r.dropoff=e.getTime();return;
        }
        if(type.equals("vehicle enters traffic")){
            v.driveStart=e.getTime();v.driveDistance=0;v.driveEmpty=v.occupancy==0;
            v.link=a.get("link");v.enter=e.getTime();v.startPosition=num(a,"relativePosition",1);return;
        }
        if(type.equals("entered link")){v.link=a.get("link");v.enter=e.getTime();v.startPosition=0;return;}
        if(type.equals("left link")){finishLink(v,a.get("link"),e.getTime(),1);return;}
        if(type.equals("vehicle leaves traffic")){
            finishLink(v,a.get("link"),e.getTime(),num(a,"relativePosition",1));
            if(Double.isFinite(v.driveStart)&&v.driveDistance>0){
                v.driveLegs++;v.driveTime+=e.getTime()-v.driveStart;
                if(v.driveEmpty){v.emptyLegs++;v.emptyTime+=e.getTime()-v.driveStart;}
            }
            v.driveStart=Double.NaN;
        }
    }
    private void finishLink(V v,String id,double time,double position){
        if(v.link==null||!v.link.equals(id))return;
        Link l=scenario.getNetwork().getLinks().get(Id.createLinkId(id));if(l==null)return;
        double d=l.getLength()*Math.max(0,position-v.startPosition);
        v.distance+=d;v.driveDistance+=d;v.passengerDistance+=d*v.occupancy;if(v.occupancy==0)v.emptyDistance+=d;
        if(v.mode.equals(AIR)&&id.startsWith("aam_air_")&&d>0)
            trajectories.add(String.join(",",v.id,id,Double.toString(v.enter),Double.toString(time),Integer.toString(v.occupancy),
                Double.toString(l.getFromNode().getCoord().getX()),Double.toString(l.getFromNode().getCoord().getY()),
                Double.toString(l.getToNode().getCoord().getX()),Double.toString(l.getToNode().getCoord().getY())));
        v.link=null;
    }
    public void notifyIterationEnds(IterationEndsEvent event){
        try{write(event.getIteration());}catch(IOException e){throw new UncheckedIOException(e);}
    }
    public void write(int iteration)throws IOException{
        Path root=Paths.get(scenario.getConfig().controler().getOutputDirectory(),"aam_metrics");
        Path dir=root.resolve("iteration_"+iteration);Files.createDirectories(dir);
        try(PrintWriter w=writer(dir,"requests.csv")){
            w.println("iteration,mode,request,person,vehicle,from_link,to_link,submitted_s,pickup_s,dropoff_s,wait_s,in_vehicle_s,direct_distance_m,direct_time_s,fare_usd,rejected,rejection_cause,hh_income_usd,hh_size,age,gender");
            for(R r:requests.values()){
                Person p=scenario.getPopulation().getPersons().get(Id.createPersonId(r.person));
                w.println(csv(iteration,r.mode,r.id,r.person,r.vehicle,r.from,r.to,r.submitted,finite(r.pickup),finite(r.dropoff),
                    finite(r.pickup-r.submitted),finite(r.dropoff-r.pickup),r.directDistance,r.directTime,r.fare,r.rejected,r.cause,
                    attr(p,"hhinc"),attr(p,"hhsize"),attr(p,"age"),attr(p,"gender")));
            }
        }
        try(PrintWriter w=writer(dir,"vehicles.csv")){
            w.println("iteration,mode,vehicle,passenger_pickups,drive_legs,empty_drive_legs,distance_m,empty_distance_m,passenger_distance_m,drive_time_s,empty_drive_time_s,max_passengers");
            for(V v:vehicles.values())w.println(csv(iteration,v.mode,v.id,v.pickups,v.driveLegs,v.emptyLegs,v.distance,v.emptyDistance,v.passengerDistance,v.driveTime,v.emptyTime,v.maxOccupancy));
        }
        try(PrintWriter w=writer(dir,"air_trajectories.csv")){
            w.println("vehicle,link,enter_s,leave_s,passengers,from_x,from_y,to_x,to_y");for(String r:trajectories)w.println(r);
        }
        try(PrintWriter w=writer(dir,"fleet_metrics.csv")){
            w.println("iteration,mode,fleet,vehicles_moved,vehicles_with_passengers,requests,served,rejected,unfinished,distinct_users,vehicle_legs,empty_vehicle_legs,vehicle_km,empty_km,empty_km_pct,passenger_km,mean_occupancy_all_km,drive_hours,empty_drive_hours,mean_wait_min,p95_wait_min,mean_in_vehicle_min,revenue_usd,same_link_requests");
            for(String mode:List.of(AIR)){
                List<V> vs=vehicles.values().stream().filter(v->v.mode.equals(mode)).collect(Collectors.toList());
                List<R> rs=requests.values().stream().filter(r->r.mode.equals(mode)).collect(Collectors.toList());
                List<R> served=rs.stream().filter(r->Double.isFinite(r.dropoff)).collect(Collectors.toList());
                double km=vs.stream().mapToDouble(v->v.distance).sum()/1000,ekm=vs.stream().mapToDouble(v->v.emptyDistance).sum()/1000;
                double pkm=vs.stream().mapToDouble(v->v.passengerDistance).sum()/1000;
                long rejected=rs.stream().filter(r->r.rejected).count();
                double[] waits=served.stream().mapToDouble(r->(r.pickup-r.submitted)/60).sorted().toArray();
                double mean=Arrays.stream(waits).average().orElse(Double.NaN),p95=waits.length==0?Double.NaN:waits[(int)Math.ceil(.95*waits.length)-1];
                w.println(csv(iteration,mode,vs.size(),vs.stream().filter(v->v.distance>0).count(),vs.stream().filter(v->v.pickups>0).count(),
                    rs.size(),served.size(),rejected,rs.size()-served.size()-rejected,served.stream().map(r->r.person).distinct().count(),
                    vs.stream().mapToLong(v->v.driveLegs).sum(),vs.stream().mapToLong(v->v.emptyLegs).sum(),km,ekm,finite(km>0?100*ekm/km:Double.NaN),
                    pkm,finite(km>0?pkm/km:Double.NaN),vs.stream().mapToDouble(v->v.driveTime).sum()/3600,vs.stream().mapToDouble(v->v.emptyTime).sum()/3600,
                    finite(mean),finite(p95),finite(served.stream().mapToDouble(r->(r.dropoff-r.pickup)/60).average().orElse(Double.NaN)),
                    rs.stream().mapToDouble(r->r.fare).sum(),rs.stream().filter(r->Objects.equals(r.from,r.to)).count()));
            }
        }
        if(iteration==scenario.getConfig().controler().getLastIteration()){
            Files.copy(dir.resolve("fleet_metrics.csv"),root.resolve("final_fleet_metrics.csv"),StandardCopyOption.REPLACE_EXISTING);
            Files.writeString(root.resolve("COMPLETED.txt"),"Iteration "+iteration+" completed. All metrics derived from actual events.\n");
        }
    }
    private static PrintWriter writer(Path p,String f)throws IOException{return new PrintWriter(Files.newBufferedWriter(p.resolve(f)));}
    private static String attr(Person p,String k){return p==null?"":Objects.toString(p.getAttributes().getAttribute(k),"");}
    private static double num(Map<String,String>a,String k,double fallback){try{return Double.parseDouble(a.get(k));}catch(Exception e){return fallback;}}
    private static Object finite(double d){return Double.isFinite(d)?d:"";}
    private static String csv(Object...xs){return Arrays.stream(xs).map(x->Objects.toString(x,"").replace("\"","\"\"")).map(x->"\""+x+"\"").collect(Collectors.joining(","));}
    private static final class V {final String id,mode;int occupancy,maxOccupancy,pickups,driveLegs,emptyLegs;
        double distance,emptyDistance,passengerDistance,driveTime,emptyTime,driveDistance,enter,startPosition,driveStart=Double.NaN;boolean driveEmpty;String link;
        V(String i,String m){id=i;mode=m;}}
    private static final class R {String mode,id,person,vehicle="",from,to,cause="";double submitted,directDistance,directTime,fare,pickup=Double.NaN,dropoff=Double.NaN;boolean rejected;}
}
