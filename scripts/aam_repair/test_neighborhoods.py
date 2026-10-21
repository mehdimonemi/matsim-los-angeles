import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from .stage_model import Alternative as A, solve
from .neighborhoods import optimize, METHODS
from .suite import compare
from .stages import run


class NeighborhoodTests(unittest.TestCase):
    def test_all_methods_use_paired_acceptance_and_failed_proposal_feedback(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);sites=root/"sites.csv";sites.write_text("id,x,y\nA,0,0\nB,1,0\nC,2,0\n")
            metadata=dict(populationHash="p",scoringHash="s",supplyFareHash="f",eligibleIdsHash="e")
            manifest={**metadata,"eligibleIds":["p"],"initialLayout":["A","B"],"candidates":["A","B","C"],
                "candidateCsv":str(sites),"population":"source","seeds":list(range(5)),"maximumStages":1,
                "minimumPredictedImprovement":.01,"minimumObservedImprovement":.01,"simulationTolerance":0,
                "estimatorCommand":[],"evaluatorCommand":[],"feederModes":["ride"],"baseFare":30,"farePerMile":2,
                "maximumWalkMeters":1000,"maximumWalkSeconds":1200,"maximumWaitSeconds":1800}
            def estimate(command,request,directory,name):
                return {**metadata,"stage":request["stage"],"eligibleIds":["p"],"coefficientCoverageComplete":True,
                    "alternatives":[dict(person="p",planId="ground",sites=[],score=0),
                        dict(person="p",planId="air",sites=["B","C"],score=10,scoreKind="observedPlanMean",
                        feederModes=["ride"],accessWalkMeters=0,egressWalkMeters=0,accessWalkSeconds=0,egressWalkSeconds=0,
                        serviceFeasible=True,continuityFeasible=True,expectedWaitSeconds=0,rejectionProbability=0,
                        successScore=10,rejectionScore=-10,fare=32,flightMeters=1609.344,capacityEvidence="events",routeEvidence="plan")]}
            for method in METHODS:
                for observed_gain in (-1,1):
                    calls=[]
                    def evaluate(command,request,directory,name):
                        calls.append(request)
                        self.assertTrue(request["preserveAlternatives"])
                        self.assertTrue(request["rerouteAndRescoreModifiedPlans"])
                        return {**metadata,"engine":"MATSim","seed":request["seed"],"scores":{"p":0 if request["layout"]==["A","B"] else observed_gain},
                            "checkpoint":"rescored","layoutId":"|".join(request["layout"]),
                            "allCompetingPlansRescored":True,"populationObjectiveByIteration":[0,0,0]}
                    out=root/(method+str(observed_gain))
                    result=run({**manifest,"searchMethod":method},out,evaluate,estimate)
                    self.assertEqual(len(calls),10)
                    self.assertEqual(result["history"][0]["validation"]["accepted"],observed_gain>0)
                    self.assertEqual(result["acceptedLayout"],["B","C"] if observed_gain>0 else ["A","B"])
                    feedback=json.loads((out/"stage-000/estimation-feedback.json").read_text())
                    self.assertEqual(feedback["observations"][-1]["proposalRejected"],observed_gain<0)

    def test_neighborhood_sizes_scope_and_adaptive_expansion(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"sites.csv"
            with path.open("w",newline="") as f:
                w=csv.writer(f);w.writerow(["id","x","y"])
                for i in range(100):w.writerow([f"C{i:03}",i,0])
            candidates=[f"C{i:03}" for i in range(100)];active=candidates[:10]
            m=dict(candidateCsv=str(path),candidates=candidates,swaps=1,minimumPredictedImprovement=.01,solverSeconds=10)
            rows=[A("p",frozenset(),0),A("p",frozenset(["C099"]),10)]
            expected={"global":901,"all-vp-k10":101,"one-vp-k10":11,"adaptive":901}
            for method in METHODS:
                r=optimize(rows,{**m,"searchMethod":method},active)
                self.assertEqual(r["layoutsEvaluated"],expected[method])
                self.assertEqual(r["relativeGap"],0)
                self.assertEqual(r["proposeChange"],method in ("global","adaptive"))
                if method=="one-vp-k10":self.assertEqual(r["weakSite"],"C000")
                if method=="adaptive":self.assertEqual([x["k"] for x in r["searchLevels"]],[5,10,20,90])
            near=[A("p",frozenset(),0),A("p",frozenset(["C010"]),10)]
            r=optimize(near,{**m,"searchMethod":"adaptive"},active)
            self.assertEqual(len(r["searchLevels"]),1)
            self.assertEqual(r["uniqueMovesSearched"],50)

    def test_restricted_solver_protects_population_and_ground_choice(self):
        rows=[A("p",frozenset(),0),A("p",frozenset("AB"),100),
              A("p",frozenset("AC"),1),A("new",frozenset(),0),A("new",frozenset("AC"),2)]
        r=solve(rows,"ABC","AB",allowed_layouts=["AC"])
        self.assertFalse(r["proposeChange"])
        self.assertEqual(r["proposal"],["A","B"])
        with self.assertRaises(ValueError):solve(rows,"ABC","AB",allowed_layouts=["C"])

    def test_eight_isolated_methods_use_unchanged_service_assumptions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);package=root/"package";package.mkdir()
            common=dict(eligibleIds=["p"],populationHash="p",eligibleIdsHash="e",initialLayout=["A","B"],candidates=["A","B","C"],
                        seeds=list(range(5)),baseFare=30,farePerMile=2,maximumWalkMeters=1000,maximumWalkSeconds=1200,
                        serviceStart=25200,serviceEnd=68400)
            for s in ("scheduled","drt"):
                (package/(s+"-production-manifest.json")).write_text(json.dumps({**common,"service":s,"maximumWaitSeconds":1800 if s=="scheduled" else 900}))
            calls=[]
            def runner(m,out,allow_large_population):
                calls.append((m,out));out.mkdir()
                self.assertEqual(m["baseFare"],30)
                self.assertEqual(m["maximumWaitSeconds"],1800 if m["service"]=="scheduled" else 900)
                return dict(status="stage_model_and_simulation_converged",history=[],acceptedLayout=m["initialLayout"])
            with patch("scripts.aam_repair.suite.validate") as verified:
                summary=compare(package,root/"output",runner=runner)
                verified.assert_called_once_with(package)
            self.assertEqual(len(summary),8)
            self.assertEqual(len({out for m,out in calls}),8)
            self.assertEqual([m["searchMethod"] for m,out in calls],list(METHODS)*2)
            with patch("scripts.aam_repair.suite.validate"):
                with self.assertRaises(FileExistsError):compare(package,root/"output",runner=runner)


if __name__=="__main__":unittest.main()
