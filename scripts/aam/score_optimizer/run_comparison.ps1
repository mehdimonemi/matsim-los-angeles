param(
    [string]$Memory = "18g",
    [string]$Output = "run-output/aam-score-optimizer-comparison-v2",
    [ValidateSet("all", "global", "all-vp-k10", "one-vp-k10", "adaptive")]
    [string]$Method = "all",
    [double]$ServiceStartTime = 0,
    [double]$ServiceEndTime = 129600,
    [string]$InitialLayout = "scenarios/aam/active-vertiports.csv",
    [switch]$SkipCompile
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
Set-Location $projectRoot
$python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { $python = (Get-Command python -ErrorAction Stop).Source }
$arguments = @("-B", "-m", "scripts.aam.score_optimizer.suite", "--output", $Output, "--memory", $Memory)
$arguments += @("--service-start-time", $ServiceStartTime, "--service-end-time", $ServiceEndTime)
$arguments += @("--initial-layout", $InitialLayout)
if ($Method -ne "all") { $arguments += @("--methods", $Method) }
if ($SkipCompile) { $arguments += "--skip-compile" }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Score-optimizer comparison failed; completed method outputs were preserved." }
