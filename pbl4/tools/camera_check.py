"""Standalone IoT camera validation over Serial + LAN, without either app.

Run with Python containing pyserial and Pillow. Optional Wi-Fi credentials are
read from VIETOCR_TEST_SSID / VIETOCR_TEST_PASSWORD, never printed or saved.
"""
import argparse
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time
from urllib.request import Request, ProxyHandler, build_opener
import zlib

# Reuse the installed PlatformIO pyserial if running from the OCR Python venv.
sys.path.append(str(Path.home() / '.platformio/penv/Lib/site-packages'))
import serial
from PIL import Image, ImageStat


class Link:
    def __init__(self, port):
        self.device = serial.Serial(port=None, baudrate=115200, timeout=.15)
        self.device.dtr = self.device.rts = False
        self.device.port = port
        self.device.open()
        self.lines = []
        self.stopped = threading.Event()
        self.condition = threading.Condition()
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    @staticmethod
    def safe(line):
        if line.startswith('WIFI SAVED PASS '): return 'WIFI SAVED PASS [REDACTED]'
        return re.sub(r'(WIFI STATUS READY \S+ )\S+', r'\1[REDACTED]', line)

    def read(self):
        while not self.stopped.is_set():
            try:
                line = self.device.readline().decode('utf-8', 'replace').strip()
            except (OSError, serial.SerialException):
                return
            if line:
                with self.condition:
                    self.lines.append(line)
                    self.condition.notify_all()
                print(self.safe(line), flush=True)

    def command(self, command, prefix='OK ', timeout=10):
        with self.condition:
            start = len(self.lines)
            self.device.write((command + '\n').encode())
            deadline = time.monotonic() + timeout
            while True:
                for line in self.lines[start:]:
                    if line.startswith(prefix):
                        return line
                    if line.startswith('ERR '):
                        raise RuntimeError(line)
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError('Serial command timed out: ' + command.split()[0])
                self.condition.wait(left)

    def close(self):
        self.stopped.set()
        self.thread.join(2)
        self.device.close()


