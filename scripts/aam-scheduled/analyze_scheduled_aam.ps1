param(
    [string]$RunDirectory,
    [string]$BaselineDirectory,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$python = "C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pythonPackages = Join-Path $projectRoot "target\analysis-python"
Set-Location $projectRoot

function Resolve-ProjectPath([string]$Path) {
    if ([System.IO.Path]::IsPathRooted($Path)) { return $Path }
    return Join-Path $projectRoot $Path
}

if (!$RunDirectory) {
    $run = Get-ChildItem (Join-Path $projectRoot "run-output") -Directory |
        Where-Object { $_.Name -like "aam-scheduled-*" -and (Test-Path (Join-Path $_.FullName "ITERS")) } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (!$run) { throw "No completed scheduled-AAM run was found under run-output." }
    $RunDirectory = $run.FullName
} else { $RunDirectory = Resolve-ProjectPath $RunDirectory }

$iteration = Get-ChildItem (Join-Path $RunDirectory "ITERS") -Directory |
    Where-Object Name -Match '^it\.\d+$' |
    Sort-Object { [int]($_.Name -replace '^it\.','') } -Descending | Select-Object -First 1
if (!$iteration) { throw "No iteration directory found in $RunDirectory\ITERS" }

$trips = Get-ChildItem $iteration.FullName -Filter "*.trips.csv.gz" -File | Select-Object -First 1
$plans = Get-ChildItem $iteration.FullName -Filter "*.plans.xml.gz" -File | Select-Object -First 1
$events = Get-ChildItem $iteration.FullName -Filter "*.events.xml.gz" -File | Select-Object -First 1
$vehicles = Get-ChildItem $RunDirectory -Filter "*.output_transitVehicles.xml.gz" -File | Select-Object -First 1
if (!$trips -or !$plans -or !$events -or !$vehicles) { throw "Run output lacks final trips, plans, events, or transit vehicles." }

if (!$BaselineDirectory) {
    $baseline = Get-ChildItem (Join-Path $projectRoot "run-output") -Directory |
        Where-Object Name -Like "baseline*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($baseline) { $BaselineDirectory = $baseline.FullName }
} else { $BaselineDirectory = Resolve-ProjectPath $BaselineDirectory }

$baselineTrips = $null
if ($BaselineDirectory -and (Test-Path -LiteralPath $BaselineDirectory -PathType Container)) {
    $baselineTrips = Get-ChildItem $BaselineDirectory -Filter "*.output_trips.csv.gz" -File | Select-Object -First 1
    if (!$baselineTrips) {
        $baselineIteration = Get-ChildItem (Join-Path $BaselineDirectory "ITERS") -Directory -ErrorAction SilentlyContinue |
            Where-Object Name -Match '^it\.\d+$' | Sort-Object { [int]($_.Name -replace '^it\.','') } -Descending | Select-Object -First 1
        if ($baselineIteration) { $baselineTrips = Get-ChildItem $baselineIteration.FullName -Filter "*.trips.csv.gz" -File | Select-Object -First 1 }
    }
}

if (!$OutputDirectory) { $OutputDirectory = Join-Path $RunDirectory "analysis-scheduled-aam" }
else { $OutputDirectory = Resolve-ProjectPath $OutputDirectory }
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw "Analysis Python runtime not found: $python" }
$env:PYTHONPATH = $pythonPackages

$arguments = @(
    (Join-Path $PSScriptRoot "analyze_scheduled_aam.py"),
    $trips.FullName, $plans.FullName, $events.FullName, $vehicles.FullName,
    (Join-Path $projectRoot "scenarios\aam-scheduled\vertiports.csv"), $OutputDirectory
)
if ($baselineTrips) { $arguments += @("--baseline", $baselineTrips.FullName) }

Write-Host "Scheduled-AAM run: $RunDirectory"
Write-Host "Final iteration: $($iteration.Name)"
Write-Host "Baseline trips: $(if ($baselineTrips) { $baselineTrips.FullName } else { 'not supplied' })"
Write-Host "Analysis output: $OutputDirectory"
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Scheduled-AAM analysis failed." }
Write-Host "Scheduled-AAM analysis completed successfully."
