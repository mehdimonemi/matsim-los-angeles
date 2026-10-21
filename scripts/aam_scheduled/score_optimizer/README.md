# Scheduled-AAM four-method vertiport comparison

This is the fixed-timetable counterpart to `scripts/aam/score_optimizer`. It runs the same four
one-swap neighborhoods independently: `global` (900 moves), `all-vp-k10` (100), `one-vp-k10`
(10), and adaptive K=5/10/20/global expansion.

At each stage, the objective starts with the selected-plan score of every passenger. For existing
scheduled-AAM users it estimates the observed AAM plan under the candidate layout. For passengers
with no AAM plan, it derives candidate trips from their selected ground plan's activity locations,
uses the selected score as the anchor, and estimates ground-trip disutility from routed leg times,
distances, and mode coefficients. In both cases it adds only positive gains over current ground
scores, so ground remains the outside option. For new users, gains are calculated per eligible
trip, allowing a feasible AAM trip to count even if another trip is not serviceable. The model adjusts access, egress, timetable wait, flight time, and
the $30 + $2/air-mile passenger fare using the fixed 07:00-19:00 departures, 30-minute headways,
30-minute maximum wait, 100 mph flight time, and income-sensitive ground cost. Like the Java router,
the proxy evaluates
combinations of the three nearest origin- and destination-side active vertiports, applies the
five-mile origin screen, and uses the three-mile minimum trip threshold. Network-routed multimodal
feeder costs remain anchored in the observed MATSim score; geometric changes are an optimization
proxy. A no-improvement stage keeps its layout and the method continues to the next stage, where
it uses the newly observed traveler scores.

At every stage startup, the model also guarantees one separate scheduled-AAM plan for each person
with a qualifying trip that starts within five miles of an active vertiport. The scheduled flight
still operates inside the ordinary transit system; the guarantee ensures the alternative enters
the person's plan choice set and is not merely left to stochastic innovation.

Each method starts from `scenarios/aam-scheduled/vertiports.csv` and the common 100-site analytical
candidate inventory. It runs eight five-iteration search stages and then ten fixed-layout,
innovation-free iterations: exactly 50 MATSim iterations per method with a 20% convergence tail.
The suite first runs one shared, one-iteration route preparation at the initial layout. It seeds and
routes the scheduled-AAM choice set once, then all four methods start from that same route-complete
population. This avoids repeating the expensive baseline ground and scheduled-AAM routing pass.
Each method still performs its own optimizer search, and layout-specific scheduled flights are
rerouted by MATSim when a method changes the active sites. Outputs are isolated under
`run-output/aam-scheduled-vertiport-comparison-v11/<method>`.

From the repository root:

```powershell
.\scripts\aam-scheduled\run_vertiport_comparison.ps1
```

To run one method:

```powershell
.\scripts\aam-scheduled\run_vertiport_comparison.ps1 -Method adaptive
```

Completed methods are skipped when the suite is rerun. Resume validates saved input fingerprints,
reuses complete search stages, reconstructs missing optimizer artifacts, and retries incomplete
stages in new folders. Compressed population XML is checked before a saved stage is reused, so a
power-loss-truncated output is rerun. The suite writes `comparison.csv` and `comparison.json` after
every completed method.
