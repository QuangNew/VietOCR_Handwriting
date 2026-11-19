$ErrorActionPreference='Stop'
$serverRoot=Split-Path $PSScriptRoot -Parent
Push-Location $serverRoot
try { & dotnet run --project 'backend/VietOcr.Server/VietOcr.Server.csproj' -- --create-admin }
finally { Pop-Location }
