"""Validate server-only APK: OAuth deep link, no models/ORT, signature and ABI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]
MOBILE=ROOT/'Mobile'
SDK=Path(os.environ.get('ANDROID_HOME',Path(os.environ['LOCALAPPDATA'])/'Android/Sdk'))
TOOLS=sorted((SDK/'build-tools').glob('*'),key=lambda p:[int(v) for v in p.name.split('.') if v.isdigit()])[-1]
JAVA=next((ROOT/'.toolchain/java').glob('jdk-21*'))/'bin/java.exe'
APK=MOBILE/'build/app/outputs/flutter-apk/app-release.apk'
OUTPUT=MOBILE/'dist/VietOCR-arm64.apk'

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def run(*args):
    result=subprocess.run([str(a) for a in args],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return result.stdout
def signature(path):
    data=run(JAVA,'-jar',TOOLS/'lib/apksigner.jar','verify','--verbose','--print-certs',path)
    assert 'Verified using v2 scheme (APK Signature Scheme v2): true' in data
    return re.search(r'Signer #1 certificate SHA-256 digest: (\S+)',data).group(1)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--validation-prefix',default='server-only');args=parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+',args.validation_prefix)
    version=re.search(r'^version:\s*([0-9.]+\+[0-9]+)',(MOBILE/'pubspec.yaml').read_text(encoding='utf-8'),re.M).group(1)
    native={}
    with zipfile.ZipFile(APK) as archive:
        names=archive.namelist()
        assert not any('/assets/models/' in n or n.endswith(('.onnx','.pth','.f32')) or 'onnxruntime' in n.lower() for n in names)
        config=json.loads(archive.read('assets/flutter_assets/assets/config/supabase.json'))
        assert config['url'].startswith('https://') and config['publishableKey'].startswith('sb_publishable_')
        assert not any(k in config for k in ['service_role','serviceKey','secret'])
        abis=sorted({n.split('/')[1] for n in names if n.startswith('lib/') and n.endswith('.so')})
        assert abis==['arm64-v8a']
        for name in names:
            if not name.startswith('lib/') or not name.endswith('.so'):continue
            with archive.open(name) as stream:
                header=stream.read(64);offset=struct.unpack_from('<Q',header,32)[0];size,count=struct.unpack_from('<HH',header,54)
                stream.seek(offset);entries=stream.read(size*count)
                align=[struct.unpack_from('<Q',entries,i*size+48)[0] for i in range(count) if struct.unpack_from('<I',entries,i*size)[0]==1]
                assert align and min(align)>=16384
                native[name]=min(align)
    tree=run(TOOLS/'aapt.exe','dump','xmltree',APK,'AndroidManifest.xml')
    assert 'OcrService' not in tree and ':ocr' not in tree
    assert 'vn.pbl4.vietocr' in tree and 'BROWSABLE' in tree and 'android.permission.INTERNET' in tree
    assert 'flutter_deeplinking_enabled' in tree
    run(TOOLS/'zipalign.exe','-c','-P','16','4',APK)
    certificate=signature(APK)
    previous_bytes=OUTPUT.stat().st_size if OUTPUT.is_file() else None
    assert not OUTPUT.is_file() or signature(OUTPUT)==certificate
    log=(ROOT/f'.toolchain/{args.validation_prefix}-mobile-tests.log').read_text(encoding='utf-8')
    match=re.search(r'\+(\d+): All tests passed!',log);assert match,'Flutter tests did not pass'
    if OUTPUT.is_file():
        old=json.loads((MOBILE/'validation.json').read_text(encoding='utf-8')).get('version','previous')
        assert re.fullmatch('[0-9.+]+|previous',old)
        backup=ROOT/f'.toolchain/VietOCR-arm64-{old}.apk'
        if not backup.exists():shutil.copy2(OUTPUT,backup)
    OUTPUT.parent.mkdir(exist_ok=True);shutil.copy2(APK,OUTPUT)
    report={'platform':'Android','version':version,'validation_date':'2026-11-03','apk':'dist/VietOCR-arm64.apk',
      'apk_bytes':OUTPUT.stat().st_size,'apk_sha256':sha(OUTPUT),'previous_apk_bytes':previous_bytes,
      'ocr':'server-only','local_models':False,'onnx_runtime':False,'native_ocr_service':False,
      'google_oauth':'Supabase PKCE, system browser, Android deep link','session_storage':'Android Keystore AES256-GCM',
      'database':'Supabase PostgreSQL + per-account RLS; local photos are account-scoped cache',
      'quota':{'daily':1000,'rolling_minute':60,'timezone':'Asia/Ho_Chi_Minh','enforcement':'atomic Postgres admission'},
      'tests_passed':int(match.group(1)),'abis':abis,'min_sdk':26,'signature_v2':True,'alignment_16k':True,'elf_alignments':native,
      'signing':'Existing debug certificate for sideload testing, not Play Store production signing',
      'physical_android_and_google_account_login_tested':False}
    (MOBILE/'validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
