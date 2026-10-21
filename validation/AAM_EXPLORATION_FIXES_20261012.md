# AAM exploration changes and validation

Prepared package: `C:/Matsim/matsim-los-angeles/run-inputs/drt-exploration-zero-base-0719-20261012`.
This supersedes the intermediate `drt-exploration-zero-base-20261011` draft, which predates the iteration-zero dispatcher fix. Existing production output directories were not changed. No new regional simulation was launched.

## Effective settings for the new DRT package

| Setting | Previous run | New package |
|---|---:|---:|
| Active vertiports | 10 | 10 |
| Base fare | $30 | $0 |
| Distance fare | $2/air mile | $2/air mile |
| Access and egress catchments | 5 miles each | 30 miles each |
| Minimum original trip length | 3 miles | 0 |
| Candidate ports | 3 per end | 3 nearest per end |
| Candidate trip/tour routing budget | 2 | 3 ranked choices per generation pass |
| Protected AAM alternatives | 1 | Up to 3 distinct trip choices |
| AAM service | 07:00–19:00 | 07:00–19:00 |
| Walking limits | 1,000 m and 1,200 s per end | Unchanged |
| Fleet | 100 aircraft | Unchanged |
| QSim horizon | 36 hours | Unchanged |
| AAM mode constant | 0 | 0 |
| Initial exploration | Ground selected at iteration 0 | Every passenger with a generated feasible AAM alternative initially tries their best predicted AAM alternative |

The wide radius permits exploration; it does not make a 30-mile feeder free or desirable. Actual feeder routing, travel costs, walking limits, distinct-port requirements, the service window, and aircraft dispatch still apply. With the same initial ten ports, removing the original-trip minimum and widening catchments to 30 miles gives **13,228 of 18,659 passengers (70.89%) at least one geometrically eligible trip**. This calculation is before service-time, road-routing, private-vehicle, and dispatch constraints; it is not a claim that 71% will fly. Reproduce the geometry calculation with `validation/measure_aam_coverage.py`.

## Alternative generation and private vehicles

Candidate ordering now compares approximate AAM cost with the replaced ground trip/tour rather than only comparing absolute AAM cost. Within the routing budget, it evaluates feasible alternatives and retains the lowest generalized daily travel cost instead of stopping after the first success. The final comparison includes other changed legs and once-per-day mode constants. This is a travel-cost estimate, not an experienced activity/parking/stuck score; MATSim remains responsible for actual plan scoring.

Private car/bike parking tours consider admissible home-side ports, not only the nearest. A chosen parking-port ID is used for both outbound access and return retrieval. The private vehicle is not available on the destination side. Intermediate private movements in that tour are replaced with passenger ground travel, and unrelated later tours remain intact.

A new optional **car-at-home tour** allows a traveler to leave the car at home, use non-car feeders, take a single AAM trip, and complete the rest of that home tour by ground passenger transport. All private-car legs in the affected tour are replaced, preventing vehicle teleportation. This permits an AAM outbound trip even when the return is after AAM closing. It does not relax the requirement to retrieve a car that was actually driven to a vertiport.

Startup seeds alternatives from the best retained ground plan, even when AAM is currently selected. Multiple protected alternatives target different trip indices. They are not guaranteed to cover every possible tour, feeder mode combination, or schedule. Broader routing will take longer than the old two-candidate pipeline; regional startup time has not been benchmarked.

## Iteration-zero exploration and the dispatcher bug

The `initialExplorationFraction` setting is 1.0 in the new profile. Only passengers with genuine routed AAM alternatives participate. A persistent person attribute records that initial exposure occurred; restarts do not repeatedly force the same people onto AAM. After initial exposure, normal score-based selection applies. Initial trials must be reported separately from stable voluntary adoption.

The first integration test exposed a previously hidden MATSim 13 API mismatch: **`DrtRoute.travelTime` is the maximum permitted request duration**, although the custom AAM router had populated it with expected flight-plus-wait time. MATSim's request creator uses that field to set the hard arrival deadline. Newly constructed iteration-zero routes could therefore be rejected even with idle aircraft; later selected plans may have been corrected by MATSim's replanning route updater.

The custom router now writes `maxTravelTimeAlpha * directRideTime + maxTravelTimeBeta` into the DRT route, reading the effective modal settings. Expected flight-plus-wait time remains on the leg for planning. This matches the locally installed MATSim 13 `DrtRouteCreator` and `DrtRequestCreator` bytecode semantics.

Controlled smoke result on the same two-person synthetic fixture:

- Before this correction: iteration 0 submitted two requests; both were rejected.
- After correction: iteration 0 completed **two rides, zero rejections, 121-second mean wait**.
- This establishes working initial exploration and dispatch. It does not establish a regional adoption gain; in this short fixture, iteration 1 selected ground plans.

## Restart learning and convergence

The new production path enables `preserveLearning`:

