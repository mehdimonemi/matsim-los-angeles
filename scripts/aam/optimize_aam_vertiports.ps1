param(
    [string]$Candidates = "scenarios/aam/vertiport-candidates-100.csv",
    [string]$Population = "run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz",
    [string]$Initial = "scenarios/aam/active-vertiports.csv",
    [string]$Output = "scenarios/aam/active-vertiports.csv",
    [int]$MaxSwaps = 10
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot
$python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
if (!(Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
& $python -B "scripts/aam/optimize_vertiports.py" --candidates $Candidates --population $Population --initial $Initial --output $Output --max-swaps $MaxSwaps
if ($LASTEXITCODE -ne 0) { throw "Vertiport optimization failed; the final layout was not replaced." }
