[CmdletBinding()]
param([switch]$Apply, [switch]$RemoveFirmwareSources, [switch]$RemoveGeneratedBuilds)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\','/')
$taskCacheRoot = [IO.Path]::GetFullPath((Join-Path $taskRoot '.toolchain'))
$taskTargets = [Collections.Generic.List[string]]::new()
if ($RemoveGeneratedBuilds) {
    foreach ($taskBuild in @('Mobile/build','target/debug')) {
        $taskBuildPath=Join-Path $taskRoot $taskBuild
        if(Test-Path -LiteralPath $taskBuildPath){$taskTargets.Add($taskBuildPath)}
    }
}

if ($RemoveFirmwareSources -and (Test-Path -LiteralPath (Join-Path $taskRoot 'pbl4'))) {
    # Source is recoverable from the base branch/history. Never delete uncommitted firmware edits.
    $taskDirty = & git -C $taskRoot status --porcelain -- pbl4
    if ($LASTEXITCODE -ne 0 -or $taskDirty) { throw 'pbl4 has local edits or Git cannot verify it. Commit/back up those edits before cleanup.' }
    & git -C $taskRoot cat-file -e 'HEAD:pbl4'
    if ($LASTEXITCODE -ne 0) { throw 'Firmware source is not present in Git HEAD; refusing deletion.' }
    $taskTargets.Add((Join-Path $taskRoot 'pbl4'))
}
if (Test-Path -LiteralPath $taskCacheRoot) {
    foreach ($taskItem in Get-ChildItem -LiteralPath $taskCacheRoot -Force) {
        # Explicit legacy ESP32 test/build prefixes and obsolete Android binary backups.
        # Keep AI models, Python environments, JDK/SDK, current Android dist and refactor evidence.
        if ($taskItem.Name -match '^(ov5640[-_]|camera[-_]|firmware[-_]|tft[-_]|blewifi[-_]|coex[-_]|music[-_]|autowifi[-_]|wifi[-_])' -or
            $taskItem.Name -match '^VietOCR-arm64-\d.*\.apk$' -or
            $taskItem.Name -in @('previous-VietOCR-arm64.apk','VietOCR-OV5640-3.0.0-backup.bin',
                'assistant_logic_music_tests.exe','assistant_logic_tests.exe','music_output_core2_tests.exe','music_output_core3_tests.exe','music_tests.exe')) {
            $taskTargets.Add($taskItem.FullName)
        }
    }
}
$taskManifest = foreach ($taskPath in $taskTargets) {
    $taskResolved = (Resolve-Path -LiteralPath $taskPath).ProviderPath.TrimEnd('\','/')
    if (-not $taskResolved.StartsWith($taskRoot + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup path escapes workspace: $taskResolved"
    }
    $taskItem = Get-Item -LiteralPath $taskResolved -Force
    if ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing reparse point: $taskResolved" }
    $taskFiles = if ($taskItem.PSIsContainer) { @(Get-ChildItem -LiteralPath $taskResolved -Recurse -File -Force) } else { @($taskItem) }
    [pscustomobject]@{ Path=$taskResolved; Files=$taskFiles.Count; Bytes=($taskFiles | Measure-Object Length -Sum).Sum }
}
$taskTotal = [long](($taskManifest | Measure-Object Bytes -Sum).Sum)
$taskReportRoot = Join-Path $taskCacheRoot 'refactor'
if ($Apply) {
    New-Item -ItemType Directory -Path $taskReportRoot -Force | Out-Null
    $taskReportName=if($RemoveGeneratedBuilds){'generated-build-cleanup.json'}else{'legacy-iot-cleanup.json'}
    $taskManifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $taskReportRoot $taskReportName) -Encoding utf8
    # Every absolute path was resolved and checked above, in this same PowerShell process.
    foreach ($taskEntry in $taskManifest) { Remove-Item -LiteralPath $taskEntry.Path -Force -Recurse }
}
[pscustomobject]@{ Applied=[bool]$Apply; Paths=@($taskManifest).Count; Files=($taskManifest | Measure-Object Files -Sum).Sum;
    Bytes=$taskTotal; GiB=[math]::Round($taskTotal/1GB,3); Recovery='Tracked pbl4 source: Git base e26faae; generated caches/APK backups can be rebuilt.' } | ConvertTo-Json
