param(
    [string]$Memory = "18g",
    [string]$PackageDirectory = "",
    [string]$Output = "",
    [ValidateSet("all", "global", "all-vp-k10", "one-vp-k10", "adaptive")]
    [string]$Method = "all",
    [switch]$Resume,
    [switch]$Run
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot
$python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { $python = (Get-Command python -ErrorAction Stop).Source }
if (!$PackageDirectory) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam/run_aam_v5.ps1 -Memory $Memory -CompileOnly
    if ($LASTEXITCODE -ne 0) { throw "DRT compilation failed." }
    $PackageDirectory = "run-inputs/drt-four-optimizers-choice-fixed-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    & $python -B -m scripts.aam_repair.production_manifests create --services drt --output $PackageDirectory --memory $Memory --iterations 5 --stages 8 --maximum-probe-layouts 1
    if ($LASTEXITCODE -ne 0) { throw "DRT package preparation failed." }
} else {
    & $python -B -m scripts.aam_repair.production_manifests validate $PackageDirectory
    if ($LASTEXITCODE -ne 0) { throw "Package fingerprints changed; prepare a fresh package." }
}
Write-Host "DRT optimizer package: $PackageDirectory"
Write-Host "Each method uses its manifest's learning and fixed-layout convergence budgets, with independent starts."
if (!$Run) {
    Write-Host "Prepared only. Launch later with -PackageDirectory $PackageDirectory -Method $Method -Run."
    return
}
if ($Resume -and !$Output) { throw "-Resume requires -Output pointing at the existing suite directory." }
if (!$Output) { $Output = "run-output/drt-four-optimizers-choice-fixed-" + (Get-Date -Format "yyyyMMdd-HHmmss") }
$methods = if ($Method -eq "all") { @("global", "all-vp-k10", "one-vp-k10", "adaptive") } else { @($Method) }
$arguments = @("-B", "-m", "scripts.aam_repair.drt_fixed_suite", $PackageDirectory, "--output", $Output, "--methods") + $methods
if ($Resume) { $arguments += "--resume" }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "DRT comparison failed; completed methods and logs are preserved in $Output." }
