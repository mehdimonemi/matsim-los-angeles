# DRT AAM Global choice-set integration

The target of the choice-set fixes is the DRT Global workflow in `scripts.aam_repair.fast_global`. The direct `run_aam_v5.ps1` launcher executes a fixed-layout DRT simulation; it does not run the global optimizer.

The fresh regional package is `run-inputs/drt-global-choice-fixed-20261010-231741`. It freezes the current Java classes and fingerprints the Python optimizer, screening, reporting and stage code. Package preparation passed static validation for 19,123 agents, including all 18,659 passengers, 100 candidate sites and ten initial active sites. Original packages and run outputs were preserved.

Changes connecting the fixes to this workflow:

- `scripts/aam_repair/run_drt_global.ps1` compiles the current DRT sources and prepares a new DRT-only package. Default invocation prepares only; `-Run` explicitly starts Global.
- `production_manifests.py` supports DRT-only packaging, fingerprints the screening module and verifies fixed runtime classes, service hours, QSim horizon and agreement between routing and optimizer distance/request-window settings.
- `fast_global.py` passes both endpoint limits and pre-service request policy to the analytical optimizer, and uses physical DRT classification for journey reporting.
- `score_optimizer/optimizer.py` accepts those parameters and uses them for pair feasibility and all-trip diagnostics. The score objective and global 900-swap neighborhood are unchanged.
- `reporting.py` excludes `mode="aam"` placeholders and marker-only ride plans from genuine alternatives and selected users. It reports marker/fallback plans separately and counts requests, boardings and completed users from events.
- `AamFeederPolicy.java` initializes vehicle mappings for ordinary configured network modes present in plans before startup routing. This fixes the regional crash on person `1005268` with `ride_school_bus`. Existing mappings are preserved.

Validation:

- Java executable regressions: **103 checks passed**, including new school-bus vehicle-mapping checks. Adaptive regression and the 17-test launcher Python subset also passed (`validation/aam-choice-school-bus-tests.log`).
- Python optimizer, population, Global protocol, stage, neighborhood, package and aircraft regressions: **43 tests passed** (`validation/drt-global-choice-integration-tests.log`). The Global protocol test verifies eight five-iteration learning stages and a ten-iteration fixed tail without candidate probe simulations.
- Actual small integration: **two passengers, seven daily trips, ten active sites, 100 candidates, two three-iteration MATSim stages and one 900-swap Global optimization** (`validation/drt-global-choice-integration-20261010/validation.json`). Both stages completed in about 16 seconds each on the synthetic network. The second stage recorded one voluntary selected AAM user, one request, one boarding, one completed journey and zero rejections. Marker-only counts were zero. A school-bus ground trip exercised the startup failure path.
- Regional production was **not** launched. The new package passed static validation; its full regional startup has not yet been rerun.

The small integration used the first fresh package (`...231507`); the final package (`...231741`) includes the additional static validation checks and final preparation documentation. Java source/runtime behavior was unchanged between those two packages.

Preserved Global assumptions: $30 base fare plus $2 per air mile, existing aircraft fleet, 07:00–19:00 AAM operation, 36-hour QSim horizon, positive innovation during learning and the existing objective. The source fixed-layout config's zero base fare is not the Global experiment fare; the new Global snapshot retains the original Global $30 setting.

To prepare a package again without starting MATSim:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam_repair/run_drt_global.ps1
```

To launch the prepared Global experiment later, from the project root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam_repair/run_drt_global.ps1 `
  -PackageDirectory run-inputs/drt-global-choice-fixed-20261010-231741 -Run
```

The latter command starts the full eight-stage learning plus ten-iteration tail experiment. It was not executed during this work. Packages are fingerprinted; source changes require preparing a fresh package.

Remaining limitations from `AAM_CHOICE_SET_REPORT.md` still apply: the best-two routing budget can miss a feasible lower-ranked trip, production routing performance is unmeasured, and the full plotting CLI has not been exercised. The other three optimizer experiments remain for later execution using the shared corrected DRT pipeline; this report does not claim those experiments have been run.
