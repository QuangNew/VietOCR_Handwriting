$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$outputRoot=Join-Path $projectRoot 'dist'
$compiler='C:\msys64\ucrt64\bin\g++.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'The existing MSYS2 UCRT compiler is required; no automatic download is performed.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.venv/Scripts/python.exe'))) { throw 'Existing .venv Python is required.' }
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$executable=Join-Path $outputRoot 'VietOCR.exe'
$env:PATH='C:\msys64\ucrt64\bin;'+$env:PATH
& $compiler '-std=c++17' '-Os' '-Wall' '-Wextra' '-Werror' '-municode' '-mwindows' '-static' '-static-libgcc' '-static-libstdc++' (Join-Path $PSScriptRoot 'desktop_launcher.cpp') '-o' $executable '-lshell32' '-luser32'
if ($LASTEXITCODE -ne 0) { throw 'Desktop launcher build failed.' }
$check=Start-Process -FilePath $executable -ArgumentList '--check' -WindowStyle Hidden -Wait -PassThru
if ($check.ExitCode -ne 0) { throw "Desktop environment check failed: $($check.ExitCode)" }
@'
VietOCR OV5640 desktop test build
Open VietOCR.exe here, or use ../Run-VietOCR.cmd.
This small Windows launcher uses the Python environment, model and source in the parent project.
Keep it under VietHandOCR_API_Release/dist; it is not a standalone portable distribution.
The independent debug terminal stays open if the GUI crashes. Logs: ../.logs.
Requires firmware OV5640 3.0.0; preview is UDP, captures are original 5 MP JPEGs over HTTP.
'@ | Set-Content -LiteralPath (Join-Path $outputRoot 'README.txt') -Encoding utf8
Get-Item -LiteralPath $executable | Select-Object FullName,Length
Get-FileHash -LiteralPath $executable -Algorithm SHA256
