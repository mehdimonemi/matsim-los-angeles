# AAM repair and controlled-validation workflow

## Current requested DRT Global protocol (8 × 5 + 10)

The user now explicitly requests optimizer-predicted acceptance without paired
MATSim validation. `scripts.aam_repair.fast_global` runs only Global: eight
five-iteration stages with innovation, then ten fixed-layout innovation-free
iterations. It performs eight analytical swap searches, zero candidate probes
and zero validation branches. It preserves checkpoints and their old-score/layout
archives, freezes the runtime and retains the manifest's fare, service and walk
limits. The final ten iterations are a convergence tail, not proof of convergence.

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -B -m scripts.aam_repair.fast_global `
  run-inputs/aam-global-8x5-20261009-01 --output NEW_OUTPUT_DIRECTORY
```

The analytical objective includes passenger selected scores and potential positive
AAM gains, using observed waiting priors and configured fares/service hours.
Walking distance AND time limits screen walking in the feeder cost approximation.
Feeder road speeds and ground-score reconstruction remain approximate; this is
explicitly recorded in the run manifest. Physical continuity and feasibility
remain enforced by the repaired Java routing/simulation. Predicted improvement
is an estimate, not a guaranteed realized score gain. The prior paired workflow
below remains a separate protocol and is not called by this run.

Started run: `run-output/drt-global-8x5-20261009-01`.

## Create regional-input manifests without simulation

`python -B -m scripts.aam_repair.production_manifests create --output NEW_DIRECTORY` creates both service manifests, effective configuration snapshots, the fixed cohort, compiled-class snapshots, input fingerprints and a static validation report. Generation does not execute Java/MATSim or alter original inputs. The repaired suite consumes these manifests for all four search methods.

The generated package currently contains 19,123 simulated agents: 18,659 `subpopulation=person` travelers in the fixed, layout-independent objective cohort and 464 freight agents still simulated outside that passenger objective. There is no incumbent-radius/current-AAM-user filter: ground-only passengers remain in the objective. This uses the existing 0.1% sample, NOT the full LA population.

Revalidate an existing package with `python -B -m scripts.aam_repair.production_manifests validate run-inputs/aam-repaired-manifests-01`. This command only reads/verifies files; it never starts a simulation. Fingerprint mismatches require reviewing the changes and generating a new package, not ignoring the check.

Defaults are explicit proposed settings: five seeds, $30 + $2/mile for both services, 07:00–19:00, walking ≤1 km AND ≤20 min at each end, scheduled wait ≤30 min, DRT pickup wait ≤15 min; 50 iterations per trial, 20-stage safety budget, two stable stages, aggregate stability tolerance 1 utility and minimum predicted/observed gain .01. These are not calibrated convergence/behavior findings. Generation flags `--iterations`, `--stages`, `--maximum-probe-layouts`, `--memory` and `--simulation-tolerance` customize budgets without editing protected files.

The repaired workflow uses a common observed coefficient estimator for all four methods. Its default 901 probes launch 901 estimator simulations plus 5 or 10 validation simulations per stage per method. Restricted methods save search evaluations, not coefficient-probe simulations; stage trajectories can diverge. `allowLargePopulation=true` is recorded, but direct Python execution also requires `--allow-large-population`. Static validation does not prove MATSim startup or calibrated behavior.

## Run all four repaired optimizers for both services

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\aam_repair\run_comparison.ps1 `
  -Output run-output/aam-repaired-four-methods-01
```

This compiles both Java models, creates a NEW timestamped manifest package,
validates its fingerprints, and sequentially runs Scheduled then DRT, each with
`global`, `all-vp-k10`, `one-vp-k10`, and `adaptive`. To prepare without simulating,
add `-PrepareOnly`. To use a prepared package, add `-ManifestDirectory PATH`.
Existing packages use their recorded budgets and memory; launcher preparation
options do not override them. Existing outputs are refused rather than overwritten.