def mjpeg_frames(response):
    # read1 drains each available TCP packet. HTTPResponse.readline on chunked
    # bodies falls back to byte reads, distorting a high-FPS throughput test.
    data=bytearray()
    while True:
        part=response.read1(65536)
        if not part: return
        data.extend(part)
        while True:
            start=data.find(b'--vietocr-frame\r\n')
            if start<0:
                if len(data)>256: raise RuntimeError('Malformed MJPEG boundary')
                break
            end=data.find(b'\r\n\r\n',start)
            if end<0: break
            match=re.search(rb'Content-Length:\s*(\d+)',data[start:end])
            if not match: raise RuntimeError('Missing JPEG size')
            size=int(match.group(1))
            if not 4<=size<=2*1024*1024: raise RuntimeError('JPEG exceeds buffer bound')
            if len(data)<end+4+size: break
            jpeg=bytes(data[end+4:end+4+size]);del data[:end+4+size]
            if not jpeg.endswith(b'\xff\xd9'): raise RuntimeError('Truncated JPEG')
            yield jpeg
        if len(data)>2*1024*1024+2048: raise RuntimeError('MJPEG buffer exceeded bound')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default='COM8')
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--preview-width', type=int)
    parser.add_argument('--max-fps', type=int)
    parser.add_argument('--preview-quality', type=int)
    parser.add_argument('--focus-x', type=int)
    parser.add_argument('--focus-y', type=int)
    parser.add_argument('--output', type=Path, default=Path('.toolchain/ov5640-hardware'))
    parser.add_argument('--serial-only', action='store_true')
    parser.add_argument('--udp', action='store_true', help='Use UDP preview, HTTP stills')
    parser.add_argument('--wake', action='store_true', help='Pulse USB-UART RTS to wake/reset the board')
    parser.add_argument('--sleep-after', action='store_true', help='Stop camera/radios and deep sleep after the test (EN/RESET wakes)')
    parser.add_argument('--show', action='store_true', help='Show the IoT test stream in a resizable window')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = {'cycles': [], 'errors': [], 'physical_board': True, 'port': args.port}
    link = Link(args.port)
    opener = build_opener(ProxyHandler({}))
    viewer=None
    if args.show:
        import tkinter as tk
        from PIL import ImageTk
        viewer=tk.Tk();viewer.title('OV5640 - IoT stream test');viewer.geometry('900x700')
        picture=tk.Label(viewer,bg='#101614');picture.pack(fill='both',expand=True)
        viewer.update()
    try:
        if args.wake:
            link.device.rts = True
            time.sleep(.15)
            link.device.rts = False
            time.sleep(3)
        result['info'] = link.command('INFO', 'INFO ')
        link.command('CAM CLOSE')
        link.command('WAKE')
        for key,value in (('focus_x',args.focus_x),('focus_y',args.focus_y)):
            if value is not None:
                if not 0<=value<=100: raise ValueError('Focus coordinates must be 0..100 percent')
                link.command(f'CAM SET {key} {value}'); time.sleep(.3)
        if args.preview_width:
            link.command(f'CAM SET preview_width {args.preview_width}')
            time.sleep(.5)
        if args.max_fps is not None:
            link.command(f'CAM SET max_fps {args.max_fps}')
            time.sleep(.5)
        if args.preview_quality is not None:
            link.command(f'CAM SET preview_quality {args.preview_quality}')
            time.sleep(.5)
        ssid = os.environ.get('VIETOCR_TEST_SSID')
        if ssid:
            link.command('WIFI SSID ' + ssid.encode().hex(), 'OK WIFI SSID')
            password = os.environ.get('VIETOCR_TEST_PASSWORD', '').encode()
            for at in range(0, len(password), 24):
                link.command('WIFI PASS ' + password[at:at+24].hex(), 'OK WIFI PASS')
            link.command('WIFI JOIN')
        if args.serial_only:
            link.command('CAM OPEN')
            time.sleep(args.seconds)
            result['status'] = link.command('CAM STATUS', 'CAM STATUS ')
            result['focus'] = link.command('CAM AF STATUS', 'CAM AF ')
            if result['status']!='CAM STATUS READY': raise RuntimeError(result['status'])
        else:
            deadline = time.monotonic() + 40
            while True:
                status = link.command('WIFI STATUS', 'WIFI STATUS ')
                if status.startswith('WIFI STATUS READY '): break
                if time.monotonic() > deadline: raise TimeoutError('ESP32 not associated with a reachable Wi-Fi network')
                time.sleep(1)
            ip, token = status.split()[3:5]
            result['ip'] = ip
            def get(path, port=80, timeout=12, data=None):
                request = Request(f'http://{ip}:{port}{path}', data=data, headers={'Authorization': 'Bearer ' + token,'Content-Type':'application/json'})
                return opener.open(request, timeout=timeout)
            with get('/health') as response: result['health_before'] = json.load(response)
            for cycle in range(args.cycles):
                link.command('CAM OPEN')
                started = time.monotonic()
                times, sizes = [], []
                row = {'cycle': cycle+1}
                result['cycles'].append(row)
                last_jpeg = None
                if args.udp:
                    from udp_preview import frames
                    stream_socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                    stream_socket.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024*1024)
                    stream_socket.bind(('0.0.0.0',0))
                    with get('/stream/udp',data=json.dumps({'port':stream_socket.getsockname()[1]}).encode()) as response:
                        control=json.load(response)
                    def renew_udp():
                        with get('/stream/udp',data=json.dumps({'port':stream_socket.getsockname()[1]}).encode()) as response:
                            return json.load(response)['stream']
                    source=frames(stream_socket,ip,control['stream'],renew=renew_udp)
                    row['transport']='UDP VOJ1, CRC32 verified on every frame'
                    resource=stream_socket
                else:
                    resource=get('/stream',port=81,timeout=20)
                    source=mjpeg_frames(resource)
                    row['transport']='HTTP MJPEG'
                with resource:
                    for jpeg in source:
                        size=len(jpeg)
                        with Image.open(io.BytesIO(jpeg)) as image:
                            image.load()
                            dimensions = list(image.size)
                            expected = result['health_before']['preview']
                            if args.preview_width: expected=[args.preview_width, args.preview_width*3//4]
                            if dimensions != expected: raise RuntimeError(f'Stale/wrong preview dimensions {dimensions}')
                            if viewer is not None:
                                display=image.copy();display.thumbnail((max(160,picture.winfo_width()),max(120,picture.winfo_height())))
                                photo=ImageTk.PhotoImage(display);picture.configure(image=photo);picture.image=photo
                                viewer.update()
                        times.append(time.monotonic()); sizes.append(size)
                        if len(times) == 1:
                            row['first_frame_seconds'] = round(times[0]-started, 3)
                            (args.output/f'preview-{cycle+1}-first.jpg').write_bytes(jpeg)
                        last_jpeg = jpeg
                        if time.monotonic()-started>=args.seconds: break
                if args.udp:
                    with get('/stream/udp',data=b'{"port":0}') as response: response.read()
                if len(times) < 2: raise RuntimeError('Not enough frames to measure FPS')
                row.update(frames=len(times), preview_dimensions=dimensions,
                    steady_fps=round((len(times)-1)/(times[-1]-times[0]), 3),
                    average_jpeg_bytes=round(sum(sizes)/len(sizes)),
                    gap_max_seconds=round(max(b-a for a,b in zip(times,times[1:])),3))
                (args.output/f'preview-{cycle+1}-last.jpg').write_bytes(last_jpeg)
                link.command('CAM CLOSE')
                frame_id = secrets.randbelow(0xfffffffe)+1
                shot_at = time.monotonic()
                link.command(f'CAM SHOT {frame_id}')
                deadline = time.monotonic()+28
                while True:
                    try:
                        metadata=link.command(f'CAM META {frame_id}', f'CAM {frame_id} ')
                        break
                    except RuntimeError as error:
                        if 'CAMERA_BUSY' not in str(error) or time.monotonic()>deadline: raise
                        time.sleep(.15)
                _, _, length, crc, width, height = metadata.split()
                with get(f'/image?id={frame_id}',timeout=20) as response: jpeg=response.read(2*1024*1024+1)
                if len(jpeg)!=int(length) or zlib.crc32(jpeg)!=int(crc,16): raise RuntimeError('Still CRC/length mismatch')
                with Image.open(io.BytesIO(jpeg)) as image:
                    image.load()
                    if image.size!=(2592,1944) or (int(width),int(height))!=image.size: raise RuntimeError(f'Photo is not full sensor resolution: {image.size}')
                    brightness=ImageStat.Stat(image.convert('L')).mean[0]
                (args.output/f'still-{cycle+1}.jpg').write_bytes(jpeg)
                row['still']={'dimensions':[2592,1944], 'bytes':len(jpeg), 'crc32_verified':True,
                    'capture_and_download_seconds':round(time.monotonic()-shot_at,3), 'mean_luminance':round(brightness,2)}
                link.command(f'CAM RELEASE {frame_id}')
                time.sleep(.1)
                print(json.dumps(row),flush=True)
            with get('/health') as response: result['health_after']=json.load(response)
        result['config'] = json.loads(link.command('CAM CONFIG','{'))
    except Exception as error:
        result['errors'].append(type(error).__name__ + ': ' + str(error))
    finally:
        try: link.command('CAM CLOSE')
        except Exception: pass
        if args.sleep_after:
            try:
                link.command('POWER SLEEP')
                deadline=time.monotonic()+12
                with link.condition:
                    while not any('POWER DEEP_SLEEP:' in line for line in link.lines):
                        remaining=deadline-time.monotonic()
                        if remaining<=0: raise TimeoutError('Board did not confirm deep sleep')
                        link.condition.wait(remaining)
                result['deep_sleep_confirmed']=True
            except Exception as error:
                result['errors'].append(f'Power down failed: {error}')
        link.close()
        if viewer is not None:
            try: viewer.destroy()
            except Exception: pass
        result['serial'] = [link.safe(line) for line in link.lines]
        (args.output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='serial'},indent=2,ensure_ascii=False))
    return 1 if result['errors'] else 0

if __name__=='__main__': sys.exit(main())
