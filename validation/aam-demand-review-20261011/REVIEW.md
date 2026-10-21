# AAM demand review — October 11, 2026 run

Run: `C:/Matsim/matsim-los-angeles/run-output/drt-four-optimizers-choice-fixed-20261011-122109`.
Read-only review of completed output snapshots, effective output configurations, and local implementation. No running simulation, input, configuration, or model source was changed. The companion `summary.json` and `*-plan-comparisons.json` contain the extracted calculations; `../review_current_aam_demand.py` reproduces them. Adaptive had completed stage 1 and was running stage 2 when inspected; its final result is unavailable in this review.

**Conclusion: yes, realized AAM demand is extremely low in the three completed methods. The strongest observed explanation is that retained AAM plans score much worse than ground alternatives. Geographic coverage and constrained choice generation limit the market before scoring; expensive fares, feeder penalties, and whole-day effects then suppress adoption. Repeated score resets and short stages complicate convergence and optimizer comparisons. This is a result of this model configuration, not yet a defensible estimate of real-world LA AAM demand.**

## 1. How low is it?

The simulation contains 19,123 agents: 18,659 passengers and 464 freight agents. Use passengers as the denominator for AAM user share. Requests are air legs, and one traveler can request more than one leg.

| Method | Completed users, stage 1 | Stage 8 | Final completed users | Passenger share | Final requests / rejected | Retained scored AAM users |
|---|---:|---:|---:|---:|---:|---:|
| Global | 318 | 169 | 5 | 0.0268% | 6 / 0 | 557 |
| All-VP-k10 | 318 | 282 | 8 | 0.0429% | 9 / 1 | 1,010 |
| One-VP-k10 | 318 | 241 | 3 | 0.0161% | 3 / 0 | 943 |
| Adaptive, incomplete | 318 | — | — | — | — | 833 at stage 1 |

These are final-iteration person counts, not cumulative users over 50 iterations, and not regional forecasts obtained by multiplying by a sample factor. The file names indicate a 0.1% population; representativeness and expansion weights need independent validation.

The decline is most visible in the fixed-choice tail. Global completed air rides by local tail iteration 0–9 are **0, 124, 161, 141, 161, 50, 12, 8, 7, 6**. All-VP has **0, 266, 265, 274, 267, 72, 18, 9, 8, 8**. One-VP ends **69, 21, 9, 6, 3** over iterations 5–9. Early counts therefore include the evaluation of newly unscored plans and are not stable voluntary adoption.

Sources: top-level `comparison.csv`; each method's stage decision JSON, final `drt_customer_stats_aam_drt.csv`, and output plans.

## 2. Direct evidence: AAM loses the plan-score comparison

For each passenger with both scored AAM and ground plans, compare the highest-scoring AAM plan with that same person's highest-scoring ground plan. Positive differences favor AAM.

| Method | Compared travelers | Median AAM minus ground score | Mean difference | AAM beats ground | Within 10 points of ground |
|---|---:|---:|---:|---:|---:|
| Global | 557 | -161.68 | -314.11 | 0 | 0 |
| All-VP-k10 | 1,010 | -178.26 | -341.36 | 1 | 5 |
| One-VP-k10 | 943 | -186.23 | -311.23 | 0 | 4 |

The effective selection parameters include ChangeExpBeta and BrainExpBeta=1. Large negative score gaps strongly disfavor AAM. The remaining 3–8 selected users need not have AAM as their best plan: a finite stochastic selection process can retain inferior choices temporarily.

These are whole-day plan scores, not a controlled comparison of an otherwise identical trip. Schedules, other modes, past experienced conditions, activity utility, and rejected trips can differ. This establishes that the current choice set is unattractive; it does not allocate the entire score gap to a single cause.

## 3. Fare and income sensitivity are powerful deterrents

The effective fare is $30 per AAM request plus $2 per air mile. A 10-mile flight costs $50 before feeders, and a paired return tour incurs two base fares. AAM has zero positive mode constant and -6 utility/hour travel disutility.

The LA scoring factory calculates money utility as `35363.89 / (household income / household size)`. In the actual passenger population its median is **2.207 utility/$**, its mean **4.340**, and its 90th percentile **7.697**. Thus a $50 fare alone costs about **110 utility points for the median money sensitivity**. The approximate opportunity value of saving 30 minutes at performing utility 9.84/hour is only 4.92 points. This is illustrative, not an exact activity-score calculation. The corresponding simple car-time/money ratio is about **$4.46/hour** at the median, which deserves calibration review for an AAM market.

