param([string]$Gateway='https://api.quangnew.tech')
$ErrorActionPreference='Stop'
if($env:OS -ne 'Windows_NT'){throw 'Windows current-user DPAPI is required.'}
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$origin=[Uri]$Gateway
if(!$origin.IsAbsoluteUri -or ($origin.Scheme-ne'https' -and !($origin.Scheme-eq'http' -and $origin.IsLoopback)) -or $origin.UserInfo -or $origin.Query -or $origin.Fragment -or $origin.AbsolutePath-ne'/'){throw 'Use an HTTPS origin or loopback development origin.'}
$destination=Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'vn.pbl4.vietocr.desktop'
$sessionFile=Join-Path $destination 'session.dpapi'
if(Test-Path -LiteralPath $sessionFile){Write-Output 'A native desktop session already exists; kept unchanged.';return}
$legacy=Join-Path $repo 'VietHandOCR_API_Release/.desktop-preferences.json'
if(!(Test-Path -LiteralPath $legacy)){Write-Output 'No previous desktop session. Sign in with Google in the new app.';return}
$raw=Get-Content -LiteralPath $legacy -Raw|ConvertFrom-Json
if(!$raw.google_session_dpapi){Write-Output 'No previous Google session. Sign in normally.';return}
$plain=[Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($raw.google_session_dpapi),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
try{
    $previous=[Text.Encoding]::UTF8.GetString($plain)|ConvertFrom-Json
    $user=[Guid]$previous.user.id
    if($user-eq[Guid]::Empty -or !$previous.refresh_token -or !$previous.access_token){throw 'Invalid previous session; sign in normally.'}
    $session=@{user_id=$user.ToString();email=[string]$previous.user.email;access_token=$previous.access_token;refresh_token=$previous.refresh_token;expires_at=[long][math]::Floor($previous.expires_at)}|ConvertTo-Json -Compress
    $cipher=[Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($session),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    New-Item -ItemType Directory -Path $destination -Force|Out-Null
    [IO.File]::WriteAllBytes($sessionFile,$cipher)
    $public=Get-Content -LiteralPath (Join-Path $repo 'Mobile/assets/config/supabase.json') -Raw|ConvertFrom-Json
    if(!(Test-Path -LiteralPath (Join-Path $destination 'config.json'))){
        @{gateway=$Gateway.TrimEnd('/');supabaseUrl=$public.url;publishableKey=$public.publishableKey}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $destination 'config.json')
    }
    # Do not create verified/account markers. The native client must still ask
    # the real gateway to verify provider/session/ban before opening the workspace.
    Write-Output ('Migrated the current user''s encrypted Google session to '+$destination)
}finally{[Array]::Clear($plain);$previous=$null;$session=$null;$cipher=$null;$raw=$null}