`-Service scheduled` or `-Service drt` runs one service; `-Method adaptive` (or
another method name) runs one method. New-package settings are `-Memory 18g`,
`-IterationsPerTrial 50`, `-MaximumStages 20`, and `-MaximumProbeLayouts 901`.
Lower probe caps are incomplete estimation experiments and cannot establish
complete-coverage convergence. Fifty is iterations **per trial**, not the total
experiment length. Stop uses the configured convergence rule with a stage
safety ceiling, rather than the legacy fixed 50-iteration experiment.

Every method has its own `SERVICE/METHOD/manifest.json`, stage decisions,
score/plan provenance, estimator probes, paired validation runs and result.
Root `comparison.csv` and `comparison.json` update after each completed method;
completed results survive a later failure. Search gaps refer to the selected
neighborhood and observed coefficient catalog, not all possible layouts.

Global searches all swaps; All-VP searches ten nearest inactive candidates per
active site; One-VP selects the smallest population removal loss and searches
its ten nearest candidates; Adaptive expands K5→K10→K20→Global until it finds a
qualifying gain. Candidate distance ties break by ID. Ground choices, walk/service
gates, fares, failed-proposal feedback and paired observed acceptance are common.

## Repaired stage optimization for both services

Use `python -B -m scripts.aam_repair.stages MANIFEST --output NEW_DIRECTORY`
with either service manifest. Regional manifests additionally require
`--allow-large-population`. The same z/s/q stage model, ground outside options,
observed feeder/service coefficients, paired validation and convergence rule
apply to scheduled AAM and AAM-DRT. Stop as soon as the configured number of
consecutive stable, fully covered, solved stages is reached; `maximumStages`
is a safety ceiling. A single no-improvement stage continues with the incumbent
so the next stage can use refreshed scores.

An optimizer improvement provisionally selects the trial layout. The incumbent
changes only after paired MATSim validation, as requested in item 9; accepting
solely on the predicted score is the separate legacy comparison below. The
aggregate bound compares both layouts under the same current-stage estimates.
It does not guarantee that observed scores never vary between stages or that
every individual improves.

## Legacy four-method score optimization comparisons

The commands in this section retain approximate feeder scores, fixed stage
budgets and prediction-only acceptance. They do **not** implement the repaired
observed-coefficient/paired-validation protocol. Use them as explicitly labeled
historical comparisons, not as evidence that items 6 and 9 are satisfied.

The score optimizer compares every passenger's selected-plan score with an AAM alternative. If a passenger has no AAM plan yet, it derives trip endpoints from the selected ground plan and estimates the ground-versus-AAM score change using routed leg times, distances and mode coefficients. It adds only positive estimated AAM gains. This newly eligible user calculation is a surrogate: daily mode constants and all ground fares/wait penalties are not fully reconstructed, so predicted scores need interpretation as estimates. Each method directly applies its best predicted one-site swap. If a stage finds no improving swap, it keeps that layout and proceeds to the next stage, where the updated MATSim traveler scores are used. The four search neighborhoods are `global`, `all-vp-k10`, `one-vp-k10`, and `adaptive`.

From the repository root, run both service suites with the same 10-site initial layout and new output roots:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\aam-scheduled\run_vertiport_comparison.ps1 `
  -InitialLayout .\scenarios\aam\active-vertiports.csv `
  -Output run-output/user-score-scheduled-four-methods-01

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\aam\score_optimizer\run_comparison.ps1 `
  -InitialLayout .\scenarios\aam\active-vertiports.csv `
  -ServiceStartTime 25200 -ServiceEndTime 68400 `
  -Output run-output/user-score-drt-four-methods-01
```

Each command runs four separate 50-iteration experiments (eight 5-iteration search stages followed by ten innovation-free iterations), for eight experiments total. Compile-only/setup runs happen before each suite; the full regional models start only when these commands are run. The scheduled and DRT service configurations remain distinct. These runs use the existing 0.1% population sample.

