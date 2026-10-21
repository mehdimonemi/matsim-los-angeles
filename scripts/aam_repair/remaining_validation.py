"""Three-site synthetic regression and controlled frequency experiment. <=2 people."""
import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from .make_small_cases import write_xml
from .matsim_adapter import evaluate, set_param
from .validation_manifest import make
from .stages import dump, run, freeze_runtime
from .reporting import allocate_departures, compare, funnel


def prepare(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=False)
    source=Path("run-output/aam-repair-validation/named-daytime-inputs-01").resolve()
    with (source/"ports.csv").open() as f:ports=list(csv.DictReader(f))
    ports.append(dict(id="VPALT",name="Synthetic displaced destination",x=str(float(ports[1]["x"])+5000),y=ports[1]["y"]))
    with (root/"ports.csv").open("x",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["id","name","x","y"]);w.writeheader();w.writerows(ports)
    population=ET.parse(source/"population.xml").getroot()
    for index,person in enumerate(population.findall("person")):
        person.set("id",f"synthetic-{index}")
        for plan in person.findall("plan"):
            elements=list(plan);acts=[e for e in elements if e.tag in ("activity","act")]
            destination=acts[1]
            for e in elements[elements.index(destination)+1:]:plan.remove(e)
            for i,act in enumerate(acts[:2]):
                act.set("x",ports[i]["x"]);act.set("y",ports[i]["y"]);act.set("link",f"road_loop_{i}")
                act.attrib.pop("end_time",None)
                if i==0:act.set("end_time",str(25500+index*60))
                attributes=act.find("attributes")
                if attributes is not None:act.remove(attributes)
            for leg in plan.findall("leg"):
                leg.set("mode","ride");leg.attrib.pop("trav_time",None)
                for e in list(leg):leg.remove(e)
    write_xml(root/"population.xml",population,"population_v6.dtd")
    import math
    net=ET.Element("network");nodes=ET.SubElement(net,"nodes");links=ET.SubElement(net,"links")
    for i,p in enumerate(ports):ET.SubElement(nodes,"node",id=f"n{i}",x=p["x"],y=p["y"])
    for i,p in enumerate(ports):
        for j,q in enumerate(ports):
            distance=math.hypot(float(p["x"])-float(q["x"]),float(p["y"])-float(q["y"]))
            ET.SubElement(links,"link",id=f"road_loop_{i}" if i==j else f"road_{i}_{j}",**{
                "from":f"n{i}","to":f"n{j}","length":str(max(1,1.4*distance)),"freespeed":"3",
                "capacity":"100000","permlanes":"2","modes":"car,freight,ride,ride_taxi,ride_school_bus,bike,bus"})
    write_xml(root/"network.xml",net,"network_v2.dtd")
    # Keep an empty ground schedule: this fixture isolates road-vs-AAM choice.
    write_xml(root/"schedule.xml",ET.Element("transitSchedule"),"transitSchedule_v2.dtd")
    for service in ("scheduled","drt"):
        c=ET.parse(source/(service+".config.xml")).getroot()
        for module,name,value in (("network","inputNetworkFile",root/"network.xml"),("plans","inputPlansFile",root/"population.xml"),
                                  ("transit","transitScheduleFile",root/"schedule.xml")):
            set_param(c,module,name,value)
        # Deliberately high road-time disutility makes this a positive swap
        # regression, not a calibration or change to the production scenario.
        for mode in c.findall("./module[@name='planCalcScore']/parameterset/parameterset"):
            named=mode.find("param[@name='mode']")
            if named is not None and named.get("value") in ("ride","ride_taxi"):
                travel=mode.find("param[@name='marginalUtilityOfTraveling_util_hr']")
                if travel is None:travel=ET.SubElement(mode,"param",name="marginalUtilityOfTraveling_util_hr")
                travel.set("value","-120")
        write_xml(root/(service+".config.xml"),c,"config_v2.dtd")
        manifest_file=root/(service+"-manifest.json")
        # Construct in memory to avoid overwriting any generated manifest.
        temporary=root/(service+"-template.json");make(root,service,temporary,stages=2)
        m=json.loads(temporary.read_text());m.update(eligibleIds=["synthetic-0","synthetic-1"],
            eligibleIdsHash=hashlib.sha256(json.dumps(["synthetic-0","synthetic-1"]).encode()).hexdigest(),
            initialLayout=["VP08","VPALT"],evaluationIterations=8,maximumProbeLayouts=3,
            note="Synthetic one-way two-person three-site fixture, 3 m/s ground speed and -120 utils/h road passenger time; positive-swap stress test, NOT Los Angeles demand evidence.")
        dump(manifest_file,m)
    dump(root/"ASSUMPTIONS.json",dict(population=2,synthetic=True,groundSpeedMetersPerSecond=3,rideTravelUtilityPerHour=-120,
        purpose="Nontrivial swap and frequency regression only",productionCalibration=False))


