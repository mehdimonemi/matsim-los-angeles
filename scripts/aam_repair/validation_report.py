"""Summarize existing two-person validation runs; never launches a simulation."""
import argparse
import hashlib
import json
from pathlib import Path
from .reporting import compare, xml_rows, is_air_plan


def build(root, output):
    inputs=root/"named-daytime-inputs-01"
    population_hash=hashlib.sha256((inputs/"population.xml").read_bytes()).hexdigest()
    ids=["10092375","10096817"]
    manifests=[];retained={}
    for service in ("scheduled","drt"):
        run=root/f"named-daytime-{service}-02"
        final=next(run.glob("*.output_plans.xml.gz"))
        retained[service]={p.get("id"):[dict(selected=q.get("selected"),score=q.get("score"),aam=is_air_plan(q))
                            for q in p.findall("plan")] for p in xml_rows(final,"person")}
        for iteration in range(5):
            folder=run/"ITERS"/f"it.{iteration}"
            manifests.append(dict(name=f"{service}-iteration-{iteration}",populationHash=population_hash,
                eligibleIdsHash=hashlib.sha256(json.dumps(ids).encode()).hexdigest(),seed=817,
                serviceStart=25200,serviceEnd=68400,
                plans=str(next(folder.glob("*.experienced_plans.xml.gz")).resolve()),
                events=str(next(folder.glob("*.events.xml.gz")).resolve()),
                fareAssumptions="$30 per boarding + $2 per air mile; mode-specific ground fares retained",
                supplyAssumptions=("4 seats; 30-minute timetable; one aircraft per departure" if service=="scheduled" else
                                   "Configured DRT fleet; 4 seats; 900-second pickup limit; insertion estimate factor 1.0"),
                scoringAssumptions="Same two people and synthetic ground graph; existing person-specific scoring; original activity-window attributes retained; end times shifted +4h for feeder exercise",
                interpretation="Diagnostic controlled service arms, NOT regional demand inference or equal-supply experiment. Iterations are correlated, not independent replications.",
                effectiveConfig=str(next(run.glob("*.output_config.xml")).resolve())))
    results=compare(manifests,output)
    with (output/"retained-alternatives.json").open("x") as f:json.dump(retained,f,indent=2)
    lines=["# Small-case validation report","",
        "Travelers 10096817 and 10092375; real coordinates/attributes, synthetic road network, departure-end times shifted four hours. This is a feeder/restart test, not a demand forecast.","",
        "| Service / iteration | Selected AAM | Attempts | Boardings | Completed journeys | Rejected | Mean boarded wait (s) |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        wait=r["meanBoardedPassengerWaitSeconds"]
        lines.append(f'| {r["name"]} | {r["selectedAamPlans"]} | {r["attemptedRequests"]} | {r["boardings"]} | {r["completedJourneys"]} | {r["rejectedRequests"]} | {wait if wait is not None else "—"} |')
    lines += ["", "Both travelers retain scored ground and AAM alternatives in both services and ultimately select ground. AAM availability does not force adoption.","",
        "Counts use executed experienced plans, not the earlier pre-mobsim plan snapshot. Detailed assumptions and source files are in comparison.json; retained scored alternatives are in retained-alternatives.json.","",
        "The service arms use the same population, seed and hours, but different documented supply policies. These results cannot establish a regional demand, frequency, cost, or optimal-layout conclusion. No full revised model was run."]
    with (output/"REPORT.md").open("x",encoding="utf-8") as f:f.write("\n".join(lines)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("root",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();build(a.root,a.output)
