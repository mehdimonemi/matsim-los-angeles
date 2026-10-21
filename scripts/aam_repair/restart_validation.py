"""Actual two-person layout-removal restart with score/layout provenance checks."""
import argparse
import json
from pathlib import Path
from .matsim_adapter import evaluate
from .reporting import xml_rows
from .stages import dump


def validate(manifest_path, prior_result, output):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    m=json.loads(manifest_path.read_text());prior=json.loads(prior_result.read_text())
    if len(m["eligibleIds"])!=2:raise ValueError("This regression is restricted to the two-person fixture")
    r=evaluate(dict(manifest=m,stage=1,seed=817,checkpoint=prior["checkpoint"],checkpointLayoutId=prior["layoutId"],
                    layout=["VP09","VPALT"]),output/"restart-result.json")
    root=output/"restart-result"
    records=[json.loads(line) for line in (root/"plans.xml.gz.observed-plans.jsonl").read_text().splitlines()]
    if not records or any(row["layoutId"]!=prior["layoutId"] or not row["layoutKnown"] for row in records):raise AssertionError("Lost source layout identity")
    if any(plan.get("score") is not None for p in xml_rows(root/"plans.xml.gz","person") for plan in p.findall("plan")):raise AssertionError("Transferred score into invalidated input")
    if not r["allCompetingPlansRescored"]:raise AssertionError("Unscored restarted alternatives")
    if r["metrics"]["selectedAamPlans"]!=0 or r["metrics"]["selectedGroundPlans"]!=2:raise AssertionError("Removed origin site must yield ground outside choices")
    dump(output/"verified.json",dict(engine="MATSim",sourceLayoutId=prior["layoutId"],newLayoutId=r["layoutId"],
        archivedPlans=len(records),sourceScoredPlans=sum(row["observedScore"] is not None for row in records),
        inputScoresCleared=True,allCompetingPlansRescored=True,selectedGroundPeople=2,
        source=str(prior_result.resolve()),interpretation="Changed site layout removes AAM eligibility. Old plan scores remain only with exact archived source plans/layout."))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("manifest",type=Path);p.add_argument("prior",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();validate(a.manifest,a.prior,a.output)
