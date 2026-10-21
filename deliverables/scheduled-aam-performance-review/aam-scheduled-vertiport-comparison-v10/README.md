# Scheduled AAM optimizer performance review

This folder reproduces the labeled graph set for
`run-output/aam-scheduled-vertiport-comparison-v10`.

From the repository root, run:

```powershell
$env:PYTHONPATH='C:\Matsim\matsim-los-angeles\target\analysis-python'
& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' deliverables/scheduled-aam-performance-review/aam-scheduled-vertiport-comparison-v10/build_scheduled_review.py
& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' deliverables/scheduled-aam-performance-review/aam-scheduled-vertiport-comparison-v10/render_scheduled_graphs.py
```

The scheduled model has no DRT fare, so graph 07 explicitly marks fare as not applicable.
Aircraft occupancy and productivity use every fixed 07:00–19:00 scheduled departure,
including empty flights.

Graphs 15 and 16 compare full-day versus 07:00–19:00 trip-departure AAM share
and destination-purpose composition. The share denominator is all completed
person trips in the corresponding departure-time scope; the numerator is trips
with an actual completed scheduled-AAM transit leg.
