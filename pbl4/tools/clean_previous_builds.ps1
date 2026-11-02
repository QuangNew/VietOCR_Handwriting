$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '..'))
$newBinary = Join-Path $projectRoot '.pio/build/esp32-s3-cam-ov5640/firmware.bin'
if (-not (Test-Path -LiteralPath $newBinary -PathType Leaf)) { throw 'Build the OV5640 firmware before cleaning previous builds.' }
$targets = @(
    '.pio/build/esp32-s3-devkitc-1', '.pio/build/esp32-s3-cam-ov3660',
    '.pio/libdeps/esp32-s3-devkitc-1', '.pio/libdeps/esp32-s3-cam-ov3660',
    'diagnostics/camera_probe/.pio', 'diagnostics/tft_probe/.pio'
) | ForEach-Object { Join-Path $projectRoot $_ }
foreach ($directory in @((Join-Path $projectRoot 'dist'), (Join-Path $workspaceRoot '.toolchain'))) {
    if (Test-Path -LiteralPath $directory -PathType Container) {
        $targets += Get-ChildItem -LiteralPath $directory -File | Where-Object {
            $_.Extension -in '.bin', '.elf', '.map' -and
            ($_.BaseName -like 'VietOCR-legacy*' -or $_.BaseName -like 'VietOCR-OV3660*')
        } | ForEach-Object { $_.FullName }
    }
}
$records = @()
foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target)) { continue }
    # Validate each resolved absolute path in this shell immediately before removal.
    $resolved = (Resolve-Path -LiteralPath $target).Path
    if (-not $resolved.StartsWith($workspaceRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing path outside workspace: $resolved" }
    if ($resolved -like '*esp32-s3-cam-ov5640*') { throw "Refusing current build: $resolved" }
    $item = Get-Item -LiteralPath $resolved -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing junction/link: $resolved" }
    $bytes = if ($item.PSIsContainer) { (Get-ChildItem -LiteralPath $resolved -Recurse -File -Force | Measure-Object Length -Sum).Sum } else { $item.Length }
    Remove-Item -LiteralPath $resolved -Recurse -Force
    $records += [pscustomobject]@{ path=$resolved.Substring($workspaceRoot.Length+1); bytes=[long]$bytes }
}
$report = [pscustomobject]@{
    date='2026-11-02'; removed=$records; freed_bytes=[long](($records | Measure-Object bytes -Sum).Sum)
    kept=@('esp32-s3-cam-ov5640 build/libdeps', 'all source files', 'hardware test reports/logs', 'global toolchains', 'desktop and mobile builds')
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $projectRoot 'docs/ov5640-cleanup.json') -Encoding utf8
$report | Select-Object date,freed_bytes,@{Name='freed_MiB';Expression={[math]::Round($_.freed_bytes/1MB,1)}}
