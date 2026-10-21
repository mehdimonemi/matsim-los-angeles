package org.matsim.run.aam;

import java.util.*;
import org.matsim.core.config.ReflectiveConfigGroup;

/** Explicit input settings for the intermodal AAM extension (MATSim 13). */
public final class AamConfigGroup extends ReflectiveConfigGroup {
    private String accessEgressModes="car,ride,ride_taxi,walk,bike";
    private int candidateVertiports=3;
    private int drtMatrixCellSize=5000;
    private String activeVertiportsFile="active-vertiports.csv";
    private int activeVertiportCount=10;
    private double baseFare=0, farePerMile=2, expectedWaitTime=120, maxWaitTime=900;
    private double maxAccessDistanceMiles=5, minimumTripDistanceMiles=3, waitTimeBin=3600;
    private Double maxEgressDistanceMiles;
    private boolean allowPreServiceRequests=true;
    private boolean cacheFeederRoutes=true;
    private boolean seedAlternativesAtStartup=true;
    @StringGetter("seedAlternativesAtStartup") public boolean getSeedAlternativesAtStartup(){return seedAlternativesAtStartup;}
    @StringSetter("seedAlternativesAtStartup") public void setSeedAlternativesAtStartup(boolean v){seedAlternativesAtStartup=v;}
    @StringGetter("cacheFeederRoutes") public boolean getCacheFeederRoutes(){return cacheFeederRoutes;}
    @StringSetter("cacheFeederRoutes") public void setCacheFeederRoutes(boolean v){cacheFeederRoutes=v;}
    private int maximumRoutedCandidates=2, protectedAlternatives=1;
    private int maximumCandidateVertiportPairs=3;
    @StringGetter("maximumCandidateVertiportPairs") public int getMaximumCandidateVertiportPairs(){return maximumCandidateVertiportPairs;}
    @StringSetter("maximumCandidateVertiportPairs") public void setMaximumCandidateVertiportPairs(int v){if(v<1)throw new IllegalArgumentException("maximumCandidateVertiportPairs must be positive");maximumCandidateVertiportPairs=v;}
    @StringGetter("maxEgressDistanceMiles") public double getMaxEgressDistanceMiles(){return maxEgressDistanceMiles==null?maxAccessDistanceMiles:maxEgressDistanceMiles;}
    @StringSetter("maxEgressDistanceMiles") public void setMaxEgressDistanceMiles(double v){maxEgressDistanceMiles=nonnegative(v);}
    @StringGetter("allowPreServiceRequests") public boolean getAllowPreServiceRequests(){return allowPreServiceRequests;}
    @StringSetter("allowPreServiceRequests") public void setAllowPreServiceRequests(boolean v){allowPreServiceRequests=v;}
    @StringGetter("maximumRoutedCandidates") public int getMaximumRoutedCandidates(){return maximumRoutedCandidates;}
    @StringSetter("maximumRoutedCandidates") public void setMaximumRoutedCandidates(int v){if(v<1)throw new IllegalArgumentException("maximumRoutedCandidates must be positive");maximumRoutedCandidates=v;}
    private double initialExplorationFraction=0;
    private boolean allowCarAtHomeAlternatives=false;
    @StringGetter("allowCarAtHomeAlternatives") public boolean getAllowCarAtHomeAlternatives(){return allowCarAtHomeAlternatives;}
    @StringSetter("allowCarAtHomeAlternatives") public void setAllowCarAtHomeAlternatives(boolean v){allowCarAtHomeAlternatives=v;}
    @StringGetter("initialExplorationFraction") public double getInitialExplorationFraction(){return initialExplorationFraction;}
    @StringSetter("initialExplorationFraction") public void setInitialExplorationFraction(double v){if(!Double.isFinite(v)||v<0||v>1)throw new IllegalArgumentException("initialExplorationFraction must be in [0,1]");initialExplorationFraction=v;}
    @StringGetter("protectedAlternatives") public int getProtectedAlternatives(){return protectedAlternatives;}
    @StringSetter("protectedAlternatives") public void setProtectedAlternatives(int v){if(v<1)throw new IllegalArgumentException("protectedAlternatives must be positive");protectedAlternatives=v;}
    private double serviceStartTime=0, serviceEndTime=36*3600;
    private double minimumInnovationFreeFraction=0.2;
    private double maximumWalkDistance=1000, maximumWalkTime=1200;
    private double insertionEstimateSpeedFactor=1.0;
    @StringGetter("insertionEstimateSpeedFactor") public double getInsertionEstimateSpeedFactor(){return insertionEstimateSpeedFactor;}
    @StringSetter("insertionEstimateSpeedFactor") public void setInsertionEstimateSpeedFactor(double v){if(!Double.isFinite(v)||v<=0||v>1)throw new IllegalArgumentException("insertionEstimateSpeedFactor must be in (0,1]");insertionEstimateSpeedFactor=v;}
    @StringGetter("maximumWalkDistance") public double getMaximumWalkDistance(){return maximumWalkDistance;}
    @StringSetter("maximumWalkDistance") public void setMaximumWalkDistance(double v){maximumWalkDistance=nonnegative(v);}
    @StringGetter("maximumWalkTime") public double getMaximumWalkTime(){return maximumWalkTime;}
    @StringSetter("maximumWalkTime") public void setMaximumWalkTime(double v){maximumWalkTime=nonnegative(v);}
    public AamConfigGroup(){super("aam");}
    @StringGetter("accessEgressModes") public String getAccessEgressModes(){return accessEgressModes;}
    @StringSetter("accessEgressModes") public void setAccessEgressModes(String value){
        Set<String> allowed=Set.of("car","ride","ride_taxi","walk","bike");
        for(String m:value.split(","))if(!allowed.contains(m.trim()))throw new IllegalArgumentException("Unsupported AAM access/egress mode: "+m);
        accessEgressModes=value;
    }
    public List<String> modes(){List<String> r=new ArrayList<>();for(String m:accessEgressModes.split(","))r.add(m.trim());return r;}
    @StringGetter("candidateVertiports") public int getCandidateVertiports(){return candidateVertiports;}
    @StringSetter("candidateVertiports") public void setCandidateVertiports(int v){if(v<1)throw new IllegalArgumentException("candidateVertiports >=1");candidateVertiports=v;}
    @StringGetter("drtMatrixCellSize") public int getDrtMatrixCellSize(){return drtMatrixCellSize;}
    @StringSetter("drtMatrixCellSize") public void setDrtMatrixCellSize(int v){if(v<500)throw new IllegalArgumentException("drtMatrixCellSize must be >= 500 m");drtMatrixCellSize=v;}
    @StringGetter("activeVertiportsFile") public String getActiveVertiportsFile(){return activeVertiportsFile;}
    @StringSetter("activeVertiportsFile") public void setActiveVertiportsFile(String v){if(v==null||v.trim().isEmpty())throw new IllegalArgumentException("activeVertiportsFile is required");activeVertiportsFile=v.trim();}
    @StringGetter("activeVertiportCount") public int getActiveVertiportCount(){return activeVertiportCount;}
    @StringSetter("activeVertiportCount") public void setActiveVertiportCount(int v){if(v<2)throw new IllegalArgumentException("activeVertiportCount must be >= 2");activeVertiportCount=v;}
    @StringGetter("baseFare") public double getBaseFare(){return baseFare;}
    @StringSetter("baseFare") public void setBaseFare(double v){baseFare=nonnegative(v);}
    @StringGetter("farePerMile") public double getFarePerMile(){return farePerMile;}
    @StringSetter("farePerMile") public void setFarePerMile(double v){farePerMile=nonnegative(v);}
    @StringGetter("expectedWaitTime") public double getExpectedWaitTime(){return expectedWaitTime;}
    @StringSetter("expectedWaitTime") public void setExpectedWaitTime(double v){expectedWaitTime=nonnegative(v);}
    @StringGetter("maxWaitTime") public double getMaxWaitTime(){return maxWaitTime;}
    @StringSetter("maxWaitTime") public void setMaxWaitTime(double v){maxWaitTime=nonnegative(v);}
    @StringGetter("maxAccessDistanceMiles") public double getMaxAccessDistanceMiles(){return maxAccessDistanceMiles;}
    @StringSetter("maxAccessDistanceMiles") public void setMaxAccessDistanceMiles(double v){maxAccessDistanceMiles=nonnegative(v);}
    @StringGetter("minimumTripDistanceMiles") public double getMinimumTripDistanceMiles(){return minimumTripDistanceMiles;}
    @StringSetter("minimumTripDistanceMiles") public void setMinimumTripDistanceMiles(double v){minimumTripDistanceMiles=nonnegative(v);}
    @StringGetter("waitTimeBin") public double getWaitTimeBin(){return waitTimeBin;}
    @StringSetter("waitTimeBin") public void setWaitTimeBin(double v){if(!Double.isFinite(v)||v<=0)throw new IllegalArgumentException("waitTimeBin must be positive");waitTimeBin=v;}
    @StringGetter("serviceStartTime") public double getServiceStartTime(){return serviceStartTime;}
    @StringSetter("serviceStartTime") public void setServiceStartTime(double v){serviceStartTime=nonnegative(v);validateServiceWindow();}
    @StringGetter("serviceEndTime") public double getServiceEndTime(){return serviceEndTime;}
    @StringSetter("serviceEndTime") public void setServiceEndTime(double v){serviceEndTime=nonnegative(v);validateServiceWindow();}
    @StringGetter("minimumInnovationFreeFraction") public double getMinimumInnovationFreeFraction(){return minimumInnovationFreeFraction;}
    @StringSetter("minimumInnovationFreeFraction") public void setMinimumInnovationFreeFraction(double v){if(!Double.isFinite(v)||v<0||v>1)throw new IllegalArgumentException("minimumInnovationFreeFraction must be in [0,1]");minimumInnovationFreeFraction=v;}
    private static double nonnegative(double v){if(!Double.isFinite(v)||v<0)throw new IllegalArgumentException("Finite nonnegative value required");return v;}
    private void validateServiceWindow(){if(serviceEndTime<serviceStartTime)throw new IllegalArgumentException("serviceEndTime must be >= serviceStartTime");}
}
