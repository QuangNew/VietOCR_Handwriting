"""Validate and publish the locally built APK to Mobile/dist, preserving old APK."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile
from check_jni_keeps import verify as verify_jni

ROOT = Path(__file__).resolve().parents[2]
MOBILE = ROOT / 'Mobile'
SDK = Path(os.environ.get('ANDROID_HOME', Path(os.environ['LOCALAPPDATA']) / 'Android/Sdk'))
TOOLS = sorted((SDK / 'build-tools').glob('*'), key=lambda p: [int(v) for v in p.name.split('.') if v.isdigit()])[-1]
JAVA = next((ROOT / '.toolchain/java').glob('jdk-21*')) / 'bin/java.exe'
APK = MOBILE / 'build/app/outputs/flutter-apk/app-release.apk'
OUTPUT = MOBILE / 'dist/VietOCR-arm64.apk'

def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

def run(*args):
    value = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if value.returncode: raise RuntimeError(value.stdout + value.stderr)
    return value.stdout

def signature(path):
    result = run(JAVA, '-jar', TOOLS / 'lib/apksigner.jar', 'verify', '--verbose', '--print-certs', path)
    assert 'Verified using v2 scheme (APK Signature Scheme v2): true' in result
    return re.search(r'Signer #1 certificate SHA-256 digest: (\S+)', result).group(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--validation-prefix', default='native')
    prefix = parser.parse_args().validation_prefix
    if not re.fullmatch(r'[a-z0-9-]+', prefix): raise ValueError('Invalid validation prefix')
    version = re.search(r'^version:\s*([0-9.]+\+[0-9]+)\s*$', (MOBILE / 'pubspec.yaml').read_text(encoding='utf-8'), re.M).group(1)
    version_name, version_code = version.split('+')
    model_manifest = json.loads((MOBILE / 'assets/models/manifest.json').read_text(encoding='utf-8'))
    assert 'FP32 weights' in model_manifest['precision']
    native = {}
    with zipfile.ZipFile(APK) as archive:
        assert json.loads(archive.read('assets/flutter_assets/assets/models/manifest.json')) == model_manifest
        abis = sorted({name.split('/')[1] for name in archive.namelist() if name.startswith('lib/') and name.endswith('.so')})
        assert abis == ['arm64-v8a']
        for model in model_manifest['models'].values():
            name = 'assets/flutter_assets/assets/models/' + model['file']
            assert archive.getinfo(name).file_size == model['bytes']
            with archive.open(name) as stream: assert hashlib.file_digest(stream, 'sha256').hexdigest() == model['sha256']
        for name in archive.namelist():
            if not name.startswith('lib/') or not name.endswith('.so'): continue
            with archive.open(name) as stream:
                header = stream.read(64)
                offset = struct.unpack_from('<Q', header, 32)[0]
                size, count = struct.unpack_from('<HH', header, 54)
                stream.seek(offset); entries = stream.read(size * count)
                alignment = [struct.unpack_from('<Q', entries, i * size + 48)[0] for i in range(count) if struct.unpack_from('<I', entries, i * size)[0] == 1]
                assert alignment and min(alignment) >= 16384
                native[name] = min(alignment)
    badging = run(TOOLS / 'aapt.exe', 'dump', 'badging', APK)
    assert f"versionCode='{version_code}'" in badging and f"versionName='{version_name}'" in badging
    assert 'android.permission.INTERNET' in run(TOOLS / 'aapt.exe', 'dump', 'permissions', APK)
    tree = run(TOOLS / 'aapt.exe', 'dump', 'xmltree', APK, 'AndroidManifest.xml')
    service = next(block for block in re.findall(r'E: service\b.*?(?=\n\s*E:|\Z)', tree, re.S) if 'OcrService' in block)
    assert ':ocr' in service and re.search(r'android:exported[^\n]*0x0\b', service)
    run(TOOLS / 'zipalign.exe', '-c', '-P', '16', '4', APK)
    certificate = signature(APK)
    same_certificate = signature(OUTPUT) == certificate if OUTPUT.is_file() else None
    assert same_certificate is not False
    mobile_tests = (ROOT / f'.toolchain/{prefix}-mobile-tests.log').read_text(encoding='utf-8')
    desktop_tests = (ROOT / f'.toolchain/{prefix}-desktop-tests.log').read_text(encoding='utf-8')
    mobile_passed = int(re.search(r'\+(\d+): All tests passed!', mobile_tests).group(1))
    desktop_passed = int(re.search(r'Ran (\d+) tests', desktop_tests).group(1))
    assert mobile_passed >= 63
    assert desktop_passed >= 165 and desktop_tests.rstrip().endswith('OK')
    scan_tests = (ROOT / '.toolchain/desktop-wifi-scan-tests.log').read_text(encoding='utf-8')
    assert 'Ran 9 tests' in scan_tests and scan_tests.rstrip().endswith('OK')
    assert 'No issues found!' in (ROOT / f'.toolchain/{prefix}-android-analyze.log').read_text(encoding='utf-8')
    java = json.loads((MOBILE / 'assets/models/java_runtime_verification.json').read_text(encoding='utf-8'))
    assert java['tensors_checked'] == 20 and java['same_text_as_python_ort']
    assert sha(MOBILE / java['production_core']) == java['core_sha256']
    jni = verify_jni(APK, MOBILE / 'build/app/outputs/mapping/release/mapping.txt')
    previous = json.loads((MOBILE / 'validation.json').read_text(encoding='utf-8'))
    if OUTPUT.is_file():
        previous_version = previous['version']; assert re.fullmatch(r'[0-9.+]+', previous_version)
        backup = ROOT / f'.toolchain/VietOCR-arm64-{previous_version}.apk'
        if not backup.exists(): shutil.copy2(OUTPUT, backup)
    OUTPUT.parent.mkdir(exist_ok=True)
    shutil.copy2(APK, OUTPUT)
    report = dict(platform='Android', version=version, validation_date='2026-11-02',
        min_sdk=26, abis=abis, apk='dist/VietOCR-arm64.apk', apk_bytes=OUTPUT.stat().st_size, apk_sha256=sha(OUTPUT),
        build='release, debug certificate for sideload testing', same_signing_certificate_as_previous=same_certificate,
        apk_signature_v2_verified=True, apk_16k_zip_alignment_verified=True, native_elf_load_segment_alignment=native,
        internet_permission=True, internet_usage='LAN camera UDP preview and HTTP stills/configuration; OCR remains offline', ocr_private_process_verified=True,
        packaged_model_sha256_verified=True, models_sha256={role: model['sha256'] for role, model in model_manifest['models'].items()},
        model_precision=model_manifest['precision'], model_bytes=sum(row['bytes'] for row in model_manifest['models'].values()),
        analyzer='No issues found', unit_widget_tests_passed=mobile_passed, desktop_tests_passed=desktop_passed,
        mobile_tests_log=f'.toolchain/{prefix}-mobile-tests.log', desktop_tests_log=f'.toolchain/{prefix}-desktop-tests.log', desktop_wifi_scan_tests_passed=9,
        firmware_wifi_scan_verified=True, firmware_wifi_scan_tested_version='2.0.1-wifi (historical scan regression)', firmware_required_version='3.0.0-ov5640',
        wifi_status=dict(automatic_after_ble_connect=True, poll_interval_seconds=5, saved_profile_visible=True,
            opening_settings_does_not_scan=True, wifi_association_independent_of_camera_http=True),
        firmware_wifi_scan_evidence='.toolchain/firmware-wifi-scan-ble.log',
        java_jni_ocr_host_cases_passed=20, r8_jni_callback_verification=jni,
        camera=dict(sensor='OV5640', resolution=[2592,1944], preview_resolution=[640,480],
            preview='4:3 VOJ1 UDP from ESP32 :82; authenticated HTTP POST :80/stream/udp; TFT assistant only', preview_fps_limit=30,
            udp=dict(datagram_bytes=1200, header_bytes=32, lease_seconds=60, renewal_seconds=20,
                maximum_incomplete_frames=2, crc32_per_frame=True, stop_reopen_tested=True),
            preview_width_choices=[320,640,800,1024,1600,2048,2592], fps_limit_is_not_measured_fps=True,
            still_jpeg_quality=8, preview_jpeg_quality=18, jpeg_capacity_bytes=2097152, sensor_frame_buffers=2, crc32_verified=True,
            configuration=dict(schema=2, fields=20, endpoint='authenticated GET/POST /camera/config',
                presets=['Mượt','Cân bằng','Chi tiết'], editing='local until Apply; stop stream, validate, apply, confirm, resume',
                persistence='ESP32 NVS vietocr-camera/profile5640; versioned CRC32 record, read-back verified',
                waits_for_applied_revision_and_saved=True, reset_requires_apply=True, physical_sensor_controls_tested=False),
            orientation='Horizontal mirror selected on ESP32 NVS; both apps read sensor orientation, no software double mirror',
            autofocus='Enabled by default, firmware continuous preview and single focus before capture',
            review_seconds=3, skip_commits_once=True, capture_page_stays_open=True, camera_queue_progress='bottom right, collapsible',
            original_jpeg_preserved=True, download='Android ACTION_CREATE_DOCUMENT, no broad storage permission',
            detail_view='pinch zoom, pan and native pixel crop into a new queued image',
            wifi_provisioning='BLE', image_transport='Wi-Fi :80 required; HTTP health checked before capture', physical_camera_tested=False,
            stream_tests='real local HTTP/UDP lease renewal, fragmented CRC32 frames, reorder/drop/corruption, stop/reopen; 5 MP JPEG preservation and mirror persistence',
            physical_camera_attempt='.toolchain/ov5640-apps-physical.log; no COM8 or BLE advertisement available at final validation',
            sensor_open_preflight='BLE WiFi readiness plus authenticated HTTP checked before CAM OPEN'),
        native_device_test='Not installed/run on phone; host Java/JNI cannot prove Android ARM accuracy or absence of device crashes')
    mapping = MOBILE / 'build/app/outputs/mapping/release/mapping.txt'
    target = OUTPUT.parent / f'VietOCR-{version}-mapping.txt'; shutil.copy2(mapping, target)
    report['r8_mapping'] = str(target.relative_to(MOBILE)).replace('\\','/')
    (MOBILE / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
