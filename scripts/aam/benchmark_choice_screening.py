"""Read-only benchmark of distance recomputation versus layout matrix lookups.

This does not launch MATSim or estimate production network routing speed.
"""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from scripts.aam.score_optimizer.common import read_sites, distance_matrix
from scripts.aam.score_optimizer.screening import TripScreen


def benchmark(population, candidates_path, layouts_root):
    candidates = read_sites(candidates_path)
    index = {site['id']: i for i, site in enumerate(candidates)}
    paths = sorted(layouts_root.glob('*-inputs/frozen-vertiports.csv'))
    layouts = [[index[s['id']] for s in read_sites(path)] for path in paths]
    screen = TripScreen(population, candidates)
    coords = np.asarray([(s['x'], s['y']) for s in candidates])
    started = time.perf_counter()
    direct_results=[]
    for active in layouts:
        ad=distance_matrix(screen.origins,coords[active])
        ed=distance_matrix(screen.destinations,coords[active])
        direct_results.append((ad,ed))
    direct_seconds=time.perf_counter()-started
    started=time.perf_counter()
    lookup_results=[(screen.origin_distance[:,active], screen.destination_distance[:,active]) for active in layouts]
    lookup_seconds=time.perf_counter()-started
    for (ad,ed),(cached_ad,cached_ed) in zip(direct_results,lookup_results):
        np.testing.assert_allclose(ad,cached_ad,rtol=0,atol=0)
        np.testing.assert_allclose(ed,cached_ed,rtol=0,atol=0)
    metrics=[screen.evaluate(active) for active in layouts]
    started=time.perf_counter()
    for active in layouts:screen.evaluate(active)
    reuse_seconds=time.perf_counter()-started
    return dict(population=str(population),passengers=len(screen.people),dailyTrips=len(screen.trips),
                layouts=len(layouts),candidateSites=len(candidates),xmlReadAndMatrixPrecomputeSeconds=screen.precompute_seconds,
                directDistanceRecomputationSeconds=direct_seconds,matrixLookupSeconds=lookup_seconds,
                unchangedLayoutReuseSeconds=reuse_seconds,distancesExactlyEquivalent=True,screening=metrics,
                limitation='Distance screening microbenchmark only; includes no production network routing. Precomputation includes XML reading and all 100 sites.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--population',type=Path,required=True)
    parser.add_argument('--candidates',type=Path,required=True)
    parser.add_argument('--layouts-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=benchmark(args.population,args.candidates,args.layouts_root)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='screening'},indent=2))
