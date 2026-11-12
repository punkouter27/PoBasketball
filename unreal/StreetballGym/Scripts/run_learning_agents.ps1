param(
    [ValidateSet("Preview", "Train", "Smoke")] [string]$Mode = "Preview",
    [ValidateRange(1, 2)] [int]$Tier = 1,
    [ValidateRange(1, 64)] [int]$Agents = 1,
    [int]$Steps = 0,
    [string]$Resume = "",
    [string]$Output = "",
    [string]$Engine = "C:\Program Files\Epic Games\UE_5.8",
    [int]$TimeoutSec = 600
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $projectRoot "StreetballGym.uproject"
$map = Join-Path $projectRoot "Content\Maps\LearningAgentsComparison.umap"
if (!(Test-Path $map)) { throw "Generate LearningAgentsComparison with make_learning_agents_level.py first." }
if ($Steps -lt 0) { throw "Steps must be nonnegative." }
if ($Resume -ne "" -and !(Test-Path (Join-Path $Resume "summary.json"))) {
    throw "Resume must name a completed Learning Agents run directory."
}
if ($Output -eq "") {
    $Output = Join-Path $projectRoot ("Saved\LearningAgents\{0}_{1}_{2}" -f $Mode, $Tier, (Get-Date -Format "yyyyMMdd_HHmmss"))
}
$Output = [System.IO.Path]::GetFullPath($Output)
if (Test-Path $Output) { throw "Output already exists; choose a fresh directory to protect previous runs." }
$args = @("/Game/Maps/LearningAgentsComparison", "-game", "-LATier=$Tier", "-LAAgents=$Agents", "-LAOutput=$Output")
if ($Resume -ne "") { $args += "-LAResume=$((Resolve-Path $Resume).Path)" }
if ($Mode -eq "Train" -or $Mode -eq "Smoke") { $args += "-LATrain" }
if ($Mode -eq "Smoke") {
    if ($Steps -eq 0) { $Steps = 8192 }
    $args += "-LAEpisodeSeconds=5"
}
if ($Steps -gt 0) { $args += "-LASteps=$Steps" }

if ($Mode -eq "Preview") {
    & (Join-Path $Engine "Engine\Binaries\Win64\UnrealEditor.exe") $project @args
    exit $LASTEXITCODE
}
$log = "$Output.log"
New-Item -ItemType Directory -Path (Split-Path -Parent $log) -Force | Out-Null
& (Join-Path $PSScriptRoot "run_headless.ps1") -TimeoutSec $TimeoutSec -LogFile $log `
    -Editor (Join-Path $Engine "Engine\Binaries\Win64\UnrealEditor-Cmd.exe") -EditorArgs $args
$code = $LASTEXITCODE
if ($code -ne 0) { exit $code }
# Unreal can request a graceful failure yet still return zero on Windows.
$failure = Select-String -Path $log -Pattern 'LearningAgents comparison FAILED:'
if ($failure) { throw $failure[-1].Line }
$summaryPath = Join-Path $Output "summary.json"
if (!(Test-Path $summaryPath) -or !(Select-String -Quiet -Path $log -Pattern 'LearningAgents comparison COMPLETE:')) {
    throw "Learning Agents did not finish successfully. See $log"
}
$summary = Get-Content -Raw $summaryPath | ConvertFrom-Json
if ($summary.status -ne "experimental_not_production" -or ($Steps -gt 0 -and $summary.steps -lt $Steps)) {
    throw "Learning Agents summary did not satisfy the requested run. See $log"
}
Write-Host "Completed $($summary.steps) transitions, $($summary.network_updates) network updates. Experimental only: $Output"
exit 0
