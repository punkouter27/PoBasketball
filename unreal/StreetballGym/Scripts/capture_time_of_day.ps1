# Captures the court at several hours with the time of day frozen (UCourtTimeOfDaySubsystem), one -game run per hour,
# through the showcase's unattended capture (-ShowcaseCapture: overlay_on/off, demo_a/b PNGs, then quits).
#
#   pwsh Scripts/capture_time_of_day.ps1 -OutDir <dir> [-Hours ref,17.6,18.3,22.5]
#
# "ref" = the hour that matches the level's own sun (what the court looked like before the time-of-day system).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string[]]$Hours = @("ref", "17.6", "18.3", "22.5"),
    [int]$TimeoutSec = 600,
    [string]$Editor = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"
)
$ErrorActionPreference = "Stop"
$project = Join-Path (Split-Path -Parent $PSScriptRoot) "StreetballGym.uproject"
foreach ($h in $Hours) {
    $dir = Join-Path $OutDir "h_$h"
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    New-Item -ItemType Directory -Force $dir | Out-Null
    $tod = if ($h -eq "ref") { @("-TimeOfDayFreeze") } else { @("-TimeOfDay=$h", "-TimeOfDayFreeze") }
    $args = @("`"$project`"", "-game", "-windowed", "-ResX=1600", "-ResY=900", "-ShowcaseCapture=`"$dir`"",
        "-log", "-stdout", "-FullStdOutLogOutput") + $tod
    $p = Start-Process -FilePath $Editor -ArgumentList $args -PassThru -RedirectStandardOutput (Join-Path $dir "game.log")
    if (-not $p.WaitForExit($TimeoutSec * 1000)) { Stop-Process -Id $p.Id -Force; Write-Host "TIMEOUT at hour $h"; continue }
    $shots = (Get-ChildItem $dir -Filter *.png | ForEach-Object Name) -join ","
    Write-Host "hour $h exit $($p.ExitCode): $shots"
    Select-String -Path (Join-Path $dir "game.log") -Pattern "LogCourtTimeOfDay" | ForEach-Object { "   " + ($_.Line -replace '^.*LogCourtTimeOfDay: ', '') }
}
