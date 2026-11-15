Set-Location (Split-Path -Parent $PSScriptRoot)
uv run tensorboard --logdir runs --port 6006 *> tensorboard.log