## Explicit assumptions proposed for comparison

These are configurable **proposals**, not calibrated findings or silently inherited behavior:

| Item | Repaired setting | Meaning |
| --- | --- | --- |
| Origin eligibility | existing 5-mile radius | Evaluated against the selected origin vertiport, not merely some nearby site. |
| Minimum trip | existing 3 miles | Eligibility, not a walking allowance. |
| Walking per end | 1,000 m AND 1,200 s | Sum all walking connectors in access independently of egress. Both tests must pass. |
| Scheduled maximum passenger wait | 1,800 s | Router screen and QSim hard timeout; boarding handling can add a simulation time step at the boundary. |
| Scheduled timetable | 07:00–19:00, 30-minute headway, 4 seats | Unchanged reference timetable; 19:00 is the last departure, not required landing time. |
| Scheduled fare | $30 boarding charge + $2/air mile | Charged once per actual boarding, using person-specific marginal utility of money. Old daily/distance scheduled-mode monetary charges are zeroed to prevent double charging. |
| DRT insertion estimate factor | 1.0 instead of 0.5 | Corrects a restrictive free-speed pre-filter; does not loosen the 900 s pickup limit, alpha 1.2, beta 1,800 s or 120 s stop duration. |
| Simulation acceptance | ≥5 paired independent seeds, lower confidence bound > configured minimum improvement | Default multiplier 2.776 is conservative for at least five pairs. Fix the rule before looking at results. |

The parameter names are `maximumWalkDistance`, `maximumWalkTime`, `maximumPassengerWait` (scheduled), and `insertionEstimateSpeedFactor` (DRT). Keep these identical across controlled arms unless they are the explicitly labelled experimental treatment. The Java defaults now enforce the proposed limits; existing result files and original timetable data are not rewritten.

A failed scheduled departure remains a real failure: full vehicles do not teleport passengers. Before each mobsim, selected AAM plans are rebooked against seats in seeded order, including in the innovation-free phase. If no acceptable flight is available, a preserved ground plan is selected. Unexpected missed connections, boarding delay, or closure during QSim generate `scheduledAamRejected` and normal MATSim stuck scoring, aborting the remaining daily plan. **There is no same-day taxi rescue after an actual QSim failure.** This is a documented conservative behavior that must be held constant across comparisons; implementing a within-day rescue would be a separate behavioral treatment.

`queuePriorsFile` can load prior observed excess queue delay and departure occupancy. Iteration snapshots are saved under `scheduled-aam-service/`. Only excess delay is learned: residual timetable waiting is not counted twice. Ordinary ground PT uses a ground-only Raptor schedule, preventing it from bypassing explicit AAM feasibility checks.

## Feeder and restart repairs

- Initialize car, bike, ride and taxi IDs before startup routing; preserve existing custom IDs. Use the existing LA congested-network ride/taxi routers.
- Failed feeder routing raises a person/mode/time diagnostic rather than silently becoming walking. `feeder-diagnostics/iteration-N.csv` counts admissible and excluded alternatives for each mode and each end, including options not selected.
- AAM scenario loading retains all competing plans. Restart sanitation retains all alternatives, archives exact old XML/score/plan hash/layout identity, and clears scores before changed routes are evaluated. Scores are never copied onto modified routes.
- Preserve private-car/bike paired-tour rules. Passenger-based counterfactuals leave the private vehicle home for the whole day and reroute converted ride trips. An old AAM-only checkpoint receives a newly routed passenger-ground outside option; this cannot reconstruct a private-car plan deleted by an older run.
- Queue-driven plan changes archive pre-change plans under `queue-plan-provenance/`, with layout provenance in the run's frozen input snapshot. A final selected-plan gate prevents prohibited walking even for carried-over transit plans.

## Original mathematical formulation and differences

