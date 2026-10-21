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
  "filesFingerprinted": 289,
  "warning": "Static file/cohort/bytecode validation is not MATSim startup validation, production calibration, or four-method integration. Full coverage means 901 estimator simulations + 5 or 10 validation simulations per stage per service; enormous compute. A cap prevents complete-coverage convergence claims.",
  "probeLayoutsPerStage": 901,
  "fullNeighborhoodLayouts": 901,
  "evaluationIterationsPerTrial": 50,
  "maximumStages": 20
}

No model has been started. Use the validate subcommand again before launching.
Cohort includes all passenger residents independent of layout; ground-only people remain in the objective.
Proposals: walking 1000m AND 1200s per end, scheduled wait 1800s, DRT wait 900s, paired minimum gain .01 utility, aggregate stability tolerance 1.0 utility over last 3 iterations, 2 stable stages.
50 iterations/trial and 20 stages are default safety budgets, NOT convergence guarantees.
The source DRT configuration has baseFare=0; the NEW snapshot explicitly sets baseFare=30 and service 07:00-19:00. Original configs/results were not modified.
Do not use synthetic validation manifests or expect four-method comparisons from these files.
