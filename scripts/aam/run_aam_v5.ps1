param(
    [string]$Memory = "18g", [switch]$Test, [switch]$SkipCompile, [switch]$CompileOnly,
    [string]$Config = "scenarios/aam/la-aam-fare30-it2.config.xml",
    [string]$Output = "", [string]$Plans = "", [string]$Vertiports = "",
    [string]$RunId = "", [string]$ClassesDirectory = "",
    [string]$WaitPriors = "", [int]$FirstIteration = -1, [int]$LastIteration = -1,
    [double]$InnovationFraction = -1, [double]$MinimumConvergence = -1,
    [double]$BaseFare = -1, [double]$FarePerMile = -1,
    [double]$ServiceStartTime = -1, [double]$ServiceEndTime = -1,
    [int]$CandidateVertiports = -1,
    [switch]$DisableInnovation
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $projectRoot
$runtime = Join-Path $projectRoot "target/aam-runtime"
$mainJar = Join-Path $runtime "release/matsim-13.0/matsim-13.0.jar"
if (!(Test-Path $mainJar)) { throw "MATSim 13 runtime missing. First use the existing run_experiment.py --build-only launcher to download dependencies." }
$classes = Join-Path $projectRoot "target/aam-v5-classes"
if ($ClassesDirectory) {
    if (!$SkipCompile) { throw "ClassesDirectory is a frozen runtime snapshot; use SkipCompile." }
    $classes = (Resolve-Path -LiteralPath $ClassesDirectory).Path
}
New-Item -ItemType Directory -Force -Path $classes | Out-Null
# Explicit filenames work both for the compiler invoked as a module and Java.
# Do not depend on wildcard expansion inside compiler arguments.
$requiredJars = @("drt-13.0.jar","dvrp-13.0.jar","ev-13.0.jar","otfvis-13.0.jar","locationchoice-13.0.jar","sbb-extensions-13.0.jar","common-13.0.jar","av-13.0.jar","taxi-13.0.jar","streamex-0.7.2.jar","commons-math3-3.6.1.jar","opencsv-4.6.jar")
$jarPaths = @($mainJar)
$jarPaths += @(Get-ChildItem -LiteralPath (Join-Path $runtime "release/matsim-13.0/libs") -Filter *.jar -File | Sort-Object Name | ForEach-Object { $_.FullName })
foreach ($jarName in $requiredJars) {
    $jarPath = Join-Path $runtime $jarName
    if (!(Test-Path -LiteralPath $jarPath -PathType Leaf)) {
        throw "Missing dependency: $jarPath. Restore it using run_experiment.py --build-only, then rerun this script."
    }
    $jarPaths += $jarPath
}
$cp = $jarPaths -join [System.IO.Path]::PathSeparator
Write-Host "Compiler classpath: $($jarPaths.Count) explicit JAR files (including DRT and DVRP)."
if (!$SkipCompile) {
    $sources = @(Get-ChildItem "src/main/java/org/matsim/run","src/main/java/org/matsim/parkingCost" -Recurse -Filter *.java | ForEach-Object { $_.FullName })
    if ($Test) { $sources += (Join-Path $projectRoot "src/test/java/org/matsim/run/aam/AamRegressionChecks.java") }
    $compileArgs = @("-m","jdk.compiler/com.sun.tools.javac.Main","--release","11","-cp",$cp,"-d",$classes) + $sources
    & java @compileArgs
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed; simulation was not started." }
}
if ($CompileOnly) {
    if ($SkipCompile) { throw "CompileOnly cannot be combined with SkipCompile." }
    Write-Host "Compilation completed; simulation was not started."
    return
}
$javaArgs = @("--add-opens=java.base/java.lang=ALL-UNNAMED","-Xms1g","-Xmx$Memory","-Djava.awt.headless=true","-Dmatsim.preferLocalDtds=true","-cp","$classes;$cp")
if ($Test) {
    $javaArgs += "org.matsim.run.aam.AamRegressionChecks"
} else {
    if (!$Output) { $Output = "run-output/aam-v5-" + (Get-Date -Format "yyyyMMdd-HHmmss") }
    $javaArgs += @("org.matsim.run.aam.RunDynamicAamLosAngelesScenario",$Config,$Output)
    if ($Plans) { $javaArgs += "--plans=$Plans" }
    if ($Vertiports) { $javaArgs += "--vertiports=$Vertiports" }
    if ($RunId) { $javaArgs += "--run-id=$RunId" }
    if ($WaitPriors) { $javaArgs += "--wait-priors=$WaitPriors" }
    if ($FirstIteration -ge 0) { $javaArgs += "--first-iteration=$FirstIteration" }
    if ($LastIteration -ge 0) { $javaArgs += "--last-iteration=$LastIteration" }
    if ($InnovationFraction -ge 0) { $javaArgs += "--innovation-fraction=$InnovationFraction" }
    if ($MinimumConvergence -ge 0) { $javaArgs += "--minimum-convergence=$MinimumConvergence" }
    if ($BaseFare -ge 0) { $javaArgs += "--base-fare=$BaseFare" }
    if ($FarePerMile -ge 0) { $javaArgs += "--fare-per-mile=$FarePerMile" }
    if ($ServiceStartTime -ge 0) { $javaArgs += "--service-start-time=$ServiceStartTime" }
    if ($ServiceEndTime -ge 0) { $javaArgs += "--service-end-time=$ServiceEndTime" }
    if ($CandidateVertiports -ge 1) { $javaArgs += "--candidate-vertiports=$CandidateVertiports" }
    if ($DisableInnovation) { $javaArgs += "--disable-innovation" }
    Write-Host "Running V5 with heap $Memory; output: $Output"
}
& java @javaArgs
if ($LASTEXITCODE -ne 0) { throw "Java failed. Preserve the error and output log for diagnosis." }
if ($Test) {
    $python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
    if (!(Test-Path -LiteralPath $python -PathType Leaf)) { $python = (Get-Command python -ErrorAction Stop).Source }
    & $python -B "scripts/aam/test_adaptive_vertiport_optimization.py"
    if ($LASTEXITCODE -ne 0) { throw "Adaptive optimizer regression checks failed." }
    & $python -B -m unittest scripts.aam.score_optimizer.test_optimizer scripts.aam.score_optimizer.test_population
    if ($LASTEXITCODE -ne 0) { throw "Score optimizer regression checks failed." }
}
