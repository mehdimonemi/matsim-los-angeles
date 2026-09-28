package org.matsim.run.aam.scheduled;

import org.matsim.core.config.ReflectiveConfigGroup;

/** Input settings for AAM operated as fixed-route, fixed-timetable public transit. */
public final class ScheduledAamConfigGroup extends ReflectiveConfigGroup {
    public static final String GROUP_NAME = "scheduledAam";

    private String vertiportsFile = "vertiports.csv";
    private double serviceStartTime = 5 * 3600;
    private double serviceEndTime = 24 * 3600;
    private double headway = 15 * 60;
    private double dwellTime = 60;
    private double cruiseSpeed = 100 * 1609.344 / 3600;
    private int seats = 4;
    private boolean innovationEnabled = true;
    private double minimumTripDistance = 20_000;
    private double maximumAccessEgressTime = 45 * 60;
    private double accessEgressSpeed = 4.16667;
    private double accessEgressBeelineFactor = 1.4;

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

    @StringGetter("minimumTripDistance")
    public double getMinimumTripDistance() {
        return minimumTripDistance;
    }

    @StringSetter("minimumTripDistance")
    public void setMinimumTripDistance(double value) {
        minimumTripDistance = nonnegative("minimumTripDistance", value);
    }

    @StringGetter("maximumAccessEgressTime")
    public double getMaximumAccessEgressTime() {
        return maximumAccessEgressTime;
    }

    @StringSetter("maximumAccessEgressTime")
    public void setMaximumAccessEgressTime(double value) {
        maximumAccessEgressTime = positive("maximumAccessEgressTime", value);
    }

    @StringGetter("accessEgressSpeed")
    public double getAccessEgressSpeed() {
        return accessEgressSpeed;
    }

    @StringSetter("accessEgressSpeed")
    public void setAccessEgressSpeed(double value) {
        accessEgressSpeed = positive("accessEgressSpeed", value);
    }

    @StringGetter("accessEgressBeelineFactor")
    public double getAccessEgressBeelineFactor() {
        return accessEgressBeelineFactor;
    }

    @StringSetter("accessEgressBeelineFactor")
    public void setAccessEgressBeelineFactor(double value) {
        accessEgressBeelineFactor = positive("accessEgressBeelineFactor", value);
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
