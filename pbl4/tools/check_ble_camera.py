"""Hold real BLE control/heartbeats while the standalone camera tester runs."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time
from bleak import BleakClient,BleakScanner

RX='6e400002-b5a3-f393-e0a9-e50e24dcca9e'
TX='6e400003-b5a3-f393-e0a9-e50e24dcca9e'

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--address',default='84:C7:BB:53:08:61')
    parser.add_argument('--output',type=Path,default=Path('.toolchain/ov5640-ble-udp'))
    parser.add_argument('--enable-radio',action='store_true',help='Temporarily enable Windows Bluetooth and restore its previous state')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    report={'heartbeats_sent':0,'pongs':0,'errors':[]};pending=bytearray();process=None;restore=[]
    def notify(_,data):
        pending.extend(data)
        while b'\n' in pending:
            line,_,rest=pending.partition(b'\n');pending[:]=rest
            if line.strip()==b'PONG':report['pongs']+=1
    try:
        if args.enable_radio:
            from winrt.windows.devices.radios import Radio,RadioKind,RadioState,RadioAccessStatus
            access=await Radio.request_access_async()
            if access!=RadioAccessStatus.ALLOWED:raise RuntimeError('Windows denied Bluetooth radio control')
            for radio in await Radio.get_radios_async():
                if radio.kind==RadioKind.BLUETOOTH and radio.state!=RadioState.ON:
                    previous=radio.state
                    if await radio.set_state_async(RadioState.ON)!=RadioAccessStatus.ALLOWED:raise RuntimeError('Windows denied enabling Bluetooth')
                    restore.append((radio,previous))
            await asyncio.sleep(2)
        device=await BleakScanner.find_device_by_address(args.address,timeout=10)
        if device is None:raise RuntimeError('Assistant BLE advertisement not found')
        async with BleakClient(device,timeout=15) as client:
            await client.start_notify(TX,notify)
            await client.write_gatt_char(RX,b'WAKE\n',response=True)
            with (args.output/'camera.log').open('w',encoding='utf-8') as output:
                process=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).with_name('camera_check.py')),
                    '--udp','--seconds','20','--cycles','2','--output',str(args.output)],stdout=output,stderr=subprocess.STDOUT)
                started=time.monotonic()
                while process.poll() is None:
                    if not client.is_connected:raise RuntimeError('BLE disconnected under camera load')
                    await client.write_gatt_char(RX,b'PING\n',response=True);report['heartbeats_sent']+=1
                    await asyncio.sleep(2)
                report['camera_exit_code']=process.returncode
                report['ble_stayed_connected']=client.is_connected
                report['seconds']=round(time.monotonic()-started,3)
                if process.returncode:raise RuntimeError('Camera test failed; see camera.log')
                if report['pongs']<report['heartbeats_sent']-1:raise RuntimeError('BLE heartbeat replies missing')
    except Exception as error:report['errors'].append(type(error).__name__+': '+str(error))
    finally:
        if process is not None and process.poll() is None:process.terminate();process.wait(5)
        for radio,state in restore:await radio.set_state_async(state)
        if restore:report['windows_radio_restored']=True
        (args.output/'ble.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,indent=2))
    return 1 if report['errors'] else 0
if __name__=='__main__':sys.exit(asyncio.run(main()))
