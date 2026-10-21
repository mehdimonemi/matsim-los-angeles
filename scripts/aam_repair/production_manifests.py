"""Generate/revalidate regional-input manifests WITHOUT running Java or MATSim.

Targets the repaired four-neighborhood stage workflow, not legacy proxy suites.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
from .matsim_adapter import set_param
from .make_small_cases import write_xml
from .reporting import xml_rows
from .stages import dump


def fingerprint(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def sites(path, count):
    with path.open(encoding="utf-8-sig",newline="") as f:rows=list(csv.DictReader(f))
    if len(rows)!=count or any(not r.get("id") for r in rows) or len({r["id"] for r in rows})!=count:
        raise ValueError(f"Expected {count} unique site IDs in {path}")
    if any(not math.isfinite(float(r[k])) for r in rows for k in ("x","y")):raise ValueError("Invalid site coordinates")
    return {r["id"]:r for r in rows}


def cohort(population):
    all_ids=set();travelers=[];subpopulations={}
    for person in xml_rows(population,"person"):
        pid=person.get("id")
        if not pid or pid in all_ids:raise ValueError("Missing/duplicate population ID")
        all_ids.add(pid)
        attr=person.find("./attributes/attribute[@name='subpopulation']")
        subpop=attr.text if attr is not None else "MISSING"
        subpopulations[subpop]=subpopulations.get(subpop,0)+1
        if subpop=="person":
            if not person.findall("plan"):raise ValueError("Traveler has no plan: "+pid)
            travelers.append(pid)
    if not travelers:raise ValueError("No subpopulation=person travelers")
    return sorted(travelers),dict(totalSimulatedPersons=len(all_ids),objectiveTravelers=len(travelers),subpopulations=subpopulations)


def validate(directory):
    directory=directory.resolve();index=json.loads((directory/"package-index.json").read_text())
    for raw,expected in index["fingerprints"].items():
        path=Path(raw)
        # Tool executables are runtime prerequisites, not experiment inputs.
        # Windows updates may replace powershell.exe without changing the
        # prepared scenario, so check availability below but do not pin bytes.
        if path.name.lower() in {"powershell.exe","python.exe","java.exe"}:
            if not path.is_file():raise ValueError("Missing runtime executable: "+raw)
            continue
        if not path.is_file() or fingerprint(path)!=expected:raise ValueError("Missing/changed input: "+raw)
    services=index.get("services",["scheduled","drt"])
    if not services or len(set(services))!=len(services) or not set(services)<= {"scheduled","drt"}:
        raise ValueError("Invalid package services")
    manifests=[json.loads((directory/(s+"-production-manifest.json")).read_text()) for s in services]
    ids,counts=cohort(Path(manifests[0]["population"]))
    candidates=sites(Path(manifests[0]["candidateCsv"]),100)
    for m in manifests:
        if m["eligibleIds"]!=ids or m["eligibleIdsHash"]!=json_hash(ids):raise ValueError("Population cohort mismatch")
        if set(m["candidates"])!=set(candidates) or len(m["initialLayout"])!=10 or not set(m["initialLayout"])<=set(candidates):raise ValueError("Invalid layout/candidate IDs")
        if len(m["seeds"])<5 or len(set(m["seeds"]))!=len(m["seeds"]):raise ValueError("Need >=5 distinct seeds")
        if not m["allowLargePopulation"] or m["launcherCommand"][0].lower().split(os.sep)[-1]!="powershell.exe":raise ValueError("Wrong launcher/large-population setting")
        if not Path(m["launcherCommand"][0]).is_file() or not Path(m["launcherCommand"][5]).is_file():raise ValueError("Missing PowerShell/launcher")
        for command in (m.get("estimatorCommand",[]),m.get("evaluatorCommand",[])):
            if not command or not Path(command[0]).is_file():raise ValueError("Missing Python runtime")
        if m["populationHash"]!=fingerprint(m["population"]) or m["scoringHash"]!=fingerprint(m["baseConfig"]):raise ValueError("Input fingerprint mismatch")
        if m["supplyFareHash"]!=json_hash(m["supplyFareAssumptions"]):raise ValueError("Supply/fare fingerprint mismatch")
        if m['service']=='drt':
            config=ET.parse(m['baseConfig']).getroot()
            def param(module,name,default=None):
                element=config.find(f"./module[@name='{module}']/param[@name='{name}']")
                return default if element is None else element.get('value')
            if param('qsim','endTime') not in ('36:00:00','36:00','129600','129600.0'):
                raise ValueError('DRT Global requires the unchanged 36-hour QSim horizon')
            if float(param('aam','serviceStartTime',0))!=m['serviceStart'] or float(param('aam','serviceEndTime',129600))!=m['serviceEnd']:
                raise ValueError('DRT routing and optimizer service windows disagree')
            access=float(param('aam','maxAccessDistanceMiles',5))
            egress=float(param('aam','maxEgressDistanceMiles',access))
            if access!=m.get('maxAccessDistanceMiles',5) or egress!=m.get('maxEgressDistanceMiles',access):
                raise ValueError('DRT routing and optimizer distance limits disagree')
            if (param('aam','allowPreServiceRequests','true').lower()=='true')!=m.get('allowPreServiceRequests',True):
                raise ValueError('DRT routing and optimizer request-window settings disagree')
            for name,key,default in [('baseFare','baseFare',0),('farePerMile','farePerMile',2),
                    ('minimumTripDistanceMiles','minimumTripDistanceMiles',3),('candidateVertiports','candidateVertiports',3),
                    ('maximumCandidateVertiportPairs','maximumCandidateVertiportPairs',3)]:
                if float(param('aam',name,default))!=float(m.get(key,default)):
                    raise ValueError('DRT routing and optimizer disagree: '+name)
            if int(param('aam','protectedAlternatives',1))!=1 or int(m.get('protectedAlternatives',1))!=1:
                raise ValueError('Fast DRT package must seed exactly one protected AAM alternative')
            if param('aam','seedAlternativesAtStartup','true').lower()!='true':
                raise ValueError('Production DRT package must enable startup alternative seeding')
            for name in ('AamCandidateScreen','AamPlanRemovalSelector','RunDynamicAamLosAngelesScenario'):
                if not (Path(m['compiledClassesDirectory'])/'org/matsim/run/aam'/f'{name}.class').is_file():
                    raise ValueError('Missing fixed DRT runtime class: '+name)
        for path in Path(m["compiledClassesDirectory"]).rglob("*.class"):
            with path.open("rb") as f:
                if f.read(4)!=b"\xca\xfe\xba\xbe":raise ValueError("Invalid compiled class: "+str(path))
    return dict(status="PASS_STATIC_VALIDATION",matSimStarted=False,**counts,
                candidates=100,initialSites=10,filesFingerprinted=len(index["fingerprints"]),
                warning="Static file/cohort/bytecode validation is not MATSim startup validation or production calibration.")


def create(project, output, iterations=50, stages=20, probes=901, memory="18g", tolerance=1.0, services=("scheduled","drt")):
    if iterations<3 or stages<1 or not 1<=probes<=901 or not math.isfinite(tolerance) or tolerance<0:
        raise ValueError("Invalid iteration/stage/probe/stability budget")
    if not services or len(set(services))!=len(services) or not set(services)<= {"scheduled","drt"}:
        raise ValueError("Invalid package services")
    project=project.resolve();output=output.resolve()
    if output.exists():raise FileExistsError("Use a NEW manifest directory: "+str(output))
    ps=Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32/WindowsPowerShell/v1.0/powershell.exe"
    if not ps.is_file():raise FileNotFoundError("Windows PowerShell executable not found")
    java=shutil.which("java")
    if not java:raise FileNotFoundError("java is not on PATH; no Java process was started")
    population=project/"run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz"
    candidate_file=project/"scenarios/aam/vertiport-candidates-100.csv"
    initial_file=project/"scenarios/aam/active-vertiports.csv"
    candidates=sites(candidate_file,100);initial=sites(initial_file,10)
    if not initial.keys()<=candidates.keys():raise ValueError("Initial site missing from candidates")
    for key in initial:
        if any(not math.isclose(float(initial[key][k]),float(candidates[key][k]),abs_tol=1e-6) for k in ("x","y")):
            raise ValueError("Initial/candidate coordinates disagree: "+key)
    ids,counts=cohort(population)
    output.mkdir(parents=True,exist_ok=False);fingerprints={}
    def track(path):
        path=Path(path).resolve()
        if str(path) not in fingerprints:fingerprints[str(path)]=fingerprint(path)
        return fingerprints[str(path)]
    track(population);track(candidate_file);track(initial_file)
    cohort_file=output/"cohort.json"
    dump(cohort_file,dict(ids=ids,**counts,definition="All subpopulation=person travelers, fixed across layouts; no current-AAM-user or incumbent-radius filter. Ineligible people retain ground choices. Other subpopulations remain simulated but outside this passenger objective."));track(cohort_file)
    # Hash pinned MATSim dependencies and scripts as well as scenario inputs.
    jars=list((project/"target/aam-runtime").rglob("*.jar"))
    if not jars:raise FileNotFoundError("MATSim runtime JARs missing")
    for path in jars:track(path)
    for path in (project/"scripts/aam_repair").glob("*.py"):track(path)
    track(project/"scripts/aam_repair/run_comparison.ps1")
    for launcher in ('run_drt_global.ps1','run_drt_optimizers.ps1'):
        track(project/'scripts/aam_repair'/launcher)
    for path in ("scripts/aam/score_optimizer/population.py","scripts/aam_scheduled/score_optimizer/population.py"):
        track(project/path)
    for name in ("experiment.py","optimizer.py","common.py","screening.py"):
        track(project/"scripts/aam/score_optimizer"/name)
    for service,base_name in (("scheduled","scenarios/aam-scheduled/la-aam-scheduled.config.xml"),("drt","scenarios/aam/la-aam-fare30-it2.config.xml")):
        if service not in services:continue
        base=project/base_name;track(base);config=ET.parse(base).getroot()
        for p in config.findall(".//param"):
            name,value=p.get("name","").lower(),p.get("value","")
            if (name.endswith("file") or name.endswith("filename")) and value not in ("","null"):
                if "://" in value:raise ValueError("Remote input not validated: "+value)
                path=Path(value);path=path if path.is_absolute() else (base.parent/path).resolve()
                track(path);p.set("value",str(path))
        module="scheduledAam" if service=="scheduled" else "aam"
        values=dict(baseFare=30,farePerMile=2,serviceStartTime=25200,serviceEndTime=68400,
                    maximumWalkDistance=1000,maximumWalkTime=1200,accessEgressModes="car,ride,ride_taxi,walk,bike",candidateVertiports=3)
        if service=="scheduled":values.update(vertiportsFile=str(initial_file),headway=1800,seats=4,dwellTime=60,cruiseSpeed=44.704,maximumPassengerWait=1800,frequencyAllocationFile="")
        else:values.update(activeVertiportsFile=str(initial_file),activeVertiportCount=10,maxWaitTime=900,insertionEstimateSpeedFactor=1,
                           baseFare=0,serviceStartTime=25200,serviceEndTime=68400,
                           maxAccessDistanceMiles=30,maxEgressDistanceMiles=30,allowPreServiceRequests="true",
                           minimumTripDistanceMiles=0,candidateVertiports=3,
                           maximumRoutedCandidates=3,maximumCandidateVertiportPairs=3,protectedAlternatives=1,initialExplorationFraction=1,
                           seedAlternativesAtStartup="true",allowCarAtHomeAlternatives="true")
        for key,value in values.items():set_param(config,module,key,value)
        set_param(config,"plans","inputPlansFile",population)
        frozen_config=output/(service+".config.xml");write_xml(frozen_config,config,"config_v2.dtd");track(frozen_config)
        compiled=project/"target"/("aam-scheduled-classes" if service=="scheduled" else "aam-v5-classes")
        main="scheduled/RunScheduledAamLosAngelesScenario" if service=="scheduled" else "RunDynamicAamLosAngelesScenario"
        for name in ("AamFeederPolicy",main):
            if not (compiled/("org/matsim/run/aam/"+name+".class")).is_file():raise FileNotFoundError("Compile first: "+str(compiled))
        for sources in (project/"src/main/java/org/matsim/run",project/"src/main/java/org/matsim/parkingCost"):
            for source in sources.rglob("*.java"):
                binary=compiled/source.relative_to(project/"src/main/java").with_suffix(".class")
                if not binary.is_file() or binary.stat().st_mtime+1<source.stat().st_mtime:raise ValueError("Missing/stale compiled source; recompile: "+str(source))
                track(source)
        snapshot=output/(service+"-classes");shutil.copytree(compiled,snapshot)
        for path in snapshot.rglob("*.class"):track(path)
        launcher=project/("scripts/aam-scheduled/run_scheduled_aam.ps1" if service=="scheduled" else "scripts/aam/run_aam_v5.ps1");track(launcher)
        assumptions=dict(service=service,effectiveServiceParameters=values,serviceHours="07:00-19:00" if service=="scheduled" else "07:00-19:00",
            passengerFare=f"${values['baseFare']} per boarding + $2 per air mile",supply="Original fixed-timetable one-aircraft-per-departure" if service=="scheduled" else "Existing generated DRT fleet; see fingerprinted runner source",
            aircraftReuse="Not enabled; separate offline evaluation",objective="Fixed passenger cohort, including ground choices",scoringConfigurationHash=track(frozen_config))
        m=dict(service=service,projectRoot=str(project),population=str(population),populationHash=track(population),
            eligibleIds=ids,eligibleIdsHash=json_hash(ids),cohortFile=str(cohort_file),baseConfig=str(frozen_config),scoringHash=track(frozen_config),
            candidateCsv=str(candidate_file),candidates=sorted(candidates),initialLayout=list(initial),initialSitesSource=str(initial_file),
            supplyFareAssumptions=assumptions,supplyFareHash=json_hash(assumptions),compiledClassesDirectory=str(snapshot),
            serviceStart=values['serviceStartTime'],serviceEnd=values['serviceEndTime'],headway=1800,baseFare=values['baseFare'],farePerMile=2,
            maxAccessDistanceMiles=values.get('maxAccessDistanceMiles',5),maxEgressDistanceMiles=values.get('maxEgressDistanceMiles',5),allowPreServiceRequests=True,
            maximumRoutedCandidates=values.get('maximumRoutedCandidates',2),protectedAlternatives=values.get('protectedAlternatives',1),
            candidateVertiports=values['candidateVertiports'],minimumTripDistanceMiles=values.get('minimumTripDistanceMiles',3),
            maximumCandidateVertiportPairs=values.get('maximumCandidateVertiportPairs',3),
            preserveLearning=True,finalIterations=30,maximumConvergenceIterations=100,
            maximumWalkMeters=1000,maximumWalkSeconds=1200,maximumWaitSeconds=1800 if service=="scheduled" else 900,
            feederModes=["car","ride","ride_taxi","walk","bike"],seeds=[817,818,819,820,821],evaluationIterations=iterations,maximumStages=stages,
            minimumPredictedImprovement=.01,minimumObservedImprovement=.01,solverSeconds=60,simulationTolerance=tolerance,stableStages=2,
            criticalValue=2.776,swaps=1,maximumProbeLayouts=probes,allowLargePopulation=True,objective="eligible_population_with_ground",searchMethod="global",
            estimatorCommand=[sys.executable,"-B","-m","scripts.aam_repair.empirical_estimator"],evaluatorCommand=[sys.executable,"-B","-m","scripts.aam_repair.matsim_adapter"],
            launcherCommand=[str(ps),"-NoProfile","-ExecutionPolicy","Bypass","-File",str(launcher),"-Memory",memory],
            note="Real 0.1% regional inputs; repaired manifest stage workflow. Suite selects one of four neighborhoods without changing service/scoring assumptions. Prepared only; no MATSim launched. Behavioral and convergence values are explicit proposed settings, not calibrated findings.")
        path=output/(service+"-production-manifest.json");dump(path,m);track(path)
    dump(output/"package-index.json",dict(fingerprints=fingerprints,services=list(services),matSimStarted=False))
    report=validate(output);report.update(services=list(services),probeLayoutsPerStage=probes,fullNeighborhoodLayouts=901,
        evaluationIterationsPerTrial=iterations,maximumStages=stages,
        warning=report["warning"]+" Full coverage means 901 estimator simulations + 5 or 10 validation simulations per stage per service; enormous compute. A cap prevents complete-coverage convergence claims.")
    dump(output/"validation-report.json",report)
    with (output/"README.txt").open("x",encoding="utf-8") as f:
        f.write(json.dumps(report,indent=2)+"\n\nNo model has been started. Use the validate subcommand again before launching.\n"
                "Cohort includes all passenger residents independent of layout; ground-only people remain in the objective.\n"
                "Proposals: walking 1000m AND 1200s per end, scheduled wait 1800s, DRT wait 900s, paired minimum gain .01 utility, aggregate stability tolerance "+str(tolerance)+" utility over last 3 iterations, 2 stable stages.\n"
                f"This package records {iterations} iterations/trial and {stages} stages; these are budgets, NOT convergence guarantees.\n"
                "DRT exploration uses zero base fare, $2/mile, 30-mile catchments, 07:00-19:00 service, one protected alternative and initial AAM trials. Frozen previous runs are unchanged.\n"
                "For DRT Global's 8x5 + 10 protocol, use scripts/aam_repair/run_drt_global.ps1 -PackageDirectory THIS_DIRECTORY -Run.\n"
                "For all four DRT neighborhoods with that same protocol, use scripts/aam_repair/run_drt_optimizers.ps1 -PackageDirectory THIS_DIRECTORY -Run.\n"
                "Prepared services: "+", ".join(services)+". No experiment has been launched.\n")
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="action",required=True)
    c=sub.add_parser("create");c.add_argument("--project",type=Path,default=Path.cwd());c.add_argument("--output",type=Path,required=True)
    c.add_argument("--iterations",type=int,default=50);c.add_argument("--stages",type=int,default=20);c.add_argument("--maximum-probe-layouts",type=int,default=901);c.add_argument("--memory",default="18g");c.add_argument("--simulation-tolerance",type=float,default=1.)
    c.add_argument("--services",nargs="+",choices=("scheduled","drt"),default=["scheduled","drt"])
    v=sub.add_parser("validate");v.add_argument("directory",type=Path)
    a=p.parse_args();result=validate(a.directory) if a.action=="validate" else create(a.project,a.output,a.iterations,a.stages,a.maximum_probe_layouts,a.memory,a.simulation_tolerance,a.services)
    print(json.dumps(result,indent=2))
