#!/usr/bin/env python3
from __future__ import annotations

import gzip
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from .experiment import FINAL_ITERATIONS, ITERATIONS_PER_STAGE, SEARCH_STAGES, run_stage
from .optimizer import ScheduledScoreObjective, UserData, optimize_one_swap, read_aam_users
from .population import sanitize_population


class FakeUsers:
    ids = ["person"]
    origins = np.zeros((1, 2))
    current_aam_plan_users = 1
    potential_new_aam_users = 0
    population_count = 1


class FakeObjective:
    base_fare = 30.0
    fare_per_mile = 2.0
    maximum_wait_seconds = 1800.0
    def __init__(self):
        self.users = FakeUsers()
        self.candidates = [{"id": f"C{i:03d}"} for i in range(100)]
        points = np.arange(100, dtype=float)[:, None]
        self.site_distance = np.abs(points - points.T)

    def evaluate(self, active):
        return {"feasible": True, "objective": float(sum(active))}


class ScheduledOptimizerTests(unittest.TestCase):
    def test_four_neighborhood_sizes(self):
        expected = {"global": 900, "all-vp-k10": 100, "one-vp-k10": 10, "adaptive": 50}
        for method, count in expected.items():
            with self.subTest(method=method):
                _, report = optimize_one_swap(FakeObjective(), list(range(10)), method)
                self.assertEqual(count, report["movesEvaluated"])

    def test_exactly_50_iterations_with_fixed_tail(self):
        self.assertEqual(50, SEARCH_STAGES * ITERATIONS_PER_STAGE + FINAL_ITERATIONS)
        self.assertEqual(10, FINAL_ITERATIONS)

    def test_observed_last_departure_overrides_feeder_approximation(self):
        candidates = [{"id": "VP01", "x": 5183.0, "y": 0.0},
                      {"id": "VP02", "x": 10000.0, "y": 0.0}]
        users = UserData(ids=["late-passenger"], origins=np.asarray([[0.0, 0.0]]),
                         destinations=np.asarray([[10000.0, 0.0]]), scores=np.asarray([10.0]),
                         money_utility=np.asarray([1.0]), trip_person_index=np.asarray([0]),
                         current_origin_site=np.asarray([0]), current_destination_site=np.asarray([1]),
                         ground_scores=np.asarray([0.0]), departure_seconds=np.asarray([67932.0]))
        objective = ScheduledScoreObjective(users, candidates, [0, 1])
        self.assertTrue(objective.evaluate([0, 1])["feasible"])
        cost, pair = objective.minimum_cost([0, 1])
        self.assertTrue(np.isfinite(cost[0]))
        self.assertEqual([0, 1], pair[0].tolist())
        # Losing the flight excludes the AAM alternative, while the traveler
        # remains in the population objective with a non-AAM outside option.
        cost, pair = objective.minimum_cost([1])
        self.assertTrue(np.isinf(cost[0]))
        self.assertEqual([-1, -1], pair[0].tolist())
        result = objective.evaluate([1])
        self.assertTrue(result["feasible"])
        self.assertEqual(0.0, result["predictedAamGainSum"])

    def test_stage_command_uses_layout_and_disables_final_innovation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, plans, layout = root / "output", root / "plans.xml.gz", root / "layout.csv"
            plans.touch(); layout.touch()
            args = SimpleNamespace(powershell="powershell.exe", launcher=root / "run.ps1", memory="18g",
                                   config=root / "config.xml", project_root=root)

            def fake_run(command, cwd, check, stdout, stderr):
                output.mkdir()
                (output / "scheduled.output_plans.xml.gz").touch()

            with patch("scripts.aam_scheduled.score_optimizer.experiment.subprocess.run", side_effect=fake_run) as called:
                run_stage(args, output, plans, layout, 10, False, False)
            command = called.call_args.args[0]
            self.assertIn("-Vertiports", command)
            self.assertIn("-DisableInnovation", command)
            self.assertEqual("9", command[command.index("-LastIteration") + 1])
            self.assertIn("-SkipCompile", command)

    def test_reads_and_sanitizes_scheduled_transit_route(self):
        route = {"transitLineId": "aam_sched_line_VP01_VP02", "accessFacilityId": "aam_sched_stop_VP01",
                 "egressFacilityId": "aam_sched_stop_VP02", "boardingTime": "07:30:00"}
        xml = ('<?xml version="1.0"?><population><person id="p"><attributes>'
               '<attribute name="hhinc" class="java.lang.Double">70000</attribute>'
               '<attribute name="hhsize" class="java.lang.Integer">2</attribute></attributes>'
               '<plan selected="yes" score="10"><attributes><attribute name="scheduled_aam_park_mode" '
               'class="java.lang.String">car</attribute></attributes><act type="home" x="0" y="0" end_time="07:00:00"/>'
               '<leg mode="access_egress_pt" dep_time="07:00:00"/><act type="pt interaction" x="0" y="0"/>'
               '<leg mode="pt" dep_time="07:10:00"><route type="default_pt">' + json.dumps(route) + '</route></leg>'
               '<act type="pt interaction" x="30000" y="0"/><leg mode="access_egress_pt"/>'
               '<act type="work" x="30000" y="0"/></plan></person></population>')
        candidates = [{"id": "VP01", "x": 0.0, "y": 0.0}, {"id": "VP02", "x": 30000.0, "y": 0.0}]
        with tempfile.TemporaryDirectory() as directory:
            source, clean = Path(directory) / "plans.xml.gz", Path(directory) / "clean.xml.gz"
            with gzip.open(source, "wt", encoding="utf-8") as stream:
                stream.write(xml)
            users = read_aam_users(source, candidates)
            report = sanitize_population(source, clean)
            with gzip.open(clean, "rt", encoding="utf-8") as stream:
                cleaned = stream.read()
        self.assertEqual([0], users.current_origin_site.tolist())
        self.assertEqual([1], users.current_destination_site.tolist())
        self.assertEqual(1, report["layoutInvalidatedAamPlans"])
        self.assertIn('mode="scheduled_aam"', cleaned)
        self.assertIn("scheduled_aam_park_mode", cleaned)
        self.assertNotIn("aam_sched_line_", cleaned)


if __name__ == "__main__":
    unittest.main()
