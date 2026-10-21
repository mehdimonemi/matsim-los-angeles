# DRT startup performance review — 2026-10-12 16:04 run

## Finding

The four-optimizer run `drt-four-optimizers-choice-fixed-20261012-160431` started Global stage 01 at 16:04:40 Eastern. Its suite manifest confirms it used `drt-exploration-fast3-20261012`: three routed trip/tour choices per generation pass, 3 nearest candidate vertiports per endpoint, three protected AAM alternatives, and 07:00–19:00 service. At the 16:42:01 log sample, startup had not emitted either `Guaranteed ... genuine routed choices` or `### ITERATION 0 BEGINS`; the console had emitted about 7,500 repeated INFO lines saying an AAM route fell back to ground. The run was progressing, but remained in initial alternative generation roughly 38 minutes after launch.

This confirms the previous fix did not bound the expensive inner search. Each of the three ranked trip/tour choices still searched the full 3-by-3 origin/destination port grid, and for each pair it could route all combinations of three access and three egress feeder modes. The maximum theoretical search per candidate was therefore 9 port pairs x 9 feeder-mode combinations, before considering repeated candidate generation for protected alternatives. The prior run's completed startup diagnostics recorded 216,228 candidate routing attempts and 11,981,443 cumulative routing milliseconds, supporting route search as the primary cost.

The current process reported 10.9–11.4 GB used within 11.4 GB of committed JVM heap, with the JVM configured for an 18 GB heap. The committed heap grew as needed and no OutOfMemoryError was recorded, so these samples do not establish memory exhaustion as the cause. They do show a high live heap while generating alternatives.

## Change

New config `maximumCandidateVertiportPairs=3` limits each trip route to the three best feasible pairs among the nearest-three origin and destination ports. Pairs are ranked with a cheap straight-line proxy: access distance + flight distance + egress distance. The full travel-cost comparison still selects among these routed pairs. The repetitive per-route infeasibility line is now DEBUG instead of INFO, avoiding synchronous console/file writes for every failed pair search.

The existing per-pass candidate cap remains 3 and the model retains up to three protected alternatives, all ten active ports, 30-mile feeder catchments, full initial iteration-zero exposure, and 07:00–19:00 service. This caps the port-pair component from nine to three combinations per candidate (up to a 3x reduction there); full wall-time savings have not yet been measured.

## Deliverable and limits

The new package is `run-inputs/drt-exploration-fast3-pairs3-20261012`. The current 16:04 run loaded the older fast3 package at startup, so it cannot receive these code/configuration changes without restarting. I left it running. The new Java sources compile, and the frozen package passes static validation for 19,123 simulated people, 18,659 passenger agents, ten initial sites, and 100 candidate sites. No MATSim experiment was launched for validation.

## Iteration 5 stall follow-up

The later run `drt-four-optimizers-choice-fixed-20261012-164421` used the previous `fast3-pairs3` package. It finished MATSim iterations 0–3 normally: iteration totals were 0:59, 4:35, 4:17, and 3:58. It entered MATSim iteration 4 (the fifth, zero-based iteration) at 18:28:07 Eastern. By 21:41 Eastern it had not logged the end of replanning or the start of mobsim. The iteration stopwatch still ended at iteration 3. The only continuing log activity was the one-minute memory monitor; the last non-monitor lines were at iteration 4 startup. No exception or OutOfMemoryError was recorded. Heap use cycled from about 12.2 to 16.3 GB of 18.2 GB committed; this is high but does not by itself prove memory exhaustion.

A concrete concurrency bottleneck is in `AamCandidateScreen`: `screen()` was synchronized on the single scenario-level instance for the entire per-plan screen, including trip extraction, port-distance loops, and candidate scoring. MATSim invokes plan strategies concurrently, so unrelated travelers serialized behind that monitor. The iteration-3 diagnostics show 29,592 screen passes and 1,583,930 cumulative screening milliseconds, alongside 96,329 full candidate routing attempts. This lock can explain poor parallel scaling and long tail latency. The prior run does not expose a worker stack, so I cannot prove this lock alone held iteration 4 for the entire interval.

The new runtime keeps screens, distance rows, and counters thread-safe while locking only the same person's screen operation. Distinct travelers can now screen concurrently. The new package `drt-exploration-parallel-screen-20261012` compiled and passed static package validation; it preserves the three-port-pair route cap, 07:00–19:00 service, ten active ports, and iteration-zero exposure. The existing process already loaded the old classes and cannot receive this change in place.

## Full-population startup bottleneck and follow-up fix

The interrupted run `drt-four-optimizers-choice-fixed-20261012-224935` did not reach iteration 0. The Windows System log records a system-initiated reboot at 23:18, so its `Java failed` wrapper message was a consequence of the reboot; there was no Java exception in its console log. Its AAM seeding counter reached 2,048, but that was not the only startup cost.

Inspection of the next run's exact stage input (`stage-01-input.xml.gz`) found 19,123 plans and no `<route>` on any input leg: 43,376 car, 19,319 ride, 4,819 walk, 1,377 PT, 873 bike, 870 school-bus, 492 taxi, and 464 freight legs. A live `jcmd Thread.print` sampled on 2026-10-12 showed the main thread in `AamFeederPolicy.routeConvertedGroundTrips` → `SwissRailRaptorCore.calcLeastCostRoute`. Startup had been routing those missing ground legs serially before alternative generation. A separate live dump also caught repeated score-config lookups in `AamCandidateScreen`'s innermost port-pair loop.

The runtime now caches score coefficients once per screen and performs each person's normalization, missing-route repair, and AAM alternative seeding in the same two bounded person workers. This removes the serial pass over roughly 70,000 unrouted ground legs and avoids constructing a separate throwaway router before the two worker routers. Startup still keeps three protected alternatives, 3 nearest candidate/parking vertiports, the 3-pair cap, ten active sites, zero base fare, 30-mile catchments, 07:00–19:00 service, and iteration-0 exploration. Startup stops routing additional trip candidates for a protected plan after a feasible trip is found, while retaining the configured runtime replanning candidate search.

The final package `run-inputs/drt-exploration-parallel-routing-20261012` passes static validation for 19,123 simulated people, 18,659 objective passengers, and ten initial sites. All 120 Java regression checks and 19 optimizer unit tests pass. The all-method run `run-output/drt-four-optimizers-choice-fixed-20261012-234522` started Global stage 01 at 23:45:29 Eastern. At 23:48:18, the parallel startup counter reached 1,024 people; iteration 0 had not started at that sample. This is a meaningful improvement over the prior serial pass, but one sample is insufficient to claim a completed startup-time benchmark. The new run remained active at the last check.
