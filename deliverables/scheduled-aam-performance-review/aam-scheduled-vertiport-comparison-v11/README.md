# Scheduled AAM optimizer performance review

This folder reproduces the labeled graph set for
`run-output/aam-scheduled-vertiport-comparison-v11`.

From the repository root, run:

```powershell
$env:PYTHONPATH='C:\Matsim\matsim-los-angeles\target\analysis-python'
& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' deliverables/scheduled-aam-performance-review/aam-scheduled-vertiport-comparison-v11/build_scheduled_review.py
& 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' deliverables/scheduled-aam-performance-review/aam-scheduled-vertiport-comparison-v11/render_scheduled_graphs.py
```

The scheduled model has no DRT fare, so graph 07 explicitly marks fare as not applicable.
Aircraft occupancy and productivity use every fixed 07:00–19:00 scheduled departure,
including empty flights.

Graphs 15 and 16 compare full-day versus 07:00–19:00 trip-departure AAM share
and destination-purpose composition. The share denominator is all completed
person trips in the corresponding departure-time scope; the numerator is trips
with an actual completed scheduled-AAM transit leg.

## Data flow

`build_scheduled_review.py` reads each optimizer's `result.json`, initial and
final layout CSVs, and the final-convergence MATSim output files. Trip adoption,
time-window shares, and destination purposes come from `output_trips.csv.gz`
joined to actual scheduled-AAM legs in `output_legs.csv.gz`. Income comes from
`output_persons.csv.gz`. Scheduled departure supply and route distance come from
`output_transitSchedule.xml.gz` and `output_network.xml.gz`.

The build step writes auditable metric CSV files and `summary.json`.
`render_scheduled_graphs.py` reads `summary.json` and creates the seven overview
PNGs plus the sixteen numbered PNGs under `graphs/`.
