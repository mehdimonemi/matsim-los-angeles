"""Read-only historical rejection audit; writes only a new explicit directory."""
import argparse
import csv
import json
from pathlib import Path


def diagnose(requests, output):
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    with requests.open(encoding="utf-8-sig", newline="") as stream:
        for request in csv.DictReader(stream):
            if "aam_loop_CAN012" not in (request["from_link"], request["to_link"]):
                continue
            t, direct = float(request["submitted_s"]), float(request["direct_time_s"])
            # MATSim13 SelectiveInsertionSearchParams default factor .5;
            # DetourTimeEstimator divides matrix free-speed time by this factor.
            # Remove 2s from direct travel time to conservatively allow loop/link
            # discretization. Even this bound exceeds the arrival constraint.
            estimated_lower = 2*max(0, direct-2)
            latest_budget = 1.2*direct+1800
            in_hours = 25200 <= t <= 68400
            rows.append({**request, "in_hours": in_hours,
                         "restrictive_estimate_lower_s": estimated_lower,
                         "latest_arrival_budget_s": latest_budget,
                         "minimum_excess_s": estimated_lower-latest_budget,
                         "prefilter_arrival_infeasible": estimated_lower > latest_budget,
                         "even_direct_trip_overruns_service": t+direct+120 > 68400})
    with (output/"can012-requests.csv").open("x", newline="", encoding="utf-8") as stream:
        writer=csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary={"requests":len(rows),"rejected":sum(r["rejected"]=="true" for r in rows),
             "withinHours":sum(r["in_hours"] for r in rows),
             "withinHoursFailRestrictiveArrivalBound":sum(r["in_hours"] and r["prefilter_arrival_infeasible"] for r in rows),
             "minimumExcessSeconds":min(r["minimum_excess_s"] for r in rows),
             "inHoursAlsoOverrunService":sum(r["in_hours"] and r["even_direct_trip_overruns_service"] for r in rows),
             "interpretation":"Sufficient pre-filter arrival infeasibility, not a complete vehicle-schedule replay. Other constraints may also bind.",
             "repair":"Use configurable factor 1.0 for free-speed air estimates; retain max wait 900, alpha 1.2, beta 1800 and stop 120. Reference factor remains reproducible as 0.5."}
    (output/"diagnosis.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    return summary


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--requests",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args();print(json.dumps(diagnose(args.requests,args.output),indent=2))
