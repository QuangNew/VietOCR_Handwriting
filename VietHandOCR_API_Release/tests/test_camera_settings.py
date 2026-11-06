import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from desktop.camera_settings import DEFAULTS,FIELDS,PRESETS,validate_settings,parse_config,request_config,apply_config
from desktop.wifi_camera import WifiEndpoint

def config(**changes):
    result=dict(schema=2,sensor='OV5640',firmware='3.0.0-ov5640',settings=dict(DEFAULTS),defaults=dict(DEFAULTS),
                revision=1,applied_revision=1,saved=True,error='')
    result.update(changes); return result

class SettingsValidationTests(unittest.TestCase):
    def test_document_preset_preserves_orientation_and_enables_focus(self):
        values = {**DEFAULTS, 'hmirror':1, 'vflip':1, **PRESETS['Tài liệu OCR']}
        validate_settings(values)
        self.assertEqual((values['hmirror'], values['vflip'], values['autofocus']), (1,1,1))
        self.assertGreaterEqual(values['still_quality'], 4)
        self.assertEqual(values['special_effect'], 0)

class LostSettingsResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_post_is_read_back_without_replaying_flash_write(self):
        from desktop.wifi_camera import CameraNetworkError
        values={**DEFAULTS,'focus_x':35}
        endpoint=WifiEndpoint('127.0.0.1','a'*32)
        commands=[]
        async def request(command,**kwargs):commands.append(command);return 'OK '+command
        results=iter([config(),CameraNetworkError('response lost'),config(settings=values,revision=2,applied_revision=2)])
        calls=[]
        def control(endpoint,settings=None,**kwargs):
            calls.append(settings)
            value=next(results)
            if isinstance(value,Exception):raise value
            return value
        with patch('desktop.wifi_camera.wifi_status',return_value='unused'),patch('desktop.wifi_camera.WifiEndpoint.parse',return_value=endpoint),patch('desktop.camera_settings.request_config',side_effect=control):
            result=await apply_config(SimpleNamespace(request=request),values)
        self.assertEqual(result['revision'],2)
        self.assertEqual(sum(v is not None for v in calls),1)
        self.assertEqual(commands,['CAM CLOSE'])

    def test_ranges_and_incompatible_frame_sizes_never_get_sent(self):
        self.assertEqual(validate_settings(DEFAULTS),DEFAULTS)
        for key,(_,_,low,high,_,_) in FIELDS.items():
            for value in (low-1,high+1,True,1.5):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    validate_settings({**DEFAULTS,key:value})
        for change in ({'preview_width':1920},{'still_quality':0},{'other':1}):
            with self.assertRaises(ValueError):validate_settings({**DEFAULTS,**change})
        with patch('desktop.camera_settings.build_opener') as network:
            with self.assertRaises(ValueError):request_config(WifiEndpoint('127.0.0.1','a'*32),{**DEFAULTS,'still_quality':0})
            network.assert_not_called()
        with self.assertRaises(ValueError):parse_config(config(schema=1))
        with self.assertRaises(ValueError):parse_config(config(applied_revision='1'))

class ConfigHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_http_applies_atomically_and_waits_for_nvs_confirmation(self):
        states=[]; calls=[]; posts=[]; token='a'*32
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status,body):
                raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                calls.append(('GET',self.path,self.headers.get('Authorization')))
                self.reply(200,states.pop(0))
            def do_POST(self):
                posts.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.reply(202,config(revision=2,applied_revision=1,saved=False,settings=posts[-1]['settings']))
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        endpoint=WifiEndpoint(f'127.0.0.1:{server.server_port}',token)
        values={**DEFAULTS,'brightness':2,'hmirror':1}
        states.extend([config(),config(revision=2,applied_revision=2,saved=False,settings=values),config(revision=2,applied_revision=2,saved=True,settings=values)])
        commands=[]
        async def request(command,**kwargs):commands.append(command);return 'OK '+command
        try:
            with patch('desktop.wifi_camera.wifi_status',return_value='unused'),patch('desktop.wifi_camera.WifiEndpoint.parse',return_value=endpoint):
                result=await apply_config(SimpleNamespace(request=request),values,persist=True)
            self.assertTrue(result['saved']);self.assertEqual(commands,['CAM CLOSE'])
            self.assertEqual(posts,[{'settings':values,'persist':True}])
            self.assertEqual(len(calls),3);self.assertTrue(all(c[1]=='/camera/config' and c[2]=='Bearer '+token for c in calls))
        finally:
            await asyncio.to_thread(server.shutdown);server.server_close();worker.join(2)

    async def test_reported_sensor_failure_keeps_existing_ble_protocol_usable(self):
        commands=[]
        async def request(command,**kwargs):commands.append(command);return 'PONG' if command=='PING' else 'OK '+command
        protocol=SimpleNamespace(request=request)
        with patch('desktop.wifi_camera.wifi_status',return_value='unused'),patch('desktop.wifi_camera.WifiEndpoint.parse',return_value=WifiEndpoint('127.0.0.1','a'*32)),patch('desktop.camera_settings.request_config',return_value=config(error='CAMERA_PROFILE: sensor refused')):
            with self.assertRaisesRegex(ValueError,'sensor refused'):await apply_config(protocol,DEFAULTS)
        self.assertEqual(await protocol.request('PING'),'PONG')

if __name__=='__main__':unittest.main()