Located in the user's earlier chat **“Review AAM DRT demand and costs”**, thread `01a0e93b-2743-7201-b637-57936c6c5b6c`, slides 61–62. It uses binary site variables z, swap indicators s, and traveler/ordered-pair assignments q. Exactly V sites are open; q requires both endpoint sites; each current AAM user receives one pair; sum(s) ≤ 2 R_swap; maximize sum(B_rmn q_rmn). The later user instruction explicitly set aside site separation and requested raw plan scores rather than monetary-equivalent benefit.

The repaired population objective adds a **ground outside option** and includes every fixed eligible traveler, not just existing AAM users. For a multi-flight daily alternative, q indexes the full daily plan and requires all of its used sites; this generalizes the ordered-pair index without changing the aggregate-score objective. Ground choice does not require a site and AAM adoption is not forced. `legacy_current_aam_users` remains an explicit comparison objective, with the population protection constraint still applied.

`stage_model.py` solves this additive binary model exactly by eliminating q (best feasible option for each traveler at a given layout) and enumerating z within the swap bound. This is not an external branch-and-cut solver. With 100 candidates, V=10 and R_swap=1, there are 901 layouts including the incumbent. On exhaustive completion, bound equals objective and gap is zero **for that stage model and neighborhood**. On timeout, it returns the feasible incumbent and a valid independent-traveler relaxation bound. Increasing the swap bound can become combinatorially expensive.

The incumbent is always a candidate. Its current-stage aggregate estimate is the non-decreasing score bound; a minimum improvement is an acceptance threshold, not an infeasible strict-improvement constraint. Aggregate protection permits one traveler to lose if others gain more. Individual protection would add one inequality per traveler and can block beneficial collective changes; it is not enabled silently.

## Estimates, validation and limits of optimality

Both services use the same `empirical_estimator` adapter. It probes layouts in MATSim with the same cohort, scoring, service/fare settings and fixed site count. Coefficients come from matched, executed per-iteration plans and events, including actual feeder routing, fare and failure scoring—not the old uniform-speed feeder proxy. Failed proposals are retained and prioritized for re-estimation; old scores are not relabelled as new-stage observations.

The stage surrogate is explicitly a **catalog of observed routed plan options**. It is not every theoretically possible itinerary. Utilities averaged across probe contexts are separable approximations; shared capacity and congestion interactions remain in MATSim validation. An exact zero gap on this table does not prove a globally optimal real-world vertiport network. Incomplete probe coverage cannot satisfy the stage convergence criterion. `maximumProbeLayouts` is an explicit computational limit, not permission to label missing options globally infeasible.

The coordinator validates incumbent and proposal from the same accepted checkpoint using matched independent seeds. It rejects incomplete score coverage and population/assumption mismatches. Only an observed population improvement under the predeclared comparison rule advances the layout. Otherwise the incumbent remains accepted and failed-proposal observations feed the next estimation stage. The canonical first replicate supplies the next checkpoint; all replicate artifacts remain available.

Stopping requires a solved stage model with no qualifying improvement, complete configured probe coverage, rescored competing plans, and a stable eligible-population score window for the configured number of stages. `maximumStages` is only a safety budget: reaching it reports `safety_budget_reached_NOT_converged`.

## CAN012 diagnosis

The historical DRT All-VP k10 audit is reproducible with `python -m scripts.aam_repair.diagnose_can012 --requests OLD_REQUESTS.csv --output NEW_DIRECTORY`.

All 107 requests were rejected; 82 were in 07:00–19:00. MATSim 13's `SelectiveInsertionSearchParams` defaults to factor 0.5; its zonal estimator divides free-speed time by that factor. The restrictive search therefore evaluates approximately twice the direct time against a latest-arrival allowance of 1.2 × direct time + 1,800 s. For every one of the 82 in-hours requests, even a conservative lower bound exceeds that allowance, by at least 601.44 s. Four also overrun the service window even without queueing. This identifies a sufficient binding pre-filter constraint, not a full replay of every aircraft's insertion schedule. Zero completed trips is not used as a site-deletion rule.

