package org.matsim.run.aam;

import java.util.*;
import org.matsim.core.config.ReflectiveConfigGroup;

/** Explicit input settings for the intermodal AAM extension (MATSim 13). */
public final class AamConfigGroup extends ReflectiveConfigGroup {
    private String accessEgressModes="car,ride,ride_taxi,walk,bike";
    private int candidateVertiports=3;
    private int drtMatrixCellSize=5000;
    private double baseFare=30, farePerMile=2, expectedWaitTime=900, maxWaitTime=900;
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
    @StringGetter("baseFare") public double getBaseFare(){return baseFare;}
    @StringSetter("baseFare") public void setBaseFare(double v){baseFare=nonnegative(v);}
    @StringGetter("farePerMile") public double getFarePerMile(){return farePerMile;}
    @StringSetter("farePerMile") public void setFarePerMile(double v){farePerMile=nonnegative(v);}
    @StringGetter("expectedWaitTime") public double getExpectedWaitTime(){return expectedWaitTime;}
    @StringSetter("expectedWaitTime") public void setExpectedWaitTime(double v){expectedWaitTime=nonnegative(v);}
    @StringGetter("maxWaitTime") public double getMaxWaitTime(){return maxWaitTime;}
    @StringSetter("maxWaitTime") public void setMaxWaitTime(double v){maxWaitTime=nonnegative(v);}
    private static double nonnegative(double v){if(!Double.isFinite(v)||v<0)throw new IllegalArgumentException("Finite nonnegative value required");return v;}
}
