param([switch]$Stop)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$binary=Join-Path $repo '.toolchain/cloudflared/cloudflared-windows-amd64.exe'
$config=Join-Path $repo '.toolchain/refactor/tunnels/compute.yml'
$stateFile=Join-Path $repo '.toolchain/refactor/tunnels/compute-process.json'
if(Test-Path -LiteralPath $stateFile){
    $saved=Get-Content -LiteralPath $stateFile -Raw|ConvertFrom-Json
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$saved.pid)
    if($process -and $process.ExecutablePath-eq$binary -and $process.CommandLine.Contains($config)){
        if($Stop){Stop-Process -Id $saved.pid;Remove-Item -LiteralPath $stateFile;Write-Output 'Stopped the project compute connector.';return}
        Write-Output ('Project compute connector already running, pid='+$saved.pid);return
    }
}
if($Stop){Write-Output 'No matching project connector is running.';return}
if(!(Test-Path -LiteralPath $config)){throw 'Prepare authorized named tunnels first.'}
& $binary --config $config tunnel ingress validate
if($LASTEXITCODE-ne0){throw 'Invalid ingress rules.'}
$folder=Split-Path $stateFile -Parent
$taskProcess=Start-Process -FilePath $binary -ArgumentList @('--no-autoupdate','--config',('"'+$config+'"'),'tunnel','run') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $folder 'compute.out.log') -RedirectStandardError (Join-Path $folder 'compute.err.log')
@{pid=$taskProcess.Id;config=$config;startedAt=[DateTime]::UtcNow.ToString('O')}|ConvertTo-Json|Set-Content -LiteralPath $stateFile
Write-Output ('Started project compute connector, pid='+$taskProcess.Id)
