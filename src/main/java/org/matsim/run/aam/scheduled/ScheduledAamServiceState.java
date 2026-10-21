package org.matsim.run.aam.scheduled;

import java.util.*;
import javax.inject.Inject;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.pt.transitSchedule.api.*;

/** Event-derived queue forecasts and fares. Shared by all routing workers. */
public final class ScheduledAamServiceState implements BasicEventHandler, org.matsim.core.controler.listener.IterationEndsListener {
    private final Scenario scenario;
    private final ScheduledAamConfigGroup config;
    private final EventsManager events;
    private final Map<String,String> lines=new HashMap<>();
    private final Set<String> drivers=new HashSet<>();
    private final Map<String,Pending> pending=new HashMap<>();
    private final Map<String,double[]> history=new HashMap<>();
    private final Map<String,double[]> currentHistory=new HashMap<>();
    private final Map<String,Integer> loads=new HashMap<>();
    private final Map<String,Integer> previousLoads=new HashMap<>();
    private final Map<String,Integer> currentLoads=new HashMap<>();
    private final Map<String,Integer> reservations=new HashMap<>();
    private boolean reserving;
    public synchronized void beginReservations(){reservations.clear();reserving=true;}
    public synchronized void endReservations(){reserving=false;}
    public synchronized void reserve(org.matsim.api.core.v01.population.Plan plan){
        for(org.matsim.api.core.v01.population.PlanElement e:plan.getPlanElements())if(e instanceof org.matsim.api.core.v01.population.Leg){
            org.matsim.api.core.v01.population.Route r=((org.matsim.api.core.v01.population.Leg)e).getRoute();
            if(!(r instanceof org.matsim.pt.routes.TransitPassengerRoute))continue;
            org.matsim.pt.routes.TransitPassengerRoute pt=(org.matsim.pt.routes.TransitPassengerRoute)r;
            if(pt.getLineId()==null||!pt.getLineId().toString().startsWith("aam_sched_line_"))continue;
            TransitRoute route=scenario.getTransitSchedule().getTransitLines().get(pt.getLineId()).getRoutes().get(pt.getRouteId());
            for(Departure d:route.getDepartures().values())if(Math.abs(d.getDepartureTime()-pt.getBoardingTime().orElse(-1))<1e-6)
                reservations.merge(pt.getLineId()+"|"+d.getId(),1,Integer::sum);
        }
    }
    public ScheduledAamServiceState(Scenario s,EventsManager e){scenario=s;events=e;config=org.matsim.core.config.ConfigUtils.addOrGetModule(s.getConfig(),ScheduledAamConfigGroup.class);
        if(!config.getQueuePriorsFile().isEmpty())try{
            java.net.URL url=org.matsim.core.config.ConfigGroup.getInputFileURL(s.getConfig().getContext(),config.getQueuePriorsFile());
            try(java.io.BufferedReader reader=new java.io.BufferedReader(new java.io.InputStreamReader(url.openStream(),java.nio.charset.StandardCharsets.UTF_8))){
                String row=reader.readLine();while((row=reader.readLine())!=null){String[] f=row.split(",",-1);
                    if(f.length!=4)throw new java.io.IOException("Invalid queue prior: "+row);
                    if("queue".equals(f[0]))history.put(f[1],new double[]{Double.parseDouble(f[2]),Double.parseDouble(f[3])});
                    else if("load".equals(f[0]))previousLoads.put(f[1],Integer.parseInt(f[2]));
                }
            }
        }catch(java.io.IOException error){throw new java.io.UncheckedIOException(error);}
    }
    public static ScheduledAamServiceState get(Scenario s){return (ScheduledAamServiceState)s.getScenarioElement("scheduledAamServiceState");}
    private static String key(String line,double time){return line+"|"+(long)Math.floor(time/3600);}
    public synchronized double forecastWait(String line,double arrival){double[] v=history.get(key(line,arrival));return reserving||v==null?0:v[0]/v[1];}
    public synchronized boolean previouslyFull(String line,String departure){return (reserving?reservations:previousLoads).getOrDefault(line+"|"+departure,0)>=config.getSeats();}
    @Override public synchronized void reset(int iteration){
        if(iteration>scenario.getConfig().controler().getFirstIteration()){
            previousLoads.clear();previousLoads.putAll(currentLoads);history.clear();history.putAll(currentHistory);
        }
        currentHistory.clear();currentLoads.clear();lines.clear();drivers.clear();pending.clear();loads.clear();
    }
    @Override public synchronized void handleEvent(Event e){
        Map<String,String>a=e.getAttributes();String type=e.getEventType(),person=a.get("person"),vehicle=a.get("vehicle");
        if("TransitDriverStarts".equals(type)&&a.getOrDefault("transitLineId","").startsWith("aam_sched_line_")){
            lines.put(a.get("vehicleId"),a.get("transitLineId"));drivers.add(a.get("driverId"));
        }else if("waitingForPt".equals(type)&&a.getOrDefault("atStop","").startsWith("aam_sched_stop_")){
            pending.put(person,new Pending(e.getTime(),"aam_sched_line_"+a.get("atStop").substring(15)+"_"+a.get("destinationStop").substring(15)));
        }else if("PersonEntersVehicle".equals(type)&&lines.containsKey(vehicle)&&!drivers.contains(person)){
            String line=lines.get(vehicle);Pending p=pending.remove(person);
            if(p!=null){
                TransitLine observed=scenario.getTransitSchedule().getTransitLines().get(Id.create(line,TransitLine.class));
                double first=observed.getRoutes().values().iterator().next().getDepartures().values().stream()
                    .mapToDouble(Departure::getDepartureTime).filter(t->t>=p.time-1e-6).min().orElse(e.getTime());
                double[] v=currentHistory.computeIfAbsent(key(line,p.time),k->new double[2]);
                // Excess queue delay only; timetable residual waiting is added by the router.
                v[0]+=Math.max(0,e.getTime()-Math.max(first,p.time));v[1]++;
            }
            loads.merge(vehicle,1,Integer::sum);
            String pair=line.substring("aam_sched_line_".length());
            double distance=scenario.getNetwork().getLinks().get(Id.createLinkId("aam_sched_flight_"+pair)).getLength();
            if(events!=null)events.processEvent(new PersonMoneyEvent(e.getTime(),Id.createPersonId(person),-fare(distance),"scheduledAamFare","scheduled_aam"));
        }else if("VehicleDepartsAtFacility".equals(type)&&lines.containsKey(vehicle)){
            String line=lines.get(vehicle);String sequence=vehicle.substring(vehicle.lastIndexOf('_')+1);
            currentLoads.merge(line+"|aam_sched_departure_"+sequence,loads.getOrDefault(vehicle,0),Math::max);
        }
    }
    public double fare(double meters){return config.getBaseFare()+config.getFarePerMile()*meters/1609.344;}
    @Override public synchronized void notifyIterationEnds(org.matsim.core.controler.events.IterationEndsEvent event){
        java.nio.file.Path path=java.nio.file.Paths.get(scenario.getConfig().controler().getOutputDirectory(),"scheduled-aam-service","iteration-"+event.getIteration()+".csv");
        try{java.nio.file.Files.createDirectories(path.getParent());
            try(java.io.BufferedWriter out=java.nio.file.Files.newBufferedWriter(path,java.nio.file.StandardOpenOption.CREATE_NEW)){
                out.write("kind,key,sum_or_load,count\n");
                for(String k:new TreeSet<>(currentHistory.keySet())){double[] v=currentHistory.get(k);out.write("queue,"+k+","+v[0]+","+v[1]+"\n");}
                for(String k:new TreeSet<>(currentLoads.keySet()))out.write("load,"+k+","+currentLoads.get(k)+",1\n");
            }
        }catch(java.io.IOException e){throw new java.io.UncheckedIOException(e);}
    }
    private static final class Pending{final double time;final String line;Pending(double t,String l){time=t;line=l;}}
}
