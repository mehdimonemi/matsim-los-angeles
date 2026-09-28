param([string]$Memory = "18g", [switch]$Test, [switch]$Validate)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot

$runtime = Join-Path $projectRoot "target/aam-runtime"
$mainJar = Join-Path $runtime "release/matsim-13.0/matsim-13.0.jar"
if (!(Test-Path $mainJar)) {
    throw "MATSim 13 runtime missing. First run: python scripts/aam/run_experiment.py --build-only"
}

$classes = Join-Path $projectRoot "target/aam-scheduled-classes"
New-Item -ItemType Directory -Force -Path $classes | Out-Null
$requiredJars = @("drt-13.0.jar","dvrp-13.0.jar","ev-13.0.jar","otfvis-13.0.jar","locationchoice-13.0.jar","sbb-extensions-13.0.jar","common-13.0.jar","av-13.0.jar","taxi-13.0.jar","streamex-0.7.2.jar","commons-math3-3.6.1.jar","opencsv-4.6.jar")
$jarPaths = @($mainJar)
$jarPaths += @(Get-ChildItem -LiteralPath (Join-Path $runtime "release/matsim-13.0/libs") -Filter *.jar -File | Sort-Object Name | ForEach-Object { $_.FullName })
foreach ($jarName in $requiredJars) {
    $jarPath = Join-Path $runtime $jarName
    if (!(Test-Path -LiteralPath $jarPath -PathType Leaf)) { throw "Missing dependency: $jarPath" }
    $jarPaths += $jarPath
}
$cp = $jarPaths -join [System.IO.Path]::PathSeparator
$sources = @(Get-ChildItem "src/main/java/org/matsim/run","src/main/java/org/matsim/parkingCost" -Recurse -Filter *.java | ForEach-Object { $_.FullName })
if ($Test) { $sources += (Join-Path $projectRoot "src/test/java/org/matsim/run/aam/scheduled/ScheduledAamRegressionChecks.java") }

& java -m jdk.compiler/com.sun.tools.javac.Main --release 11 -cp $cp -d $classes @sources
if ($LASTEXITCODE -ne 0) { throw "Compilation failed; simulation was not started." }

$javaArgs = @("--add-opens=java.base/java.lang=ALL-UNNAMED","-Xms1g","-Xmx$Memory","-Djava.awt.headless=true","-Dmatsim.preferLocalDtds=true","-cp","$classes;$cp")
if ($Test) {
    $javaArgs += "org.matsim.run.aam.scheduled.ScheduledAamRegressionChecks"
} else {
    if ($Validate) {
        $output = "run-output/aam-scheduled-validation"
        $javaArgs += @("org.matsim.run.aam.scheduled.RunScheduledAamLosAngelesScenario","scenarios/aam-scheduled/la-aam-scheduled.config.xml",$output,"--validate-only")
        Write-Host "Loading and validating the complete scheduled AAM scenario."
    } else {
        $output = "run-output/aam-scheduled-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        $javaArgs += @("org.matsim.run.aam.scheduled.RunScheduledAamLosAngelesScenario","scenarios/aam-scheduled/la-aam-scheduled.config.xml",$output)
        Write-Host "Running scheduled AAM with heap $Memory; output: $output"
    }
}
& java @javaArgs
if ($LASTEXITCODE -ne 0) { throw "Java failed. Preserve the error and output log for diagnosis." }
