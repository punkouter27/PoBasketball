# 2026-11-08 night: 8 h unattended plan "urgent_20261108" (dribble l2a_push -> scramble -> dribble -> scramble).
# Launched hidden via WMI Win32_Process.Create (ShowWindow=0) so it survives the Claude session.
Set-Location "C:\Users\punko\Downloads\CODE_MATT\PoBasketball\sim"
uv run python -m streetball.queue --plan urgent_20261108 --hours 8 --tag n9 *> runs\night_20261108_stdout.txt
