$ErrorActionPreference='Stop'
$serverRoot=Split-Path $PSScriptRoot -Parent
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
$env:NEXT_TELEMETRY_DISABLED='1'
& dotnet build (Join-Path $serverRoot 'backend/VietOcr.Server/VietOcr.Server.csproj') -c Release --nologo
if($LASTEXITCODE -ne 0){throw 'Backend build failed.'}
Push-Location (Join-Path $serverRoot 'web')
try {
    & npm.cmd run build
    if($LASTEXITCODE -ne 0){throw 'Next.js build failed.'}
} finally {Pop-Location}
Write-Host 'C# Release and Next.js production builds ready. Run tools/Start-Server.ps1.'
