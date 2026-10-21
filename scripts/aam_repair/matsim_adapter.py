"""Small-by-default evaluator adapter for stages.py; both service implementations.

Arguments: request.json result.json. Never overwrites a prior trial directory.
"""
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import shutil
import sys
import xml.etree.ElementTree as ET
from .reporting import xml_rows, funnel


def set_param(tree,module,name,value):
    m=tree.find(f"./module[@name='{module}']")
    if m is None:m=ET.SubElement(tree,"module",{"name":module})
    p=m.find(f"./param[@name='{name}']")
    if p is None:p=ET.SubElement(m,"param",{"name":name})
    p.set("value",str(value))


def evaluate(request,result_path):
    m=request["manifest"];source=Path(request["checkpoint"])
    ids=[p.get("id") for p in xml_rows(source,"person")]
    if len(ids)>100 and not m.get("allowLargePopulation",False):raise ValueError("Evaluator refuses >100 simulated people by default")
    if not set(m["eligibleIds"])<=set(ids):raise ValueError("Checkpoint missing eligible people")
    root=result_path.with_suffix("");root.mkdir(parents=True,exist_ok=False)
    layout=root/"layout.csv"
    with Path(m["candidateCsv"]).open(encoding="utf-8-sig",newline="") as f:sites={r["id"]:r for r in csv.DictReader(f)}
    with layout.open("x",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["id","name","x","y"]);w.writeheader()
        for site in request["layout"]:w.writerow({k:sites[site][k] for k in w.fieldnames})
    layout_id=hashlib.sha256(layout.read_bytes()).hexdigest()
    service=m["service"]
    if service=="scheduled":from scripts.aam_scheduled.score_optimizer.population import sanitize_population
    elif service=="drt":from scripts.aam.score_optimizer.population import sanitize_population
    else:raise ValueError("Unknown service")
    plans=root/"plans.xml.gz"
    sanitize_population(source,plans,request.get("checkpointLayoutId"))
    base=Path(m["baseConfig"]).resolve();config=ET.parse(base).getroot()
    # Relocating a config must not relocate its input paths.
    for parameter in config.findall(".//param"):
        name,value=parameter.get("name",""),parameter.get("value","")
        if (name.lower().endswith("file") or name.lower().endswith("filename")) and value and value!="null" and "://" not in value:
            path=Path(value)
            if not path.is_absolute():parameter.set("value",str((base.parent/path).resolve()))
    set_param(config,"global","randomSeed",request["seed"])
    set_param(config,"global","numberOfThreads",1);set_param(config,"qsim","numberOfThreads",1)
    set_param(config,"controler","writePlansInterval",1)
    set_param(config,"controler","createGraphs","false")
    set_param(config,"planCalcScore","writeExperiencedPlans","true")
    module="scheduledAam" if service=="scheduled" else "aam"
    for name,key in (("maximumWalkDistance","maximumWalkMeters"),("maximumWalkTime","maximumWalkSeconds"),
                     ("baseFare","baseFare"),("farePerMile","farePerMile"),
                     ("serviceStartTime","serviceStart"),("serviceEndTime","serviceEnd")):
        set_param(config,module,name,m[key])
    set_param(config,module,"maximumPassengerWait" if service=="scheduled" else "maxWaitTime",m["maximumWaitSeconds"])
    if service=="drt":set_param(config,module,"insertionEstimateSpeedFactor",m.get("insertionEstimateSpeedFactor",1))
    else:
        set_param(config,module,"headway",m["headway"])
        if "frequencyAllocationFile" in m:set_param(config,module,"frequencyAllocationFile",m["frequencyAllocationFile"])
    config_path=root/"config.xml"
    config_path.write_text('<?xml version="1.0"?><!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'+ET.tostring(config,encoding="unicode"),encoding="utf-8")
    output=root/"matsim"
    compiled=Path(m.get("compiledClassesDirectory",Path(m["projectRoot"])/"target"/("aam-scheduled-classes" if service=="scheduled" else "aam-v5-classes")))
    classes=root/"classes"
    shutil.copytree(compiled,classes)
    if not (classes/"org/matsim/run/aam/AamFeederPolicy.class").is_file():raise ValueError("Incomplete compiled runtime; compile before evaluation")
    digest=hashlib.sha256()
    for path in sorted(classes.rglob("*.class")):
        digest.update(path.relative_to(classes).as_posix().encode());digest.update(path.read_bytes())
    class_hash=digest.hexdigest()
    command=[*m["launcherCommand"],"-Config",str(config_path.resolve()),"-Output",str(output.resolve()),
             "-Plans",str(plans.resolve()),"-Vertiports",str(layout.resolve()),"-RunId","repair",
             "-FirstIteration","0","-LastIteration",str(m["evaluationIterations"]-1),"-DisableInnovation","-SkipCompile",
             "-ClassesDirectory",str(classes.resolve())]
    with (root/"console.log").open("x",encoding="utf-8") as log:subprocess.run(command,check=True,cwd=m["projectRoot"],stdout=log,stderr=subprocess.STDOUT)
    plan_outputs=list(output.glob("*.output_plans.xml.gz"));event_outputs=list(output.glob("*.output_events.xml.gz"))
    experienced_outputs=list(output.glob("*.output_experienced_plans.xml.gz"))
    if len(plan_outputs)!=1 or len(event_outputs)!=1 or len(experienced_outputs)!=1:raise ValueError("Missing/ambiguous MATSim output or experienced plans")
    scores={};all_scored=True
    for person in xml_rows(plan_outputs[0],"person"):
        if person.get("id") not in m["eligibleIds"]:continue
        for plan in person.findall("plan"):
            score=float(plan.get("score","nan"));all_scored &= math.isfinite(score)
    # PlansDumping occurs BEFORE the final selected-plan/queue gate. Only
    # experienced plans provide the executed population objective.
    for person in xml_rows(experienced_outputs[0],"person"):
        if person.get("id") in m["eligibleIds"]:
            chosen=next(p for p in person.findall("plan") if p.get("selected")=="yes")
            scores[person.get("id")]=float(chosen.get("score","nan"))
    if set(scores)!=set(m["eligibleIds"]) or any(not math.isfinite(s) for s in scores.values()):raise ValueError("Missing observed population scores; never drop unfinished travelers")
    metrics,_=funnel(event_outputs[0],experienced_outputs[0])
    result={k:m[k] for k in ("populationHash","scoringHash","supplyFareHash","eligibleIdsHash")}
    series=[];iteration_outputs=[]
    for iteration_dir in sorted((output/"ITERS").glob("it.*"),key=lambda p:int(p.name.split(".")[-1])):
        files=list(iteration_dir.glob("*.experienced_plans.xml.gz"))
        if len(files)!=1:continue
        event_files=list(iteration_dir.glob("*.events.xml.gz"))
        if len(event_files)==1:iteration_outputs.append({"checkpoint":str(files[0].resolve()),"events":str(event_files[0].resolve()),"iteration":int(iteration_dir.name.split(".")[-1])})
        observed={}
        for person in xml_rows(files[0],"person"):
            if person.get("id") not in m["eligibleIds"]:continue
            chosen=next((p for p in person.findall("plan") if p.get("selected")=="yes"),None)
            if chosen is not None:observed[person.get("id")]=float(chosen.get("score","nan"))
        if set(observed)==set(m["eligibleIds"]) and all(math.isfinite(v) for v in observed.values()):series.append(math.fsum(observed.values()))
    result.update(engine="MATSim",classSnapshotHash=class_hash,stage=request["stage"],seed=request["seed"],scores=scores,checkpoint=str(plan_outputs[0].resolve()),experiencedPlans=str(experienced_outputs[0].resolve()),events=str(event_outputs[0].resolve()),
                  layoutId=layout_id,metrics=metrics,allCompetingPlansRescored=all_scored,
                  populationObjectiveByIteration=series,iterationOutputs=iteration_outputs)
    with result_path.open("x",encoding="utf-8") as f:json.dump(result,f,indent=2,allow_nan=False)
    return result


if __name__=="__main__":evaluate(json.loads(Path(sys.argv[1]).read_text()),Path(sys.argv[2]))