## Reports and supply comparisons

`reporting.py` reports selected alternatives, attempted requests, boardings, completed air legs, completed door-to-door journeys, rejections and unfinished journeys separately. Completion requires the subsequent main activity after egress, not merely an aircraft drop-off. Passenger wait and scheduled stop dwell are separate. Aircraft idle time is not fabricated by calling passenger queueing “vehicle wait.”

Controlled comparison manifests require the same population, eligible cohort, seed and service hours, and explicitly record fare, supply and scoring assumptions. `comparison.json`, `comparison.csv` and per-request JSONL are written only to a new directory.

The reference still constructs one aircraft per departure. `reuse_report` separately computes a minimum-aircraft path-cover **lower bound** with same-site reuse, a supplied turnaround time and explicit cost rates. It is not an operational fleet claim: battery/range, charging, maintenance, reserve aircraft and pad capacity are not modelled. Production operating-cost conclusions require those assumptions to be supplied and validated.

`allocate_departures` creates a separate demand-weighted frequency allocation under a fixed total departure budget. Set `frequencyAllocationFile` to a CSV with header `origin,destination,departures`, listing every active directed corridor (including zeros). Allocated departures are evenly spaced within service hours; a single departure is at the midpoint. An empty file setting retains the reference timetable. Frequency optimization and vehicle reuse are separate from vertiport-layout acceptance.

## Reproducible small validation

- `scripts/aam-scheduled/run_scheduled_aam.ps1 -Test -Memory 2g`: routing/restart tests plus seven-person saturated VP08 → VP09 QSim, hard wait/closure behavior and exact boarding charges.
- `pwsh -ExecutionPolicy Bypass -File scripts/aam/run_aam_v5.ps1 -Test -Memory 2g`: DRT feeder, continuity, startup and dispatch checks plus legacy optimizer regressions.
- `python -B -m scripts.aam_repair.test_stage_model`: exact objective/ground choice, bound, minimum improvement, paired variability, immutable score provenance and report/supply checks.
- `make_small_cases` extracts travelers 10096817 and 10092375. Their coordinates, activities and attributes are real; the small complete road graph is synthetic and explicitly labelled. `--shift-seconds 14400` is a separate daytime feeder test, not a claim about their observed behavior.
- `validation_manifest` creates a small stage manifest; the resulting stage-protocol smoke uses actual MATSim runs but only two sites, so swap behavior is tested separately rather than claimed from this trivial layout.

All validation outputs are under new `run-output/aam-repair-validation/` subdirectories. Failed test artifacts are retained as well. No old result directories are modified. Regional convergence, demand response and operational fleet realism are **not validated by these small tests**.

### Validation results (2026-10-08)

- Scheduled regression suite and seven-person capacity/fare QSim pass, including separate frequency-allocation construction. Latest log: `target/aam-repair-scheduled-final-tests-03.log`.
- DRT: 65 Java checks and 8 legacy Python checks pass. The CAN012 → CAN025 dispatch reproduction rejects at factor 0.5 and completes at factor 1.0, with unchanged passenger constraints. Log: `target/aam-repair-drt-final-tests-02.log`.
- Nine stage/report Python tests pass, including accepted and rejected proposals, failed-proposal feedback, legacy-objective population protection, and refusal to declare convergence with incomplete coefficient coverage. Adapter mocks in these unit tests are not MATSim evidence.
- Actual two-person daytime runs are `named-daytime-scheduled-02` and `named-daytime-drt-02`. Each traveler completes AAM in iteration 1; mean passenger wait is 215 s scheduled and 121 s DRT. Both retain scored ground/AAM alternatives and ultimately select ground. Ride and taxi are admissible at both ends; the historic long walks are excluded. The synthetic road graph and time-shifted test are not regional behavioral evidence.
- `controlled-report-01/REPORT.md`, `comparison.json`, `comparison.csv`, and `retained-alternatives.json` summarize those runs. Regenerate into a NEW directory with `python -B -m scripts.aam_repair.validation_report run-output/aam-repair-validation --output NEW_DIRECTORY`.
- `stage-protocol-03/result.json` is an actual two-stage, five-seed-per-stage MATSim pilot, plus current-stage estimator probes. It reports `safety_budget_reached_NOT_converged`: exact stage-model gap zero, but simulation stability fails. Its only two candidate sites are both open, so this pilot does NOT validate a real site swap. Nontrivial acceptance/rejection is regression-tested separately.

