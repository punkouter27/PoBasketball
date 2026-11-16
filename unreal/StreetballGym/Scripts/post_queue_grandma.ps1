# Runs the Unreal half of the grandma skin AFTER the training queue exits (UU_AGENT: no editor while a long
# headless run is active, and the machine has < 3 GB commit headroom while training).
#   1. wait for `streetball.queue` to exit
#   2. import Content/Art/Exports/Grandma/SK_Grandma.fbx  -> /Game/Art/Characters/Grandma/SK_Grandma
#   3. build StreetballGymEditor (AStreetballCharacter::ApplyMainCharacterMesh)
#   4. dump SK_Grandma's bind joints and compare with shared/mannequin_bones.json (<= 1 cm)
#   5. run the Streetball automation tests (B5.BoneMapper checks the bind pose against the sim)
# Results: DOCS/<day>/post_queue_grandma.md
param([string]$Engine = "C:\Program Files\Epic Games\UE_5.8", [switch]$NoWait)
$ErrorActionPreference = "Continue"
$proj = Split-Path -Parent $PSScriptRoot
$repo = Resolve-Path (Join-Path $proj "..\..")
$uproject = Join-Path $proj "StreetballGym.uproject"
$headless = Join-Path $PSScriptRoot "run_headless.ps1"
$out = Join-Path $repo ("DOCS\{0}" -f (Get-Date -Format yyyyMMdd))
New-Item -ItemType Directory -Force $out | Out-Null
$md = Join-Path $out "post_queue_grandma.md"
$logs = Join-Path $proj "Saved\Logs\grandma"
New-Item -ItemType Directory -Force $logs | Out-Null
function Say($m) { $l = "- [$(Get-Date -Format HH:mm:ss)] $m"; Write-Host $l; Add-Content -Path $md -Value $l -Encoding utf8 }

if (-not (Test-Path $md)) { Set-Content -Path $md -Value "# Post-queue: grandma skin in Unreal`n" -Encoding utf8 }
if (-not $NoWait) {
    Say "waiting for the training queue to exit"
    while (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "streetball\.(queue|train|evaluate)" }) {
        Start-Sleep -Seconds 60
    }
    Say "training queue finished"
}

# 2. import
$log = Join-Path $logs "import.log"
& $headless -TimeoutSec 1800 -LogFile $log -- "-run=pythonscript" "-script=$(Join-Path $PSScriptRoot 'import_grandma.py')"
$ok = Select-String -Quiet -Path $log -Pattern "GRANDMA_IMPORT OK"
Say "import: rc=$LASTEXITCODE ok=$ok (log $log)"
if (-not $ok) { Say "STOP: import failed"; exit 1 }

# 3. build
$blog = Join-Path $logs "build.log"
& (Join-Path $Engine "Engine\Build\BatchFiles\Build.bat") StreetballGymEditor Win64 Development "-Project=$uproject" -WaitMutex *> $blog
$rc = $LASTEXITCODE
Say "build StreetballGymEditor: rc=$rc (log $blog)"
if ($rc -ne 0) { Say "STOP: build failed"; exit 1 }

# 4. bind-joint check
$dump = Join-Path $out "grandma_bones_ue.json"
$dlog = Join-Path $logs "dump.log"
& $headless -TimeoutSec 900 -LogFile $dlog -- "-run=pythonscript" "-script=$(Join-Path $PSScriptRoot 'dump_mannequin_bones.py') $dump /Game/Art/Characters/Grandma/SK_Grandma"
$cmp = & python (Join-Path $PSScriptRoot "compare_bones.py") (Join-Path $repo "shared\mannequin_bones.json") $dump --tol-cm 1.0 2>&1
Add-Content -Path $md -Value "`n``````n$($cmp -join "`n")`n```````n" -Encoding utf8
Say "bind-joint check vs Manny: rc=$LASTEXITCODE"

# 5. automation tests (headless, real RHI)
$tlog = Join-Path $logs "tests.log"
& $headless -TimeoutSec 1800 -LogFile $tlog -- "-ExecCmds=Automation RunTests Streetball; Quit" "-TestExit=Automation Test Queue Empty"
$pass = (Select-String -Path $tlog -Pattern "Test Completed\. Result=\{Success\}").Count
$fail = (Select-String -Path $tlog -Pattern "Test Completed\. Result=\{(Fail|Failed)\}").Count
$mesh = (Select-String -Path $tlog -Pattern "Character mesh: (\S+)" | Select-Object -Last 1).Matches.Groups[1].Value
Say "automation: $pass passed, $fail failed; character mesh in tests: $mesh (log $tlog)"
Say "done"
