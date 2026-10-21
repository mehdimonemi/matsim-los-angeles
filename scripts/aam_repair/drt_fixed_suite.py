"""Four independent DRT optimizer runs with the fixed 8x5 + 10 protocol.

Shares the corrected Global model/objective; only the swap neighborhood differs.
No candidate MATSim probes, paired validation branches or scheduled service.
"""
import argparse
import csv
import json
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from scripts.aam.score_optimizer.experiment import run_stage
from .fast_global import run
from .neighborhoods import METHODS
from .production_manifests import fingerprint, validate
from .matsim_adapter import set_param
from .reporting import xml_rows
from .stages import dump


def write_comparison(output,rows):
    (output/'comparison.json').write_text(json.dumps(rows,indent=2,allow_nan=False),encoding='utf-8')
    if rows:
        with (output/'comparison.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)


def prepare_route_complete_population(manifest,output):
    """Run one ground-only bootstrap and share its routed plans across methods."""
    project=Path(manifest['projectRoot'])
    config=ET.parse(manifest['baseConfig']).getroot()
    set_param(config,'aam','seedAlternativesAtStartup','false')
    set_param(config,'aam','initialExplorationFraction',0)
    config_path=output/'route-preparation.config.xml'
    config_path.write_text('<?xml version="1.0"?><!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'+
                           ET.tostring(config,encoding='unicode'),encoding='utf-8')
    layout=output/'route-preparation-layout.csv'
    shutil.copyfile(manifest['initialSitesSource'],layout)
    args=SimpleNamespace(project_root=project,powershell=manifest['launcherCommand'][0],
        launcher=Path(manifest['launcherCommand'][5]),config=config_path,memory=manifest['launcherCommand'][-1],
        base_fare=manifest['baseFare'],fare_per_mile=manifest['farePerMile'],
        service_start_time=manifest['serviceStart'],service_end_time=manifest['serviceEnd'],
        candidate_vertiports=manifest.get('candidateVertiports',3),
        classes_directory=Path(manifest['compiledClassesDirectory']))
    routed,_,elapsed=run_stage(args,output/'route-preparation',Path(manifest['population']),layout,None,1,False,False)
    missing=0;total=0
    for person in xml_rows(routed,'person'):
        for leg in person.findall('./plan/leg'):
            total+=1
            if leg.find('route') is None:missing+=1
    if missing:
        raise ValueError(f'Route preparation left {missing} of {total} plan legs without routes')
    record=dict(population=str(routed.resolve()),populationHash=fingerprint(routed),
        basePopulationHash=manifest['populationHash'],groundOnlyBootstrapIterations=1,
        routingWallSeconds=elapsed,planLegs=total,unroutedPlanLegs=missing,
        startupDiagnostics=str((output/'route-preparation'/'aam-choice-set'/'layout'/'ground-routing.csv').resolve()))
    dump(output/'route-preparation.json',record)
    return record


def compare(package,output,methods=METHODS,runner=run,resume=False):
    methods=tuple(methods)
    if not methods or len(set(methods))!=len(methods) or not set(methods)<=set(METHODS):
        raise ValueError('Provide distinct supported DRT optimizer methods')
    validate(package)
    manifest=json.loads((package/'drt-production-manifest.json').read_text())
    if manifest['service']!='drt':raise ValueError('DRT package required')
    if resume:
        if not output.is_dir() or not (output/'suite.json').is_file():
            raise ValueError('Resume requires an existing suite output directory with suite.json')
        previous=json.loads((output/'suite.json').read_text(encoding='utf-8'))
        if previous.get('service')!='drt':raise ValueError('Resume package is not for a DRT suite')
        if previous.get('package')!=str(package.resolve()):
            comparable=('populationHash','scoringHash','supplyFareHash','initialLayout')
            if any(previous.get(key)!=manifest.get(key) for key in comparable):
                raise ValueError('Resume package inputs differ from the existing DRT suite')
    else:
        output.mkdir(parents=True,exist_ok=False)
    suite_record=dict(service='drt',package=str(package.resolve()),methods=list(methods),
        executionProtocol='eight learning stages plus measured fixed-layout convergence',
        minimumIterationsPerMethod=8*manifest.get('iterationsPerSearchStage',5)+manifest.get('finalIterations',10),
        maximumIterationsPerMethod=8*manifest.get('iterationsPerSearchStage',5)+manifest.get('maximumConvergenceIterations',manifest.get('finalIterations',10)),
        candidateProbeSimulations=0,
        populationHash=manifest['populationHash'],scoringHash=manifest['scoringHash'],
        supplyFareHash=manifest['supplyFareHash'],initialLayout=manifest['initialLayout'],
        compiledClassesDirectory=manifest['compiledClassesDirectory'],
        acceptance='Predicted improvement only; same corrected score objective across methods',
        execution='Sequential independent starts; no carry-over of plans, layouts or wait priors between methods',
        routePreparation='One shared ground-only bootstrap creates a route-complete initial population before all methods start')
    if resume:(output/'suite.json').write_text(json.dumps(suite_record,indent=2,allow_nan=False),encoding='utf-8')
    else:dump(output/'suite.json',suite_record)
    routed_manifest=dict(manifest)
    if resume and runner is run:
        route_record_path=output/'route-preparation.json'
        if not route_record_path.is_file():raise ValueError('Cannot resume: route-preparation.json is missing')
        prepared=json.loads(route_record_path.read_text(encoding='utf-8'))
        prepared_path=Path(prepared['population'])
        if not prepared_path.is_file() or fingerprint(prepared_path)!=prepared['populationHash']:
            raise ValueError('Cannot resume: shared route-prepared population is missing or changed')
        routed_manifest['routePreparedPopulation']=str(prepared_path)
        routed_manifest['routePreparedPopulationHash']=prepared['populationHash']
    elif runner is run:
        try:
            prepared=prepare_route_complete_population(manifest,output)
            routed_manifest['routePreparedPopulation']=prepared['population']
            routed_manifest['routePreparedPopulationHash']=prepared['populationHash']
        except Exception as error:
            dump(output/'failure.json',dict(phase='route-preparation',error=str(error),completedMethods=[]))
            raise
    rows=[]
    previous_rows=[]
    comparison_path=output/'comparison.json'
    if resume and comparison_path.is_file():previous_rows=json.loads(comparison_path.read_text(encoding='utf-8'))
    rows=list(previous_rows)
    for method in methods:
        if any(row.get('method')==method and row.get('status') for row in rows):
            print(f'Skipping completed DRT optimizer: {method}',flush=True)
            continue
        started=time.perf_counter()
        print(f'Starting DRT optimizer: {method}',flush=True)
        try:
            # Every method starts from the same immutable manifest/population.
            method_output=output/method
            if runner is run:
                result=runner(dict(routed_manifest),method_output,method=method,
                              resume=resume and method_output.is_dir())
            else:
                result=runner(dict(routed_manifest),method_output,method=method)
        except Exception as error:
            dump(output/'failure.json',dict(method=method,error=str(error),completedMethods=[r['method'] for r in rows]))
            raise
        history=result['history'];final=history[-1]
        retained=final.get('retainedPlanMetrics',{});journey=final.get('journeyMetrics',{})
        rows.append(dict(method=method,status=result['status'],totalMatsimIterations=result['totalMatsimIterations'],
            acceptedSwaps=sum(r.get('optimization',{}).get('accepted',False) for r in history),
            selectedAamUsers=journey.get('selectedAamUsers'),
            finalRequestsSubmitted=journey.get('attemptedRequests'),
            finalCompletedAamUsers=journey.get('completedAamUsers'),finalRejectedRequests=journey.get('rejectedRequests'),
            scoredAamAlternativeUsers=retained.get('scoredAamAlternativeUsers'),
            selectedPlanScoreSum=retained.get('selectedPlanScoreSum'),bestPlanScoreSum=retained.get('bestPlanScoreSum'),
            matsimSeconds=sum(r['matsimSeconds'] for r in history),
            optimizerSeconds=sum(r.get('optimization',{}).get('optimizerSeconds',0) for r in history),
            wallSeconds=time.perf_counter()-started,finalLayout=result['finalLayout'],finalPlans=result['finalPlans']))
        write_comparison(output,rows)
    if (output/'failure.json').exists():(output/'failure.json').unlink()
    dump(output/'result.json',dict(status='completed',service='drt',methods=[r['method'] for r in rows],
        totalMatsimIterations=sum(r['totalMatsimIterations'] for r in rows),comparison=rows))
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--methods',nargs='+',choices=METHODS,default=list(METHODS))
    parser.add_argument('--resume',action='store_true',help='Continue a prior suite, preserving completed methods and stages')
    args=parser.parse_args();compare(args.package.resolve(),args.output.resolve(),args.methods,resume=args.resume)
