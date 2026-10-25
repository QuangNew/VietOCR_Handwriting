$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$libraryRoot = Join-Path $projectRoot 'lib/VietMusic/src'
$outputRoot = Join-Path $projectRoot '.pio/host-tests'
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$compiler = (Get-Command g++ -ErrorAction Stop).Source
$baseFlags = @('-std=c++11', '-Wall', '-Wextra', '-Werror', "-I$libraryRoot", "-I$projectRoot/include")

function Invoke-HostTest {
    param([string]$Name, [string[]]$Sources, [string[]]$ExtraFlags = @())
    $executable = Join-Path $outputRoot "$Name.exe"
    & $compiler @baseFlags @ExtraFlags @Sources '-o' $executable
    if ($LASTEXITCODE -ne 0) { throw "Compile failed: $Name" }
    & $executable
    if ($LASTEXITCODE -ne 0) { throw "Test failed: $Name" }
}

$musicSources = @("$libraryRoot/VietMusic.cpp", "$libraryRoot/VietMusicSongs.cpp")
Invoke-HostTest 'assistant_logic' ($musicSources + @("$projectRoot/src/assistant_logic.cpp", "$projectRoot/test/test_assistant_logic.cpp"))
Invoke-HostTest 'music' ($musicSources + @("$projectRoot/test/test_music.cpp"))
$driverSources = @("$libraryRoot/VietMusicOutput.cpp", "$projectRoot/test/test_music_output.cpp")
$fakeInclude = "-I$projectRoot/test/fakes"
Invoke-HostTest 'music_output_core2' $driverSources @($fakeInclude)
Invoke-HostTest 'music_output_core3' $driverSources @($fakeInclude, '-DESP_ARDUINO_VERSION_MAJOR=3')
