package org.matsim.run.aam.scheduled;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import org.matsim.core.config.ReflectiveConfigGroup;

/** Input settings for AAM operated as fixed-route, fixed-timetable public transit. */
public final class ScheduledAamConfigGroup extends ReflectiveConfigGroup {
    public static final String GROUP_NAME = "scheduledAam";

    private String vertiportsFile = "vertiports.csv";
    private double serviceStartTime = 5 * 3600;
    private double serviceEndTime = 24 * 3600;
    private double headway = 15 * 60;
    private double dwellTime = 60;
    private double cruiseSpeed = 98 * org.matsim.run.aam.AamMissionProfile.KNOTS_TO_METERS_PER_SECOND;
    private int seats = 4;
    private boolean innovationEnabled = true;
    private boolean seedAlternativesAtStartup = true;
    private double minimumTripDistance = 3 * 1609.344;
    private String accessEgressModes = "car,ride,ride_taxi,walk,bike";
    private int candidateVertiports = 3;
    private double maximumGroundAccessDistanceMiles = 5;
    private double maximumWalkDistance=1000, maximumWalkTime=1200, maximumPassengerWait=1800;
    private String queuePriorsFile="";
    private String frequencyAllocationFile="";
    @StringGetter("frequencyAllocationFile") public String getFrequencyAllocationFile(){return frequencyAllocationFile;}
    @StringSetter("frequencyAllocationFile") public void setFrequencyAllocationFile(String v){frequencyAllocationFile=v;}
    @StringGetter("queuePriorsFile") public String getQueuePriorsFile(){return queuePriorsFile;}
    @StringSetter("queuePriorsFile") public void setQueuePriorsFile(String v){queuePriorsFile=v;}
    private double baseFare=0, farePerMile=2;
    @StringGetter("maximumWalkDistance") public double getMaximumWalkDistance(){return maximumWalkDistance;}
    @StringSetter("maximumWalkDistance") public void setMaximumWalkDistance(double v){maximumWalkDistance=nonnegative("maximumWalkDistance",v);}
    @StringGetter("maximumWalkTime") public double getMaximumWalkTime(){return maximumWalkTime;}
    @StringSetter("maximumWalkTime") public void setMaximumWalkTime(double v){maximumWalkTime=nonnegative("maximumWalkTime",v);}
    @StringGetter("maximumPassengerWait") public double getMaximumPassengerWait(){return maximumPassengerWait;}
    @StringSetter("maximumPassengerWait") public void setMaximumPassengerWait(double v){maximumPassengerWait=nonnegative("maximumPassengerWait",v);}
    @StringGetter("baseFare") public double getBaseFare(){return baseFare;}
    @StringSetter("baseFare") public void setBaseFare(double v){baseFare=nonnegative("baseFare",v);}
    @StringGetter("farePerMile") public double getFarePerMile(){return farePerMile;}
    @StringSetter("farePerMile") public void setFarePerMile(double v){farePerMile=nonnegative("farePerMile",v);}

    public ScheduledAamConfigGroup() {
        super(GROUP_NAME);
    }

    @StringGetter("vertiportsFile")
    public String getVertiportsFile() {
        return vertiportsFile;
    }

    @StringSetter("vertiportsFile")
    public void setVertiportsFile(String value) {
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalArgumentException("vertiportsFile must not be empty");
        }
        vertiportsFile = value.trim();
    }

    @StringGetter("serviceStartTime")
    public double getServiceStartTime() {
        return serviceStartTime;
    }

    @StringSetter("serviceStartTime")
    public void setServiceStartTime(double value) {
        serviceStartTime = nonnegative("serviceStartTime", value);
    }

    @StringGetter("serviceEndTime")
    public double getServiceEndTime() {
        return serviceEndTime;
    }

    @StringSetter("serviceEndTime")
    public void setServiceEndTime(double value) {
        serviceEndTime = nonnegative("serviceEndTime", value);
    }

    @StringGetter("headway")
    public double getHeadway() {
        return headway;
    }

    @StringSetter("headway")
    public void setHeadway(double value) {
        headway = positive("headway", value);
    }

    @StringGetter("dwellTime")
    public double getDwellTime() {
        return dwellTime;
    }

    @StringSetter("dwellTime")
    public void setDwellTime(double value) {
        dwellTime = nonnegative("dwellTime", value);
    }

    @StringGetter("cruiseSpeed")
    public double getCruiseSpeed() {
        return cruiseSpeed;
    }

    @StringSetter("cruiseSpeed")
    public void setCruiseSpeed(double value) {
        cruiseSpeed = positive("cruiseSpeed", value);
    }

    @StringGetter("seats")
    public int getSeats() {
        return seats;
    }

    @StringSetter("seats")
    public void setSeats(int value) {
        if (value < 1) {
            throw new IllegalArgumentException("seats must be at least 1");
        }
        seats = value;
    }

    @StringGetter("innovationEnabled")
    public boolean isInnovationEnabled() {
        return innovationEnabled;
    }

    @StringSetter("innovationEnabled")
    public void setInnovationEnabled(boolean value) {
        innovationEnabled = value;
    }

    @StringGetter("seedAlternativesAtStartup")
    public boolean getSeedAlternativesAtStartup() { return seedAlternativesAtStartup; }

    @StringSetter("seedAlternativesAtStartup")
    public void setSeedAlternativesAtStartup(boolean value) { seedAlternativesAtStartup = value; }

    @StringGetter("minimumTripDistance")
    public double getMinimumTripDistance() {
        return minimumTripDistance;
    }

    @StringSetter("minimumTripDistance")
    public void setMinimumTripDistance(double value) {
        minimumTripDistance = nonnegative("minimumTripDistance", value);
    }

    @StringGetter("accessEgressModes")
    public String getAccessEgressModes() {
        return accessEgressModes;
    }

    @StringSetter("accessEgressModes")
    public void setAccessEgressModes(String value) {
        Set<String> allowed = Set.of("car", "ride", "ride_taxi", "walk", "bike");
        for (String mode : value.split(",")) {
            if (!allowed.contains(mode.trim())) {
                throw new IllegalArgumentException("Unsupported scheduled-AAM access/egress mode: " + mode);
            }
        }
        accessEgressModes = value;
    }

    public List<String> modes() {
        List<String> result = new ArrayList<>();
        for (String mode : accessEgressModes.split(",")) {
            result.add(mode.trim());
        }
        return result;
    }

    @StringGetter("candidateVertiports")
    public int getCandidateVertiports() {
        return candidateVertiports;
    }

    @StringSetter("candidateVertiports")
    public void setCandidateVertiports(int value) {
        if (value < 1) {
            throw new IllegalArgumentException("candidateVertiports must be positive");
        }
        candidateVertiports = value;
    }

    @StringGetter("maximumGroundAccessDistanceMiles")
    public double getMaximumGroundAccessDistanceMiles() {
        return maximumGroundAccessDistanceMiles;
    }

    @StringSetter("maximumGroundAccessDistanceMiles")
    public void setMaximumGroundAccessDistanceMiles(double value) {
        maximumGroundAccessDistanceMiles = nonnegative("maximumGroundAccessDistanceMiles", value);
    }

    private static double nonnegative(String name, double value) {
        if (!Double.isFinite(value) || value < 0) {
            throw new IllegalArgumentException(name + " must be finite and nonnegative");
        }
        return value;
    }

    private static double positive(String name, double value) {
        if (!Double.isFinite(value) || value <= 0) {
            throw new IllegalArgumentException(name + " must be finite and positive");
        }
        return value;
    }
}
