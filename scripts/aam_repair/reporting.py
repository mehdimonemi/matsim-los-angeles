"""Event-based journey funnel and separately labelled supply counterfactuals."""
import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def xml_rows(path, tag):
    opener=gzip.open if Path(path).suffix==".gz" else open
    with opener(path,"rb") as stream:
        for _, element in ET.iterparse(stream,events=("end",)):
            if element.tag==tag:
                yield element
                element.clear()


def is_air_plan(plan, service=None):
    for leg in plan.findall("leg"):
        route=leg.find("route")
        if leg.get("mode")=="aam_drt":
            return True
        if service!="drt" and (leg.get("mode")=="scheduled_aam" or
                (route is not None and "aam_sched_line_" in (route.text or ""))):
            return True
    return False


def funnel(events, plans, service=None, passenger_ids=None):
    counts={"selectedAamPlans":0,"availableAamAlternatives":0,"selectedGroundPlans":0,
            "passengerAgentsEvaluated":0,"genuineAamAlternativeUsers":0,
            "scoredAamAlternativeUsers":0,"markerOnlyPlans":0,"groundFallbackPlans":0}
    for person in xml_rows(plans,"person"):
        if passenger_ids is not None and person.get('id') not in passenger_ids:continue
        if person.findtext("./attributes/attribute[@name='subpopulation']") not in (None,"person"):continue
        counts["passengerAgentsEvaluated"]+=1
        genuine=False;scored=False
        for plan in person.findall("plan"):
            air=is_air_plan(plan,service)
            genuine|=air
            try:scored|=air and math.isfinite(float(plan.get("score")))
            except (TypeError,ValueError):pass
            marker=(plan.get("type")=="aam" or any(l.get("mode")=="aam" or
                    l.findtext("./attributes/attribute[@name='routingMode']")=="aam" for l in plan.findall("leg")))
            counts["markerOnlyPlans"]+=int(marker and not air)
            fallback=plan.findtext("./attributes/attribute[@name='aam_ground_fallback']")
            counts["groundFallbackPlans"]+=int(not air and (marker or (fallback or "").lower()=="true"))
            counts["availableAamAlternatives"]+=int(air)
            if plan.get("selected")=="yes":counts["selectedAamPlans" if air else "selectedGroundPlans"]+=1
        counts["genuineAamAlternativeUsers"]+=int(genuine)
        counts["scoredAamAlternativeUsers"]+=int(scored)
    counts["selectedAamUsers"]=counts["selectedAamPlans"]
    attempts=[];active={};request_ids={};aircraft={};drivers=set();dwell_start={}
    dwell=0.;vehicle_intervals={};move_start={};move_seconds=0.;tasks={};task_seconds={};saw_tasks=False
    for event in xml_rows(events,"event"):
        e=event.attrib;t=float(e["time"]);kind=e["type"];p=e.get("person");v=e.get("vehicle")
        if kind.startswith("dvrpTask") and e.get("dvrpMode")=="aam_drt":
            saw_tasks=True;key=(e.get("dvrpVehicle"),e.get("taskIndex"))
            if kind=="dvrpTaskStarted":tasks[key]=(t,e.get("taskType"))
            elif kind=="dvrpTaskEnded" and key in tasks:
                start,task_type=tasks.pop(key);task_seconds[task_type]=task_seconds.get(task_type,0)+t-start
        if kind=="TransitDriverStarts" and e.get("transitLineId","").startswith("aam_sched_line_"):
            aircraft[e["vehicleId"]]=e["transitLineId"];drivers.add(e["driverId"])
        if kind=="waitingForPt" and e.get("atStop","").startswith("aam_sched_stop_"):
            row={"person":p,"service":"scheduled","attempt_s":t,"from":e["atStop"],"to":e.get("destinationStop")}
            attempts.append(row);active[p]=row
        elif kind=="DrtRequest submitted" and e.get("mode")=="aam_drt":
            row={"person":p,"service":"drt","attempt_s":t,"request":e["request"],"from":e.get("fromLink"),"to":e.get("toLink")}
            attempts.append(row);active[p]=row;request_ids[e["request"]]=row
        elif kind=="PassengerRequest rejected" and e.get("mode")=="aam_drt":
            row=request_ids.get(e.get("request"))
            if row is not None:row.update(rejected_s=t,reason=e.get("cause"));active.pop(row["person"],None)
        elif kind=="scheduledAamRejected":
            row=active.pop(p,None)
            if row is not None:row.update(rejected_s=t,reason=e.get("reason"))
        elif kind=="passenger picked up" and e.get("mode")=="aam_drt":
            row=request_ids.get(e.get("request"))
            if row is not None:row.update(board_s=t,vehicle=v)
        elif kind=="passenger dropped off" and e.get("mode")=="aam_drt":
            row=request_ids.get(e.get("request"))
            if row is not None:row["air_arrival_s"]=t
        elif kind=="PersonEntersVehicle" and v in aircraft and p not in drivers:
            if p in active:active[p].update(board_s=t,vehicle=v)
        elif kind=="PersonLeavesVehicle" and v in aircraft and p not in drivers:
            if p in active:active[p]["air_arrival_s"]=t
        elif kind=="actstart" and "interaction" not in e.get("actType","").lower():
            row=active.get(p)
            if row is not None and "air_arrival_s" in row:row["journey_complete_s"]=t;active.pop(p)
        if v in aircraft or (v or "").startswith("aam_drt_"):
            span=vehicle_intervals.setdefault(v,[t,t]);span[1]=t
            if kind=="VehicleArrivesAtFacility":dwell_start[v]=t
            elif kind=="VehicleDepartsAtFacility" and v in dwell_start:dwell+=t-dwell_start.pop(v)
            if kind=="vehicle enters traffic":move_start[v]=t
            elif kind=="vehicle leaves traffic" and v in move_start:move_seconds+=t-move_start.pop(v)
    counts.update(attemptedRequests=len(attempts),boardings=sum("board_s" in r for r in attempts),
                  completedAirLegs=sum("air_arrival_s" in r for r in attempts),
                  completedJourneys=sum("journey_complete_s" in r for r in attempts),
                  rejectedRequests=sum("rejected_s" in r for r in attempts),
                  unfinishedJourneys=sum("journey_complete_s" not in r and "rejected_s" not in r for r in attempts))
    counts["completedAamUsers"]=len({r["person"] for r in attempts if "air_arrival_s" in r})
    waits=[r["board_s"]-r["attempt_s"] for r in attempts if "board_s" in r]
    counts.update(passengerWaitSeconds=sum(waits),meanBoardedPassengerWaitSeconds=sum(waits)/len(waits) if waits else None,
                  rejectedWaitingSeconds=sum(r["rejected_s"]-r["attempt_s"] for r in attempts if "rejected_s" in r),
                  scheduledStopDwellSeconds=dwell,aircraftTrafficSpanSeconds=move_seconds,
                  aircraftIdleSeconds=task_seconds.get("STAY",0) if saw_tasks else None,
                  drtStopDwellSeconds=task_seconds.get("STOP",0),drtDriveTaskSeconds=task_seconds.get("DRIVE",0),
                  unfinishedVehicleTasks=len(tasks),
                  idleNote="DRT idle = completed STAY task duration; dwell = STOP. Scheduled full-day idle is not defined by one-aircraft-per-departure construction; use the explicit reuse scenario.")
    return counts,attempts


