"""Build a small-only stage manifest from make_small_cases outputs (does not run)."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from .stages import dump


def make(inputs,service,output,stages=2):
    project=Path.cwd().resolve();inputs=inputs.resolve()
    with (inputs/"ports.csv").open() as f:sites=[r["id"] for r in csv.DictReader(f)]
    ids=["10092375","10096817"]
    m=dict(service=service,population=str(inputs/"population.xml"),projectRoot=str(project),eligibleIds=ids,
        eligibleIdsHash=hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
        populationHash=hashlib.sha256((inputs/"population.xml").read_bytes()).hexdigest(),
        scoringHash=hashlib.sha256((inputs/(service+".config.xml")).read_bytes()).hexdigest(),
        supplyFareHash=hashlib.sha256(f"{service}|7-19|4seats|1800|30+2/mile|toy-v1".encode()).hexdigest(),
        baseConfig=str(inputs/(service+".config.xml")),candidateCsv=str(inputs/"ports.csv"),
        initialLayout=sites,candidates=sites,seeds=[817,818,819,820,821],
        serviceStart=25200,serviceEnd=68400,headway=1800,baseFare=30,farePerMile=2,
        maximumWalkMeters=1000,maximumWalkSeconds=1200,maximumWaitSeconds=1800 if service=="scheduled" else 900,
        feederModes=["car","ride","ride_taxi","walk","bike"],evaluationIterations=5,maximumStages=stages,
        minimumPredictedImprovement=.01,minimumObservedImprovement=.01,solverSeconds=30,
        simulationTolerance=.01,stableStages=2,criticalValue=2.776,swaps=1,maximumProbeLayouts=1,
        estimatorCommand=[sys.executable,"-B","-m","scripts.aam_repair.empirical_estimator"],
        evaluatorCommand=[sys.executable,"-B","-m","scripts.aam_repair.matsim_adapter"],
        launcherCommand=["pwsh","-NoProfile","-ExecutionPolicy","Bypass","-File",
            str(project/("scripts/aam-scheduled/run_scheduled_aam.ps1" if service=="scheduled" else "scripts/aam/run_aam_v5.ps1")),"-Memory","2g"],
        allowLargePopulation=False,
        note="Plumbing/convergence test with two real traveler records on a toy graph. No alternative sites: swap/acceptance behavior has separate unit tests.")
    dump(output,m)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("inputs",type=Path);p.add_argument("--service",choices=["scheduled","drt"],required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--stages",type=int,default=2)
    a=p.parse_args();make(a.inputs,a.service,a.output,a.stages)
