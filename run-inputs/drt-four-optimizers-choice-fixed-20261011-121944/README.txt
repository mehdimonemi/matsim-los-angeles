{
  "status": "PASS_STATIC_VALIDATION",
  "matSimStarted": false,
  "totalSimulatedPersons": 19123,
  "objectiveTravelers": 18659,
  "subpopulations": {
    "person": 18659,
    "freight": 464
  },
  "candidates": 100,
  "initialSites": 10,
  "filesFingerprinted": 243,
  "warning": "Static file/cohort/bytecode validation is not MATSim startup validation or production calibration. Full coverage means 901 estimator simulations + 5 or 10 validation simulations per stage per service; enormous compute. A cap prevents complete-coverage convergence claims.",
  "services": [
    "drt"
  ],
  "probeLayoutsPerStage": 1,
  "fullNeighborhoodLayouts": 901,
  "evaluationIterationsPerTrial": 5,
  "maximumStages": 8
}

No model has been started. Use the validate subcommand again before launching.
Cohort includes all passenger residents independent of layout; ground-only people remain in the objective.
Proposals: walking 1000m AND 1200s per end, scheduled wait 1800s, DRT wait 900s, paired minimum gain .01 utility, aggregate stability tolerance 1.0 utility over last 3 iterations, 2 stable stages.
This package records 5 iterations/trial and 8 stages; these are budgets, NOT convergence guarantees.
The source DRT configuration has baseFare=0; the NEW snapshot explicitly sets baseFare=30 and service 07:00-19:00. Original configs/results were not modified.
For DRT Global's 8x5 + 10 protocol, use scripts/aam_repair/run_drt_global.ps1 -PackageDirectory THIS_DIRECTORY -Run.
For all four DRT neighborhoods with that same protocol, use scripts/aam_repair/run_drt_optimizers.ps1 -PackageDirectory THIS_DIRECTORY -Run.
Prepared services: drt. No experiment has been launched.
