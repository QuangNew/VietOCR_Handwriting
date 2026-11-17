$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$source=Join-Path $repo 'VietHandOCR_API_Release'
$config=Get-Content -LiteralPath (Join-Path $source 'model/model_config.json') -Raw|ConvertFrom-Json
if([IO.Path]::GetFileName($config.weights_file)-ne$config.weights_file){throw 'Unsafe model filename.'}
$deployed=Join-Path $repo ('Server/models/'+$config.name)
foreach($folder in @((Join-Path $source 'model'),$deployed)){
    $hash=(Get-FileHash -LiteralPath (Join-Path $folder $config.weights_file) -Algorithm SHA256).Hash.ToLowerInvariant()
    if($hash-ne$config.weights_sha256){throw 'Model hash mismatch. No file was changed.'}
}
if((Get-FileHash -LiteralPath (Join-Path $source 'viethandocr_lite.py')).Hash-ne(Get-FileHash -LiteralPath (Join-Path $repo 'Server/worker/core/recognizer.py')).Hash){throw 'AI recognizer and compute copy differ.'}
$ai=[IO.File]::ReadAllText((Join-Path $source 'AI.py')).Replace("`r`n","`n")
$runtime=[IO.File]::ReadAllText((Join-Path $repo 'Server/worker/core/preprocessing.py')).Replace("`r`n","`n")
$begin=$ai.IndexOf('class VietOCR_DIP_Pipeline:')
$end=$ai.IndexOf('# 3. CORE API CLASS')
$pipeline=$ai.Substring($begin,$end-$begin)
$pipeline=$pipeline.Substring(0,$pipeline.LastIndexOf('# =========================================================================')).Trim()
if(!$runtime.Contains($pipeline)){throw 'AI preprocessing differs from compute. Review before syncing.'}
[pscustomobject]@{WeightsSha256=$hash;RecognizerIdentical=$true;PreprocessingIdentical=$true;Model=$config.name;MutatedFiles=0}|ConvertTo-Json
