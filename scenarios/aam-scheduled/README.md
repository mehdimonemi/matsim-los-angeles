# Scheduled AAM scenario

This scenario represents AAM as ordinary MATSim public transit. At startup the runner appends ten
vertiport stops, a direct route for every ordered vertiport pair, fixed departures, and four-seat
transit vehicles to the existing Los Angeles transit schedule.

It intentionally does not install DRT/DVRP modules, create requests, dispatch aircraft, or use the
custom DRT AAM access/egress router. Travelers access the vertiports through the normal public-transit
router, and their passenger legs retain MATSim's `pt` mode. The transit route's transport mode and the
aircraft network mode are `aam`, which makes the scheduled flights identifiable in schedules and events.

Configuration is in `la-aam-scheduled.config.xml`; vertiport coordinates are in `vertiports.csv`.
Times and headways are seconds after midnight. The shipped service runs every 30 minutes from 07:00
through 19:00 on every directed pair at 100 mph.

`scheduled_aam` is the traveler-facing routing mode. `ScheduledAamInnovation` creates additional
candidate plans for non-car, non-bike trips of at least 20 km. A dedicated routing module turns that
request into teleported `access_egress_pt` legs and a timetable-valid `pt` passenger leg whose transit
line is an AAM line. All returned legs retain `scheduled_aam` as their routing mode, so analysis and
choice distinguish the whole journey from conventional PT. The aircraft leg also uses the
`scheduled_aam` scoring parameters while retaining physical mode `pt`, which is required for normal
waiting, boarding, capacity, and alighting behavior.

The source plan is retained, and MATSim's ordinary scoring and plan selection decide whether the AAM
alternative survives. The feasibility screen permits up to three hours of access and three hours of
egress so that service quality is primarily rejected through scoring rather than hidden by the router.
The strategy runs only during the configured innovation portion of the run; aircraft remain
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

Analyze the newest completed run with:

```powershell
.\scripts\aam-scheduled\analyze_scheduled_aam.ps1
```

Pass `-RunDirectory` and optionally `-BaselineDirectory` to select specific runs. Scheduled AAM is
identified using its transit line IDs because passenger legs retain MATSim's `pt` mode. The analysis
reports AAM journeys and users, waits and onboard times, access/egress chains, corridor utilization,
offered seats and load factor, user income, and matched baseline trip-time changes.
