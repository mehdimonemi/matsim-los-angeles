"""Constraint-aware fixed-timetable aircraft reuse, separate from passenger fares.

Deterministic feasible greedy dispatcher, NOT minimum-fleet optimization. Flights
are never silently delayed or repositioned. Failed departures remain explicit.
All technical/cost inputs must be supplied; no production defaults are invented.
"""
import argparse
import copy
import json
import math
from pathlib import Path
from .stages import dump


def slot(calendar, start, duration, latest_end):
    """Earliest nonoverlapping interval among parallel resources."""
    choices=[]
    for resource,intervals in enumerate(calendar):
        candidate=start
        for a,b in sorted(intervals):
            if candidate+duration<=a:break
            if candidate<b:candidate=b
        if candidate+duration<=latest_end+1e-9:choices.append((candidate,resource))
    return min(choices) if choices else None


def dispatch(flights, assumptions, reuse=True):
    a=assumptions
    positive=("batteryKWh","maximumRangeMeters","chargerKW","maximumDutySeconds","maintenanceAfterFlightSeconds")
    nonnegative=("energyKWhPerMeter","takeoffEnergyKWh","reserveKWh","turnaroundSeconds","padOccupancySeconds","maintenanceSeconds")
    for key in positive+nonnegative:
        if not math.isfinite(a[key]) or (a[key]<=0 if key in positive else a[key]<0):raise ValueError("Invalid "+key)
    if not 0<a["chargingEfficiency"]<=1 or not 0<=a["reserveKWh"]<a["batteryKWh"]:raise ValueError("Invalid charging efficiency/reserve")
    for key in ("maximumFleet","reserveAircraft"):
        if not isinstance(a[key],int) or a[key]<0:raise ValueError("Invalid fleet count")
    if a["reserveAircraft"]>a["maximumFleet"]:raise ValueError("Reserve exceeds fleet")
    ports={f[k] for f in flights for k in ("origin","destination")}
    for key in ("padsPerSite","chargersPerSite"):
        if not ports<=a[key].keys() or any(not isinstance(v,int) or v<0 for v in a[key].values()):raise ValueError("Missing/invalid site infrastructure: "+key)
    if len({f["id"] for f in flights})!=len(flights):raise ValueError("Duplicate flight")
    pads={p:[[] for _ in range(a["padsPerSite"][p])] for p in ports}
    chargers={p:[[] for _ in range(a["chargersPerSite"][p])] for p in ports}
    tails=[];served=[];rejected=[];charges=[];maintenance=[]
    for f in sorted(flights,key=lambda f:(f["departure"],f["id"])):
        dep,arr,dist=f["departure"],f["arrival"],f["meters"]
        if any(not math.isfinite(v) for v in (dep,arr,dist)) or arr<=dep or dist<0:raise ValueError("Invalid flight")
        energy=a["takeoffEnergyKWh"]+a["energyKWhPerMeter"]*dist
        reason=None
        if dist>a["maximumRangeMeters"]:reason="range"
        elif energy+a["reserveKWh"]>a["batteryKWh"]:reason="battery_reserve"
        elif arr-dep>a["maximumDutySeconds"]:reason="duty"
        elif arr-dep>a["maintenanceAfterFlightSeconds"]:reason="maintenance_interval"
        # Check pads transactionally: no occupancy is committed for a failed flight.
        pad_trial=copy.deepcopy(pads);pad_bookings=[]
        for site,start in ((f["origin"],dep-a["padOccupancySeconds"]),(f["destination"],arr)):
            booking=slot(pad_trial[site],start,a["padOccupancySeconds"],start+a["padOccupancySeconds"])
            if booking is None:reason=reason or "pad_capacity";break
            _,resource=booking;pad_trial[site][resource].append((start,start+a["padOccupancySeconds"]))
            pad_bookings.append(dict(site=site,resource=resource,start=start,end=start+a["padOccupancySeconds"]))
        if reason:rejected.append(dict(flight=f["id"],reason=reason));continue
        feasible=[];unavailable=set()
        for i,t in enumerate(tails if reuse else []):
            if t["site"]!=f["origin"]:unavailable.add("location");continue
            maintenance_needed=t["flightSinceMaintenance"]+arr-dep>a["maintenanceAfterFlightSeconds"]
            ready=t["ready"]+(a["maintenanceSeconds"] if maintenance_needed else 0)
            if ready>dep-a["padOccupancySeconds"]:unavailable.add("turnaround_or_maintenance");continue
            if arr-t["dutyStart"]>a["maximumDutySeconds"]:unavailable.add("duty");continue
            needed=max(0,energy+a["reserveKWh"]-t["soc"])
            charge=None
            if needed:
                duration=needed/(a["chargerKW"]*a["chargingEfficiency"])*3600
                booking=slot(chargers[t["site"]],ready,duration,dep-a["padOccupancySeconds"])
                if booking is None:unavailable.add("charging_capacity_or_time");continue
                start,resource=booking;charge=dict(site=t["site"],resource=resource,start=start,end=start+duration,kWh=needed/a["chargingEfficiency"])
            feasible.append((needed,i,charge,maintenance_needed))
        if feasible:
            _,index,charge,maintenance_needed=min(feasible,key=lambda x:(x[0],x[1]));t=tails[index]
            if maintenance_needed:
                maintenance.append(dict(aircraft=t["id"],start=t["ready"],end=t["ready"]+a["maintenanceSeconds"]))
                t["flightSinceMaintenance"]=0
        elif len(tails)<a["maximumFleet"]-a["reserveAircraft"]:
            t=dict(id=f"reuse_{len(tails):04d}",site=f["origin"],initialSite=f["origin"],ready=dep-a["padOccupancySeconds"],
                   soc=a["batteryKWh"],dutyStart=dep,flightSinceMaintenance=0,flights=[])
            tails.append(t);charge=None
        else:
            rejected.append(dict(flight=f["id"],reason="fleet_unavailable",bindingCandidates=sorted(unavailable)));continue
        pads=pad_trial
        before=t["soc"]
        if charge:
            chargers[charge["site"]][charge["resource"]].append((charge["start"],charge["end"]))
            t["soc"]+=charge["kWh"]*a["chargingEfficiency"]
            charges.append(dict(aircraft=t["id"],**charge))
        t["soc"]-=energy;t["site"]=f["destination"]
        t["lastArrival"]=arr
        t["ready"]=arr+max(a["turnaroundSeconds"],a["padOccupancySeconds"])
        t["flightSinceMaintenance"]+=arr-dep
        if t["flightSinceMaintenance"]>=a["maintenanceAfterFlightSeconds"]:
            maintenance.append(dict(aircraft=t["id"],start=t["ready"],end=t["ready"]+a["maintenanceSeconds"]))
            t["ready"]+=a["maintenanceSeconds"];t["flightSinceMaintenance"]=0
        t["flights"].append(f["id"])
        served.append(dict(**f,aircraft=t["id"],socBeforeCharging=before,socAfter=t["soc"],energyKWh=energy,padBookings=pad_bookings))
    costs=a.get("costs");total_cost=None;cost_breakdown=None
    energy=sum(f["energyKWh"] for f in served)/a["chargingEfficiency"]
    if costs is not None:
        keys=("aircraftPerDay","flightHour","crewDutyHour","electricityPerKWh","maintenanceEvent")
        if any(k not in costs or not math.isfinite(costs[k]) or costs[k]<0 for k in keys):raise ValueError("Missing/invalid operating cost")
        cost_breakdown=dict(aircraft=(len(tails)+a["reserveAircraft"])*costs["aircraftPerDay"],
            flight=sum(f["arrival"]-f["departure"] for f in served)/3600*costs["flightHour"],
            crew=sum(t["lastArrival"]-t["dutyStart"] for t in tails)/3600*costs["crewDutyHour"],
            energy=energy*costs["electricityPerKWh"],maintenance=len(maintenance)*costs["maintenanceEvent"])
        total_cost=sum(cost_breakdown.values())
    idle=0.
    for tail in tails:
        assigned=[f for f in served if f["aircraft"]==tail["id"]]
        for previous,current in zip(assigned,assigned[1:]):
            window_start,window_end=previous["arrival"],current["departure"]
            charged=sum(c["end"]-c["start"] for c in charges if c["aircraft"]==tail["id"] and window_start<=c["start"] and c["end"]<=window_end)
            maintained=sum(c["end"]-c["start"] for c in maintenance if c["aircraft"]==tail["id"] and window_start<=c["start"] and c["end"]<=window_end)
            idle+=max(0,window_end-window_start-max(a["turnaroundSeconds"],a["padOccupancySeconds"])-a["padOccupancySeconds"]-charged-maintained)
    return dict(method="feasible greedy fixed-timetable dispatch; NOT fleet optimum",assumptions=a,reuse=reuse,
        aircraftUsed=len(tails),reserveAircraft=a["reserveAircraft"],served=served,rejected=rejected,aircraft=tails,
        charging=charges,maintenance=maintenance,padCalendars=pads,chargerCalendars=chargers,
        operatingCost=total_cost,costBreakdown=cost_breakdown,energyReplacementKWh=energy,
        betweenFlightIdleSeconds=idle,chargingSeconds=sum(c["end"]-c["start"] for c in charges),
        maintenanceSeconds=sum(c["end"]-c["start"] for c in maintenance),
        turnaroundSeconds=len(served)*max(a["turnaroundSeconds"],a["padOccupancySeconds"]),
        timeNote="Aircraft intervals, not passenger waiting. Turnaround includes landing pad occupancy; departure pad occupancy is separate. Idle excludes overnight/start/end-of-day parking.",
        costNote="Passenger fare is not operating cost. Energy includes end-of-day battery inventory replenishment; end-of-day charging schedule is not modeled.",
        limitations="Deterministic nominal times, no weather/delay propagation, no empty repositioning, no maintenance staffing or parking stands. Reserve aircraft withheld, not dispatched. Not QSim aircraft-rotation validation.")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input",type=Path);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args();data=json.loads(args.input.read_text());args.output.mkdir(parents=True,exist_ok=False)
    dump(args.output/"reuse.json",dispatch(data["flights"],data["assumptions"]))
    dump(args.output/"one-aircraft-per-departure.json",dispatch(data["flights"],data["assumptions"],reuse=False))
