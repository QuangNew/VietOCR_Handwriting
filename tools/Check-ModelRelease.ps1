$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$folder = Join-Path $repo 'services/compute/models/ML_s44'
$config = Get-Content -LiteralPath (Join-Path $folder 'model_config.json') -Raw | ConvertFrom-Json
if ($config.name -ne 'ML_s44' -or [IO.Path]::GetFileName($config.weights_file) -ne $config.weights_file) {
    throw 'Invalid checkpoint configuration.'
}
$weights = Join-Path $folder $config.weights_file
$hash = (Get-FileHash -LiteralPath $weights -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hash -ne $config.weights_sha256) { throw 'Checkpoint SHA-256 mismatch.' }
[pscustomobject]@{ Model = $config.name; Path = $weights; Verified = $true; Bytes = (Get-Item -LiteralPath $weights).Length }
