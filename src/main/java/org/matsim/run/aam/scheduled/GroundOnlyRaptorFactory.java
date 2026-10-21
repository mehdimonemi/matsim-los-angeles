package org.matsim.run.aam.scheduled;

import javax.inject.*;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.Config;
import org.matsim.core.scenario.*;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.pt.transitSchedule.api.*;
import ch.sbb.matsim.routing.pt.raptor.*;

/** Ordinary PT must not bypass AAM feeder, fare-aware and queue-aware routing. */
@Singleton public final class GroundOnlyRaptorFactory implements Provider<SwissRailRaptor> {
    private final SwissRailRaptorFactory delegate;
    @Inject public GroundOnlyRaptorFactory(Scenario full,Config config,RaptorParametersForPerson parameters,
            RaptorRouteSelector selector,Provider<RaptorStopFinder> stops,OccupancyData occupancy,
            RaptorInVehicleCostCalculator inVehicle,RaptorTransferCostCalculator transfer,EventsManager events){
        MutableScenario ground=(MutableScenario)ScenarioUtils.createScenario(config);
        ground.setNetwork(full.getNetwork());ground.setTransitVehicles(full.getTransitVehicles());
        TransitSchedule schedule=ground.getTransitSchedule();
        full.getTransitSchedule().getFacilities().values().stream()
            .filter(f->!f.getId().toString().startsWith("aam_sched_stop_")).forEach(schedule::addStopFacility);
        full.getTransitSchedule().getTransitLines().values().stream()
            .filter(l->!l.getId().toString().startsWith("aam_sched_line_")).forEach(schedule::addTransitLine);
        MinimalTransferTimes.MinimalTransferTimesIterator it=full.getTransitSchedule().getMinimalTransferTimes().iterator();
        while(it.hasNext()){it.next();if(schedule.getFacilities().containsKey(it.getFromStopId())&&schedule.getFacilities().containsKey(it.getToStopId()))
            schedule.getMinimalTransferTimes().set(it.getFromStopId(),it.getToStopId(),it.getSeconds());}
        delegate=new SwissRailRaptorFactory(ground,config,parameters,selector,stops,occupancy,inVehicle,transfer,events);
    }
    @Override public SwissRailRaptor get(){return delegate.get();}
}
