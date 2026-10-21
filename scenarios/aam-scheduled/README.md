# Scheduled AAM scenario

This scenario represents AAM as ordinary MATSim public transit. At startup the runner appends ten
vertiport stops, a direct route for every ordered vertiport pair, fixed departures, and four-seat
transit vehicles to the existing Los Angeles transit schedule.

It intentionally does not install DRT/DVRP modules, create requests, or dispatch aircraft. Explicit
scheduled-AAM alternatives use the same multimodal feeder-choice and vehicle-continuity rules as AAM
DRT, while ordinary PT/Raptor journeys can also discover the flights. Passenger aircraft legs retain
MATSim's `pt` mode. The transit route's transport mode and the
aircraft network mode are `aam`, which makes the scheduled flights identifiable in schedules and events.

Configuration is in `la-aam-scheduled.config.xml`; vertiport coordinates are in `vertiports.csv`.
Times and headways are seconds after midnight. The shipped service runs every 30 minutes from 07:00
through 19:00 on every directed pair at 100 mph.

`scheduled_aam` is the traveler-facing routing mode. Eligible trips are at least three miles and
begin within five miles of an active vertiport. The router jointly evaluates the three nearest
origin- and destination-side vertiports using income-sensitive generalized cost and real MATSim
ride, taxi, walk, bike, and appropriate car feeder routes. Car/bike alternatives are paired tours
that return the private vehicle to its home-side parking location. The strategy inserts those ground
routes and a timetable-valid `pt` passenger leg whose transit line is an AAM line. All returned legs
retain `scheduled_aam` as their routing mode, so analysis and
choice distinguish the whole journey from conventional PT. The aircraft leg also uses the
`scheduled_aam` scoring parameters while retaining physical mode `pt`, which is required for normal
waiting, boarding, capacity, and alighting behavior.

The source plan is retained, and every eligible traveler is guaranteed a separate AAM alternative.
For this guarantee only, car and bike trips in the cloned comparison plan are converted to passenger
ride, leaving the private vehicle at home and allowing complex tours to remain physically consistent.
Normal scheduled-AAM innovation continues to require paired outbound/return AAM for private-vehicle tours.
Additional innovation runs during the configured innovation portion; aircraft remain
fixed-route transit vehicles and are never dispatched as DRT. `scheduled_aam` must not be added to
`qsim.mainModes`.

From the repository root:

```powershell
.\scripts\aam-scheduled\run_scheduled_aam.ps1 -Test
.\scripts\aam-scheduled\run_scheduled_aam.ps1 -Validate -Memory 12g
.\scripts\aam-scheduled\run_scheduled_aam.ps1 -Memory 12g
```

The full run creates a timestamped directory under `run-output`. The `-Test` form only builds a tiny
in-memory scenario and checks the generated timetable, routes, network, and vehicles. `-Validate`
loads all LA inputs and adds the complete AAM service, but stops before creating a controller output.

## Four vertiport-change methods

The scheduled model has its own score-anchored implementation of the four DRT experiment
neighborhoods. It retains the same fair 50-iteration structure, but evaluates layouts with scheduled
departures and headway waiting rather than DRT dispatch waits and fares. Code and detailed assumptions
are isolated in `scripts/aam_scheduled/score_optimizer`; the PowerShell entry point remains with the
other scheduled-AAM scripts:

```powershell
.\scripts\aam-scheduled\run_vertiport_comparison.ps1
```

Results are isolated under `run-output/aam-scheduled-vertiport-comparison-v7`, with one directory for
each of `global`, `all-vp-k10`, `one-vp-k10`, and `adaptive`.

Analyze the newest completed run with:

```powershell
.\scripts\aam-scheduled\analyze_scheduled_aam.ps1
```

Pass `-RunDirectory` and optionally `-BaselineDirectory` to select specific runs. Scheduled AAM is
identified using its transit line IDs because passenger legs retain MATSim's `pt` mode. The analysis
reports AAM journeys and users, waits and onboard times, access/egress chains, corridor utilization,
offered seats and load factor, user income, and matched baseline trip-time changes.
