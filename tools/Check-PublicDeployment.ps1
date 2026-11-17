#requires -Version 7.2
param([string]$Gateway='https://api.quangnew.tech',[string]$Compute='https://ocr.quangnew.tech')
$ErrorActionPreference='Stop'
foreach($origin in @($Gateway,$Compute)){
    $uri=[Uri]$origin
    if(!$uri.IsAbsoluteUri -or $uri.Scheme-ne'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath-ne'/'){throw 'Expected a public HTTPS origin.'}
}
$checks=@(
    @{name='Gateway health';url=$Gateway+'/health/live';status=200;health=$true},
    @{name='Camera requires Google';url=$Gateway+'/api/v2/cameras';status=401},
    @{name='Compute machine ingress protected';url=$Compute+'/api/internal/v2/status';status=401},
    @{name='Direct result requires ticket';url=$Compute+'/api/v2/results/00000000-0000-4000-8000-000000000001';status=401},
    @{name='Admin is not public';url=$Compute+'/api/admin/auth/csrf';status=404},
    @{name='Legacy OCR is not public';url=$Compute+'/api/v1/jobs';status=404}
)
$results=foreach($check in $checks){
    try{
        $response=Invoke-WebRequest -Uri $check.url -SkipHttpErrorCheck -TimeoutSec 15 -MaximumRedirection 0
        $pass=[int]$response.StatusCode-eq$check.status
        if($check.health){try{$body=$response.Content|ConvertFrom-Json;$pass=$pass-and$body.service-eq'raspberry-gateway'-and$body.status-eq'alive'}catch{$pass=$false}}
        if($response.Headers['CF-Cache-Status'] -contains 'HIT'){$pass=$false}
        [pscustomobject]@{Check=$check.name;Http=[int]$response.StatusCode;Passed=$pass}
    }catch{[pscustomobject]@{Check=$check.name;Http=$null;Passed=$false}}
}
$results|Format-Table
if(@($results|Where-Object {!$_.Passed}).Count){throw 'Public deployment not ready. Check DNS, active connectors, backend and ingress rules; no credential or OAuth test was performed.'}
Write-Output 'Public routing/TLS and anonymous denial checks PASS. A real Google-to-OCR check is still required.'
