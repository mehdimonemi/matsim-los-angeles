"""Two-passenger integration check through the actual DRT Global stage adapter.

Two three-iteration stages and one global swap calculation, using the frozen
runtime. Synthetic inputs only; never starts the regional experiment.
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from scripts.aam.score_optimizer.common import atomic_write_layout, read_sites
from scripts.aam.score_optimizer.experiment import run_stage
from scripts.aam.score_optimizer.optimizer import optimize_population, observed_ground_scores
from scripts.aam.score_optimizer.population import sanitize_population, population_score_metrics
from .matsim_adapter import set_param
from .make_small_cases import write_xml
from .production_manifests import validate
from .reporting import funnel


def run(package, output):
    validate(package)
    m=json.loads((package/'drt-production-manifest.json').read_text())
    project=Path(m['projectRoot']);fixture=project/'validation/choice-small-positive'
    output.mkdir(parents=True,exist_ok=False)
    ports=read_sites(fixture/'ports.csv')
    # Ten active sites, 90 inactive; the same 900-swap neighborhood as production.
    candidates=[]
    for i in range(100):
        base=ports[i%2];offset=(i//2)*25
        candidates.append(dict(id=f'TEST{i:03d}',name=f'Test {i}',x=base['x']+offset,y=base['y']))
    candidate_file=output/'candidates.csv';layout=output/'layout-00.csv'
    atomic_write_layout(candidate_file,candidates);layout_id=atomic_write_layout(layout,candidates[:10])
    config=ET.parse(fixture/'drt.config.xml').getroot()
    set_param(config,'aam','activeVertiportCount',10)
    config_file=output/'small.config.xml';write_xml(config_file,config,'config_v2.dtd')
    population=ET.parse(fixture/'population.xml').getroot()
    # Exercise the regional startup failure mode without altering real inputs.
    next(population.iter('leg')).set('mode','ride_school_bus')
    population_file=output/'people.xml';write_xml(population_file,population,'population_v6.dtd')
    args=SimpleNamespace(project_root=project,powershell=m['launcherCommand'][0],
        launcher=Path(m['launcherCommand'][5]),config=config_file,memory='2g',
        base_fare=m['baseFare'],fare_per_mile=m['farePerMile'],
        service_start_time=m['serviceStart'],service_end_time=m['serviceEnd'],
        candidate_vertiports=3,classes_directory=Path(m['compiledClassesDirectory']))
    checkpoint=output/'stage-01-input.xml.gz';sanitize_population(population_file,checkpoint,layout_id)
    plans,waits,seconds=run_stage(args,output/'stage-01',checkpoint,layout,None,3,False,True)
    prediction=optimize_population(plans,candidate_file,layout,output/'layout-01.csv','global',
        base_fare=m['baseFare'],fare_per_mile=m['farePerMile'],wait_priors=waits,
        service_start_time=m['serviceStart'],service_end_time=m['serviceEnd'],
        maximum_wait_seconds=m['maximumWaitSeconds'],maximum_walk_distance=m['maximumWalkMeters'],
        maximum_walk_time=m['maximumWalkSeconds'],minimum_improvement=m['minimumPredictedImprovement'],
        ground_score_history=observed_ground_scores(plans),max_access_distance_miles=m['maxAccessDistanceMiles'],
        max_egress_distance_miles=m['maxEgressDistanceMiles'],allow_pre_service_requests=m['allowPreServiceRequests'])
    assert prediction['inputLayoutScreening']['passengerAgentsEvaluated']==2
    checkpoint=output/'stage-02-input.xml.gz'
    sanitize_population(plans,checkpoint,prediction['sha256'])
    plans2,waits2,seconds2=run_stage(args,output/'stage-02',checkpoint,output/'layout-01.csv',waits,3,False,True)
    journeys=[]
    for stage in ('stage-01','stage-02'):
        directory=output/stage
        metrics,_=funnel(next(directory.glob('*.output_events.xml.gz')),
                        next(directory.glob('*.output_experienced_plans.xml.gz')),service='drt')
        journeys.append(metrics)
        assert metrics['passengerAgentsEvaluated']==2
        assert metrics['markerOnlyPlans']==0
    report=dict(status='PASS_SMALL_DRT_GLOBAL_INTEGRATION',regionalModelStarted=False,
        stages=2,iterationsPerStage=3,passengers=2,globalPrediction=prediction,
        retainedPlanMetrics=population_score_metrics(plans2),journeyMetrics=journeys,
        stageSeconds=[seconds,seconds2],runtime=str(args.classes_directory))
    (output/'validation.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=run(args.package.resolve(),args.output.resolve())
    print(result['status'])
