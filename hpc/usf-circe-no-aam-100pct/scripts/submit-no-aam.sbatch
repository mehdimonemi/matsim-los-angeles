#!/usr/bin/env bash
#SBATCH --job-name=la100-noaam
#SBATCH --partition=amd_2021
#SBATCH --qos=longrun
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=980G
#SBATCH --time=3-00:00:00
#SBATCH --output=la-no-aam-%j.log

set -euo pipefail
module add apps/jdk/11.0.5
bundle_root="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$bundle_root"

jar="lib/matsim-los-angeles-v1.1-jar-with-dependencies.jar"
config="config/la-v1.1-100pct-no-aam.config.xml"
plans="inputs/los-angeles-v1.0-population-100pct_2020-05-20.xml.gz"

for required in "$jar" "$config" "$plans" \
  "inputs/los-angeles-v1.0-network_2019-12-10.xml.gz" \
  "inputs/los-angeles-v1.0-mode-vehicle-types_2019-12-05.xml" \
  "inputs/los-angeles-v1.0-transitSchedule_2019-12-18.xml.gz" \
  "inputs/los-angeles-v1.0-transitVehicles_2019-11-19.xml.gz"; do
  [[ -s "$required" ]] || { echo "Missing input: $required" >&2; exit 2; }
done

mkdir -p outputs
threads="${SLURM_CPUS_PER_TASK:-32}"
heap="${MATSIM_HEAP:-850G}"
output_dir="outputs/la-v1.1-100pct-no-aam-${SLURM_JOB_ID:-manual}"
echo "Host: $(hostname)"
echo "Started: $(date -Is)"
echo "Java: $(java -version 2>&1 | head -n 1)"
echo "Threads: $threads; heap: $heap"
echo "Output: $output_dir"

exec java -Xms8G "-Xmx$heap" -Djava.awt.headless=true \
  -Dmatsim.preferLocalDtds=true \
  -cp "$jar" org.matsim.run.RunLosAngelesScenario "$config" \
  "--config:controler.outputDirectory=$output_dir"
