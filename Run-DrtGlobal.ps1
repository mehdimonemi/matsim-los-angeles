param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = 'C:\Users\mahdimoneminodehi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path 'run-output' ('drt-global-fixed-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
if (Test-Path -LiteralPath $OutputDirectory) { throw "Output already exists: $OutputDirectory" }
& $taskPython -B -u -m scripts.aam_repair.fast_global `
    run-inputs/aam-global-ground-score-fixed-20261009-01 `
    --output $OutputDirectory `
    --resume-stage-one run-output/drt-global-8x5-20261009-01
if ($LASTEXITCODE -ne 0) { throw "DRT Global stopped. Inspect $OutputDirectory and the console output." }
