param([switch]$Dev, [switch]$Lan, [int]$WebPort=3000)
$ErrorActionPreference='Stop'
$serverRoot=Split-Path $PSScriptRoot -Parent
$projectPath=Join-Path $serverRoot 'backend/VietOcr.Server/VietOcr.Server.csproj'
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
$env:NEXT_TELEMETRY_DISABLED='1'
$ApiPort=5080
foreach($port in @($ApiPort,$WebPort)) {
    if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){throw "Port $port is already in use. Stop the existing server before starting another instance."}
}
if (-not (Test-Path -LiteralPath (Join-Path $serverRoot 'server.local.json'))) { throw 'Run Setup-Server.ps1 to configure Supabase first.' }
if ($Lan) { $env:Server__AllowInsecureLan='true'; $env:AllowedHosts='*' }
$apiBind=if($Lan){'0.0.0.0'}else{'127.0.0.1'}
dotnet build $projectPath -c Release --nologo
if($LASTEXITCODE -ne 0){throw 'Backend build failed.'}
$env:VIETOCR_API_ORIGIN="http://127.0.0.1:$ApiPort"
if(-not $Dev){
    Push-Location (Join-Path $serverRoot 'web')
    try{
        & npm.cmd run build
        if($LASTEXITCODE -ne 0){throw 'Next.js build failed.'}
    }finally{Pop-Location}
}
$dll=Join-Path $serverRoot 'backend/VietOcr.Server/bin/Release/net10.0/VietOcr.Server.dll'
$logRoot=Join-Path $serverRoot 'runtime/logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$outputLog=Join-Path $logRoot "api-$stamp.log"
$errorLog=Join-Path $logRoot "api-$stamp.error.log"
$backendArguments=@(('"'+$dll+'"'),'--urls',"http://${apiBind}:$ApiPort")
$backend=Start-Process dotnet -ArgumentList $backendArguments -WorkingDirectory $serverRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $outputLog -RedirectStandardError $errorLog
Write-Host "Dashboard: http://127.0.0.1:$WebPort | API: http://${apiBind}:$ApiPort"
Write-Host "API log: $outputLog"
try {
    $env:VIETOCR_API_ORIGIN="http://127.0.0.1:$ApiPort"
    Push-Location (Join-Path $serverRoot 'web')
    try {
        if($Dev){ & npm.cmd exec -- next dev --hostname $apiBind --port $WebPort }
        else { & npm.cmd exec -- next start --hostname $apiBind --port $WebPort }
    } finally { Pop-Location }
} finally {
    # Stop only this launcher-owned backend tree; unrelated services are untouched.
    if(-not $backend.HasExited){ & taskkill.exe /PID $backend.Id /T /F | Out-Null }
}
