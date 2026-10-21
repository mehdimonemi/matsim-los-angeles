# USF CIRCE package: Los Angeles 100% baseline (no AAM)

This package runs the MATSim Los Angeles v1.1 configuration with the standard 100% v1.0 plans and no AAM module. It is a single-node Slurm job. The supplied resource request is a starting point; check the partition limits and adjust memory, CPUs, and wall time to what your allocation permits.

## Package contents

- `config/la-v1.1-100pct-no-aam.config.xml`: 300-iteration baseline configuration using local `inputs/` files.
- `lib/matsim-los-angeles-v1.1-jar-with-dependencies.jar`: runnable dependency bundle. The model classes in the repository's current `target/classes` were overlaid on the built dependency jar.
- `scripts/fetch-inputs.sh`: downloads the public LA network, standard 100% population, vehicles, and transit inputs.
- `scripts/submit-no-aam.sbatch`: Slurm job script.

The bundled JAR disables a legacy JAI ImageIO output-stream service provider that fails to initialize on CIRCE's Java 11 during chart writing. Java's built-in ImageIO providers remain available.

The standard 100% population is `los-angeles-v1.0-population-100pct_2020-05-20.xml.gz`; it is distinct from the separate `_teleported` variant. The large population is downloaded on CIRCE and is not included in the transfer archive.

The submit script targets the `amd_2021` partition with the `longrun` QOS, requesting 32 CPUs, 980 GB of memory, an 850 GB Java heap, and 3 days. The large memory request follows a recorded full-population run that reached about 895 GiB RSS before Slurm killed it under a 900 GiB allocation. It fits only on the partition's 1 TB nodes; scheduling may take longer. It loads CIRCE's `apps/jdk/11.0.5` module.

## Upload and run

From the X2Go desktop, open a terminal on CIRCE. Use `/work/$USER` for active inputs and outputs, as CIRCE recommends scratch storage for running jobs. Keep the package tarball in `/home` or another backed-up location, then extract it under `/work/$USER`.

From your local Windows computer, upload the archive using `scp` from PowerShell (replace `NETID` with your USF NetID):

```powershell
scp .\hpc\usf-circe-no-aam-100pct.tar.gz NETID@circe.rc.usf.edu:~/
```

On CIRCE:

```bash
mkdir -p "$WORK/matsim-la-no-aam"
tar -xzf ~/usf-circe-no-aam-100pct.tar.gz -C "$WORK/matsim-la-no-aam" --strip-components=1
cd "$WORK/matsim-la-no-aam"
bash scripts/fetch-inputs.sh
java -version
sinfo
```

The job script loads Java 11 automatically. Review the `#SBATCH` memory/time/CPU values in `scripts/submit-no-aam.sbatch` against the partition/allocation available to your account. Then:

```bash
sbatch scripts/submit-no-aam.sbatch
squeue -u "$USER"
```

Outputs go to a job-specific `outputs/la-v1.1-100pct-no-aam-JOBID/` directory. The scheduler log is `la-no-aam-%j.log` in the package root. Copy results you want to keep from `/work` back to backed-up storage after the run; scratch may be purged.

## Notes

- The standard 100% plans file contains network-routed demand. The separate teleported plans file is not selected here.
- The job writes large MATSim output to scratch. Verify free space and quota with `myquota` before starting; a 100% population run can require substantial memory, scratch, and wall time.
- CIRCE documentation: [USF Research Computing](https://wiki.rc.usf.edu/index.php/Main_Page), [SLURM Users](https://wiki.rc.usf.edu/index.php/SLURM_Users), and [CIRCE Data Management](https://wiki.rc.usf.edu/index.php/CIRCE_Data_Management).
