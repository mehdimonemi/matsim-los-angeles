package org.matsim.run.aam;
import java.util.List;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.router.*;
import org.matsim.run.LosAngelesIntermodalPtDrtRouterAnalysisModeIdentifier;
/** Count complete AAM chains once and delegate all existing LA modes. */
public final class AamMainModeIdentifier implements MainModeIdentifier,AnalysisMainModeIdentifier {
    private final LosAngelesIntermodalPtDrtRouterAnalysisModeIdentifier delegate=new LosAngelesIntermodalPtDrtRouterAnalysisModeIdentifier();
    public String identifyMainMode(List<? extends PlanElement> es){
        for(PlanElement e:es)if(e instanceof Leg && List.of("aam","aam_drt").contains(((Leg)e).getMode()))return "aam";
        return delegate.identifyMainMode(es);
    }
}
