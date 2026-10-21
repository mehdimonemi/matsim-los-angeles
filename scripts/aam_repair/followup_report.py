"""Consolidate verified follow-up artifacts, never start or overwrite a run."""
import argparse
import json
from pathlib import Path
from .stages import dump


def build(root,output):
    root=root.resolve();output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    def read(path):return json.loads((root/path).read_text())
    scheduled=read("three-site-scheduled-02/stage-000/decision.json")
    drt=read("three-site-drt-02/stage-000/decision.json")
    continuation=read("three-site-drt-continuation-01/result.json")
    scheduled_restart=read("scheduled-restart-provenance-01/verified.json")
    drt_restart=read("drt-restart-provenance-01/verified.json")
    rejects=[read("scheduled-rejection-replay-02/stage-000/decision.json"),read("drt-rejection-replay-01/stage-000/decision.json")]
    if not scheduled["validation"]["accepted"] or not drt["validation"]["accepted"]:raise AssertionError("Missing accepted actual swaps")
    if any(r["validation"]["accepted"] for r in rejects):raise AssertionError("Harmful replay not rejected")
    if not all(r["inputScoresCleared"] and r["allCompetingPlansRescored"] for r in (scheduled_restart,drt_restart)):raise AssertionError("Restart verification failed")
    facts=dict(scheduledSwap=scheduled,drtSwap=drt,drtContinuation=continuation,
               scheduledRestart=scheduled_restart,drtRestart=drt_restart,rejectionReplays=rejects)
    dump(output/"verified-summary.json",facts)
    def link(label,path):return f'[{label}]({(root/path).as_posix()})'
    lines=["# AAM follow-up repair validation","",
        "Existing results preserved. All new simulations use two synthetic travelers, or the previously documented small regression fixtures. No full revised regional model was run.","",
        "## Actual layout changes and restart checks","",
        "| Service | Accepted swap | Predicted utility improvement | Observed improvement, five paired seeds |",
        "|---|---|---:|---:|"]
    for label,r in (("Scheduled",scheduled),("DRT",drt)):
        lines.append(f'| {label} | VP08/VPALT → VP08/VP09 | {r["optimization"]["predictedImprovement"]:.6f} | {r["validation"]["realizedImprovement"]:.6f} |')
    lines += ["", "Both services pass actual restart checks: four scored source plans archived with exact plan/layout provenance, restarted input scores cleared, and alternatives rerouted and rescored. Removing the origin site yields ground choices, not prohibited walking or deleted ground options.","",
        "The scheduled test exposed and repaired an empty-ground-transit fallback crash. A separate concurrent-build class-loading failure interrupted the DRT post-acceptance stage. Private per-trial class snapshots now isolate runs from later compilation; paired comparisons check build hashes. The DRT continuation uses the last committed checkpoint, not partial trial output.","",
        f'DRT continuation status: `{continuation["status"]}`. Scheduled two-stage status: `safety_budget_reached_NOT_converged` (one stable stage after its accepted change is insufficient for the configured two-stage criterion). Neither status establishes global MATSim optimality.',"",
        "Harmful-layout rejection is verified through the real controller using cached paired MATSim observations and deliberately optimistic estimate fault injection. These are clearly labeled replays, not additional independent simulations. Failed-proposal feedback and population protection also pass unit tests.","",
        link("Scheduled swap and score audit","scheduled-swap-audit-01/REPORT.md")+" · "+link("DRT swap and score audit","drt-swap-audit-01/REPORT.md"),"",
        "## Controlled frequency comparison","",
        "Same population, scoring, fare, service hours, four seats and 50 departures in both arms. Demand allocation is trained on seed 817 only: 40 forward/10 reverse versus the reference 25/25. On held-out seeds 818–821, mean observed boarded wait falls from 1,471.5 to 779.5 seconds. Final ground choices and aggregate scores do not change. Iteration journeys are not unique demand, and this is not a regional forecast.","",
        link("Frequency report and assumptions","frequency-report-01/REPORT.md"),"",
        "## Aircraft reuse and cost accounting","",
        "The new offline dispatcher checks range, battery reserve, charging power/slots, turnaround, pads, maintenance, duty, aircraft site continuity and withheld reserves. It reports unserved departures and separate charging, maintenance and idle times. Under explicit synthetic technical inputs it serves 50 departures with two operating aircraft plus one reserve; the reference uses 50 operating aircraft.","",
        "Operating-cost formulas are implemented and tested, but numerical operating costs remain NOT SUPPLIED. The user's $30 base plus $2/mile is passenger fare, not aircraft/crew/energy/maintenance cost. No aircraft specification has been inferred from that fare.","",
        link("Constraint-aware aircraft report","aircraft-operations-02/REPORT.md"),"",
        "## Scope and remaining production decisions","",
        "The original named-traveler and saturated-corridor regressions remain valid; the new positive-swap fixture deliberately uses synthetic road speeds and high road-time disutility to exercise acceptance. It does not change production scoring. The exact stage solver optimizes the observed alternative catalog within the chosen candidate/swap universe; it is not a global optimum of the simulation.","",
        "Before production: agree walking/wait limits and failure behavior; provide calibrated aircraft technical and operating-cost inputs. Aircraft reuse is evaluated offline, not through shared-aircraft QSim rotations, and does not model weather/delay propagation, empty repositioning, maintenance staffing or parking stands. No calibrated fleet-size or profitability claim is made."]
    with (output/"REPORT.md").open("x",encoding="utf-8") as f:f.write("\n".join(lines)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("root",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();build(a.root,a.output)
