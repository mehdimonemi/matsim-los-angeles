# Score-based vertiport optimizer comparison

This package is separate from the earlier generalized-minutes and paired-branch
optimizers. It implements the four one-swap neighborhoods from the proposed
model while keeping the objective identical across methods.

## Objective

At each stage, the optimizer sums the selected scores for all passenger
travelers as the baseline. For travelers with a scored AAM plan, it predicts
that plan under each candidate layout. For travelers with no AAM plan, it
derives candidate trips from selected ground-plan activity locations, uses the
observed plan score as the anchor, and estimates ground-trip disutility from
routed times, distances and mode coefficients. For either group, it adds a gain
only when predicted AAM scores exceed the current selected-plan score. The
objective is the full passenger score baseline plus those positive gains.
MATSim runs the next stage with the best one-swap layout, then the optimizer
uses that stage's newly selected-plan scores. A no-improvement stage keeps its
layout and the experiment continues to the next stage.

For a traveler with an existing AAM alternative, the contribution is the
better of the current selected-plan score and the estimated AAM-plan score.
For a traveler without one, each qualifying trip contributes a gain only when
its estimated AAM disutility is lower than that trip's ground disutility; the
gains are added to the current whole-plan score. Ground-plan-derived AAM
scores are estimates, not MATSim-observed AAM plan scores; the next stage
supplies the observed choice and score. AAM adoption is not forced.

The estimate uses the same LA scoring coefficients and person-specific
`marginalUtilityOfMoney` used by the Java AAM router. Origin-destination/time-bin
waits already observed by MATSim are reused, while every previously unseen pair
gets the common 120-second fallback until QSim evaluates it. The experiment
uses a $30 base fare plus $2/mile.
The observed score anchor carries forward congestion and interaction effects
already experienced in MATSim. The next five-iteration stage evaluates the
proposed swap and supplies the next score anchor and current AAM-user set.

There is no site-separation constraint. Trips shorter than three miles are
excluded from optimization, and the existing Java eligibility rule prevents
those AAM alternatives from entering QSim. The optimizer does not impose a five-mile facility constraint;
the existing Java rule separately guarantees an AAM alternative to agents whose
origins are within five miles of an active vertiport.

## Four methods

- `global`: all 10 active x 90 inactive swaps (900 evaluations).
- `all-vp-k10`: 10 nearest inactive candidates for every active vertiport (100).
- `one-vp-k10`: identify the active site with the smallest removal loss, then
  evaluate its 10 nearest inactive candidates (10).
- `adaptive`: evaluate all active sites with K=5, then expand to 10, 20, and
  global only while no improving swap is found.

Every accepted update changes at most one active vertiport.
For tractable multimodal routing, each trip evaluates its three nearest active
origin-side and three nearest active destination-side vertiports. The score
optimizer applies the identical nearest-three restriction. This does not change
the four facility-swap neighborhoods: Global still evaluates all 900 possible
active/inactive site replacements.

## Fair 50-iteration experiment

Each method starts independently from the same population and same 10-site
layout. It runs eight 5-iteration search stages (40 iterations), optimizing
after each stage, followed by 10 iterations with the final layout frozen and
innovation disabled. Thus each method receives exactly 50 MATSim iterations,
including a common 20% convergence tail.

The suite compiles Java once before timing any method. Compilation time is not
charged to Global or any other method, so the reported MATSim and wall-clock
runtimes are comparable.

The comparison permits an 18 GB maximum Java heap because the first
`PersonPrepareForSim` pass has been observed to require about 15 GB. This is a
maximum, not a reservation: the committed heap grows as needed. Each stage
redirects the verbose nested Java/PowerShell console stream to
`<stage>.console.log`; this prevents a full or detached terminal output pipe
from suspending Java while MATSim's normal `logfile.log` continues to provide
simulation diagnostics.

Run all four sequentially from the repository root:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\aam\score_optimizer\run_comparison.ps1
```

Run only one method:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\aam\score_optimizer\run_comparison.ps1 -Method adaptive
```

Do not use `-SkipCompile` on a fresh checkout. It is intended only when the Java
sources have already been compiled. Outputs are isolated under
`run-output/aam-score-optimizer-comparison-v2/<method>`. The stopped exhaustive-routing
run remains untouched under the older output root. The suite writes
`comparison.csv` and `comparison.json` after each completed method, so completed
results survive a later failure. The comparison separates actual selected-plan
AAM users from agents that merely retain a scored AAM alternative, and reports
both AAM scores and whole-population selected/best-plan scores alongside runtime.
Rerunning the suite skips methods with a completed `result.json`; a partial
method directory is never overwritten and must be diagnosed or replaced by a
new output root.