- **Identical layout:** preserve routes, scores, plan selection, and exploration history.
- **Changed layout:** retain ground plans and their learned scores; clear AAM scores and replace layout-specific chains with reroutable AAM intent while retaining tour metadata. Startup reroutes that intent rather than replacing all AAM alternatives with generic rides. Invalid private tours still fall back through the physical-feasibility gate.
- Legacy sanitation remains available for callers that deliberately request full invalidation; the updated DRT runner uses learning preservation.

The small checkpoint test preserves all six plans without clearing any score on an unchanged layout. On a changed layout it retains four AAM intents, clears the two previously scored AAM alternatives, and preserves ground scores. A real changed-intent startup rebuilt four genuine air alternatives with zero marker-only or fallback plans, and did not re-force initial exploration. A real unchanged-layout restart also completed successfully.

Eight five-iteration learning stages remain. New packages request at least **30 fixed-layout tail iterations**, extending in ten-iteration blocks up to **100 tail iterations** if necessary. Stability requires both the mean executed score and mean completed air rides to stabilize across two consecutive five-iteration windows (absolute tolerances 0.1 score points and one ride). Missing/nonfinite statistics never imply convergence. The result explicitly distinguishes observed tail stability from budget exhaustion, and does not claim a global equilibrium. All methods use the same criteria, though realized iteration budgets can differ.

Local controller iteration numbering and random streams still restart with each Java process; this change preserves behavioral state, not a bitwise-identical continuation of one uninterrupted controller. The analytical layout optimizer remains an approximate predicted-score model and does not fully reproduce the Java tour/parking search. Regional comparisons should report that limitation and the actual convergence budget used.

## Parking cost and positive AAM utility

**Parking can enter car scores already.** `RunLosAngelesScenario.prepareControler` installs `ParkingCostModule`. It reads the road-link attributes `oneHourPCost`, `extraHourPCost`, `dailyPCost`, and `maxDailyPCost`, computes duration-based charges with caps, and emits negative money events. The income-dependent money scorer converts those events into utility losses. Home parking is excluded by the handler; missing/zero link prices produce no charge. The car's $15.47 daily monetary constant is a separate configured mode cost, not proof of an explicit parking charge.

There is no newly invented vertiport parking tariff in this change. The inherited parking handler tracks vehicle entry/exit events generically; an exact audit of how AAM/taxi transfers affect parking-duration bookkeeping remains advisable before claiming precise vertiport parking costs. The candidate ranking does not include a full prediction of parking events; experienced scoring does.

**A positive AAM mode constant can be appropriate only if supported by calibration.** It represents preference not already explained by time, fare, reliability, and access. It should not be added just to make demand increase, and a positive marginal utility of travel time would reward longer flights. The new profile keeps the constant at zero and improves access to choices. A later calibrated constant can represent measured comfort or preference. [MATSim scoring calibration guidance](https://www.matsim.org/files/book/partOne-latest.pdf).

## Validation and launch

- **118 Java regression checks passed**, including candidate comparison, initial exposure, return-car continuity, car-at-home late returns, dispatcher time allowance, and real DRT pickup/dropoff checks.
- Launcher adaptive check plus **19 Python optimizer/population tests passed**.
- Targeted optimizer/population/protocol/convergence run: **29 tests passed** (overlaps the launcher subset).
- AAM repair discovery suite: **32 tests passed**.
- Real two-person synthetic MATSim initial run and restart checks passed; `validation/aam-exploration-integration/verification.json` records the corrected iteration-zero dispatch and checkpoint metrics.
- New regional package passed static validation for **19,123 agents, 18,659 passenger agents, ten initial ports, and 100 candidate sites**. Static validation does not substitute for a regional run.

Relevant logs: `validation/aam-exploration-tests.log`, `validation/aam-exploration-python-tests.log`, `validation/aam-exploration-all-python-tests.log`, `validation/aam-exploration-dispatch-fixed.log`, and `validation/aam-exploration-package-final.log`.

To launch the prepared four-method experiment from the project directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam_repair/run_drt_optimizers.ps1 -PackageDirectory run-inputs/drt-exploration-zero-base-0719-20261012 -Run
```

This command has not been launched. Do not resume the old low-demand run with the new settings: use the new package and a new output directory to keep comparisons interpretable.

Latest revision restores 07:00–19:00 service and three nearest candidate ports per endpoint. Ten ports remain active. The generic OD shortlist shrinks from up to 100 to nine pairs per routing call; private-car parking variants still explore feasible parking sites. This reduces routing work and temporary cache pressure, but regional RAM savings have not been measured. The updated launcher tests passed (118 Java checks and 19 Python tests plus the adaptive check); the new frozen package passed static validation.

## Startup and replanning runtime fix

Profiling the first regional controller showed 216,228 full AAM routing attempts during initial alternative generation (about 11,981,443 cumulative routing milliseconds). Each call to create a protected alternative could route up to eight distinct trip/tour choices, and this search repeated up to three times per person. The package now caps each generation pass at the three highest-ranked choices, while retaining up to three protected AAM alternatives per eligible person and the initial exploration selection. Parking-tour options are also capped at the three nearest eligible vertiports. This should reduce repeated full routes substantially; exact wall-time savings need measurement in the next run.