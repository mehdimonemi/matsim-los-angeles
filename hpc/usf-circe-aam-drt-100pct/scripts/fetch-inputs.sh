#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
input_dir="$bundle_root/inputs"
base_url="https://svn.vsp.tu-berlin.de/repos/public-svn/matsim/scenarios/countries/us/los-angeles/los-angeles-v1.0/input"
mkdir -p "$input_dir"

files=(
  "los-angeles-v1.0-network_2019-12-10.xml.gz"
  "los-angeles-v1.0-population-100pct_2020-05-20.xml.gz"
  "los-angeles-v1.0-mode-vehicle-types_2019-12-05.xml"
  "los-angeles-v1.0-transitSchedule_2019-12-18.xml.gz"
  "los-angeles-v1.0-transitVehicles_2019-11-19.xml.gz"
)

for file in "${files[@]}"; do
  if [[ -s "$input_dir/$file" ]]; then
    echo "Already present: $file"
    continue
  fi
  echo "Downloading $file"
  curl --fail --location --retry 3 --output "$input_dir/$file.part" "$base_url/$file"
  mv "$input_dir/$file.part" "$input_dir/$file"
done

echo "Inputs ready in $input_dir"