def frequencies(manifest_path,output):
    m=json.loads(manifest_path.read_text());output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    m=freeze_runtime(m,output)
    m["initialLayout"]=["VP08","VP09"];m["maximumStages"]=1
    results=[];manifests=[];allocation=None
    for seed in m["seeds"]:
        for arm in ("reference","demand-weighted"):
            trial=copy.deepcopy(m)
            if arm=="demand-weighted":
                trial["frequencyAllocationFile"]=str(allocation)
                trial["supplyFareHash"]=hashlib.sha256(m["supplyFareHash"].encode()+allocation.read_bytes()).hexdigest()
            r=evaluate(dict(manifest=trial,stage=0,seed=seed,checkpoint=m["population"],layout=m["initialLayout"]),output/f"{arm}-{seed}.json")
            results.append(dict(arm=arm,**r))
            if allocation is None:
                # Freeze demand weights from FIRST baseline training run only.
                demand={"VP08_VP09":0,"VP09_VP08":0}
                for obs in r["iterationOutputs"]:
                    _,attempts=funnel(obs["events"],obs["checkpoint"])
                    for a in attempts:
                        key=a["from"].replace("aam_sched_stop_","")+"_"+a["to"].replace("aam_sched_stop_","")
                        if key in demand:demand[key]+=1
                counts=allocate_departures(demand,50,minimum_per_corridor=10)
                allocation=output/"frequency-allocation.csv"
                with allocation.open("x",newline="") as f:
                    w=csv.writer(f);w.writerow(["origin","destination","departures"])
                    for key,count in counts.items():w.writerow([*key.split("_"),count])
                dump(output/"frequency-training.json",dict(demand=demand,counts=counts,trainingSeed=seed,
                    note="Training seed reported separately; seeds 818-821 are held-out policy evaluation. 50 departures in both arms."))
            for obs in r["iterationOutputs"]:
                manifests.append(dict(name=f"{arm}-{seed}-iteration-{obs['iteration']}",populationHash=m["populationHash"],
                    eligibleIdsHash=m["eligibleIdsHash"],seed=seed,serviceStart=m["serviceStart"],serviceEnd=m["serviceEnd"],
                    plans=obs["checkpoint"],events=obs["events"],fareAssumptions="$30 + $2 per air mile",
                    scoringAssumptions=m["scoringHash"],supplyAssumptions=f"{arm}: 50 departures, 4 seats each, one aircraft per departure"))
        compare([r for r in manifests if r["seed"]==seed],output/f"comparison-{seed}")
    dump(output/"results.json",results)


def continue_accepted(source,output):
    """New output root, last committed accepted checkpoint; never resume partial trials."""
    m=json.loads((source/"manifest.json").read_text())
    decisions=sorted(source.glob("stage-*/decision.json"))
    if not decisions:raise ValueError("No completed stage to continue")
    path=decisions[-1];decision=json.loads(path.read_text())
    arm="proposal" if decision["validation"]["accepted"] else "incumbent"
    prior=json.loads((path.parent/f'{arm}-{m["seeds"][0]}-result.json').read_text())
    m.update(initialLayout=decision["acceptedLayout"],initialLayoutId=prior["layoutId"],population=prior["checkpoint"],
             continuationOf=str(source.resolve()),continuationDecision=str(path.resolve()))
    return run(m,output)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=["prepare","stage","frequency","continue"]);p.add_argument("path",type=Path);p.add_argument("--output",type=Path)
    a=p.parse_args()
    if a.action=="prepare":prepare(a.path)
    elif a.action=="stage":run(json.loads(a.path.read_text()),a.output)
    elif a.action=="continue":continue_accepted(a.path,a.output)
    else:frequencies(a.path,a.output)
