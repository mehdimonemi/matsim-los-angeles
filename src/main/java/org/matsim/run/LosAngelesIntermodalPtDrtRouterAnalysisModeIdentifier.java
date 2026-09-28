/* *********************************************************************** *
 * AAM-aware variant of the Los Angeles analysis main-mode identifier.
 * *********************************************************************** */
package org.matsim.run;

import java.util.*;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.router.AnalysisMainModeIdentifier;
import org.matsim.core.router.TripStructureUtils;
import com.google.inject.Inject;

public final class LosAngelesIntermodalPtDrtRouterAnalysisModeIdentifier implements AnalysisMainModeIdentifier {
    private final List<String> modeHierarchy=new ArrayList<>();
    private final List<String> drtModes;
    private static final Logger log=Logger.getLogger(LosAngelesIntermodalPtDrtRouterAnalysisModeIdentifier.class);
    @Inject public LosAngelesIntermodalPtDrtRouterAnalysisModeIdentifier(){
        drtModes=Arrays.asList(TransportMode.drt,"drt1","drt2","drt_teleportation","drt1_teleportation","drt2_teleportation");
        modeHierarchy.add(TransportMode.walk);modeHierarchy.add("access_egress_pt");modeHierarchy.add("bike");
        modeHierarchy.add(TransportMode.ride);modeHierarchy.add("ride_taxi");modeHierarchy.add("ride_school_bus");
        modeHierarchy.add(TransportMode.car);modeHierarchy.addAll(drtModes);modeHierarchy.add(TransportMode.pt);modeHierarchy.add("freight");
    }
    @Override public String identifyMainMode(List<? extends PlanElement> elements){
        for(PlanElement pe:elements)if(pe instanceof Leg){
            String routingMode=TripStructureUtils.getRoutingMode((Leg)pe);
            if("scheduled_aam".equals(routingMode))return "scheduled_aam";
        }
        // A complete intermodal chain must be counted once as AAM, regardless of
        // the access/egress modes surrounding its dynamic aircraft leg.
        for(PlanElement pe:elements)if(pe instanceof Leg){String m=((Leg)pe).getMode();
            if("aam".equals(m)||"aam_drt".equals(m))return "aam";
        }
        int main=-1;List<String> found=new ArrayList<>();
        for(PlanElement pe:elements){if(!(pe instanceof Leg))continue;String mode=((Leg)pe).getMode();
            if(TransportMode.non_network_walk.equals(mode))continue;
            if(TransportMode.transit_walk.equals(mode))mode=TransportMode.pt;
            else for(String d:drtModes)if(mode.equals(d+"_fallback"))mode=d;
            found.add(mode);int index=modeHierarchy.indexOf(mode);
            if(index<0)throw new RuntimeException("unknown mode="+mode);if(index>main)main=index;
        }
        if(main<0)throw new RuntimeException("no main mode found for trip "+elements);
        String result=modeHierarchy.get(main);if(!TransportMode.pt.equals(result))return result;
        boolean accessEgressPt=false,drt=false;
        for(String mode:found){
            if(TransportMode.pt.equals(mode)||TransportMode.walk.equals(mode))continue;
            if("access_egress_pt".equals(mode)){accessEgressPt=true;continue;}
            if(drtModes.contains(mode)){drt=true;continue;}
            log.error("unknown intermodal pt trip: "+elements);throw new RuntimeException("unknown intermodal pt trip");
        }
        return accessEgressPt?"pt_with_access_egress_pt":drt?"pt_with_drt":TransportMode.pt;
    }
}
