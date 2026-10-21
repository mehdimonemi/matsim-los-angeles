"""Evaluate actual generated timetable with explicitly synthetic technical inputs."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from .aircraft_operations import dispatch
from .empirical_estimator import seconds
from .reporting import xml_rows
from .stages import dump


def compare(run,output,assumptions_file=None):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    schedule=next(run.glob("*.output_transitSchedule.xml.gz"));network=next(run.glob("*.output_network.xml.gz"))
    lengths={link.get("id"):float(link.get("length")) for link in xml_rows(network,"link")}
    flights=[]
    for line in xml_rows(schedule,"transitLine"):
        if not line.get("id","").startswith("aam_sched_line_"):continue
        for route in line.findall("transitRoute"):
            stops=route.findall("./routeProfile/stop");origin=stops[0].get("refId").replace("aam_sched_stop_","");destination=stops[-1].get("refId").replace("aam_sched_stop_","")
            meters=lengths[f"aam_sched_flight_{origin}_{destination}"]
            for d in route.findall("./departures/departure"):
                departure=seconds(d.get("departureTime"))
                flights.append(dict(id=line.get("id")+"|"+d.get("id"),origin=origin,destination=destination,
                    departure=departure,arrival=departure+seconds(stops[-1].get("arrivalOffset")),meters=meters))
    sites={f[k] for f in flights for k in ("origin","destination")}
    if assumptions_file:
        assumptions=json.loads(assumptions_file.read_text())
    else:
        assumptions=dict(batteryKWh=80,maximumRangeMeters=80000,chargerKW=300,maximumDutySeconds=13*3600,
            maintenanceAfterFlightSeconds=10*3600,energyKWhPerMeter=.001,takeoffEnergyKWh=2,reserveKWh=15,
            turnaroundSeconds=600,padOccupancySeconds=60,maintenanceSeconds=1800,chargingEfficiency=.9,
            maximumFleet=3,reserveAircraft=1,padsPerSite={s:1 for s in sites},chargersPerSite={s:1 for s in sites},
            costs=None,calibration="SYNTHETIC regression parameters; no aircraft specifications or production costs supplied")
    dump(output/"input.json",dict(flights=flights,assumptions=assumptions,sourceSchedule=str(schedule.resolve()),
        scheduleHash=hashlib.sha256(schedule.read_bytes()).hexdigest()))
    results={"reuse":dispatch(flights,assumptions),"reference-same-fleet-budget":dispatch(flights,assumptions,reuse=False)}
    expanded=copy.deepcopy(assumptions);expanded["maximumFleet"]=len(flights)+assumptions["reserveAircraft"]
    results["reference-one-per-departure"]=dispatch(flights,expanded,reuse=False)
    for label,result in results.items():
        # Independently check resource bookings and physical site continuity.
        for key in ("padCalendars","chargerCalendars"):
            for resources in result[key].values():
                for calendar in resources:
                    ordered=sorted(calendar)
                    if any(x[1]>y[0]+1e-6 for x,y in zip(ordered,ordered[1:])):raise AssertionError("Overlapping resource bookings")
        for tail in result["aircraft"]:
            assigned=[f for f in result["served"] if f["aircraft"]==tail["id"]]
            for previous,current in zip(assigned,assigned[1:]):
                if previous["destination"]!=current["origin"] or previous["arrival"]>current["departure"]:raise AssertionError("Aircraft teleported/overlapped")
            if any(f["socAfter"]<assumptions["reserveKWh"]-1e-6 for f in assigned):raise AssertionError("Battery reserve violated")
        dump(output/(label+".json"),result)
    lines=["# Aircraft reuse — constraint-aware timetable comparison","",
        "Technical parameters are explicit in input.json. Built-in example values are SYNTHETIC, not aircraft specifications. Passenger fare remains $30 + $2/mile and is not used as operating cost.","",
        "| Arm | Aircraft used | Reserve withheld | Served departures | Unserved | Operating cost |",
        "|---|---:|---:|---:|---:|---:|"]
    for name,r in results.items():lines.append(f'| {name} | {r["aircraftUsed"]} | {r["reserveAircraft"]} | {len(r["served"])} | {len(r["rejected"])} | {r["operatingCost"] if r["operatingCost"] is not None else "Not supplied"} |')
    lines += ["","The greedy dispatcher enforces range, battery reserve, site continuity, charging slots/power, turnaround, pad slots, maintenance intervals and duty limits. It is a feasible construction, not a minimum-fleet proof.","",
        "This is a separate offline operational evaluation of the generated MATSim timetable, not a QSim simulation of reused aircraft. No weather/delay propagation, empty repositioning, maintenance staffing or parking-stand model is included. Cost formulas are implemented, but monetary results require independent aircraft/crew/energy/maintenance rates."]
    with (output/"REPORT.md").open("x",encoding="utf-8") as f:f.write("\n".join(lines)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("run",type=Path);p.add_argument("--output",type=Path,required=True);p.add_argument("--assumptions",type=Path)
    a=p.parse_args();compare(a.run,a.output,a.assumptions)
