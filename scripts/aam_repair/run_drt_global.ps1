param(
    [string]$Memory = "18g",
    [string]$PackageDirectory = "",
    [string]$Output = "",
    [switch]$Run
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot
$python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { $python = (Get-Command python -ErrorAction Stop).Source }
if (!$PackageDirectory) {
    # Compile current fixes before freezing the DRT runtime. No MATSim run.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/aam/run_aam_v5.ps1 -Memory $Memory -CompileOnly
    if ($LASTEXITCODE -ne 0) { throw "DRT compilation failed." }
    $PackageDirectory = "run-inputs/drt-global-choice-fixed-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    & $python -B -m scripts.aam_repair.production_manifests create --services drt --output $PackageDirectory --memory $Memory --iterations 5 --stages 8 --maximum-probe-layouts 1
    if ($LASTEXITCODE -ne 0) { throw "DRT package preparation failed." }
} else {
    & $python -B -m scripts.aam_repair.production_manifests validate $PackageDirectory
    if ($LASTEXITCODE -ne 0) { throw "DRT package validation failed; prepare a fresh package for changed sources." }
}
Write-Host "DRT Global package: $PackageDirectory"
Write-Host "Protocol and fare are pinned in the package manifest. New packages preserve learning and measure tail stability."
Write-Host "New DRT profile: `$0 base + `$2/mile, 30-mile catchments, service 07:00-19:00, QSim 36:00."
if (!$Run) {
    Write-Host "Prepared only. To launch later, rerun with -PackageDirectory $PackageDirectory -Run."
    return
}
if (!$Output) { $Output = "run-output/drt-global-choice-fixed-" + (Get-Date -Format "yyyyMMdd-HHmmss") }
& $python -B -m scripts.aam_repair.fast_global $PackageDirectory --output $Output
if ($LASTEXITCODE -ne 0) { throw "DRT Global failed; inspect stage console logs in $Output." }
