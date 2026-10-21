param(
    [string]$Memory = "18g",
    [int]$Epochs = 47,
    [int]$BootstrapIterations = 5,
    [int]$IterationsPerEpoch = 5,
    [int]$FinalIterations = 60,
    [int]$MinimumAamUsers = 100,
    [double]$MinimumScoreImprovement = 0.0,
    [double]$MinimumMeanScoreImprovement = 0.0,
    [double]$MinimumBetterShare = 0.5,
    [string]$Candidates = "scenarios/aam/vertiport-candidates-100.csv",
    [string]$Population = "run-inputs/los-angeles-v1.0-population-0.1pct_2019-12-09.xml.gz",
    [string]$InitialWaitPriors = "",
    [switch]$SkipBootstrap,
    [string]$WorkDir = "run-output/aam-adaptive-location-search-1",
    [string]$FinalOutput = "run-output/aam-adaptive-final-1"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot
$python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { $python = (Get-Command python -ErrorAction Stop).Source }
$shellName = if ($PSVersionTable.PSEdition -eq "Core") { "pwsh.exe" } else { "powershell.exe" }
$shellExecutable = Join-Path $PSHOME $shellName
$adaptiveArgs = @("-B","scripts/aam/run_adaptive_vertiport_optimization.py","--memory",$Memory,"--epochs",$Epochs,
    "--bootstrap-iterations",$BootstrapIterations,"--iterations-per-epoch",$IterationsPerEpoch,
    "--final-iterations",$FinalIterations,"--minimum-aam-users",$MinimumAamUsers,
    "--minimum-score-improvement",$MinimumScoreImprovement,
    "--minimum-mean-score-improvement",$MinimumMeanScoreImprovement,
    "--minimum-better-share",$MinimumBetterShare,"--candidates",$Candidates,"--population",$Population,
    "--work-dir",$WorkDir,"--final-output",$FinalOutput,"--powershell",$shellExecutable)
if ($InitialWaitPriors) { $adaptiveArgs += @("--initial-wait-priors",$InitialWaitPriors) }
if ($SkipBootstrap) { $adaptiveArgs += "--skip-bootstrap" }
& $python @adaptiveArgs
if ($LASTEXITCODE -ne 0) { throw "Adaptive vertiport optimization failed; inspect its last completed stage." }
