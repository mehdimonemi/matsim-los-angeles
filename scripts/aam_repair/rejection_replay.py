"""Fault-injection test of production rejection path using exact cached MATSim pairs.

Not a new simulation or an empirical forecast: deliberately optimistic coefficients
request the observed worse layout. All observed scores remain unmodified.
"""
import argparse
import copy
import json
from pathlib import Path
from .stages import run, dump


def replay(source, output):
    stage=source/"stage-000";m=json.loads((source/"manifest.json").read_text())
    decision=json.loads((stage/"decision.json").read_text())
    if not decision["validation"]["accepted"]:raise ValueError("Need an actual accepted paired layout change")
    good=decision["acceptedLayout"];bad=m["initialLayout"]
    m.update(initialLayout=good,maximumStages=1,note="Fault-injection replay of actual paired MATSim trials; not new simulations or calibrated estimates")
    def estimator(command,request,directory,name):
        value=copy.deepcopy(json.loads((stage/"estimates-result.json").read_text()))
        for row in value["alternatives"]:
            if set(row["sites"])==set(bad):
                row["scoreKind"]="faultInjected";row["successScore"]=row["score"]+1000;row["rejectionScore"]=row["score"]+1000
        value["faultInjection"]="Add 1000 utility to worse layout's AAM estimates; observations unchanged"
        dump(directory/(name+"-result.json"),value)
        return value
    def evaluator(command,request,directory,name):
        arm="proposal" if request["layout"]==good else "incumbent"
        path=stage/f'{arm}-{request["seed"]}-result.json'
        original_request=json.loads(path.with_name(path.name.replace("-result.json","-request.json")).read_text())
        for key in ("seed","checkpoint"):
            if request[key]!=original_request[key]:raise ValueError("Cached trial does not match requested "+key)
        if sorted(request["layout"])!=sorted(original_request["layout"]):raise ValueError("Cached layout mismatch")
        result=json.loads(path.read_text())
        for key in ("populationHash","scoringHash","supplyFareHash","eligibleIdsHash"):
            if result[key]!=m[key]:raise ValueError("Cached assumptions mismatch")
        result["cachedTrialSource"]=str(path.resolve())
        dump(directory/(name+"-result.json"),result)
        return result
    result=run(m,output,evaluator,estimator)
    if result["history"][0]["validation"]["accepted"] or result["acceptedLayout"]!=good:
        raise AssertionError("Observed harmful proposal must be rejected and incumbent retained")
    dump(output/"REPLAY-NOT-NEW-SIMULATION.json",dict(source=str(source.resolve()),faultInjection=True,
        outcome="Optimistic proposal rejected using unchanged paired MATSim observations; incumbent retained"))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("source",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();replay(a.source,a.output)
