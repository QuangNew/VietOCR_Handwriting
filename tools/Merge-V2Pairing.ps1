#requires -Version 7.2
param([switch]$Apply)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$private=Join-Path $repo 'Server/server.local.json'
$patch=Get-Content -LiteralPath (Join-Path $repo '.toolchain/refactor/pairing/compute.patch.json') -Raw|ConvertFrom-Json -AsHashtable
$current=Get-Content -LiteralPath $private -Raw|ConvertFrom-Json -AsHashtable
if(!$current.Server -or !$current.Server.SupabaseServiceKey){throw 'Configure compute Supabase privately first; no configuration changed.'}
$allowed=@('GatewayIngressKeySha256','GatewayTelemetryKeySha256','PublicResultsOrigin','ServerId','LegacyClientApiEnabled','GatewayAutoScale')
if(@($patch.Keys|Where-Object {$_-notin@('AllowedHosts','Server')}).Count -or @($patch.Server.Keys|Where-Object {$_-notin$allowed}).Count){throw 'Unexpected pairing fields.'}
foreach($key in @('GatewayIngressKeySha256','GatewayTelemetryKeySha256')){if($patch.Server[$key]-notmatch'^[a-f0-9]{64}$'){throw 'Expected machine credential hash.'}}
$uri=[Uri]$patch.Server.PublicResultsOrigin
if(!$uri.IsAbsoluteUri -or ($uri.Scheme-ne'https' -and !($uri.Scheme-eq'http' -and $uri.IsLoopback)) -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath-ne'/'){throw 'Invalid public results origin.'}
if($patch.Server.LegacyClientApiEnabled-ne$false){throw 'Legacy client ingress must stay disabled.'}
$current.AllowedHosts=$patch.AllowedHosts
foreach($key in $allowed){if(!$patch.Server.ContainsKey($key)){throw 'Incomplete pairing patch.'};$current.Server[$key]=$patch.Server[$key]}
if(!$Apply){Write-Output 'Validated pairing patch. Use -Apply after reviewing the selected origins; Supabase/Python/worker settings are preserved.';return}
$temporary=$private+'.pairing.tmp'
try{
    $acl=Get-Acl -LiteralPath $private
    New-Item -ItemType File -Path $temporary -Force|Out-Null
    Set-Acl -LiteralPath $temporary -AclObject $acl
    [IO.File]::WriteAllText($temporary,($current|ConvertTo-Json -Depth 12))
    [IO.File]::Move($temporary,$private,$true)
}finally{if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary};$current=$null;$patch=$null}
Write-Output 'Merged pairing fields only. Restart the project compute host; no credentials were printed.'
