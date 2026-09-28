param([string]$Memory = "12g", [switch]$Test, [switch]$Validate)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $MyInvocation.MyCommand.Path -Parent
$launcher = Join-Path $projectRoot "scripts\aam-scheduled\run_scheduled_aam.ps1"
if (!(Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Missing scheduled AAM launcher: $launcher"
}
& $launcher -Memory $Memory -Test:$Test -Validate:$Validate
if ($LASTEXITCODE -ne 0) {
    throw "Scheduled AAM command failed."
}
