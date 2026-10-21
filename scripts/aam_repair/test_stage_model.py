import unittest
import tempfile
from pathlib import Path
import json
from .stage_model import Alternative as A, solve, paired_acceptance
from .checkpoints import archive_population
from .reporting import reuse_report, allocate_departures, funnel
from .stages import run, freeze_runtime


class StageModelTests(unittest.TestCase):
    def test_experiment_runtime_snapshot_is_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);compiled=root/"target/aam-v5-classes/org/matsim/run/aam";compiled.mkdir(parents=True)
            original=compiled/"AamFeederPolicy.class";original.write_bytes(b"original")
            output=root/"experiment";output.mkdir()
            m=freeze_runtime(dict(projectRoot=str(root),service="drt"),output)
            original.write_bytes(b"recompiled")
            frozen=Path(m["compiledClassesDirectory"])/"org/matsim/run/aam/AamFeederPolicy.class"
            self.assertEqual(frozen.read_bytes(),b"original")
    def test_failed_proposal_feedback_selects_adverse_seed_without_copying_scores(self):
        from .empirical_estimator import feedback_seed
        self.assertEqual(feedback_seed([],817),817)
        self.assertEqual(feedback_seed([dict(proposalRejected=True,pairedDifferences=[2,-8,1],
                                            runs=[dict(seed=817),dict(seed=818),dict(seed=819)])],817),818)
    def test_legacy_objective_cannot_harm_population(self):
        rows=[A("old",frozenset(),0),A("old",frozenset("AB"),10),A("old",frozenset("AC"),11),
              A("new",frozenset(),0),A("new",frozenset("AB"),100)]
        result=solve(rows,"ABC","AB",legacy_current_users={"old"})
        self.assertFalse(result["proposeChange"])
        self.assertEqual(result["baselinePopulationObjective"],110)

    def test_stage_rejection_keeps_layout_and_updates_estimates(self):
        metadata=dict(populationHash="p",scoringHash="s",supplyFareHash="f",eligibleIdsHash="e")
        m={**metadata,"eligibleIds":["p"],"initialLayout":["A","B"],"candidates":["A","B","C"],
           "population":"initial","seeds":list(range(5)),"maximumStages":2,"estimatorCommand":[],"evaluatorCommand":[],
           "minimumPredictedImprovement":0,"minimumObservedImprovement":0,"simulationTolerance":0,
           "feederModes":["ride"],"baseFare":30,"farePerMile":2,"maximumWalkMeters":1000,
           "maximumWalkSeconds":1200,"maximumWaitSeconds":1800}
        requests=[]
        def estimate(command,request,directory,name):
            requests.append(request)
            air=dict(person="p",planId="air",sites=["A","C"],score=10,scoreKind="observedPlanMean",
                feederModes=["ride"],accessWalkMeters=0,egressWalkMeters=0,accessWalkSeconds=0,egressWalkSeconds=0,
                serviceFeasible=True,continuityFeasible=True,expectedWaitSeconds=0,rejectionProbability=0,
                successScore=10,rejectionScore=-10,fare=32,flightMeters=1609.344,capacityEvidence="events",routeEvidence="plan")
            return {**metadata,"stage":request["stage"],"eligibleIds":["p"],"coefficientCoverageComplete":True,
                    "alternatives":[dict(person="p",planId="ground",sites=[],score=0),air]}
        def evaluate(command,request,directory,name):
            old=request["layout"]==["A","B"]
            return {**metadata,"seed":request["seed"],"engine":"MATSim","scores":{"p":0 if old else -1},
                    "checkpoint":"accepted-checkpoint" if old else "rejected-checkpoint","layoutId":"AB" if old else "AC",
                    "allCompetingPlansRescored":True,"populationObjectiveByIteration":[0,0,0]}
        with tempfile.TemporaryDirectory() as d:
            result=run(m,Path(d)/"new",evaluate,estimate)
        self.assertEqual(result["acceptedLayout"],["A","B"])
        self.assertFalse(result["history"][0]["validation"]["accepted"])
        self.assertEqual(requests[1]["checkpoint"],"accepted-checkpoint")
        self.assertEqual(requests[1]["checkpointLayoutId"],"AB")
        self.assertTrue(any(o["layout"]==["A","C"] for o in requests[1]["observations"]))
        self.assertEqual(result["status"],"safety_budget_reached_NOT_converged")
        def improving_evaluate(command,request,directory,name):
            value=evaluate(command,request,directory,name)
            value["scores"]={"p":0 if request["layout"]==["A","B"] else 1}
            return value
        with tempfile.TemporaryDirectory() as d:
            accepted=run({**m,"maximumStages":1},Path(d)/"new",improving_evaluate,estimate)
        self.assertEqual(accepted["acceptedLayout"],["A","C"])
        self.assertTrue(accepted["history"][0]["validation"]["accepted"])
        def no_change_estimate(command,request,directory,name):
            value=estimate(command,request,directory,name)
            value["alternatives"]=value["alternatives"][:1]
            return value
        with tempfile.TemporaryDirectory() as d:
            converged=run({**m,"maximumStages":7},Path(d)/"new",evaluate,no_change_estimate)
        self.assertEqual(converged["status"],"stage_model_and_simulation_converged")
        self.assertEqual(len(converged["history"]),2)
        self.assertFalse(converged["globalOptimalityClaim"])
        def incomplete_estimate(command,request,directory,name):
            value=no_change_estimate(command,request,directory,name)
            value["coefficientCoverageComplete"]=False
            return value
        with tempfile.TemporaryDirectory() as d:
            incomplete=run(m,Path(d)/"new",evaluate,incomplete_estimate)
        self.assertEqual(incomplete["status"],"safety_budget_reached_NOT_converged")

    def test_separate_reuse_and_frequency(self):
        flights=[dict(id="1",origin="A",destination="B",departure=0,arrival=100),
                 dict(id="2",origin="B",destination="A",departure=200,arrival=300),
                 dict(id="3",origin="A",destination="B",departure=400,arrival=500)]
        r=reuse_report(flights,60,100,10)
        self.assertEqual(r["reuseAircraftLowerBound"],1)
        self.assertEqual(r["betweenFlightIdleSeconds"],80)
        self.assertEqual(sum(allocate_departures({"AB":8,"BA":2},10).values()),10)
        self.assertEqual(allocate_departures({"AB":8,"BA":2},10),{"AB":8,"BA":2})

    def test_door_to_door_not_just_air_arrival(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.xml";e=Path(d)/"e.xml"
            p.write_text('<population><person id="p"><plan selected="yes"><leg mode="aam_drt"/></plan></person></population>')
            e.write_text('<events><event time="1" type="DrtRequest submitted" mode="aam_drt" person="p" request="1"/><event time="2" type="passenger picked up" mode="aam_drt" person="p" request="1" vehicle="aam_drt_1"/><event time="3" type="passenger dropped off" mode="aam_drt" person="p" request="1"/></events>')
            counts,_=funnel(e,p)
            self.assertEqual(counts["completedAirLegs"],1)
            self.assertEqual(counts["completedJourneys"],0)
            self.assertEqual(counts["unfinishedJourneys"],1)
    def test_new_users_and_ground_outside_option(self):
        rows=[A("old",frozenset(),10),A("new",frozenset(),10),
              A("old",frozenset("AB"),12),A("new",frozenset("AC"),20),
              A("old",frozenset("AC"),-50)]
        r=solve(rows,"ABC","AB")
        self.assertEqual(r["proposal"],["A","C"])
        self.assertEqual(r["baselineObjective"],22)
        self.assertEqual(r["incumbentObjective"],30)
        self.assertEqual(r["relativeGap"],0)
        legacy=solve(rows,"ABC","AB",legacy_current_users={"old"})
        self.assertFalse(legacy["proposeChange"])

    def test_infeasible_walking_never_rewarded(self):
        rows=[A("10096817",frozenset(),0),A("10096817",frozenset("AC"),1000,False)]
        self.assertFalse(solve(rows,"ABC","AB")["proposeChange"])

    def test_minimum_improvement_does_not_make_incumbent_infeasible(self):
        rows=[A("p",frozenset(),1),A("p",frozenset("AC"),2)]
        r=solve(rows,"ABC","AB",minimum_improvement=5)
        self.assertFalse(r["proposeChange"])
        self.assertEqual(r["proposal"],["A","B"])
        self.assertEqual(r["incumbentObjective"],2)

    def test_paired_variability_and_missing_person(self):
        old=[dict(seed=i,populationHash="p",scoringHash="s",supplyFareHash="f",eligibleIdsHash="e",scores={"p":1}) for i in range(5)]
        new=[{**r,"scores":{"p":2}} for r in old]
        self.assertTrue(paired_acceptance(old,new)["accepted"])
        new[-1]["scores"]={"p":-10}
        self.assertFalse(paired_acceptance(old,new)["accepted"])
        new[-1]["scores"]={}
        with self.assertRaises(ValueError):paired_acceptance(old,new)
        new=[{**r,"scores":{"p":2},"classSnapshotHash":"different-build"} for r in old]
        with self.assertRaises(ValueError):paired_acceptance(old,new)

    def test_saved_plan_score_layout_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"p.xml";o=Path(d)/"archive.jsonl"
            p.write_text('<population><person id="10092375"><plan score="12" selected="yes"><leg mode="ride"/></plan><plan score="11"><leg mode="aam"/></plan></person></population>')
            self.assertEqual(archive_population(p,o,"AB"),2)
            rows=[json.loads(x) for x in o.read_text().splitlines()]
            self.assertEqual(rows[0]["observedScore"],12)
            self.assertEqual(rows[1]["layoutId"],"AB")
            with self.assertRaises(FileExistsError):archive_population(p,o,"AB")


if __name__=="__main__":unittest.main()
