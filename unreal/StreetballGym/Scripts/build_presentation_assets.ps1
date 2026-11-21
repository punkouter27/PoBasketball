# Rebuilds every presentation asset of the 2026-11-17 plugins pass, in dependency order, headlessly.
# Cosmetic only: none of these touch sim/, shared/ or the policies. Close the editor first; don't run while training.
#
#   pwsh Scripts/build_presentation_assets.ps1 [-Blender] [-VoiceBake]
#
#   -Blender    also regenerate the Blender sources (env proxies, grandma cloth hem, groom) before importing
#   -VoiceBake  also re-bake the grandma voice (tools/voice_bake, needs uv) before importing
param([switch]$Blender, [switch]$VoiceBake)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$proj = Split-Path -Parent $here
$repo = Split-Path -Parent (Split-Path -Parent $proj)
$logs = Join-Path $proj "Saved\Logs\presentation"
New-Item -ItemType Directory -Force $logs | Out-Null
$blenderExe = "C:\Program Files\Blender Foundation\Blender 5.3\blender.exe"

if ($Blender) {
    $g = Join-Path $proj "Content\Art\Exports\Grandma"
    & $blenderExe -b --factory-startup --python (Join-Path $here "make_env_proxies_blender.py")
    & $blenderExe -b --factory-startup --python (Join-Path $here "split_grandma_cloth_blender.py") -- (Join-Path $g "SK_Grandma.fbx") (Join-Path $g "SK_Grandma_Cloth.fbx") $g
    & $blenderExe -b --factory-startup --python (Join-Path $here "make_grandma_groom_blender.py") -- (Join-Path $g "SK_Grandma.fbx") (Join-Path $g "Groom") (Join-Path $repo "docs\20261116\grandma_bones_ue.json")
}
if ($VoiceBake) {
    Push-Location $repo
    uv run tools/voice_bake/bake.py
    Pop-Location
}

$steps = @(
    @("make_metasounds.py", "METASOUNDS OK"),
    @("make_court_materials.py", "COURT_MATERIALS OK"),
    @("import_env_assets.py", "ENV_IMPORT OK"),
    @("make_niagara_fx.py", "NIAGARA_FX OK"),
    @("build_grandma_extras.py", "GRANDMA_EXTRAS OK"),
    @("import_voice_bank.py", "VOICE_IMPORT OK"),
    @("build_environment.py", "ENVIRONMENT OK")
)
foreach ($s in $steps) {
    $log = Join-Path $logs ($s[0] -replace "\.py$", ".log")
    & (Join-Path $here "run_headless.ps1") -TimeoutSec 2400 -LogFile $log -EditorArgs @("-run=pythonscript", "-script=$(Join-Path $here $s[0])")
    $ok = Select-String -Path $log -Pattern $s[1] -Quiet
    if (-not $ok) { Write-Host "FAILED: $($s[0]) (see $log)"; exit 1 }
    Write-Host "ok: $($s[0])"
}
Write-Host "presentation assets rebuilt"
