# Runs UnrealEditor-Cmd headlessly with a hard wall-clock timeout so a hung editor can never
# block a CI step or a developer. Never touches any other process.
#
#   pwsh Scripts/run_headless.ps1 -TimeoutSec 900 -LogFile out.log -- -ExecCmds="Automation RunTests Streetball; Quit" [-GateReplay=...]
#
# Exit code: the editor's exit code, or 124 on timeout (editor killed).
param(
    [int]$TimeoutSec = 900,
    [string]$LogFile = "",
    [string]$Editor = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$EditorArgs
)
$ErrorActionPreference = "Stop"
$project = Join-Path (Split-Path -Parent $PSScriptRoot) "StreetballGym.uproject"
# Start-Process joins the list with spaces and does not quote, so quote anything containing whitespace
# (e.g. -ExecCmds=Automation RunTests X; Quit) or the editor would see it as several arguments.
$quoted = foreach ($a in $EditorArgs) { if ($a -match '\s' -and $a -notmatch '^".*"$') { '"' + $a + '"' } else { $a } }
$args = @("`"$project`"") + $quoted + @("-unattended", "-nosplash", "-nop4", "-stdout", "-FullStdOutLogOutput")
if ($LogFile -eq "") { $LogFile = Join-Path $env:TEMP ("ue_headless_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss")) }
$p = Start-Process -FilePath $Editor -ArgumentList $args -PassThru -NoNewWindow -RedirectStandardOutput $LogFile -RedirectStandardError ($LogFile + ".err")
try {
    Wait-Process -Id $p.Id -Timeout $TimeoutSec -ErrorAction Stop
    exit $p.ExitCode
} catch {
    Write-Host "TIMEOUT after $TimeoutSec s: killing UnrealEditor-Cmd pid $($p.Id)"
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    exit 124
}
