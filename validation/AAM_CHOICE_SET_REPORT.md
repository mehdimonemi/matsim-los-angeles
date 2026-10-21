# Dynamic AAM choice-set implementation and validation

Implemented in `C:/Matsim/matsim-los-angeles` on October 10, 2026. Existing unrelated workspace changes were retained. No full production experiment was launched.

Every passenger's main-activity trips now enter cheap screening. Java caches activity-to-vertiport distances and layout/trip signatures; Python maintains origin and destination matrices for all 100 candidate sites. A layout swap can reuse the matrices and perform a full vectorized eligibility scan. Unchanged signatures reuse screening; changed activity timing is reconsidered rather than reusing stale temporal eligibility.

Eligible trips are ranked by a proxy cost before complete routing. Java uses configured mode scoring, feeder distance/time estimates, flight time, expected wait, fare and person-specific money utility. At most two ranked candidates are attempted by default, stopping at the first genuine result. `maximumRoutedCandidates` accepts 1 or 2. `protectedAlternatives` defaults to 1. A paired tour counts as one candidate, although both halves must route successfully.

Genuine alternatives require a physical `aam_drt` leg. AAM type and routing markers do not qualify a ground fallback. Startup normalizes unresolved/saved layout-specific routes to ordinary ground plans, keeps candidate intent on the person, and rebuilds alternatives through the bounded pipeline. Python checkpoints likewise keep unresolved metadata outside executable AAM classification, clear copied scores, remove old AAM stages and parking metadata, and retain main activities. Feeder caches are exact-time and scoped to a routing request; they never reuse a network route across iterations, people or changing travel times.

Startup retains the selected source plan. Newly routed alternatives have null scores. A physical-leg-aware removal selector protects the last genuine alternative even if a false marker has the same plan type. Additional configured protected alternatives receive distinct types at startup. Normal replanning and ChangeExpBeta decide selection.

Iteration 0 remains the initial selected-plan baseline/warm-up. Replanning after iteration 0 may select an AAM alternative, allowing execution from iteration 1. Startup does not force an AAM trial cohort. Staged restarts can retain a previously selected executable genuine plan; the iteration number alone does not imply a ground-only baseline for every possible checkpoint.

Both activity endpoints must satisfy their configured radius, using activity coordinates rather than displaced road-link coordinates. Vertiports must differ. `maxEgressDistanceMiles` inherits `maxAccessDistanceMiles` when unspecified. The production XML explicitly sets both to five miles and retains the three-mile minimum trip distance.

Car/bike innovation detects home-based tours rather than requiring exactly two daily trips. Outbound private access and return private egress use the same home-side vertiport. Intermediate private movements within the parked tour become passenger ride; activities and unrelated later tours remain. An infeasible half rolls back the whole new alternative. Native MATSim rerouting of a saved tour can flag an infeasible return without aborting parallel replanning; the pre-QSim gate then retains a ground choice and normalizes the failed tour.

The QSim end time remains 129,600 seconds (36:00). Production AAM and generated fleet availability remain 25,200–68,400 seconds (07:00–19:00). `allowPreServiceRequests=true` permits an early request only when waiting until opening fits the maximum wait. `false` excludes feeder arrival/request before opening. Full routing checks predicted pickup/flight completion, including stop allowance, against closing. Actual pickup/completion times are reported from events. Fares, fleet size and optimizer objective formula were not changed.

Diagnostics are written under each run's `aam-choice-set/layout` and `aam-choice-set/iteration-N`. Layout output includes detailed candidate records; each iteration writes the funnel, screening/reason counters and separate access/egress distance distributions. Detailed candidate CSVs are not duplicated every iteration. The funnel separates screened eligibility, current routed alternatives, physical selected/scored AAM plans, marker-only plans, ground fallbacks, alternative kind/direction, submitted requests, boardings, completions and rejections. Existing request-level and fleet CSVs remain event-based. Python analysis exposes the same physical-plan distinction and derives operational adoption from request records.

Files changed for this task:

| File | Change |
| --- | --- |
| `src/main/java/org/matsim/run/aam/AamCandidateScreen.java` | New cached screening, candidate metadata, reasons, proxy ranking inputs and distance distributions |
| `src/main/java/org/matsim/run/aam/AamPlanRemovalSelector.java` | New physical-alternative memory protection |
| `src/main/java/org/matsim/run/aam/AamConfigGroup.java` | Egress radius, request policy, candidate/alternative limits and cache toggle |
| `src/main/java/org/matsim/run/aam/AamMultimodalRoutingModule.java` | Both endpoint limits, exact-time feeder reuse, service gate, distance attributes and safe failed-private-tour signal |
| `src/main/java/org/matsim/run/aam/AamPlanStrategyModule.java` | Bounded ranked routing and home-based car/bike tours |
| `src/main/java/org/matsim/run/aam/AamAlternativeGuarantee.java` | All-passenger startup screen and genuine, unselected alternative seeding |
| `src/main/java/org/matsim/run/aam/AamFeederPolicy.java` | Physical classification and fallback/stale-plan normalization |
| `src/main/java/org/matsim/run/aam/AamSelectedPlanValidator.java` | Pre-QSim normalization and rejection of infeasible private return chains |
| `src/main/java/org/matsim/run/aam/AamFleetMetrics.java` | Per-layout/per-iteration choice and operational funnel |
| `src/main/java/org/matsim/run/aam/RunDynamicAamLosAngelesScenario.java` | Wire physical removal protection; avoid redundant AAM ReRoute after innovation |
| `src/test/java/org/matsim/run/aam/AamRegressionChecks.java` | Classification, screening, caching, temporal, choice, memory and tour regressions |
| `scenarios/aam/la-aam-fare30-it2.config.xml` | Explicit egress/access limits, service hours and choice-set defaults |
| `scripts/aam/score_optimizer/population.py` | Physical AAM score/adoption metrics and durable checkpoint candidate intent |
| `scripts/aam/score_optimizer/optimizer.py` | Both radius/window gates and all-passenger screening diagnostics; objective formula retained |
| `scripts/aam/score_optimizer/screening.py` | New vectorized all-trip matrices and layout cache |
| `scripts/aam/score_optimizer/test_population.py` | New reporting, checkpoint and screening tests |
| `scripts/aam/run_adaptive_vertiport_optimization.py` | Exclude marker-only scores and normalize checkpoints while keeping candidate intent |
| `scripts/aam/test_adaptive_vertiport_optimization.py` | Corrected physical-AAM expectations |
| `scripts/aam/analyze_aam_run.py` | Physical trip classification, selected/scored plan counts and event-based adoption |
| `scripts/aam/benchmark_choice_screening.py` | New read-only distance/screening benchmark |
| `scripts/aam/run_aam_v5.ps1` | Include the new Python regressions in `-Test` |
| `scripts/aam_repair/test_fast_global.py` | AAM-marked ride fallback remains a valid observed ground score |

