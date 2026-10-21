"""Summarize existing controlled frequency trials without starting simulations."""
import argparse
import json
from pathlib import Path
from .reporting import funnel
from .stages import dump


def summarize(root,output):
    output.mkdir(parents=True,exist_ok=False)
    runs=json.loads((root/"results.json").read_text());training=json.loads((root/"frequency-training.json").read_text())
    rows=[]
    for run in runs:
        counts=[funnel(o["events"],o["checkpoint"])[0] for o in run["iterationOutputs"]]
        boardings=sum(c["boardings"] for c in counts)
        rows.append(dict(arm=run["arm"],seed=run["seed"],trainingSeed=run["seed"]==training["trainingSeed"],
            finalPopulationScore=sum(run["scores"].values()),finalAamUsers=run["metrics"]["selectedAamPlans"],
            iterationJourneyBoardings=boardings,meanBoardedWaitSeconds=sum(c["passengerWaitSeconds"] for c in counts)/boardings if boardings else None,
            iterationJourneyCompletions=sum(c["completedJourneys"] for c in counts),
            iterationJourneyRejections=sum(c["rejectedRequests"] for c in counts)))
    dump(output/"summary.json",dict(training=training,rows=rows,
        interpretation="8 correlated learning iterations per seed; iteration journeys are not unique demand. Four held-out seeds, descriptive comparison only."))
    lines=["# Controlled frequency comparison","",
        "Same two synthetic people, service 07:00–19:00, scoring, $30 + $2/mile fare, four seats and 50 total departures in both arms. No regional run.","",
        f'Demand weights were learned only from baseline seed {training["trainingSeed"]}; allocation: {training["counts"]}. Reference: 25 departures in each direction. Seeds 818–821 are held out.',"",
        "| Arm | Seed | Final AAM users | Final aggregate score | Boarded iteration-journeys | Mean boarded wait (s) |",
        "|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        wait=r["meanBoardedWaitSeconds"]
        lines.append(f'| {r["arm"]} | {r["seed"]} | {r["finalAamUsers"]} | {r["finalPopulationScore"]:.3f} | {r["iterationJourneyBoardings"]} | {wait:.2f} |' if wait is not None else
                     f'| {r["arm"]} | {r["seed"]} | {r["finalAamUsers"]} | {r["finalPopulationScore"]:.3f} | 0 | — |')
    lines += ["","This allocation changes departure counts by corridor, not aircraft reuse. The same 50 one-use aircraft are constructed in both arms. A boarding observation during learning does not imply final AAM adoption; ground alternatives remain available.","",
        "Iterations are correlated. This is a diagnostic counterfactual with four held-out seeds, not a production demand estimate or a claim that demand-weighted frequency is globally optimal."]
    with (output/"REPORT.md").open("x",encoding="utf-8") as f:f.write("\n".join(lines)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("root",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();summarize(a.root,a.output)
