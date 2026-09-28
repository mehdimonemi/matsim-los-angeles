param([string]$Memory = "12g")

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$config = Join-Path $projectRoot "scenarios\los-angeles-v1.1\input\los-angeles-v1.1-0.1pct.config.xml"

Set-Location $projectRoot

if (!(Test-Path -LiteralPath $config -PathType Leaf)) {
    throw "Missing baseline configuration: $config"
}

$env:MAVEN_OPTS = "-Xms2g -Xmx$Memory -Djava.awt.headless=true -Dmatsim.preferLocalDtds=true"

Write-Host "Compiling the latest original LA model..."
& mvn.cmd -DskipTests compile
if ($LASTEXITCODE -ne 0) {
    throw "Maven compilation failed; the simulation was not started."
}

Write-Host "Running original LA 0.1% model with heap $Memory"
Write-Host "Configuration: $config"
& mvn.cmd "-Dexec.mainClass=org.matsim.run.RunLosAngelesScenario" "-Dexec.args=$config" exec:java
if ($LASTEXITCODE -ne 0) {
    throw "Original LA simulation failed. Check the output log for details."
}

Write-Host "Original LA simulation completed successfully."
