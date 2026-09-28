package org.matsim.run.aam;

import javax.inject.Inject;
import org.matsim.contrib.drt.analysis.DrtModeAnalysisModule;
import org.matsim.contrib.drt.run.*;
import org.matsim.core.controler.AbstractModule;

/**
 * MATSim 13 multi-mode DRT services without rebinding MainModeIdentifier.
 * The LA scenario's SwissRailRaptor module already owns that global binding.
 */
public final class AamMultiModeDrtModule extends AbstractModule {
    @Inject private MultiModeDrtConfigGroup config;
    @Override public void install(){
        for(DrtConfigGroup mode:config.getModalElements()){
            install(new DrtModeModule(mode));
            installQSimModule(new DrtModeQSimModule(mode));
            install(new DrtModeAnalysisModule(mode));
        }
    }
}
