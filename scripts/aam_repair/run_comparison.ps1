param(
    [string]$ManifestDirectory = "",
    [string]$Output = "",
    [ValidateSet("both", "scheduled", "drt")][string]$Service = "both",
    [ValidateSet("all", "global", "all-vp-k10", "one-vp-k10", "adaptive")][string]$Method = "all",
    [string]$Memory = "18g",
    [int]$IterationsPerTrial = 50,
    [int]$MaximumStages = 20,
    [int]$MaximumProbeLayouts = 901,
    [switch]$PrepareOnly
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot
$python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { $python = (Get-Command python -ErrorAction Stop).Source }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (!$Output) { $Output = "run-output/aam-repaired-four-methods-$stamp" }
if (Test-Path -LiteralPath $Output) { throw "Use a new output directory: $Output" }
if (!$ManifestDirectory) {
    $ManifestDirectory = "run-inputs/aam-repaired-four-methods-$stamp"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam-scheduled/run_scheduled_aam.ps1 -CompileOnly -Memory $Memory
    if ($LASTEXITCODE -ne 0) { throw "Scheduled compilation failed." }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam/run_aam_v5.ps1 -CompileOnly -Memory $Memory
    if ($LASTEXITCODE -ne 0) { throw "DRT compilation failed." }
    & $python -B -m scripts.aam_repair.production_manifests create --output $ManifestDirectory --iterations $IterationsPerTrial --stages $MaximumStages --maximum-probe-layouts $MaximumProbeLayouts --memory $Memory
    if ($LASTEXITCODE -ne 0) { throw "Manifest preparation failed." }
} else {
    # Existing packages are immutable: their recorded budgets and memory apply.
    & $python -B -m scripts.aam_repair.production_manifests validate $ManifestDirectory
    if ($LASTEXITCODE -ne 0) { throw "Manifest fingerprints failed; prepare a new package." }
}
Write-Host "Manifest package: $ManifestDirectory"
if ($PrepareOnly) { Write-Host "Prepared and verified; no MATSim simulation launched."; return }
$services = if ($Service -eq "both") { @("scheduled", "drt") } else { @($Service) }
$methods = if ($Method -eq "all") { @("global", "all-vp-k10", "one-vp-k10", "adaptive") } else { @($Method) }
$arguments = @("-B", "-m", "scripts.aam_repair.suite", $ManifestDirectory, "--output", $Output, "--allow-large-population", "--services") + $services + @("--methods") + $methods
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Repaired comparison failed; completed trials and diagnostics are preserved in $Output." }
