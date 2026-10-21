#!/usr/bin/env python3
"""Fast regression checks for the four swap neighborhoods."""
from __future__ import annotations

import unittest
import tempfile
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from .optimizer import optimize_one_swap, read_wait_priors, ScoreObjective, UserData
from .experiment import (FINAL_ITERATIONS, ITERATIONS_PER_STAGE,
                         ROUTED_CANDIDATE_VERTIPORTS, SEARCH_STAGES, run_stage)


class FakeUsers:
    ids = ["person-1"]
    origins = np.zeros((1, 2))
    current_aam_plan_users = -1
    potential_new_aam_users = 0
    population_count = 1


class FakeObjective:
    def __init__(self):
        self.users = FakeUsers()
        self.routing_candidate_vertiports = 3
        self.candidates = [{"id": f"C{i:03d}"} for i in range(100)]
        points = np.arange(100, dtype=float)[:, None]
        self.site_distance = np.abs(points - points.T)

    def evaluate(self, active):
        return {"feasible": True, "objective": float(sum(active))}


class NeighborhoodTests(unittest.TestCase):
    def test_candidate_cannot_hide_losses_below_observed_population_score(self):
        class BelowObserved(FakeObjective):
            def evaluate(self,active):
                return dict(feasible=True,objective=float(sum(active)),currentPopulationScoreSum=10000)
        _,report=optimize_one_swap(BelowObserved(),list(range(10)),"global")
        self.assertFalse(report["accepted"])
        self.assertEqual(report["aggregateProtectionFloor"],10000)

    def test_best_ground_or_air_score_counts_losses_and_ground_only_gain(self):
        users=UserData(ids=["ground","air"],origins=np.zeros((2,2)),destinations=np.ones((2,2)),
            scores=np.asarray([10.,20.]),money_utility=np.ones(2),trip_person_index=np.asarray([0,1]),
            current_origin_site=np.asarray([-1,0]),current_destination_site=np.asarray([-1,1]),
            ground_scores=np.asarray([10.,8.]),departure_seconds=np.zeros(2),selected_scores=np.asarray([10.,20.]),
            population_score_sum=30,population_count=2,has_aam_plan_by_person=np.asarray([False,True]))
        obj=ScoreObjective.__new__(ScoreObjective);obj.users=users;obj.anchor_cost=np.asarray([10.,10.])
        obj.minimum_cost=lambda active:(np.asarray([5.,15.]),np.asarray([[0,1],[0,1]]))
        result=obj.evaluate([0,1])
        self.assertEqual(result["objective"],30) # 15 ground-user gain, 15 degraded AAM score.
        self.assertEqual(result["positiveScoreChangeSum"],5)
        self.assertEqual(result["negativeScoreChangeSum"],-5)
        obj.minimum_cost=lambda active:(np.asarray([float("inf"),float("inf")]),np.full((2,2),-1))
        result=obj.evaluate([0,1])
        self.assertEqual(result["objective"],18) # Ground 10 and fallback ground 8.
        self.assertEqual(result["negativeScoreChangeSum"],-12)
        users.ground_scores[1]=float("nan")
        with self.assertRaisesRegex(ValueError,"scored ground alternative"):obj.evaluate([0,1])

    def test_finite_anchor_even_when_approximate_service_screen_rejects_old_pair(self):
        users=UserData(ids=["p"],origins=np.asarray([[0.,0.]]),destinations=np.asarray([[20000.,0.]]),
            scores=np.asarray([20.]),money_utility=np.ones(1),trip_person_index=np.asarray([0]),
            current_origin_site=np.asarray([0]),current_destination_site=np.asarray([1]),
            ground_scores=np.asarray([8.]),departure_seconds=np.asarray([70000.]),selected_scores=np.asarray([20.]))
        sites=[dict(id="A",x=0,y=0),dict(id="B",x=20000,y=0)]
        obj=ScoreObjective(users,sites,[0,1],30,2,120)
        self.assertTrue(np.isfinite(obj.anchor_cost[0]))
        result=obj.evaluate([0,1])
        self.assertEqual(result["objective"],8)
        import json
        json.dumps({k:v for k,v in result.items() if k!="pair"},allow_nan=False)

    def test_global_evaluates_all_900_one_swaps(self):
        _, report = optimize_one_swap(FakeObjective(), list(range(10)), "global")
        self.assertEqual(900, report["movesEvaluated"])
        self.assertTrue(report["accepted"])

    def test_all_vp_k10_evaluates_100_moves(self):
        _, report = optimize_one_swap(FakeObjective(), list(range(10)), "all-vp-k10")
        self.assertEqual(100, report["movesEvaluated"])

    def test_one_vp_k10_evaluates_10_moves(self):
        _, report = optimize_one_swap(FakeObjective(), list(range(10)), "one-vp-k10")
        self.assertEqual(10, report["movesEvaluated"])
        self.assertEqual("C000", report["removed"])

    def test_adaptive_stops_after_improving_k5(self):
        _, report = optimize_one_swap(FakeObjective(), list(range(10)), "adaptive")
        self.assertEqual(50, report["movesEvaluated"])
        self.assertEqual(["k5"], [level["level"] for level in report["levels"]])

    def test_no_site_separation_constraint(self):
        _, report = optimize_one_swap(FakeObjective(), list(range(10)), "global")
        self.assertFalse(report["siteSeparationConstraint"])

    def test_observed_wait_and_new_vertiport_fallback(self):
        candidates = [{"id": "A"}, {"id": "B"}, {"id": "NEW"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "waits.csv"
            path.write_text("from,to,time_bin,count,mean_wait_s\n"
                            "aam_loop_A,aam_loop_B,0,2,300\n", encoding="utf-8")
            waits, observed = read_wait_priors(path, candidates, np.asarray([0.0]), 120.0)
        self.assertEqual(1, observed)
        self.assertEqual(300.0, waits[0, 0, 1])
        self.assertEqual(120.0, waits[0, 0, 2])

    def test_default_experiment_is_exactly_50_iterations(self):
        self.assertEqual(50, SEARCH_STAGES * ITERATIONS_PER_STAGE + FINAL_ITERATIONS)
        self.assertEqual(10, FINAL_ITERATIONS)

    def test_stage_command_applies_fare_and_three_routing_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, plans, layout = root / "output", root / "plans.xml.gz", root / "layout.csv"
            plans.touch(); layout.touch()
            args = SimpleNamespace(
                powershell="powershell.exe", launcher=root / "launcher.ps1", memory="18g",
                config=root / "config.xml", base_fare=30.0, fare_per_mile=2.0,
                service_start_time=25200.0, service_end_time=68400.0,
                candidate_vertiports=ROUTED_CANDIDATE_VERTIPORTS, project_root=root)

            def fake_run(command, cwd, check, stdout, stderr):
                self.assertIsNotNone(stdout)
                self.assertEqual(subprocess.STDOUT, stderr)
                output.mkdir()
                (output / "la-aam-fare30-scoreopt.output_plans.xml.gz").touch()
                input_dir = Path(str(output) + "-inputs"); input_dir.mkdir()
                (input_dir / "wait-priors.csv").touch()

            with patch("scripts.aam.score_optimizer.experiment.subprocess.run", side_effect=fake_run) as called:
                run_stage(args, output, plans, layout, None, 5, compile_sources=False, innovation=True)
            command = called.call_args.args[0]
            self.assertIn("30.0", command)
            self.assertIn("-CandidateVertiports", command)
            self.assertIn("3", command)
            self.assertEqual("25200.0", command[command.index("-ServiceStartTime") + 1])
            self.assertEqual("68400.0", command[command.index("-ServiceEndTime") + 1])
            self.assertIn("-LastIteration", command)
            self.assertEqual("4", command[command.index("-LastIteration") + 1])
            self.assertIn("-SkipCompile", command)
            self.assertTrue((root / "output.console.log").is_file())


if __name__ == "__main__":
    unittest.main()
