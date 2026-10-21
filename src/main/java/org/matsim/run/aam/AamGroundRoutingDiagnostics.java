package org.matsim.run.aam;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.LongAdder;
import org.matsim.api.core.v01.Scenario;

/** Counts actual ground-route calculations by startup phase and runtime caller. */
public final class AamGroundRoutingDiagnostics {
    private final ConcurrentMap<String,LongAdder> routes=new ConcurrentHashMap<>();
    private final ConcurrentMap<String,LongAdder> nanos=new ConcurrentHashMap<>();
    private AamGroundRoutingDiagnostics(){}
    public static AamGroundRoutingDiagnostics get(Scenario scenario){synchronized(scenario){
        AamGroundRoutingDiagnostics d=(AamGroundRoutingDiagnostics)scenario.getScenarioElement("aamGroundRoutingDiagnostics");
        if(d==null){d=new AamGroundRoutingDiagnostics();scenario.addScenarioElement("aamGroundRoutingDiagnostics",d);}return d;
    }}
    public void record(String context,long elapsed){routes.computeIfAbsent(context,k->new LongAdder()).increment();nanos.computeIfAbsent(context,k->new LongAdder()).add(elapsed);}
    public synchronized void write(Path path)throws IOException{
        Files.createDirectories(path.getParent());
        try(BufferedWriter w=Files.newBufferedWriter(path,StandardOpenOption.CREATE,StandardOpenOption.TRUNCATE_EXISTING)){
            w.write("context,routedGroundTrips,routingMilliseconds\n");
            Set<String> contexts=new TreeSet<>(routes.keySet());contexts.addAll(nanos.keySet());
            for(String context:contexts)w.write(context+","+routes.getOrDefault(context,new LongAdder()).sum()+","+nanos.getOrDefault(context,new LongAdder()).sum()/1000000+"\n");
        }
    }
}
