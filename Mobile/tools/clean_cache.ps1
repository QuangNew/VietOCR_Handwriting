# Run after Flutter/Gradle commands have finished. Preserves source, models and APK.
$ErrorActionPreference = 'Stop'
$taskMobileRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskApkSource = Join-Path $taskMobileRoot 'build/app/outputs/flutter-apk/app-release.apk'
$taskDist = Join-Path $taskMobileRoot 'dist'
if (Test-Path -LiteralPath $taskApkSource) {
    New-Item -ItemType Directory -Path $taskDist -Force | Out-Null
    Copy-Item -LiteralPath $taskApkSource -Destination (Join-Path $taskDist 'VietOCR-arm64.apk') -Force
}

$taskCachePaths = @(
    'build', '.dart_tool', '.flutter-plugins-dependencies',
    'android/.gradle', 'android/.kotlin', 'android/.cxx', 'android/app/.cxx',
    'android/app/build', 'tools/__pycache__'
)
$taskCacheBytes = 0L
foreach ($taskRelative in $taskCachePaths) {
    $taskTarget = [IO.Path]::GetFullPath((Join-Path $taskMobileRoot $taskRelative))
    if (-not $taskTarget.StartsWith($taskMobileRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cache target escapes Mobile: $taskRelative"
    }
    if (-not (Test-Path -LiteralPath $taskTarget)) { continue }
    $taskItem = Get-Item -LiteralPath $taskTarget -Force
    if ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to recurse through a linked cache: $taskRelative"
    }
    if ($taskItem.PSIsContainer) {
        $taskCacheBytes += (Get-ChildItem -LiteralPath $taskTarget -File -Recurse -Force | Measure-Object Length -Sum).Sum
        Remove-Item -LiteralPath $taskTarget -Recurse -Force
    } else {
        $taskCacheBytes += $taskItem.Length
        Remove-Item -LiteralPath $taskTarget -Force
    }
}
Write-Output ("Cleared {0:N1} MiB of project cache. Source, models and dist APK preserved." -f ($taskCacheBytes / 1MB))
