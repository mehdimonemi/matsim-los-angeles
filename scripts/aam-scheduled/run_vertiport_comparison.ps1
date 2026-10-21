param(
    [string]$Output = "run-output/aam-scheduled-vertiport-comparison-v11",
    [string]$Memory = "18g",
    [ValidateSet("global","all-vp-k10","one-vp-k10","adaptive")]
    [string[]]$Method = @("global","all-vp-k10","one-vp-k10","adaptive"),
    [string]$InitialLayout = "scenarios/aam-scheduled/vertiports.csv",
    [switch]$SkipCompile
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot
$python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { $python = (Get-Command python -ErrorAction Stop).Source }
$arguments = @("-B", "-m", "scripts.aam_scheduled.score_optimizer.suite", "--output", $Output,
               "--memory", $Memory, "--initial-layout", $InitialLayout, "--methods") + $Method
if ($SkipCompile) { $arguments += "--skip-compile" }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Scheduled-AAM vertiport comparison failed." }
