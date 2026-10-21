"""MATSim-measured coefficient adapter, explicitly restricted to observed plan catalog.

Uses the same evaluator for both scheduled and DRT: no uniform-speed feeder proxy,
no invented fare benefit. Candidate probes retain the incumbent fleet/site count.
This expensive but reproducible reference estimator is small-case oriented.
"""
import copy
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from .reporting import xml_rows, funnel
from .stages import adapter, dump


def seconds(value):
    if value is None or value=="undefined":return math.nan
    if ":" in value:
        h,m,s=map(float,value.split(":"));return h*3600+m*60+s
    return float(value)


def air_leg(leg):
    route=leg.find("route")
    if route is None:return False
    return leg.get("mode")=="aam_drt" or "aam_sched_line_" in (route.text or "")


def plan_record(person,plan,manifest,run,attempts=()):
    score=float(plan.get("score","nan"))
    if not math.isfinite(score):return None
    canonical=copy.deepcopy(plan);canonical.attrib.pop("score",None);canonical.attrib.pop("selected",None)
    for leg in canonical.findall("leg"):
        for key in ("dep_time","trav_time"):leg.attrib.pop(key,None)
        route=leg.find("route")
        if route is not None:route.attrib.pop("trav_time",None)
    plan_id=hashlib.sha256(ET.tostring(canonical)).hexdigest()
    row={"person":person,"planId":plan_id,"score":score,"sites":[],
         "scoreKind":"observedPlanMean","sourceLayout":run["layoutId"],
         "sourceCheckpoint":run["checkpoint"],"stage":run.get("stage")}
    elements=list(plan);main=[i for i,e in enumerate(elements) if e.tag in ("activity","act") and "interaction" not in e.get("type","").lower()]
    sites=set();modes=set();access_d=[];egress_d=[];access_t=[];egress_t=[];waits=[];distance=0;flights=0;service_ok=True
    def walk_totals(segment):
        legs=[l for l in segment if l.tag=="leg" and l.get("mode") in ("walk","transit_walk","non_network_walk")]
        return sum(float(l.find("route").get("distance","nan")) for l in legs),sum(seconds(l.get("trav_time",l.find("route").get("trav_time"))) for l in legs)
    for start,end in zip(main,main[1:]):
        trip=elements[start+1:end];air=[i for i,l in enumerate(trip) if l.tag=="leg" and air_leg(l)]
        if not air:continue
        access,egress=trip[:air[0]],trip[air[-1]+1:]
        d,t=walk_totals(access);access_d.append(d);access_t.append(t)
        d,t=walk_totals(egress);egress_d.append(d);egress_t.append(t)
        modes.update(l.get("mode") for l in access+egress if l.tag=="leg" and l.get("mode")!="walk")
        if not any(l.tag=="leg" and l.get("mode")!="walk" for l in access):modes.add("walk")
        if not any(l.tag=="leg" and l.get("mode")!="walk" for l in egress):modes.add("walk")
        for i in air:
            leg=trip[i];route=leg.find("route");flights+=1;distance+=float(route.get("distance","nan"))
            for key in ("start_link","end_link"):
                link=route.get(key,"")
                for prefix in ("aam_sched_loop_","aam_loop_"):
                    if link.startswith(prefix):sites.add(link[len(prefix):])
            departure=seconds(leg.get("dep_time"));travel=seconds(leg.get("trav_time"))
            service_ok &= math.isfinite(departure) and departure>=manifest["serviceStart"] and departure<=manifest["serviceEnd"]
            try:data=json.loads(route.text or "{}")
            except json.JSONDecodeError:data={}
            boarding=seconds(str(data.get("boardingTime","undefined")))
            waits.append(max(0,boarding-departure) if math.isfinite(boarding) else 0.)
            # DRT must complete before fleet end. Scheduled end is LAST DEPARTURE,
            # so flights already departed may finish after that timestamp.
            if manifest["service"]=="drt":service_ok &= math.isfinite(travel) and departure+travel<=manifest["serviceEnd"]
    if not flights:return row
    if not sites:raise ValueError("Cannot identify actual selected vertiports in routed plan")
    actual=[a for a in attempts if a["person"]==person]
    if actual:
        waits=[a["board_s"]-a["attempt_s"] for a in actual if "board_s" in a]
    rejection_rate=sum("rejected_s" in a for a in actual)/len(actual) if actual else 0.
    row.update(sites=sorted(sites),feederModes=sorted(modes),accessWalkMeters=max(access_d),egressWalkMeters=max(egress_d),
        accessWalkSeconds=max(access_t),egressWalkSeconds=max(egress_t),serviceFeasible=bool(service_ok),continuityFeasible=True,
        expectedWaitSeconds=max(waits,default=0.),rejectionProbability=rejection_rate,successScore=score,rejectionScore=score,
        fare=manifest["baseFare"]*flights+manifest["farePerMile"]*distance/1609.344,flightMeters=distance,flightCount=flights,
        capacityEvidence=run["events"],routeEvidence=run["checkpoint"],
        scoreNote="Observed full-plan score already includes realized fare, waiting, activity timing, capacity/rejection penalties. No second failure penalty is added.")
    return row


