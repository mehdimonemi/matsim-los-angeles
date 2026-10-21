# Diagnosis of the final count of 14

The completed run `run-output/drt-global-choice-fixed-20261010-231924` really submitted and completed 14 AAM requests in its last iteration. This is a final-iteration count, not the number of passengers who ever used AAM across the experiment.

The final layout screened all 18,659 passengers and 71,126 daily trips. It produced 1,615 genuine alternatives. In the final stage, selected AAM users fell from 420 in iteration 1 to 14 in iteration 9, while all 1,615 alternatives remained protected and were eventually scored. The bottleneck was voluntary selection after scoring, rather than missing plan memory or aircraft rejection in the last iteration.

Read-only comparison of each person's best scored AAM plan against their best scored ground plan found:

- 1,615 people had both options scored.
- Only three best AAM scores exceeded the person's best ground score.
- Median AAM minus ground score: -122.38 utility units; mean: -205.23.
- 404 people had car legs in their best ground plan but none in their best AAM plan.

Raw stage totals, plan examples and score differences are in `drt-global-demand-drop-diagnosis.json`; the analysis can be reproduced with `validation/analyze_aam_demand_drop.py`. These comparisons concern whole plans, which can have different timing and modes; they do not isolate a causal score component or predict corrected adoption.

An implementation regression was found in startup seeding: before using the new tour-aware strategy, it converted **every** car and bike leg in the copied daily plan to `ride`. This disabled private paired-tour construction at startup and changed unrelated trips. The final-layout startup funnel consequently reported 1,615 single-trip alternatives and zero paired-tour alternatives. The blanket conversion was introduced in this chat and should not have remained in the tour-aware pipeline.

Fix:

- Removed the blanket private-mode conversion from `AamAlternativeGuarantee.seedAlternatives`.
- Startup now passes the original source modes to `AamPlanStrategyModule`, which pairs a feasible car/bike home tour and changes intermediate private movements only within that affected tour. Unrelated later private trips remain intact.
- Added startup-level car and bike regressions proving paired-tour generation, preservation of unrelated private trips, a null alternative score and an unchanged selected ground plan.
- Corrected Global journey passenger accounting by applying the manifest's fixed passenger IDs. Experienced-plan files omit subpopulation attributes, so the earlier journey report incorrectly listed all 19,123 people as passengers. This counting issue did not create the 14 requests.

Validation:

- **109 Java checks passed**, plus the adaptive regression and 17-test launcher Python subset (`drt-global-tour-startup-tests.log`).
- **43 Python tests passed**, including experienced-plan reporting without freight attributes (`drt-global-demand-fix-python-tests.log`).
- The corrected frozen runtime completed two three-iteration small MATSim stages connected by a real 900-swap Global calculation (`drt-global-tour-startup-integration-20261011/validation.json`). The first stage had one genuine startup alternative. The small run's last stage selected no AAM trips; this is not a demand improvement claim. Startup car/bike tour invariants are established by the added regressions.
- No corrected regional production experiment was launched. The amount of demand recovery is **not yet measured**. Five-mile endpoint limits, operating hours, fares, fleet, optimizer objective and voluntary choice are unchanged. The earlier best-two coverage and production performance limitations remain.

Fresh package: `run-inputs/drt-global-choice-fixed-20261011-121303`. The completed low-demand run and all earlier packages were preserved. Start from the fresh package rather than resuming its converted AAM plans or using its old frozen classes.

Run command, from PowerShell:

```powershell
Set-Location C:\Matsim\matsim-los-angeles
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam_repair/run_drt_global.ps1 `
  -PackageDirectory run-inputs/drt-global-choice-fixed-20261011-121303 `
  -Run
```

This starts the Global eight five-iteration learning stages plus the ten-iteration fixed tail. It has not been run as part of this fix.
