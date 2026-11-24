# Renders a broadcast replay of the live game with Movie Render Queue (assets from Scripts/make_broadcast_render.py):
# the Court map in -game, MuJoCo + policies stepping on MRQ's fixed 30 fps frame time, through the broadcast camera.
# Frames land in Saved/MovieRenders/<date>_<time>/broadcast.NNNN.png; the editor quits when the render is done.
#
#   pwsh Scripts/render_broadcast.ps1 [-TimeoutSec 1800] [extra game args, e.g. -TimeOfDay=17.6 -TimeOfDayFreeze -StreetballSeed=7]
[CmdletBinding(PositionalBinding = $false)]
param(
    [int]$TimeoutSec = 1800,
    [string]$Editor = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe",
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$GameArgs
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root "StreetballGym.uproject"
$log = Join-Path $root ("Saved\Logs\render_broadcast_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
$args = @("`"$project`"", "/Game/Project/Environments/Maps/Court", "-game", "-windowed", "-ResX=1280", "-ResY=720",
    "-LevelSequence=`"/Game/Project/Core/Cinematics/LS_Broadcast.LS_Broadcast`"",
    "-MoviePipelineConfig=`"/Game/Project/Core/Cinematics/MRQ_Broadcast.MRQ_Broadcast`"",
    "-Unattended", "-log", "-stdout", "-FullStdOutLogOutput") + $GameArgs
$p = Start-Process -FilePath $Editor -ArgumentList $args -PassThru -RedirectStandardOutput $log
if (-not $p.WaitForExit($TimeoutSec * 1000)) { Stop-Process -Id $p.Id -Force; Write-Host "TIMEOUT after $TimeoutSec s ($log)"; exit 124 }
$dir = Get-ChildItem (Join-Path $root "Saved\MovieRenders") -Directory | Sort-Object LastWriteTime | Select-Object -Last 1
$n = if ($dir) { (Get-ChildItem $dir.FullName -Filter *.png).Count } else { 0 }
Write-Host "exit $($p.ExitCode): $n frames in $($dir.FullName) (log $log)"
exit $p.ExitCode
