# USF CIRCE package: Los Angeles AAM-DRT, 100% population

This package runs the repository's dynamic AAM model using the standard public 100% Los Angeles plans. In this implementation, the aircraft service is a DRT service with mode `aam_drt`; ordinary LA ground modes and transit remain available. Its ten active sites are the final layout from the Global optimizer workflow, selected from the 100 density-weighted candidate sites and bundled in `config/active-vertiports.csv`. The optimizer used the available smaller population sample; the CIRCE job itself runs the 100% plans with that layout held fixed. This package runs Global's selected layout only; it does not run the optimizer stages or compare other optimizer methods.

The AAM settings follow the repository's current AAM config: zero base fare, $2 per mile, 100 aircraft, a 50-iteration run, and a 20% innovation-free tail. The package sets events and plans output intervals to 50 to limit scratch use. Global replanning uses 32 threads and QSim uses 8, matching the current full-population baseline's CPU layout. Flow and storage capacity factors are 0.1 to match that baseline package.

## Contents

- `config/la-v1.1-100pct-aam-drt.config.xml`: AAM configuration pointing to local package inputs and the 100% plans.
- `config/vertiport-candidates-100.csv`: the 100 density-weighted candidate locations used by the optimizer.
- `config/active-vertiports.csv` and its `.optimization.json`: the fixed ten-site Global layout and its optimization record.
- `lib/matsim-los-angeles-v1.1-jar-with-dependencies.jar`: runnable MATSim bundle, including the full-population scoring-duration fix through 36 hours.
- `scripts/fetch-inputs.sh`: downloads the public network, standard 100% plans, vehicles, and transit inputs.
- `scripts/submit-aam-drt.sbatch`: single-node Slurm submission script for CIRCE.

The bundled JAR disables a legacy JAI ImageIO output-stream service provider that fails to initialize on CIRCE's Java 11 during chart writing. Java's built-in ImageIO providers remain available.

The `fare30` source config currently has `baseFare=0.0` and `farePerMile=2.0`; this package preserves those actual values.

## Upload and run

Extract this package under `/work/$USER` on CIRCE, then:

```bash
cd /work/$USER/usf-circe-aam-drt-100pct
bash scripts/fetch-inputs.sh
myquota
sinfo -p amd_2021 -N -o "%N %c %m %t"
```

The submit script requests `amd_2021`, QOS `longrun`, 32 CPUs, 900G of RAM, an 850G Java heap, and 3 days. It loads `apps/jdk/11.0.5`. Confirm those limits and available scratch space before submitting:

```bash
sbatch scripts/submit-aam-drt.sbatch
squeue -u "$USER"
```

Each job writes to a unique `outputs/la-v1.1-100pct-aam-drt-JOBID/` directory. The launcher also writes fleet inputs and the effective config in the matching `-inputs` directory. Keep those files together with the result directory.

This package has not been run end-to-end with the 100% population. AAM alternative generation and DRT scheduling add memory and runtime beyond the no-AAM run; monitor `sstat` and the Slurm log. If the model configuration is changed, keep the `planCalcScore` duration range in the jar aligned with the QSim horizon.
