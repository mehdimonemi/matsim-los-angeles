# AAM vertiport location workflow

Location search and the final MATSim run are intentionally separate.

1. Generate 100 analytical candidate sites from the original population's
   activity-origin density. Seeded k-means++ makes the result reproducible and
   each demand center is snapped to an observed activity coordinate. The ten
   current sites are retained in the candidate set as the starting layout:

   ```powershell
   python -B scripts/aam/generate_vertiport_candidates.py `
     --population run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz
   ```

   These are analytical demand candidates, not proof of physical, zoning, or
   aviation feasibility. Replace or filter them before final site approval if
   a feasibility-screened candidate inventory is available.
2. Run the external one-swap search:

   ```powershell
   powershell.exe -ExecutionPolicy Bypass -File scripts/aam/optimize_aam_vertiports.ps1 `
     -Candidates scenarios/aam/vertiport-candidates-100.csv `
     -MaxSwaps 10
   ```

   It accepts only swaps that lower the demand-weighted approximate AAM
   generalized cost. It writes the frozen ten-site layout atomically to
   `scenarios/aam/active-vertiports.csv` and writes the complete search history
   and file hash beside it as `active-vertiports.csv.optimization.json`.
An improving swap is rejected if it would move any trip origin that was
eligible under the initial layout outside the five-mile access radius. This
keeps the previously guaranteed AAM-alternative population covered.
3. Review the audit and then run the production model normally:

   ```powershell
   powershell.exe -ExecutionPolicy Bypass -File scripts/aam/run_aam_v5.ps1 -Memory 18g
   ```

The production runner validates and reads the frozen CSV once before MATSim is
started, copies it into the run's input snapshot, and never changes locations
during iterations. It also caps the innovation phase according to
`minimumInnovationFreeFraction`. Because `lastIteration=50` represents MATSim
iterations 0-50, the shipped value of 0.20 reserves iterations 40-50: 11 of 51
iterations, a true minimum of 20% after integer rounding.

The optimizer objective is a screening proxy built from population trip
coordinates, five-mile origin coverage, ground access/egress time, 100 mph
flight time, and the configured distance fare. Final site approval should still
consider physical feasibility, and competing layouts can be confirmed with
separate MATSim runs before declaring the production layout final.

## Adaptive MATSim-scored search

For location decisions that respond to agents' replanning and network
interaction, use the staged coordinator:

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts/aam/run_adaptive_vertiport_optimization.ps1 `
  -Memory 18g -BootstrapIterations 5 -Epochs 47 -IterationsPerEpoch 5 -FinalIterations 60
```

Each epoch starts two MATSim branches from the same population and wait-history
checkpoint. The baseline retains the current ten sites; the candidate branch
changes exactly one. The geometric proxy ranks proposals but does not veto a
swap; MATSim's aggregate AAM-plan scores make the acceptance decision. Each branch runs
five iterations with the same random seed, allowing AAM alternatives and their
network interactions to be evaluated before the decision. Every location epoch
then stops the controller, rebuilds the air network, and starts a new one.

Before the first location epoch, a five-iteration bootstrap on the original
layout creates and protects AAM alternatives for all initially eligible agents.
Those typed plans survive every later layout change and are rerouted through
the proposed network; newly eligible agents can also receive alternatives.
Both branches must first contain at least 100 scored AAM users. A valid
candidate is accepted when at least three of these five rules pass:

1. The sum of best AAM-plan scores across all AAM users increases.
2. The average best AAM-plan score across all AAM users increases.
3. The mean best-AAM score change among users present in both branches is positive.
4. More than half of the paired AAM users receive a higher score.
5. The number of scored AAM users is retained or increased.

The two branch cohorts do not need to contain the same users. Every rule and
the final vote count are stored in the audit for each epoch. The default score
margins are zero and the paired-majority threshold is strictly greater than
50%; command-line parameters can require larger improvements.

Before every network restart, the coordinator clears all plan scores and
collapses old AAM routes and interaction activities to unrouted AAM legs. The
new controller rebuilds and reroutes them against the proposed air network.
Observed wait priors carry across accepted stages for unchanged port pairs. A
pair involving a never-observed candidate receives the configured 120-second
fallback until MATSim observes pickups there. Each branch restarts its aircraft
fleet; QSim vehicle state is not transferred across different networks.

After the location epochs, the accepted layout is held fixed for sixty final
iterations with every innovation strategy disabled. The accepted trajectory is
5 bootstrap + 47×5 adaptive + 60 convergence = 300 iterations; paired branch
evaluation means 535 MATSim iterations are actually executed. Only after that final stage
succeeds is `scenarios/aam/active-vertiports.csv` replaced. The full decisions,
score comparisons, paths, and final layout hash are written to
`run-output/aam-adaptive-location-search/adaptive-search.json`.
