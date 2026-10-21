"""Sequential manifest-based four-neighborhood comparison for both services."""
import argparse
import csv
import json
import time
from pathlib import Path
from .neighborhoods import METHODS
from .production_manifests import validate
from .stages import run, dump


def compare(package, output, services=("scheduled","drt"), methods=METHODS,
            allow_large_population=False, runner=run):
    validate(package)
    manifests={s:json.loads((package/(s+"-production-manifest.json")).read_text()) for s in services}
    for m in manifests.values():
        if len(m["eligibleIds"])>100 and not allow_large_population:
            raise ValueError("Use --allow-large-population to launch regional trials")
    if len(manifests)==2:
        for key in ("populationHash","eligibleIdsHash","initialLayout","candidates","seeds","baseFare","farePerMile",
                    "maximumWalkMeters","maximumWalkSeconds","serviceStart","serviceEnd"):
            if manifests["scheduled"][key]!=manifests["drt"][key]:raise ValueError("Incomparable service manifests: "+key)
    output.mkdir(parents=True,exist_ok=False)
    dump(output/"suite.json",dict(package=str(package.resolve()),services=list(services),methods=list(methods),
        sharedCoefficientPolicy="All methods probe the full configured swap universe at each stage; method trajectories subsequently differ.",
        acceptance="Paired MATSim lower confidence bound above manifest minimum improvement",
        note="Iteration counts are per trial; stage budgets and convergence differ from the legacy fixed 50-iteration suite."))
    summaries=[]
    for service,m in manifests.items():
        service_root=output/service;service_root.mkdir()
        for method in methods:
            trial={**m,"searchMethod":method}
            started=time.monotonic()
            result=runner(trial,service_root/method,allow_large_population=allow_large_population)
            summaries.append(dict(service=service,method=method,status=result["status"],stages=len(result["history"]),
                acceptedChanges=sum(r["validation"]["accepted"] for r in result["history"]),
                acceptedLayout="|".join(result["acceptedLayout"]),elapsedSeconds=time.monotonic()-started,
                estimationSeconds=sum(r.get("estimationSeconds",0) for r in result["history"]),
                optimizationSeconds=sum(r.get("optimizationSeconds",0) for r in result["history"]),
                validationSeconds=sum(r.get("validationSeconds",0) for r in result["history"]),
                predictedGain=sum(r["optimization"]["predictedImprovement"] for r in result["history"]),
                realizedAcceptedGain=sum(r["validation"]["realizedImprovement"] for r in result["history"] if r["validation"]["accepted"])))
            # Update only this new suite's progress files; all trial artifacts are immutable.
            (output/"comparison.json").write_text(json.dumps(summaries,indent=2,allow_nan=False),encoding="utf-8")
            with (output/"comparison.csv").open("w",newline="",encoding="utf-8") as f:
                writer=csv.DictWriter(f,fieldnames=list(summaries[0]));writer.writeheader();writer.writerows(summaries)
    return summaries


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("package",type=Path);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--services",nargs="+",choices=["scheduled","drt"],default=["scheduled","drt"])
    p.add_argument("--methods",nargs="+",choices=METHODS,default=list(METHODS))
    p.add_argument("--allow-large-population",action="store_true")
    a=p.parse_args();compare(a.package,a.output,a.services,a.methods,a.allow_large_population)
