#requires -Version 7.2
param(
    [string]$ComputeOrigin='http://127.0.0.1:5080',
    [string]$ResultsOrigin='http://127.0.0.1:5080',
    [string]$OutputDirectory='.toolchain/refactor/pairing',
    [switch]$Rotate
)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$destination=[IO.Path]::GetFullPath((Join-Path $repo $OutputDirectory))
$privateRoot=[IO.Path]::GetFullPath((Join-Path $repo '.toolchain')).TrimEnd('\','/')
if(!$destination.StartsWith($privateRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Pairing files must stay under the ignored .toolchain directory.'}
foreach($origin in @($ComputeOrigin,$ResultsOrigin)){
    $uri=[Uri]$origin
    if(!$uri.IsAbsoluteUri -or ($uri.Scheme-ne'https' -and !($uri.Scheme-eq'http' -and $uri.IsLoopback)) -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath-ne'/'){throw 'Use an HTTPS origin or a loopback HTTP development origin.'}
}
New-Item -ItemType Directory -Path $destination -Force|Out-Null
if(!$IsWindows){throw 'Prepare pairing on Windows with PowerShell7; copy only Pi credentials to the Linux host.'}
# Secure the folder before creating any credential, including failure paths.
$account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $destination /inheritance:r /grant:r ($account+':(OI)(CI)F') /Q|Out-Null
if($LASTEXITCODE-ne0){throw 'Cannot protect pairing directory before writing credentials.'}
$public=Get-Content -LiteralPath (Join-Path $repo 'apps/android/assets/config/supabase.json') -Raw|ConvertFrom-Json
$tokens=@{}
foreach($name in @('ingress','telemetry')){
    $file=Join-Path $destination ($name+'.token')
    if($Rotate -or !(Test-Path -LiteralPath $file)){
        $token=[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
        [IO.File]::WriteAllText($file,$token)
    }else{$token=[IO.File]::ReadAllText($file).Trim()}
    if($token-notmatch'^[a-zA-Z0-9_-]{32,256}$'){throw 'Invalid machine token file.'}
    $tokens[$name]=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($token))).ToLowerInvariant()
}
$gateway=Get-Content -LiteralPath (Join-Path $repo 'services/gateway/config.example.json') -Raw|ConvertFrom-Json
$gateway.auth.supabaseUrl=$public.url;$gateway.auth.publishableKey=$public.publishableKey
$gateway.compute=@{origin=$ComputeOrigin.TrimEnd('/');publicResultsOrigin=$ResultsOrigin.TrimEnd('/');tokenFile='/etc/vietocr/ingress.token';concurrentUploads=4}
$gateway.telemetry=@{url=$ComputeOrigin.TrimEnd('/')+'/api/internal/v2/status';tokenFile='/etc/vietocr/telemetry.token'}
$patch=@{AllowedHosts='localhost;127.0.0.1;[::1];'+([Uri]$ComputeOrigin).Host+';'+([Uri]$ResultsOrigin).Host;Server=@{
    GatewayIngressKeySha256=$tokens.ingress;GatewayTelemetryKeySha256=$tokens.telemetry;
    PublicResultsOrigin=$ResultsOrigin.TrimEnd('/');ServerId='compute-1';LegacyClientApiEnabled=$false;GatewayAutoScale=$true
}}
[IO.File]::WriteAllText((Join-Path $destination 'gateway.json'),($gateway|ConvertTo-Json -Depth 12))
[IO.File]::WriteAllText((Join-Path $destination 'compute.patch.json'),($patch|ConvertTo-Json -Depth 6))
if($IsWindows){
    $account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $destination /inheritance:r /grant:r ($account+':(OI)(CI)F') /Q | Out-Null
    foreach($name in @('ingress.token','telemetry.token','gateway.json','compute.patch.json')){
        & icacls (Join-Path $destination $name) /grant:r ($account+':F') /inheritance:r /Q | Out-Null
    }
    if($LASTEXITCODE-ne0){throw 'Cannot protect pairing directory ACL.'}
}
$token=$null;$tokens=$null
Write-Output ('Created private pairing files in '+$destination)
Write-Output 'Merge compute.patch.json into server.local.json; do not replace the Supabase/Python settings.'
Write-Output 'Copy gateway.json and the two .token files to /etc/vietocr on Pi with mode0600. Never commit them.'
