param(
    [string]$Memory = "18g", [switch]$Test, [switch]$Validate,
    [switch]$SkipCompile, [switch]$CompileOnly,
    [string]$Config = "scenarios/aam-scheduled/la-aam-scheduled.config.xml",
    [string]$Output = "", [string]$Plans = "", [string]$Vertiports = "",
    [string]$RunId = "", [string]$ClassesDirectory = "", [int]$FirstIteration = -1, [int]$LastIteration = -1,
    [double]$InnovationFraction = -1, [switch]$DisableInnovation
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot

$runtime = Join-Path $projectRoot "target/aam-runtime"
$mainJar = Join-Path $runtime "release/matsim-13.0/matsim-13.0.jar"
if (!(Test-Path $mainJar)) {
    throw "MATSim 13 runtime missing. First run: python scripts/aam/run_experiment.py --build-only"
}

$classes = Join-Path $projectRoot "target/aam-scheduled-classes"
if ($ClassesDirectory) {
    if (!$SkipCompile) { throw "ClassesDirectory is a frozen runtime snapshot; use SkipCompile." }
    $classes = (Resolve-Path -LiteralPath $ClassesDirectory).Path
}
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
if (!$SkipCompile) {
    $sources = @(Get-ChildItem "src/main/java/org/matsim/run","src/main/java/org/matsim/parkingCost" -Recurse -Filter *.java | ForEach-Object { $_.FullName })
    if ($Test) { $sources += @(Get-ChildItem "src/test/java/org/matsim/run/aam/scheduled" -Filter *.java | ForEach-Object { $_.FullName }) }
    & java -m jdk.compiler/com.sun.tools.javac.Main --release 11 -cp $cp -d $classes @sources
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed; simulation was not started." }
}
if ($CompileOnly) {
    if ($SkipCompile) { throw "CompileOnly cannot be combined with SkipCompile." }
    Write-Host "Compilation completed; simulation was not started."
    return
}

$javaArgs = @("--add-opens=java.base/java.lang=ALL-UNNAMED","-Xms1g","-Xmx$Memory","-Djava.awt.headless=true","-Dmatsim.preferLocalDtds=true","-cp","$classes;$cp")
if ($Test) {
    $javaArgs += "org.matsim.run.aam.scheduled.ScheduledAamRegressionChecks"
} else {
    if ($Validate) {
        if (!$Output) { $Output = "run-output/aam-scheduled-validation" }
        $javaArgs += @("org.matsim.run.aam.scheduled.RunScheduledAamLosAngelesScenario",$Config,$Output,"--validate-only")
        Write-Host "Loading and validating the complete scheduled AAM scenario."
    } else {
        if (!$Output) { $Output = "run-output/aam-scheduled-" + (Get-Date -Format "yyyyMMdd-HHmmss") }
        $javaArgs += @("org.matsim.run.aam.scheduled.RunScheduledAamLosAngelesScenario",$Config,$Output)
        if ($Plans) { $javaArgs += "--plans=$Plans" }
        if ($Vertiports) { $javaArgs += "--vertiports=$Vertiports" }
        if ($RunId) { $javaArgs += "--run-id=$RunId" }
        if ($FirstIteration -ge 0) { $javaArgs += "--first-iteration=$FirstIteration" }
        if ($LastIteration -ge 0) { $javaArgs += "--last-iteration=$LastIteration" }
        if ($InnovationFraction -ge 0) { $javaArgs += "--innovation-fraction=$InnovationFraction" }
        if ($DisableInnovation) { $javaArgs += "--disable-innovation" }
        Write-Host "Running scheduled AAM with heap $Memory; output: $Output"
    }
}
& java @javaArgs
if ($LASTEXITCODE -ne 0) { throw "Java failed. Preserve the error and output log for diagnosis." }
if ($Test) {
    & java "--add-opens=java.base/java.lang=ALL-UNNAMED" "-Xmx$Memory" "-Djava.awt.headless=true" "-Dmatsim.preferLocalDtds=true" -cp "$classes;$cp" org.matsim.run.aam.scheduled.ScheduledAamQueueSmoke
    if ($LASTEXITCODE -ne 0) { throw "Scheduled AAM queue QSim smoke failed." }
    $python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
    if (!(Test-Path -LiteralPath $python -PathType Leaf)) { $python = (Get-Command python -ErrorAction Stop).Source }
    & $python -B -m "scripts.aam_scheduled.score_optimizer.test_optimizer"
    if ($LASTEXITCODE -ne 0) { throw "Scheduled-AAM optimizer regression checks failed." }
}