def feedback_seed(observations, default):
    """Recheck the most adverse failed-proposal seed in fresh current-stage runs.

    All layouts use that same seed. Old observed scores are NEVER assigned to a
    changed plan. This is a conservative stress estimate, not an unbiased mean
    over all seeds; independent paired validation still decides acceptance.
    """
    adverse=[]
    for o in observations:
        if o.get("proposalRejected"):
            adverse.extend((difference,r["seed"]) for difference,r in zip(o["pairedDifferences"],o["runs"]))
    return min(adverse)[1] if adverse else default


def estimate(request,result_path):
    m=request["manifest"];incumbent=frozenset(request["incumbent"]);candidates=frozenset(m["candidates"])
    root=result_path.with_suffix("");root.mkdir(parents=True,exist_ok=False)
    layouts=[sorted(incumbent)]
    for count in range(1,min(m.get("swaps",1),len(incumbent),len(candidates-incumbent))+1):
        for removed in combinations(sorted(incumbent),count):
            for added in combinations(sorted(candidates-incumbent),count):layouts.append(sorted((incumbent-set(removed))|set(added)))
    limit=m.get("maximumProbeLayouts",len(layouts))
    if limit<1:raise ValueError("At least the incumbent must be probed")
    all_layouts=len(layouts);rows=[];legacy_users=set()
    # Failed proposals inform probe priority, but their old scores are NOT copied
    # into the new stage: every included probe is rerouted and rescored now.
    failed_layouts=[o["layout"] for o in request.get("observations",[]) if o["layout"]!=sorted(incumbent)]
    layouts.sort(key=lambda x:(x!=sorted(incumbent),x not in failed_layouts,x))
    layouts=layouts[:limit]
    probe_seed=feedback_seed(request.get("observations",[]),m["seeds"][0])
    for i,layout in enumerate(layouts):
        run=adapter(m["evaluatorCommand"],{"manifest":m,"stage":request["stage"],"seed":probe_seed,
                    "checkpoint":request["checkpoint"],"checkpointLayoutId":request.get("checkpointLayoutId"),
                    "layout":layout,"preserveAlternatives":True},root,f"probe-{i:04d}")
        if run.get("engine")!="MATSim":raise ValueError("Empirical estimator requires MATSim")
        if not run.get("allCompetingPlansRescored",False):raise ValueError("Unscored probe alternatives; increase small-case evaluation budget")
        if not run.get("iterationOutputs"):raise ValueError("Need matched per-iteration plans and events for score provenance")
        for observation in run["iterationOutputs"]:
            _,attempts=funnel(observation["events"],observation["checkpoint"])
            for person in xml_rows(observation["checkpoint"],"person"):
                if person.get("id") not in m["eligibleIds"]:continue
                for plan in person.findall("plan"):
                    if plan.get("selected")!="yes":continue
                    row=plan_record(person.get("id"),plan,m,{**run,**observation},attempts)
                    if row is not None:
                        rows.append(row)
                        if layout==sorted(incumbent) and row["sites"]:legacy_users.add(row["person"])
    # Identical plan options can be observed under multiple operating contexts.
    # Their mean is a separable stage estimate; validation measures interaction effects.
    grouped={}
    for row in rows:grouped.setdefault((row["person"],row["planId"]),[]).append(row)
    alternatives=[]
    for observations in grouped.values():
        row=dict(observations[0]);row["score"]=sum(o["score"] for o in observations)/len(observations)
        row["coefficientSourceObservations"]=[dict(checkpoint=o["sourceCheckpoint"],layout=o["sourceLayout"],score=o["score"],stage=o["stage"]) for o in observations]
        row["observedScoreRange"]=[min(o["score"] for o in observations),max(o["score"] for o in observations)]
        if row["sites"]:
            for key in ("accessWalkMeters","egressWalkMeters","accessWalkSeconds","egressWalkSeconds","expectedWaitSeconds"):
                row[key]=max(o[key] for o in observations)
            for key in ("serviceFeasible","continuityFeasible"):row[key]=all(o[key] for o in observations)
            row["rejectionProbability"]=sum(o["rejectionProbability"] for o in observations)/len(observations)
        row["coefficientObservations"]=len(observations);alternatives.append(row)
    result={k:m[k] for k in ("populationHash","scoringHash","supplyFareHash","eligibleIdsHash","eligibleIds")}
    result.update(stage=request["stage"],alternatives=alternatives,probeLayouts=layouts,probeSeed=probe_seed,legacyCurrentUsers=sorted(legacy_users),
                  coefficientCoverageComplete=len(layouts)==all_layouts,
                  scope="Observed routed plan catalog from current-stage MATSim probes, not every theoretically possible plan.",
                  approximation="Separable mean full-plan utilities across probe contexts; congestion/capacity interactions require paired MATSim validation.")
    dump(result_path,result);return result


if __name__=="__main__":estimate(json.loads(Path(sys.argv[1]).read_text()),Path(sys.argv[2]))
