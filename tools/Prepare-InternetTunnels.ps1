param(
    [string]$GatewayHost='api.quangnew.tech',
    [string]$ComputeHost='ocr.quangnew.tech',
    [string]$Cloudflared='.toolchain/cloudflared/cloudflared-windows-amd64.exe'
)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$binary=[IO.Path]::GetFullPath((Join-Path $repo $Cloudflared))
foreach($hostname in @($GatewayHost,$ComputeHost)){
    if($hostname -notmatch '^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$' -or $hostname -notlike '*.quangnew.tech'){throw 'Use an explicitly selected project subdomain.'}
}
if($GatewayHost-eq$ComputeHost){throw 'Gateway and compute require distinct public hosts.'}
if(!(Test-Path -LiteralPath $binary)){throw 'Install the verified official cloudflared binary first.'}
$certificate=Join-Path $env:USERPROFILE '.cloudflared/cert.pem'
if(!(Test-Path -LiteralPath $certificate)){throw 'Complete cloudflared tunnel login in the browser first; never paste the certificate into chat.'}
$destination=Join-Path $repo '.toolchain/refactor/tunnels'
New-Item -ItemType Directory -Path $destination -Force|Out-Null
function Find-Tunnel([string]$name){
    $json=& $binary tunnel list --output json
    if($LASTEXITCODE-ne0){throw 'Cannot read named tunnels; verify Cloudflare authorization.'}
    $matching=@($json|ConvertFrom-Json|Where-Object {$_.name-eq$name})
    if($matching.Count-gt1){throw 'Ambiguous tunnel name; inspect the Cloudflare dashboard.'}
    if($matching.Count-eq1){return $matching[0]}
    return $null
}
$tunnels=@{}
foreach($entry in @(@{name='vietocr-pi';host=$GatewayHost},@{name='vietocr-compute';host=$ComputeHost})){
    $tunnel=Find-Tunnel $entry.name
    if(!$tunnel){& $binary tunnel create $entry.name;if($LASTEXITCODE-ne0){throw 'Tunnel creation failed.'};$tunnel=Find-Tunnel $entry.name}
    if(!$tunnel -or $tunnel.id-notmatch'^[0-9a-f-]{36}$'){throw 'Invalid tunnel id.'}
    $credential=Join-Path $env:USERPROFILE ('.cloudflared/'+$tunnel.id+'.json')
    if(!(Test-Path -LiteralPath $credential)){throw 'Existing tunnel credential is missing on this machine; do not create duplicate tunnels or overwrite DNS.'}
    # No overwrite flag: a conflicting DNS record must be reviewed, not destroyed.
    & $binary tunnel route dns $tunnel.id $entry.host
    if($LASTEXITCODE-ne0){throw ('DNS route failed for '+$entry.host+'; no overwrite was attempted.')}
    $tunnels[$entry.name]=@{id=$tunnel.id;credential=$credential;host=$entry.host}
}
$pi=$tunnels['vietocr-pi'];$compute=$tunnels['vietocr-compute']
$piText=[IO.File]::ReadAllText((Join-Path $repo 'infra/tunnel/pi.example.yml')).Replace('REPLACE_PI_TUNNEL_UUID',$pi.id).Replace('api.quangnew.tech',$GatewayHost)
$computeText=[IO.File]::ReadAllText((Join-Path $repo 'infra/tunnel/compute.example.yml')).Replace('REPLACE_COMPUTE_TUNNEL_UUID',$compute.id).Replace('C:/ProgramData/cloudflared/'+$compute.id+'.json',$compute.credential.Replace('\','/')).Replace('ocr.quangnew.tech',$ComputeHost)
[IO.File]::WriteAllText((Join-Path $destination 'pi.yml'),$piText)
[IO.File]::WriteAllText((Join-Path $destination 'compute.yml'),$computeText)
# Copy only Pi connector credentials, never the account-management certificate.
Copy-Item -LiteralPath $pi.credential -Destination (Join-Path $destination ($pi.id+'.json')) -Force
$account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $destination /inheritance:r /grant:r ($account+':(OI)(CI)F') /Q|Out-Null
Get-ChildItem -LiteralPath $destination -File|ForEach-Object {& icacls $_.FullName /grant:r ($account+':F') /inheritance:r /Q|Out-Null}
if($LASTEXITCODE-ne0){throw 'Cannot protect local tunnel files.'}
foreach($name in @('pi','compute')){& $binary --config (Join-Path $destination ($name+'.yml')) tunnel ingress validate;if($LASTEXITCODE-ne0){throw 'Ingress validation failed.'}}
Write-Output ('Prepared project connectors in '+$destination)
Write-Output 'Install only pi.yml and its UUID credential on Pi. Compute runs on Windows. Pairing must be switched only after HTTPS connectivity checks pass.'
