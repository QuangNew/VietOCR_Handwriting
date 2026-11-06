param([string]$ProjectRef='rrdxhztiikizgogxtlhu', [switch]$SkipInstall)
$ErrorActionPreference='Stop'
$serverRoot=Split-Path $PSScriptRoot -Parent
$repoRoot=Split-Path $serverRoot -Parent
$pythonPath=Join-Path $repoRoot 'VietHandOCR_API_Release/.venv/Scripts/python.exe'
& $pythonPath -X utf8 (Join-Path $PSScriptRoot 'configure_supabase.py') --project-ref $ProjectRef
if($LASTEXITCODE -ne 0){throw 'Supabase configuration failed. Login/link with Supabase CLI first.'}
$account=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe (Join-Path $serverRoot 'server.local.json') /inheritance:r /grant:r "${account}:(F)" | Out-Null
$runtimePath=Join-Path $serverRoot 'runtime'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
& icacls.exe $runtimePath /inheritance:r /grant:r "${account}:(OI)(CI)(F)" | Out-Null
if(-not $SkipInstall){
    & dotnet restore (Join-Path $serverRoot 'backend/VietOcr.Server/VietOcr.Server.csproj')
    if($LASTEXITCODE -ne 0){throw 'Backend restore failed.'}
    Push-Location (Join-Path $serverRoot 'web')
    try { $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1'; & npm.cmd ci --no-audit --no-fund; if($LASTEXITCODE -ne 0){throw 'npm install failed.'} }
    finally { Pop-Location }
}
Write-Host 'Configured. Apply SQL migrations in supabase/migrations once, create an admin if needed, build, then run Run-Server.cmd.'