MATSim writes the regular per-iteration plan snapshot **before** the final pre-mobsim feasibility/queue gate. Use `experienced_plans` matched to events for executed alternatives and objective scores. Use full `output_plans` separately to audit retained competing alternatives. Mixing these snapshots previously produced apparent selected AAM users with no AAM requests; the report and estimator now distinguish them.

Production prerequisites remain agreement on walking/wait limits and failure behavior, and calibrated aircraft/operating-cost inputs. The follow-up implementation and three-site tests below supersede the earlier two-site-only validation limitation.

## Follow-up implementation and validation

`remaining_validation.py` constructs a separate three-site, two-person synthetic fixture. `three-site-inputs-01` uses the existing scoring as a ground-choice control. `three-site-inputs-02` deliberately uses -120 utils/hour for road-passenger time to exercise a positive layout swap; it is NOT a calibration or a production scoring change. Both use a synthetic 3 m/s road graph and the unchanged $30 + $2/mile passenger fare.

Scheduled `three-site-scheduled-02` actually accepts VP08/VP09 instead of VP08/VPALT with +108.815185 aggregate utility in all five paired seeds, then reroutes/rescores the accepted checkpoint in stage 1. It ends at its safety budget, correctly NOT claiming convergence after only one stable stage following a change. The `scheduled-swap-audit-01` report compares predicted and realized scores. The DRT ground-choice control `three-site-drt-01` reaches its two-stage stability criterion without forcing AAM adoption.

DRT `three-site-drt-02` also accepts that swap, with +139.375571 aggregate utility in all five paired seeds. `scheduled-rejection-replay-02` and `drt-rejection-replay-01` verify the negative observed changes are rejected despite deliberately optimistic estimates. Both `scheduled-restart-provenance-01/verified.json` and `drt-restart-provenance-01/verified.json` confirm four scored source plans were archived with the correct source layout, scores cleared before rerouting, and both travelers rescored on ground alternatives after removing the origin site.

The multi-site restart test exposed an additional unavailable-ground-transit fallback crash. Scheduled routing now falls back to the available passenger-road router; paired private tours still restore a whole-day ground plan. The new empty-transit regression is in `ScheduledAamRegressionChecks`.

`rejection_replay.py` deliberately injects optimistic coefficients for the worse layout and drives the production acceptance controller using exact cached MATSim pairs with matching source checkpoint, seeds, layout and assumptions. It verifies rejection and incumbent retention without changing observed scores. This is explicitly a fault-injection REPLAY, not new independent simulations or an empirical forecast. `estimation-feedback.json` preserves rejected trials and the next accepted checkpoint. The empirical estimator chooses the most adverse failed-proposal seed for fresh common-seed probes across all candidate layouts; old scores are never attached to modified plans. This conservative stress estimate is not an unbiased multi-seed mean; separate paired validation governs acceptance.

`restart_validation.py` runs actual layout-removal restarts, verifies exact old score/plan/source-layout archives, confirms input scores were cleared, and checks that both people choose newly scored ground alternatives. The stage coordinator now forwards checkpoint layout IDs into estimation probes as well as validation runs.

### Controlled frequency experiment

