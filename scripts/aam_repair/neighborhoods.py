"""Four search neighborhoods over the same observed z/s/q stage model."""
import csv
import math
import time
from .stage_model import objective, solve

METHODS=("global","all-vp-k10","one-vp-k10","adaptive")


def optimize(rows, manifest, incumbent, legacy_users=None):
    method=manifest.get("searchMethod","global")
    if method not in METHODS:raise ValueError("Unknown search method: "+method)
    common=dict(swaps=manifest.get("swaps",1),minimum_improvement=manifest["minimumPredictedImprovement"],
                legacy_current_users=legacy_users)
    budget=manifest.get("solverSeconds",60)
    if method=="global":
        result=solve(rows,manifest["candidates"],incumbent,time_limit=budget,**common)
        result.update(searchMethod=method,searchScope="full configured swap neighborhood")
        return result
    if common["swaps"]!=1:raise ValueError("Restricted methods require swaps=1")
    with open(manifest["candidateCsv"],encoding="utf-8-sig",newline="") as f:
        coords={r["id"]:(float(r["x"]),float(r["y"])) for r in csv.DictReader(f)}
    active=set(incumbent);inactive=set(manifest["candidates"])-active
    if not set(manifest["candidates"])<=coords.keys():raise ValueError("Missing candidate coordinates")
    ranked={a:sorted(inactive,key=lambda b:(math.dist(coords[a],coords[b]),b)) for a in active}
    # Population outside options keep removal losses finite even when the
    # legacy comparison objective requires an AAM assignment.
    loss={a:objective(rows,active)[0]-objective(rows,active-{a})[0] for a in active}
    weak=min(active,key=lambda a:(loss[a],a))
    sites=[weak] if method=="one-vp-k10" else sorted(active)
    levels=[5,10,20,len(inactive)] if method=="adaptive" else [10]
    started=time.monotonic();seen=set();audit=[];evaluations=0
    result=solve(rows,manifest["candidates"],incumbent,time_limit=budget,allowed_layouts=[],**common)
    for k in dict.fromkeys(levels):
        permitted={tuple(sorted((active-{a})|{b})) for a in sites for b in ranked[a][:k]}
        # Re-evaluate the cumulative neighborhood to preserve an exact bound.
        remaining=budget-(time.monotonic()-started)
        if remaining<=0:
            result["status"]="time_limit"
            # No subsequent level was solved: keep a valid full relaxation bound.
            bound=objective([a for a in rows if legacy_users is None or (a.person in legacy_users and a.sites)],set(manifest["candidates"]))[0]
            result.update(bestBound=bound,absoluteGap=bound-result["incumbentObjective"],
                          relativeGap=(bound-result["incumbentObjective"])/max(1,abs(result["incumbentObjective"])))
            break
        ordered=sorted(permitted)
        result=solve(rows,manifest["candidates"],incumbent,time_limit=remaining,
                     allowed_layouts=ordered,**common)
        evaluations+=result["layoutsEvaluated"]
        seen.update(ordered[:result["layoutsEvaluated"]-1])
        audit.append(dict(k=k,movesPermitted=len(permitted),movesEvaluated=result["layoutsEvaluated"]-1,
                          status=result["status"],predictedImprovement=result["predictedImprovement"]))
        if result["proposeChange"] or result["status"]!="optimal":break
    result.update(searchMethod=method,searchLevels=audit,weakSite=weak,removalLosses=loss,
                  uniqueMovesSearched=len(seen),solverLayoutEvaluations=evaluations,
                  searchScope="permitted neighborhood at last reached level",
                  optimalityScope="current observed coefficients and searched neighborhood; NOT global swap or MATSim optimality")
    return result
