"""Publish only the OV5640 image that passed the connected-board checks."""
import hashlib
import json
from pathlib import Path
import shutil

PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT.parent
LAB=ROOT/'.toolchain'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    binary=PROJECT/'.pio/build/esp32-s3-cam-ov5640/firmware.bin'
    assert b'3.0.0-ov5640' in binary.read_bytes()
    upload=(LAB/'ov5640-final-upload.log').read_text(encoding='utf-8')
    assert '[SUCCESS]' in upload and 'Hash of data verified.' in upload
    host=(LAB/'ov5640-host-tests.log').read_text(encoding='utf-8')
    for expected in ('PASS UDP JPEG','PASS OV5640 autofocus','native_jpeg: 20 checks passed','native_dma: 229 checks passed'):
        assert expected in host
    tests=(LAB/'ov5640-udp-receiver-tests.log').read_text(encoding='utf-8')
    assert 'Ran 2 tests' in tests and tests.rstrip().endswith('OK')
    physical={name:read(LAB/name/'result.json') for name in ('ov5640-hotspot-udp','ov5640-ble-udp','ov5640-after-reset')}
    frames=0;rates=[];photos=[]
    for result in physical.values():
        assert not result['errors'] and '3.0.0-ov5640' in result['info']
        for cycle in result['cycles']:
            assert cycle['preview_dimensions']==[640,480] and cycle['steady_fps']>=15
            assert cycle['still']['dimensions']==[2592,1944] and cycle['still']['crc32_verified']
            frames+=cycle['frames'];rates.append(cycle['steady_fps']);photos.append(cycle['still'])
    ble=read(LAB/'ov5640-ble-udp/ble.json')
    assert not ble['errors'] and ble['ble_stayed_connected'] and ble['pongs']==ble['heartbeats_sent']==28
    previous=read(LAB/'ov5640-persist-before-reset.json')
    restored=physical['ov5640-after-reset']['config']
    assert restored['saved'] and previous['settings']==restored['settings']
    cleanup=read(PROJECT/'docs/ov5640-cleanup.json')
    assert not (PROJECT/'.pio/build/esp32-s3-cam-ov3660').exists()
    assert not (PROJECT/'.pio/build/esp32-s3-devkitc-1').exists()
    destination=PROJECT/'dist/VietOCR-OV5640.bin';destination.parent.mkdir(exist_ok=True)
    shutil.copy2(binary,destination)
    source=['platformio.ini','src/assistant_camera.cpp','src/assistant_wifi.cpp','src/main.cpp',
        'include/camera_settings.h','include/camera_transfer.h','include/camera_udp.h',
        'lib/Ov5640Autofocus/src/autofocus_control.h','lib/NativeCameraHal/src/native_jpeg.h']
    result={
        'date':'2026-11-02','firmware':'3.0.0-ov5640','environment':'esp32-s3-cam-ov5640',
        'artifact':'pbl4/dist/VietOCR-OV5640.bin','bytes':destination.stat().st_size,'sha256':sha(destination),
        'flashed':True,'port':'COM8','esptool_flash_hash_verified':True,
        'sensor':'OV5640','preview':[640,480],'preview_jpeg_qs':18,'preview_fps_ceiling':30,
        'preview_transport':'UDP VOJ1; authenticated HTTP setup; frame CRC32; drop stale/incomplete frames',
        'preview_frames_received_and_decoded':frames,'received_fps_by_cycle':rates,
        'received_fps_min':min(rates),'received_fps_max':max(rates),
        'still':[2592,1944],'still_jpeg_qs':8,'still_transport':'HTTP LAN with byte length and CRC32',
        'verified_photos':photos,'photo_count':len(photos),
        'autofocus':{'firmware_loaded':True,'single_lock_reported':True,'continuous_preview':True,
            'optical_resolution_chart_measured':False,'first_AF_load_seconds_approx':5},
        'ble_and_udp':ble,'nvs_camera_persistence_after_hard_reset_verified':True,
        'nvs_camera_key':'vietocr-camera/profile5640','nvs_record_bytes':92,
        'wifi_profile':'QuangNew','wifi_reconnect_after_hard_reset_verified':True,
        'wifi_power_save':'MAX_MODEM with listen_interval=1; modem sleep stays enabled for BLE',
        'tcp_mjpeg_compatibility':{'port':81,'prior_VGA_received_fps':[9.202,10.11,10.124],
            'note':'UDP is the measured fast preview. Old apps still need UDP/schema integration.'},
        'physical_logs':[f'.toolchain/{name}/result.json' for name in physical],
        'upload_log':'.toolchain/ov5640-final-upload.log','host_tests_log':'.toolchain/ov5640-host-tests.log',
        'receiver_tests_passed':2,'cleanup_freed_bytes':cleanup['freed_bytes'],
        'source_sha256':{name:sha(PROJECT/name) for name in source},
        'apps_modified_or_built_this_turn':False,'new_SDK_or_AI_model_downloaded':False,
        'hotspot_testing_uses_LAN_only':True,
        'notes':'Measured on this physical board/hotspot/scene. AF status does not certify optical sharpness. UDP may discard incomplete frames. Camera was closed after testing; Wi-Fi settings retained.'
    }
    (PROJECT/'docs/ov5640-validation.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    summary=read(PROJECT/'docs/camera-validation.json')
    summary['latest_firmware']='3.0.0-ov5640';summary['ov5640_physical_2026_11_02']=result
    summary['legacy_and_ov3660_builds_removed_2026_11_02']='See ov5640-cleanup.json; historical artifact paths are no longer present.'
    (PROJECT/'docs/camera-validation.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('artifact','bytes','sha256','preview_frames_received_and_decoded','received_fps_by_cycle','photo_count','cleanup_freed_bytes')},indent=2))
if __name__=='__main__':main()
