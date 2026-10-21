"""Read-only analysis of completed small MATSim trials; writes a NEW audit."""
import argparse
import json
import math
from pathlib import Path
from .stage_model import objective, paired_acceptance
from .stages import alternatives_from_estimate, dump


def audit(root,output):
    output.mkdir(parents=True,exist_ok=False)
    m=json.loads((root/"manifest.json").read_text());rows=[];reverse=[];completed=[]
    for stage in sorted(root.glob("stage-*")):
        if not (stage/"decision.json").exists():continue
        decision=json.loads((stage/"decision.json").read_text());index=decision["stage"]
        completed.append(decision)
        estimates=json.loads((stage/"estimates-result.json").read_text());alternatives=alternatives_from_estimate(estimates,m,index)
        old=[];new=[]
        for label,collection in (("incumbent",old),("proposal",new)):
            paths=sorted(stage.glob(label+"-*-result.json"))
            for path in paths:
                r=json.loads(path.read_text());request=json.loads(path.with_name(path.name.replace("-result.json","-request.json")).read_text())
                collection.append(r);predicted,_=objective(alternatives,frozenset(request["layout"]))
                actual=math.fsum(r["scores"].values())
                rows.append(dict(stage=index,arm=label,seed=r["seed"],layout=request["layout"],predicted=predicted,
                    observed=actual,residual=actual-predicted,allCompetingPlansRescored=r["allCompetingPlansRescored"],
                    source=str(path.resolve())))
        if old and new:
            # These are the SAME paired simulations with the comparison reversed,
            # not new replications and not an optimizer-selected bad proposal.
            reverse.append(dict(stage=index,**paired_acceptance(new,old,m["minimumObservedImprovement"],m["criticalValue"]),
                interpretation="Reverse-layout negative control using actual paired MATSim results. Demonstrates rejection rule, not a new optimizer trajectory."))
    dump(output/"estimate-versus-observed.json",rows);dump(output/"reverse-layout-controls.json",reverse)
    result=json.loads((root/"result.json").read_text()) if (root/"result.json").exists() else {
        "status":"partial_run_ONLY_committed_stages_audited","history":completed}
    lines=["# Three-site MATSim validation","",m["note"],"",f'Completion status: `{result["status"]}`.',"",
        "| Stage | Predicted improvement | Realized improvement | Accepted | Accepted layout |",
        "|---|---:|---:|---|---|"]
    for stage in result["history"]:
        lines.append(f'| {stage["stage"]} | {stage["optimization"]["predictedImprovement"]:.6f} | {stage["validation"]["realizedImprovement"]:.6f} | {stage["validation"]["accepted"]} | {", ".join(stage["acceptedLayout"])} |')
    lines += ["","Estimate-versus-observed residuals are saved per seed. Predicted objective is best feasible estimated alternatives; observed objective uses actually executed plans, so finite-iteration choice and service variation can differ.","",
        "Reverse-layout controls use the same observed paired results in the opposite direction. They are not independent experiments or evidence that the optimizer proposed a known harmful layout. Failed-proposal retention/feedback is tested separately.","",
        "This synthetic fixture validates mechanics, not calibrated demand or global MATSim optimality. All eligible people are retained, including those choosing ground."]
    with (output/"REPORT.md").open("x",encoding="utf-8") as f:f.write("\n".join(lines)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("root",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();audit(a.root,a.output)