def reuse_report(flights, turnaround_seconds, cost_per_aircraft_day, cost_per_flight_hour):
    """Minimum aircraft for fixed flights, no repositioning, via DAG path cover.

    flights: id, origin, destination, departure, arrival. Charging/range/maintenance
    are not modelled; this is a scheduling lower bound, NOT an operational fleet.
    """
    flights=sorted(flights,key=lambda f:(f["departure"],f["id"]))
    if turnaround_seconds<0 or cost_per_aircraft_day<0 or cost_per_flight_hour<0:
        raise ValueError("Negative turnaround or cost")
    if any(f["arrival"]<=f["departure"] for f in flights):raise ValueError("Invalid flight times")
    edges=[[j for j,b in enumerate(flights) if j>i and a["destination"]==b["origin"] and a["arrival"]+turnaround_seconds<=b["departure"]] for i,a in enumerate(flights)]
    matched={}
    def augment(i,seen):
        for j in edges[i]:
            if j in seen:continue
            seen.add(j)
            if j not in matched or augment(matched[j],seen):matched[j]=i;return True
        return False
    for i in range(len(flights)):augment(i,set())
    next_flight={i:j for j,i in matched.items()};chains=[];idle=0
    for i in range(len(flights)):
        if i in matched:continue
        chain=[]
        while True:
            chain.append(flights[i]["id"])
            if i not in next_flight:break
            j=next_flight[i];idle+=flights[j]["departure"]-flights[i]["arrival"]-turnaround_seconds;i=j
        chains.append(chain)
    hours=sum(f["arrival"]-f["departure"] for f in flights)/3600
    return {"referenceAircraft":len(flights),"reuseAircraftLowerBound":len(chains),"rotations":chains,
            "turnaroundSeconds":turnaround_seconds,"betweenFlightIdleSeconds":idle,
            "referenceCost":len(flights)*cost_per_aircraft_day+hours*cost_per_flight_hour,
            "reuseCostLowerBound":len(chains)*cost_per_aircraft_day+hours*cost_per_flight_hour,
            "costPerAircraftDay":cost_per_aircraft_day,"costPerFlightHour":cost_per_flight_hour,
            "limitations":"No charging, range, maintenance, repositioning, reserve fleet or vertiport pad conflicts. Not QSim-validated."}