The best retained AAM plans imply median daily air fares of $44.71, $40.51, and $45.59 for Global, All-VP, and One-VP. Their median estimated fare penalties are 105.12, 127.69, and 141.07 score points respectively. These are calculated from planned air-route distances and leg counts; actual fare events can differ if routes or execution differ.

**Static fare sensitivity:** add back 50% or 100% of the estimated fare penalty to the existing best AAM plan, holding all travel, schedules, and ground scores fixed:

| Method | AAM beats ground now | At half fare | At zero air fare |
|---|---:|---:|---:|
| Global | 0 | 0 | 14 |
| All-VP-k10 | 1 | 3 | 23 |
| One-VP-k10 | 0 | 1 | 30 |

Even after this zero-fare adjustment the median residual gaps are -24.05, -21.08, and -19.74 points. These calculations are diagnostics, **not rerun demand forecasts**: they do not regenerate routes, evaluate every alternative, update congestion, remove rejection penalties, or change selection. Nevertheless, fare alone cannot explain away the poor performance of most currently retained alternatives.

Check income units, household-size interpretation, population representativeness, and the intended value-of-time distribution. Do not arbitrarily cap income sensitivity or inflate AAM's constant simply to obtain a desired market share. MATSim's scoring calibration guidance connects time, money, and mode constants jointly: [MATSim book, chapter 14](https://www.matsim.org/files/book/partOne-latest.pdf).

## 4. Most trips never reach a usable AAM alternative

The common initial layout screens 71,126 trips. Of these, 31,829 fail the three-mile minimum, 25,394 fail access distance, 6,886 fail egress distance, and 3,033 map to the same vertiport. Only 3,984 are geometrically eligible and 3,861 pass the initial temporal screen: **5.43% of trips**. Only 1,954 passengers have a temporally eligible candidate: **10.47% of passengers**. Network routing and private-vehicle tour feasibility reduce this further.

Global's final startup screen is worse: 2,242 temporally eligible trips, 1,205 passengers with a candidate, and 557 genuinely routed AAM alternatives. That is approximately **3.15% of trips**, **6.46% of passengers screened eligible**, and **2.99% of passengers with a routed choice**. All-VP's final values are 4,277 trips, 1,970 passengers, and 1,010 routed alternatives.

Current limits are 10 active ports, five-mile access and egress radii, a three-mile original-trip minimum, service 07:00–19:00, and at most 1,000 m and 1,200 seconds of walking at each end. The simple temporal screen excludes relatively few trips, but that does not make the operating window unimportant: detailed routing and the requirement for feasible return tours impose additional restrictions.

The diagnostic reason counters represent the screening pipeline and may reflect updated/repeated candidate outcomes; they are not independent causal effects to add together. In particular `unresolvedCandidates` includes trips never routed because of earlier failures. It does not mean 70,000 otherwise eligible passengers were accidentally ignored.

## 5. Feeders and private-car tours impose additional costs

The actual scorer applies mode constants per leg. A `ride` leg contributes -12 points; two such feeder legs can therefore contribute -24 before time, distance, or air fare. Taxi feeders contribute -2.85 per leg and $0.0025/m of distance cost. Walking contributes -19.68/hour travel disutility in addition to lost activity time. Private-car use retains its once-per-day constants and distance costs.

At Global's final startup, only 13 of 1,024 attempted walk-access routes and 8 of 1,144 walk-egress routes pass the walking limits. These are route evaluations, not unique passengers. Consequently many alternatives rely on penalized ride/taxi feeders. Do not interpret the presence of zero-distance walk connectors in an AAM plan as evidence that the journey is actually walk-accessible.

The new paired-tour logic preserves private vehicle location: home-side access/egress uses the parked car or bike, both outbound and return AAM legs must be feasible, the home-side port is pinned to the nearest port, and intermediate private-vehicle movements are converted to ride. This is physically preferable to teleporting a car, but it restricts opportunities and can add fares and ride penalties. Only 52 of Global's 557 final alternatives are paired tours; the remainder are single-trip alternatives.

The earlier suspected blanket loss of cars is **not** sufficient to explain this run: only 55/557, 71/1,010, and 67/943 comparisons have a ground plan containing car and an AAM plan without car. The current implementation explicitly pairs private tours. Remaining car-availability and feeder constraints still deserve controlled tests.

Potential changes: introduce an explicitly calibrated AAM feeder mode if the current generic ride constants do not describe the intended service; offer plausible integrated shuttles or transit feeders; improve walkable port access; allow physically valid mixed-mode return tours. Keep vehicle-location conservation. Extending feeder radii alone may add expensive, slow alternatives without increasing adoption.

## 6. Choice generation can miss the alternatives with greatest benefit

`AamPlanStrategyModule` orders candidate trips by absolute estimated AAM cost (`c.proxy`, summed for a paired tour), tries at most two candidates, and stops at the first fully routed success. It does **not** rank opportunities by improvement over that traveler's ground trip or whole tour. With `protectedAlternatives=1`, a feasible but uncompetitive cheap/short flight can occupy the protected slot while a longer, more useful congestion-avoiding trip is never tried. Candidates use the three closest ports, and the private home-side port is fixed to the nearest.

This is a confirmed algorithmic limitation; the number of lost adopters is not measured here. It offers a more principled fix than merely increasing the innovation weight: rank by predicted whole-tour score gain against the matched ground alternative, enforce car/bike continuity, and retain a small diverse set of genuinely different high-benefit alternatives. Test candidate limits 2/5/10 and protected alternatives 1/2/3 on a fixed layout, reporting evaluated candidates, best score gaps, and runtime.

## 7. Stage restarts disrupt learning

`sanitize_population` unconditionally clears every copied plan score and collapses every AAM journey into a ground ride before the next stage. It receives a layout identifier but does not check equality to preserve unchanged-layout AAM plans. Startup then seeds new AAM alternatives from each person's selected source plan.

For Global's final tail this clears **97,468 scores** and invalidates **701 AAM plans**. This happens even for One-VP, which accepts **zero swaps**. The eight five-iteration stages therefore repeatedly rebuild and reevaluate choices rather than preserving a continuous 40-iteration learned state. The final tail again starts with zero AAM rides, despite being called convergence.

Fix the unchanged-layout path first: preserve valid routes, plan identity, and learned scores, and continue the iteration schedule. On changed layouts, invalidate affected routes explicitly; re-evaluate scores under new conditions without treating historical scores as current observations. Preserve candidate intent and ground comparators. Use the same restart policy across methods.

Ten tail iterations are insufficient evidence of equilibrium. Global's mean executed score still rises from 85.01 to 86.55 between the last two iterations; One-VP rides fall from six to three. A longer tail may lower counts further. Define convergence from several consecutive stable score and demand windows, then report a window average and variability. Repeated independent seeds are essential when outcomes are only a few people.

## 8. The optimizer is solving a different, approximate problem

The objective is the sum of each traveler's best feasible predicted ground-or-AAM score, not AAM ridership or geographic coverage. Ground is an outside option. It is entirely possible for a welfare-improving predicted swap to reduce AAM coverage. Global's screened passenger coverage drops from 1,954 initially to 1,205 finally despite eight accepted swaps.

The Python surrogate uses straight-line distances, fixed ground speed/circuity, approximate feeder costs, and observed wait priors. Its generic feeder calculation uses walk/ride/taxi rather than explicitly reproducing every Java private-car paired tour. It does not recreate full activity scheduling or the bounded alternative-generation process. Acceptance is based on predicted improvements only; the saved decisions explicitly contain no observed improvement or paired simulation validation. “Global” means the evaluated analytical swap neighborhood, not a global optimum of MATSim demand.

Improve surrogate agreement by using network/time-dependent feeder skims, matched tour alternatives, actual income and mode scoring, and comparable activity effects. First diagnose prediction error for proposals already evaluated in the run. If a future experiment permits additional simulations, validate a small shortlist under common demand and seeds. If ridership is the intended objective, define that explicitly and report its tradeoff with welfare, coverage, and operating cost.

## 9. Supply shortage is not the primary final bottleneck

Global's final six requests all board and complete; mean wait is 121 seconds, with zero rejection. It records 4,317,026 aircraft idle seconds against 1,534 drive-task seconds and 1,440 stop-dwell seconds. The configured fleet has 100 aircraft for a 12-hour window. This indicates extreme underuse, not an aggregate shortage. One-VP also has zero final rejection. All-VP has one rejection out of nine, which matters locally but cannot explain why almost all passengers choose ground.

Earlier Global stage 1 has 11 rejections out of 406 requests (2.7%) and mean boarded wait 283.5 seconds. Operational feasibility can damage individual plans, but these numbers do not support adding aircraft as the first fix. Investigate OD/time-specific rejects and dispatch constraints after the demand and choice-set issues.

## 10. Baseline road congestion needs a scaling audit

The selected input population is named 0.1%, but effective QSim flow and storage capacity factors are both 0.02 (2%): twenty times the nominal population fraction. This could make driving too uncongested and reduce AAM's time advantage. It is a **calibration question, not a proven configuration bug**: minimum capacities, transit supply, omitted/background demand, and the scenario's original calibration may justify non-proportional scaling. Compare modeled car time/speed distributions with the intended baseline before changing it. A capacity-factor change affects every mode and cannot be interpreted as an isolated AAM improvement.

## 11. Recommended experiment sequence

1. **Measurement and continuity:** finish the current comparison unchanged; archive these outputs. Add per-person matched ground/AAM score decomposition (fare events, feeder constants, distance cost, travel/wait, activity utility, stuck/rejected penalty), candidate-rank diagnostics, and unchanged-layout continuation. Acceptance: an unchanged-layout restart does not discard valid AAM choices or invent fresh learning; metrics distinguish selected output plans from actually executed journeys.
2. **Fixed-layout choice-set test:** compare current ranking with whole-tour benefit ranking; candidate caps 2/5/10 and one versus multiple diverse protected choices. Hold population, scoring, supply, and seeds fixed. Acceptance: measure improved best feasible alternatives and stable selected demand, not just more generated plans.
3. **Joint behavioral calibration:** verify household income units and target population; estimate or justify feeder constants and time/money sensitivity. Run fare pairs (30,2), (15,1), and (0,0) as diagnostics, with the current coefficients and with independently justified coefficients. Zero fare is a diagnostic boundary, not a recommended business fare.
4. **Coverage and operations:** test demand-benefit-based port layouts, 10/15/20 ports, more walk-accessible locations, and a longer service day (e.g. 06:00–22:00) while reporting newly feasible round trips. Check how much demand is added per site and aircraft, not only the raw count. Preserve physically feasible private-vehicle chains.
5. **Optimizer comparison:** only then rerun all methods with the same warmed-up population, scoring, seeds, continuation rules, and convergence criteria. Report mean and variability over the stable tail, traveler welfare, ridership, rejection, geographic coverage, and prediction error. Avoid ranking algorithms conclusively on final counts of 3, 5, and 8.

Priority: fix comparability and alternative quality first; calibrate economics second; expand physical coverage if the resulting feasible trips justify it. More fleet or more iterations alone will not remove the current large score disadvantage.

## Implementation references and limits

- `src/main/java/org/matsim/run/LosAngelesPlanScoringFunctionFactory.java`: income-sensitive money utility.
- `src/main/java/org/matsim/run/CharyparNagelLegScoringWithPersonSpecificMarginalUtilityOfMoney.java`: per-leg constants and daily constants.
- `src/main/java/org/matsim/run/aam/AamPlanStrategyModule.java`: candidate ranking and paired tours.
- `src/main/java/org/matsim/run/aam/AamMultimodalRoutingModule.java`: feeder options, port candidates, generalized cost and service feasibility.
- `src/main/java/org/matsim/run/aam/AamAlternativeGuarantee.java`: startup seeding.
- `scripts/aam/score_optimizer/population.py`: unconditional score/route sanitation.
- `scripts/aam_repair/fast_global.py`: eight five-iteration stages plus ten-iteration tail.
- `scripts/aam/score_optimizer/optimizer.py`: analytical objective and feeder approximations.

The active run uses frozen compiled classes. Behavioral/configuration conclusions above are supported by its saved output; code-level fixes reference the current local source and should be checked against the frozen build before editing a successor experiment. This review did not rerun MATSim, calibrate to external travel observations, or fully decompose event-level scores. It identifies strong measured explanations and specific testable limitations, not exact causal percentages for every mechanism.
