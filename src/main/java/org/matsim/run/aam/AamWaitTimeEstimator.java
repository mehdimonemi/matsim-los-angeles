package org.matsim.run.aam;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.events.handler.BasicEventHandler;
import static org.matsim.run.aam.RunDynamicAamLosAngelesScenario.AIR;

/** Learns request-specific AAM waits from completed requests in preceding mobsims. */
public final class AamWaitTimeEstimator implements BasicEventHandler {
    private final double binSize;
    private final Map<String,Pending> pending=new HashMap<>();
    private final ConcurrentMap<String,Stats> odTime=new ConcurrentHashMap<>(),originTime=new ConcurrentHashMap<>(),globalTime=new ConcurrentHashMap<>(),origin=new ConcurrentHashMap<>();
    private final Set<String> observedLinks=ConcurrentHashMap.newKeySet();
    private final Stats global=new Stats();

    public AamWaitTimeEstimator(){this(3600);}
    public AamWaitTimeEstimator(double binSize){if(!Double.isFinite(binSize)||binSize<=0)throw new IllegalArgumentException("binSize must be positive");this.binSize=binSize;}

    @Override public synchronized void reset(int iteration){pending.clear();}

    @Override public synchronized void handleEvent(Event event){
        Map<String,String> a=event.getAttributes();String type=event.getEventType();
        if("DrtRequest submitted".equals(type)&&AIR.equals(a.get("mode"))){
            pending.put(a.get("request"),new Pending(a.get("fromLink"),a.get("toLink"),event.getTime()));
        }else if("passenger picked up".equals(type)&&AIR.equals(a.get("mode"))){
            Pending p=pending.remove(a.get("request"));if(p!=null)record(p.from,p.to,p.submitted,event.getTime());
        }else if("PassengerRequest rejected".equals(type)&&AIR.equals(a.get("mode"))){
            pending.remove(a.get("request"));
        }
    }

    synchronized void record(String from,String to,double submitted,double pickup){
        double wait=pickup-submitted;if(!Double.isFinite(wait)||wait<0)return;
        observedLinks.add(from);observedLinks.add(to);
        long bin=bin(submitted,binSize);add(odTime,key(from,to,bin),wait);add(originTime,key(from,"",bin),wait);
        add(globalTime,Long.toString(bin),wait);add(origin,from,wait);global.add(wait);
    }

    public double estimate(Id<Link> from,Id<Link> to,double departure,double fallback,double maximum){
        String o=from.toString(),d=to.toString();long bin=bin(departure,binSize);Stats s=odTime.get(key(o,d,bin));
        // A newly introduced vertiport receives the common configured prior
        // until its first observed request, rather than inheriting another
        // vertiport's operational history.
        if(!observedLinks.contains(o)||!observedLinks.contains(d))return Math.max(0,Math.min(maximum,fallback));
        if(s==null)s=originTime.get(key(o,"",bin));if(s==null)s=globalTime.get(Long.toString(bin));
        if(s==null)s=origin.get(o);if(s==null&&global.count()>0)s=global;
        double estimate=s==null?fallback:s.mean();return Math.max(0,Math.min(maximum,estimate));
    }

    public synchronized void read(Path path)throws IOException{
        if(path==null||!Files.isRegularFile(path))return;
        try(BufferedReader reader=Files.newBufferedReader(path)){
            String line;boolean header=true;while((line=reader.readLine())!=null){if(header){header=false;continue;}if(line.trim().isEmpty())continue;
                String[] f=line.split(",");if(f.length!=5)throw new IOException("Invalid AAM wait-prior row: "+line);
                String from=f[0],to=f[1];long bin=Long.parseLong(f[2]),count=Long.parseLong(f[3]);double mean=Double.parseDouble(f[4]);
                addWeighted(odTime,key(from,to,bin),count,mean);addWeighted(originTime,key(from,"",bin),count,mean);
                addWeighted(globalTime,Long.toString(bin),count,mean);addWeighted(origin,from,count,mean);global.add(count,mean);
                observedLinks.add(from);observedLinks.add(to);
            }
        }
    }
    public synchronized void write(Path path)throws IOException{
        Files.createDirectories(path.toAbsolutePath().getParent());
        try(PrintWriter writer=new PrintWriter(Files.newBufferedWriter(path))){writer.println("from,to,time_bin,count,mean_wait_s");
            List<String> keys=new ArrayList<>(odTime.keySet());Collections.sort(keys);for(String key:keys){String[] f=key.split("\\|",-1);Stats s=odTime.get(key);
                writer.printf(Locale.ROOT,"%s,%s,%s,%d,%.9f%n",f[0],f[1],f[2],s.count,s.mean);}
        }
    }

    private static long bin(double time,double size){return (long)Math.floor(time/size);}
    private static String key(String from,String to,long bin){return from+'|'+to+'|'+bin;}
    private static void add(Map<String,Stats> map,String key,double wait){map.computeIfAbsent(key,k->new Stats()).add(wait);}
    private static void addWeighted(Map<String,Stats> map,String key,long count,double mean){map.computeIfAbsent(key,k->new Stats()).add(count,mean);}
    private static final class Pending {final String from,to;final double submitted;Pending(String f,String t,double s){from=f;to=t;submitted=s;}}
    private static final class Stats {
        private long count;private double mean;
        synchronized void add(double value){add(1,value);}
        synchronized void add(long n,double value){if(n<=0)return;mean=(mean*count+value*n)/(count+n);count+=n;}
        synchronized long count(){return count;}
        synchronized double mean(){return mean;}
    }
}
