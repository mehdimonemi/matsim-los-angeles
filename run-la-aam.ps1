param([string]$Memory = "18g", [switch]$Test)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$launcher = Join-Path $projectRoot "scripts\aam\run_aam_v5.ps1"

Set-Location $projectRoot

if (!(Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Missing AAM launcher: $launcher"
}

Write-Host "Running AAM LA 0.1% model with heap $Memory"
& $launcher -Memory $Memory -Test:$Test
if ($LASTEXITCODE -ne 0) {
    throw "AAM simulation failed. Check the output log for details."
}

Write-Host "AAM simulation completed successfully."