def allocate_departures(demand, total_departures, minimum_per_corridor=0):
    """Separate demand-responsive frequency counterfactual, same departure budget."""
    keys=sorted(demand)
    if not keys or any(v<0 for v in demand.values()) or total_departures<minimum_per_corridor*len(keys):raise ValueError("Invalid frequency budget")
    remaining=total_departures-minimum_per_corridor*len(keys);total=sum(demand.values())
    shares={k:remaining*(demand[k]/total if total else 1/len(keys)) for k in keys}
    result={k:minimum_per_corridor+int(shares[k]) for k in keys}
    for k in sorted(keys,key=lambda k:(-(shares[k]-int(shares[k])),k))[:total_departures-sum(result.values())]:result[k]+=1
    return result


def compare(manifests, output):
    output.mkdir(parents=True,exist_ok=False)
    baseline=manifests[0];results=[]
    for m in manifests:
        for field in ("populationHash","eligibleIdsHash","serviceStart","serviceEnd","seed"):
            if field not in m or m[field]!=baseline.get(field):raise ValueError("Uncontrolled comparison: "+field)
        for field in ("name","fareAssumptions","supplyAssumptions","scoringAssumptions"):
            if field not in m:raise ValueError("Undocumented assumptions: "+field)
        counts,rows=funnel(m["events"],m["plans"])
        results.append({**m,**counts})
        with (output/(str(len(results))+"-journeys.jsonl")).open("x",encoding="utf-8") as f:
            for row in rows:f.write(json.dumps(row)+"\n")
    (output/"comparison.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    columns=["name","selectedAamPlans","attemptedRequests","boardings","completedAirLegs","completedJourneys","rejectedRequests","unfinishedJourneys","meanBoardedPassengerWaitSeconds"]
    with (output/"comparison.csv").open("x",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction="ignore");w.writeheader();w.writerows(results)
    return results


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("manifest",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();compare(json.loads(a.manifest.read_text(encoding="utf-8")),a.output)
