# AAM score optimizer comparison, 07:00–19:00

This folder contains analysis files and graphs generated from the completed
`run-output/aam-score-optimizer-comparison-0700-1900` simulations. Those runs
use `serviceStartTime=25200` and `serviceEndTime=68400`.

From the repository root, recreate the metrics and figures with:

```powershell
& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  .\deliverables\drt-performance-review\aam-score-optimizer-comparison-0700-1900\build_drt_review.py

$env:PYTHONPATH="$PWD\target\analysis-python"
& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  .\deliverables\drt-performance-review\aam-score-optimizer-comparison-0700-1900\render_drt_graphs.py
```

The first command extracts CSV and JSON metrics from the four optimizer output
folders. The second command creates seven overview figures and sixteen separate
PNG graphs under `graphs/`.

Graphs 15 and 16 compare full-day versus 07:00–19:00 trip-departure AAM share
and destination-purpose composition. The share denominator is all completed
person trips in the corresponding departure-time scope; the numerator is trips
with an actual completed `aam_drt` leg.
