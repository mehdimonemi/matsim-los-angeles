"""Observable fixed-layout convergence; missing data never implies stability."""
import csv
import math
from pathlib import Path

def assess(directory: Path, window=5, score_tolerance=0.1, ride_tolerance=1):
    scores=list(directory.glob('*.scorestats.txt'))
    rides=list(directory.glob('*.drt_customer_stats_aam_drt.csv'))
    if len(scores)!=1 or len(rides)!=1:
        return dict(stable=False,reason='missing iteration statistics')
    with scores[0].open() as f:s=list(csv.DictReader(f,delimiter='\t'))
    with rides[0].open() as f:r=list(csv.DictReader(f,delimiter=';'))
    if len(s)<2*window or len(r)<2*window:
        return dict(stable=False,reason='need two complete windows')
    score=[float(x['avg. EXECUTED']) for x in s[-2*window:]]
    demand=[float(x['rides']) for x in r[-2*window:]]
    if not all(math.isfinite(x) for x in score+demand):
        return dict(stable=False,reason='nonfinite statistics')
    mean=lambda xs:sum(xs)/len(xs)
    ds=abs(mean(score[:window])-mean(score[window:]))
    dr=abs(mean(demand[:window])-mean(demand[window:]))
    return dict(stable=ds<=score_tolerance and dr<=ride_tolerance,
                window=window,meanExecutedScoreChange=ds,meanCompletedRidesChange=dr,
                meanCompletedRides=mean(demand[window:]),
                scoreTolerance=score_tolerance,rideTolerance=ride_tolerance,
                scope='two-window executed-score and completed-air-leg stability; not proof of global equilibrium')
