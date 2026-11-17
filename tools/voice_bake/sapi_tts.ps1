# Offline Windows SAPI (System.Speech) batch synthesizer used by bake.py.
# Usage: pwsh -File sapi_tts.ps1 -Jobs jobs.json
# jobs.json: [{"ssml": "<speak ...>...</speak>", "out": "C:/path/raw.wav"}, ...]
param([Parameter(Mandatory=$true)][string]$Jobs, [switch]$ListVoices)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($ListVoices) {
  $synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
    "{0}|{1}|{2}|{3}" -f $_.VoiceInfo.Name, $_.VoiceInfo.Gender, $_.VoiceInfo.Age, $_.VoiceInfo.Culture }
  exit 0
}
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$list = Get-Content -Raw -Encoding UTF8 $Jobs | ConvertFrom-Json
foreach ($j in $list) {
  $synth.SetOutputToWaveFile($j.out, $fmt)
  $synth.SpeakSsml($j.ssml)
  $synth.SetOutputToNull()
  Write-Output ("ok " + $j.out)
}
$synth.Dispose()
