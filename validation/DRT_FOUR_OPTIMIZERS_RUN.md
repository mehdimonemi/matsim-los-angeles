# Fixed DRT model: all four optimizers

Use `scripts/aam_repair/run_drt_optimizers.ps1`. It uses the corrected DRT stage runner and objective from Global for all four independent experiments, changing only the analytical swap neighborhood:

1. Global (`global`)
2. All-VP-K10 (`all-vp-k10`)
3. One-VP-K10 (`one-vp-k10`)
4. Adaptive (`adaptive`)

Each method starts from the same original population, ten-site layout, seed and frozen runtime. Each runs eight five-iteration learning stages plus ten fixed-layout iterations. Methods run sequentially: 50 MATSim iterations each, 200 total. Plans, learned wait priors and optimized layouts are not carried between methods. Fares, fleet, utility coefficients, objective, 07:00–19:00 service and 36-hour QSim are unchanged. There are no candidate simulation probes or paired acceptance branches.

The suite writes a separate directory per method and updates `comparison.csv` and `comparison.json` after each completes. Final-iteration event counts distinguish selected users, requests, completed users and rejections from retained scored alternatives. A failure stops the suite and preserves completed results plus `failure.json`; existing output directories are never overwritten.

Implementation: parameterized `fast_global.py`, new `drt_fixed_suite.py`, new PowerShell launcher and new protocol/suite regressions. **47 focused Python tests passed**, including all four 8x5+10 protocols, independent starts, method dispatch and failure preservation. No Java behavior changed in this launcher work; the previously tested tour-aware startup fix remains in the compiled runtime. The latest package passed static validation. No production experiment was launched.

Prepared package: `run-inputs/drt-four-optimizers-choice-fixed-20261011-121944`.

Run all four:

```powershell
Set-Location C:\Matsim\matsim-los-angeles
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam_repair/run_drt_optimizers.ps1 `
  -PackageDirectory run-inputs/drt-four-optimizers-choice-fixed-20261011-121944 `
  -Method all `
  -Run
```

Outputs default to a fresh timestamped `run-output/drt-four-optimizers-choice-fixed-*` directory. To run just one method, replace `all` with its name above. To prepare a new package after source changes, invoke the launcher without `-PackageDirectory` and without `-Run`.

This preserves the shared model rather than adjusting fares, scoring or forcing selection to increase AAM demand. The corrected model's regional adoption and comparative performance remain to be measured by these experiments.
