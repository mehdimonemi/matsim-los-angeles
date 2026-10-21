# DRT four-optimizer choice-fixed comparison

This folder contains analysis files and graphs generated from the completed
`run-output/drt-four-optimizers-choice-fixed-20261013-115020` simulations. These
runs use corrected plan-choice handling, a $0 base fare plus $2 per mile, and
DRT service from 07:00 to 19:00.

From the repository root, recreate the metrics and figures with:

```powershell
& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  .\deliverables\drt-performance-review\drt-four-optimizers-choice-fixed-20261013-115020\build_drt_review.py

$env:PYTHONPATH="$PWD\target\analysis-python"
& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  .\deliverables\drt-performance-review\drt-four-optimizers-choice-fixed-20261013-115020\render_drt_graphs.py

& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  .\deliverables\drt-performance-review\drt-four-optimizers-choice-fixed-20261013-115020\video\render_final_drt_flights.py
```

The first command extracts CSV and JSON metrics from the four optimizer output
folders. The second command creates seven overview figures and sixteen separate
PNG graphs under `graphs/`.

Graphs 15 and 16 compare full-day versus 07:00–19:00 trip-departure AAM share
and destination-purpose composition. The share denominator is all completed
person trips in the corresponding departure-time scope; the numerator is trips
with an actual completed `aam_drt` leg.

The movie renderer reads each method's final converged output recorded in
`result.json`, reconstructs actual aircraft movements from events, creates four
method-specific 07:00–19:00 movies, and combines them into a synchronized 2×2
comparison movie under `video/`.
