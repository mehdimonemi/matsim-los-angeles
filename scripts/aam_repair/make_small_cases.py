"""Prepare (do not run) a two-real-traveler regression on a documented toy road graph.

Activity coordinates/times and person attributes come from the original population;
the complete Euclidean x1.4 road graph is NOT the Los Angeles road network.
"""
import argparse
import copy
import csv
import gzip
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from .matsim_adapter import set_param
from .reporting import xml_rows


def write_xml(path, root, dtd=None):
    text='<?xml version="1.0" encoding="utf-8"?>\n'
    if dtd:text+=f'<!DOCTYPE {root.tag} SYSTEM "http://www.matsim.org/files/dtd/{dtd}">\n'
    text+=ET.tostring(root,encoding="unicode")
    with path.open("x",encoding="utf-8") as f:f.write(text)


def prepare(project,output,shift_seconds=0):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    source=project/"run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz"
    wanted={"10096817","10092375"};people=[];coords=[]
    for person in xml_rows(source,"person"):
        if person.get("id") not in wanted:continue
        clone=copy.deepcopy(person)
        for plan in clone.findall("plan"):
            plan.attrib.pop("score",None)
            for leg in plan.findall("leg"):
                for route in leg.findall("route"):leg.remove(route)
            for act in list(plan.findall("activity"))+list(plan.findall("act")):
                if shift_seconds and act.get("end_time"):
                    raw=act.get("end_time")
                    if ":" in raw:
                        h,m,s=map(float,raw.split(":"));value=h*3600+m*60+s
                    else:value=float(raw)
                    act.set("end_time",str(value+shift_seconds))
                coord=(float(act.get("x")),float(act.get("y")))
                if coord not in coords:coords.append(coord)
                act.set("link",f"road_loop_{coords.index(coord)}")
        people.append(clone)
    if {p.get("id") for p in people}!=wanted:raise ValueError("Named travelers missing from initial population")
    with (project/"scenarios/aam-scheduled/vertiports.csv").open(encoding="utf-8-sig") as f:
        ports=[r for r in csv.DictReader(f) if r["id"] in {"VP08","VP09"}]
    for port in ports:
        coord=(float(port["x"]),float(port["y"]))
        if coord not in coords:coords.append(coord)
    population=ET.Element("population");population.extend(people);write_xml(output/"population.xml",population,"population_v6.dtd")
    network=ET.Element("network");nodes=ET.SubElement(network,"nodes");links=ET.SubElement(network,"links")
    for i,(x,y) in enumerate(coords):ET.SubElement(nodes,"node",id=f"n{i}",x=str(x),y=str(y))
    for i,origin in enumerate(coords):
        for j,destination in enumerate(coords):
            ET.SubElement(links,"link",{"id":f"road_loop_{i}" if i==j else f"road_{i}_{j}","from":f"n{i}","to":f"n{j}",
                "length":str(max(1,1.4*math.dist(origin,destination))),"freespeed":"13.89","capacity":"100000","permlanes":"2",
                "modes":"car,freight,ride,ride_taxi,ride_school_bus,bike,bus"})
    write_xml(output/"network.xml",network,"network_v2.dtd")
    with (output/"ports.csv").open("x",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["id","name","x","y"]);w.writeheader();w.writerows(ports)
    schedule=ET.Element("transitSchedule");stops=ET.SubElement(schedule,"transitStops")
    indices=[coords.index((float(p["x"]),float(p["y"]))) for p in ports]
    for i,p in zip(indices,ports):ET.SubElement(stops,"stopFacility",id=f"ground_{i}",x=p["x"],y=p["y"],linkRefId=f"road_loop_{i}",isBlocking="false")
    vehicles=ET.Element("vehicleDefinitions",{"xmlns":"http://www.matsim.org/files/dtd","xmlns:xsi":"http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation":"http://www.matsim.org/files/dtd http://www.matsim.org/files/dtd/vehicleDefinitions_v1.0.xsd"})
    vt=ET.SubElement(vehicles,"vehicleType",id="bus");capacity=ET.SubElement(vt,"capacity");ET.SubElement(capacity,"seats",persons="40");ET.SubElement(capacity,"standingRoom",persons="0")
    for i,j in (indices,indices[::-1]):
        line=ET.SubElement(schedule,"transitLine",id=f"bus_{i}_{j}");route=ET.SubElement(line,"transitRoute",id=f"bus_{i}_{j}")
        ET.SubElement(route,"transportMode").text="bus";profile=ET.SubElement(route,"routeProfile")
        tt=math.ceil(1.4*math.dist(coords[i],coords[j])/13.89)
        ET.SubElement(profile,"stop",refId=f"ground_{i}",departureOffset="0",awaitDeparture="true")
        ET.SubElement(profile,"stop",refId=f"ground_{j}",arrivalOffset=str(tt),departureOffset=str(tt+60),awaitDeparture="true")
        nr=ET.SubElement(route,"route")
        for link in (f"road_loop_{i}",f"road_{i}_{j}",f"road_loop_{j}"):ET.SubElement(nr,"link",refId=link)
        departures=ET.SubElement(route,"departures")
        for hour in range(7,20):
            vid=f"bus_{i}_{j}_{hour}";ET.SubElement(vehicles,"vehicle",id=vid,type="bus")
            ET.SubElement(departures,"departure",id=str(hour),departureTime=str(hour*3600),vehicleRefId=vid)
    write_xml(output/"schedule.xml",schedule,"transitSchedule_v2.dtd");write_xml(output/"transit-vehicles.xml",vehicles)
    for service,base in (("scheduled","scenarios/aam-scheduled/la-aam-scheduled.config.xml"),("drt","scenarios/aam/la-aam-fare30-it2.config.xml")):
        base=(project/base).resolve();c=ET.parse(base).getroot()
        for parameter in c.findall(".//param"):
            name,value=parameter.get("name",""),parameter.get("value","")
            if name.lower().endswith("file") and value and value!="null" and "://" not in value and not Path(value).is_absolute():parameter.set("value",str((base.parent/value).resolve()))
        for module,name,value in (("network","inputNetworkFile",output/"network.xml"),("plans","inputPlansFile",output/"population.xml"),
            ("transit","transitScheduleFile",output/"schedule.xml"),("transit","vehiclesFile",output/"transit-vehicles.xml"),
            ("global","numberOfThreads",1),("qsim","numberOfThreads",1),("global","randomSeed",817),
            ("qsim","flowCapacityFactor",1),("qsim","storageCapacityFactor",1),("controler","lastIteration",3)):
            set_param(c,module,name,value)
        module="scheduledAam" if service=="scheduled" else "aam"
        for name,value in (("maximumWalkDistance",1000),("maximumWalkTime",1200),("baseFare",30),("farePerMile",2),
                           ("serviceStartTime",25200),("serviceEndTime",68400)):
            set_param(c,module,name,value)
        if service=="scheduled":set_param(c,module,"vertiportsFile",output/"ports.csv")
        else:
            set_param(c,module,"activeVertiportsFile",output/"ports.csv");set_param(c,module,"activeVertiportCount",2)
            set_param(c,module,"insertionEstimateSpeedFactor",1)
        write_xml(output/(service+".config.xml"),c,"config_v2.dtd")
    (output/"case.json").write_text(json.dumps({"persons":sorted(wanted),"source":str(source),"population":2,
        "roadAssumption":"Synthetic complete graph, 1.4 x Euclidean distance, 13.89 m/s; NOT regional validation",
        "vertiports":[p["id"] for p in ports],"activityEndTimeShiftSeconds":shift_seconds,"serviceHours":[25200,68400],"baseFare":30,"farePerMile":2},indent=2))
    return output


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,required=True);p.add_argument("--project",type=Path,default=Path.cwd())
    p.add_argument("--shift-seconds",type=float,default=0)
    a=p.parse_args();print(prepare(a.project,a.output,a.shift_seconds))