`frequency-comparison-01` holds population, fare, scoring, hours, seats and total departures constant. The baseline has 25 departures per direction. Demand weights learned only from baseline seed 817 allocate 40 forward and 10 reverse departures. Seeds 818–821 are held out. Their observed learning-iteration boarded waits fall from 1,471.5 to 779.5 seconds; final ground choices and aggregate scores remain unchanged. Thus better frequency does not force AAM adoption. See `frequency-report-01/REPORT.md`; iterations are correlated and are not unique traveler demand observations.

The first comparison's run metadata retained the common reference `supplyFareHash`; the arm labels and frozen effective configs explicitly distinguish the frequency treatment. The generator now fingerprints the allocation file into that hash for future comparisons. Existing outputs were not rewritten.

### Constraint-aware aircraft operations (separate from fares)

`aircraft_operations.py` adds a deterministic feasible dispatcher, distinct from the earlier minimum-path-cover lower bound. It enforces site continuity, range, battery reserve, charger power/slots/efficiency, turnaround, pad occupancy, maintenance intervals, crew duty and withheld reserve fleet. Unserved departures and binding reasons are explicit. It does not silently delay flights or reposition aircraft. Charging, maintenance, turnaround and between-flight aircraft idle time are separate from passenger waiting.

`aircraft_comparison.py RUN --output NEW_DIRECTORY [--assumptions INPUT.json]` reads the actual generated timetable and checks resource overlaps, site continuity and battery reserve. `aircraft-operations-02` serves all 50 departures with two operating aircraft plus one withheld reserve under labeled SYNTHETIC assumptions; the one-per-departure reference uses 50 operating aircraft. This is a feasible example, NOT an optimal fleet or an aircraft specification.

Operating-cost formulas separately accept `aircraftPerDay`, `flightHour`, `crewDutyHour`, `electricityPerKWh`, and `maintenanceEvent`. Missing costs produce null totals, not invented estimates. Passenger fare ($30 + $2/mile) is not an operating-cost input. Energy cost includes end-of-day battery inventory replenishment; the overnight charging schedule is not modeled.

This remains an OFFLINE operational evaluation of the MATSim timetable, not QSim execution of shared aircraft rotations. Delay propagation/weather, empty repositioning, maintenance staffing and parking stands are not modeled. Production fleet/cost conclusions require agreed technical and monetary inputs. Four executable tests in `test_aircraft_operations` exercise reuse, charging shortages, range/reserve/pad/duty constraints, maintenance and cost accounting.

All follow-up outputs use new directories under `run-output/aam-repair-validation/`. `three-site-scheduled-01` is an intentionally retained failed intermediate run that exposed the restart bug; it must not be counted as a completed validation. No full regional model was run.

Each new evaluator trial now copies compiled classes into its private output directory and records `classSnapshotHash`; paired acceptance rejects differing build snapshots. This prevents a concurrent compiler from replacing class files while a running JVM loads them. Compile before starting an experiment. The interrupted post-acceptance stage of `three-site-drt-02` was caused by that shared-build race, not a demand/insertion failure; its committed five-seed stage-0 decision remains valid. `remaining_validation continue SOURCE --output NEW_DIRECTORY` starts fresh trials from the last committed checkpoint without overwriting or trusting partial runs.

Final follow-up summary: `followup-report-01/REPORT.md`. `three-site-drt-continuation-01` completes two fresh stable stages on VP08/VP09 and reports `stage_model_and_simulation_converged` for the small fixture. Per-stage bound equals incumbent objective and gap is zero within its three-site observed-plan model. This is not global regional optimality. All five replicas in the first continuation stage used an identical runtime snapshot and rescored every competing alternative. Future experiments additionally freeze one shared experiment-level snapshot before creating private trial copies.

Final checks: 15 repair Python tests pass; scheduled routing/restart/frequency and saturated-corridor QSim checks pass; DRT 65 Java checks and 8 legacy optimizer Python checks pass. Latest Java logs are `target/aam-repair-scheduled-followup-tests-02.log` and `target/aam-repair-drt-followup-tests.log`. The passenger fare remains $30 + $2/air mile. No full revised model was run.