Validation results:

| Check | Result |
| --- | --- |
| Java AAM executable regressions | 101 checks passed, including existing ten-port DRT and long-flight dispatcher smoke cases |
| Python optimizer, population, stage, neighborhood, manifest and aircraft tests | 42 tests passed |
| Adaptive restart/decision regression script | Passed |
| Small MATSim validation | Two passengers, seven trips, iterations 0–2, synthetic road network; no regional production run |
| Production time/fleet checks | 36-hour horizon; all 100 aircraft available 07:00–19:00; both five-mile limits; observed pickup/completion within hours |
| Scoped whitespace check | Clean for task source changes; unrelated existing whitespace was left untouched |

The positive small case produced this voluntary-choice funnel:

| Iteration | Passengers evaluated | Trips evaluated | Genuine alternatives | Selected AAM users | Requests | Completed users | Rejected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2 | 7 | 1 | 0 | 0 | 0 | 0 |
| 1 | 2 | 7 | 1 | 1 | 1 | 1 | 0 |
| 2 | 2 | 7 | 1 | 0 | 0 | 0 | 0 |

Screening passes stayed at 3 and full candidate-routing attempts stayed at 2 across these iterations. The extra initial signature follows startup ground preparation; geometry required only 14 unique coordinate/site distance calculations. A separate two-site case with no eligible passengers completed normally without adding false alternatives.

Performance comparison:

| Measurement | Before/recomputed | After/cached |
| --- | --- | --- |
| Origin/destination distance retrieval for 71,126 trips and nine layouts | 0.128 s direct recomputation | 0.058 s matrix lookup |
| Reusing the nine unchanged layout screens | New eligibility computation required without a layout cache | 0.000013 s cached retrieval |
| Equivalent Java feeder-routing fixture | 4 feeder calls | 3 feeder calls, identical route signature |

The population benchmark included all 18,659 passengers and all 71,126 passenger main-activity trips in the supplied stage-01 input. Reading XML and building both matrices for all 100 candidate sites took 1.344 s. Lookup timing excludes that initial cost. Feeder call reduction is 25%; its sub-millisecond timing is a microbenchmark, not a production network-routing speed claim. Across the nine supplied layouts, 1,644–1,978 passengers passed the optimistic corrected screen on the fixed initial population. Those are candidates, not confirmed routes or adoption, and must not be compared directly with users accumulated across 50 iterations.

Evidence files are `validation/aam-choice-tests.log`, `validation/aam-choice-python-tests.log`, `validation/aam-choice-screening-benchmark.json` and `validation/aam-choice-small-verification.json`. The integrated positive case is `run-output/aam-choice-small-verified-20261010`; its detailed layout candidates and per-iteration funnels are retained. The benchmark and tests are reproducible through the new benchmark module, the existing launcher `-Test`, and Python unittest modules listed above. Python tests used a temporary directory inside the workspace because the desktop sandbox could not write to its default temporary directory.

Remaining limitations and expected coverage:

- Screening coverage is all passengers/all daily trips, including non-home trips. Corrected genuine coverage should improve for overlooked trips and newly feasible layouts; reported AAM counts can decrease because false markers and out-of-radius destinations are now excluded.
- The proxy and best-two routing budget can miss a routable lower-ranked trip. Such trips remain unresolved candidate records; screened eligibility is not proof that every possible network-feasible itinerary has been exhausted.
- Home-based car/bike tours are supported. Other private-vehicle chains, mixed private modes, non-home parking and relocation are conservatively excluded rather than inventing vehicle positions. Startup's independent ride alternative converts private legs in the copied comparison plan; the original selected private plan is retained.
- Java caches are scenario/request scoped. A new MATSim JVM rebuilds its active-layout geometry cache. Python precomputes all candidate-site matrices and reuses them within a screening/optimizer invocation; no disk-persisted Java matrix format was introduced.
- The paired-tour budget is counted in alternatives, so two paired candidates can require four trip routes. Network/cache errors caused by missing feeder configuration retain explicit fatal diagnostics; ordinary infeasibility becomes unresolved intent.
- The small network validates mechanics, not calibrated regional demand or production wall-clock speed. Full plotting was not exercised because the bundled Python lacks matplotlib; pure analysis classification and event-count helpers were tested.
- Service-window routing is a feasibility prediction. Actual dispatch capacity and traffic can still produce rejection; operational adoption remains the event-based funnel. No 50-iteration production results or coverage gains are claimed.
