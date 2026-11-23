# Opens the training Benchmark page (benchmark/page.html) for this repo: one button runs ~10 s of the real training
# loop (sim/streetball/train.py) and records step time, machine and machine load in benchmark/history.json
# (commit it to compare laptops).
# -Run: no page; runs one Benchmark in this console, records it in benchmark/history.json and exits 0 (recorded) or 1.
$ErrorActionPreference = 'Stop'
$py = Join-Path $PSScriptRoot 'sim/.venv/Scripts/python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'Creating the training environment (uv sync in sim/, see docs/env_setup.md)...'
    Push-Location (Join-Path $PSScriptRoot 'sim'); uv sync; Pop-Location
}
& $py (Join-Path $PSScriptRoot 'benchmark/serve.py') @args
exit $LASTEXITCODE
