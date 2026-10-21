package org.matsim.run.aam;

import java.nio.file.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.LongAdder;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.controler.events.IterationEndsEvent;
import org.matsim.core.controler.listener.IterationEndsListener;

/** Explicit per-mode/per-end routing coverage, including non-chosen alternatives. */
public final class AamFeederDiagnostics implements IterationEndsListener {
    private final Scenario scenario;private final ConcurrentMap<String,LongAdder> counts=new ConcurrentHashMap<>();
    private AamFeederDiagnostics(Scenario s){scenario=s;}
    public static AamFeederDiagnostics get(Scenario s){synchronized(s){
        AamFeederDiagnostics d=(AamFeederDiagnostics)s.getScenarioElement("aamFeederDiagnostics");
        if(d==null){d=new AamFeederDiagnostics(s);s.addScenarioElement("aamFeederDiagnostics",d);}return d;
    }}
    public void record(String mode,String end,String outcome){counts.computeIfAbsent(mode+","+end+","+outcome,key->new LongAdder()).increment();}
    @Override public synchronized void notifyIterationEnds(IterationEndsEvent event){
        Path path=Paths.get(scenario.getConfig().controler().getOutputDirectory(),"feeder-diagnostics","iteration-"+event.getIteration()+".csv");
        Map<String,Long> snapshot=new TreeMap<>();counts.forEach((key,value)->{long count=value.sumThenReset();if(count>0)snapshot.put(key,count);});
        try{Files.createDirectories(path.getParent());try(BufferedWriter w=Files.newBufferedWriter(path,StandardOpenOption.CREATE_NEW)){
            w.write("mode,end,outcome,count\n");for(Map.Entry<String,Long> entry:snapshot.entrySet())w.write(entry.getKey()+","+entry.getValue()+"\n");}
        }catch(IOException e){throw new UncheckedIOException(e);}counts.clear();
    }
}
