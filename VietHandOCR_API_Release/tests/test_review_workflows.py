"""User workflows: lossless batch export, saved Wi-Fi and dismissible progress."""
import asyncio
import io
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from PIL import Image
from desktop.domain import ImageBatch
from desktop.image_export import export_all_images
from desktop.wifi_camera import wifi_profiles
from desktop.bluetooth_transport import RobotCommandRejected


class ExportTests(unittest.TestCase):
    def test_all_originals_survive_crop_and_existing_files_are_never_overwritten(self):
        batch=ImageBatch()
        jpeg=io.BytesIO();Image.new('RGB',(640,480),'red').save(jpeg,format='JPEG')
        original=jpeg.getvalue()
        item=batch.add_jpeg(original,'Same.jpg')
        item.replace_image(item.image.crop((10,10,60,60)))
        batch.add(Image.new('RGB',(100,80),'white'),'Same.jpg','File')
        with tempfile.TemporaryDirectory() as folder:
            existing=Path(folder)/'001_Same.jpg';existing.write_bytes(b'keep')
            paths=export_all_images(batch.items,folder)
            self.assertEqual(existing.read_bytes(),b'keep')
            self.assertEqual(paths[0].read_bytes(),original)
            self.assertEqual(paths[1].suffix,'.png')
            with Image.open(paths[1]) as image:
                self.assertEqual(image.size,(100,80))
        batch.clear();batch._directory.cleanup()


class SavedWifiTests(unittest.IsolatedAsyncioTestCase):
    async def test_password_chunks_open_network_and_utf8_survive_without_repr_leak(self):
        entries=[('Mạng riêng','á'*20+'abc'),('Open','')]
        class Protocol:
            async def request(self,command,**kwargs):
                if command=='WIFI SAVED COUNT': return 'WIFI SAVED COUNT 2'
                fields=command.split();index=int(fields[3]);ssid,password=entries[index]
                if fields[2]=='SSID': return command+' '+ssid.encode().hex()
                offset=int(fields[4]);data=password.encode()[offset:offset+24]
                return command+' '+(data.hex() or '-')
        profiles=await wifi_profiles(Protocol())
        self.assertEqual([(p.ssid,p.password) for p in profiles],entries)
        self.assertNotIn(entries[0][1],repr(profiles))

    async def test_old_firmware_gets_upgrade_message(self):
        class Protocol:
            async def request(self,*args,**kwargs):
                raise RobotCommandRejected('ERR WIFI_COMMAND')
        with self.assertRaisesRegex(ValueError,'3.2.0'):
            await wifi_profiles(Protocol())


class NotificationTests(unittest.TestCase):
    def test_hide_stays_hidden_until_new_work_and_completed_queue_auto_hides(self):
        from desktop.queue_progress import QueueProgress
        from desktop.widgets import configure_styles
        root=tk.Tk();root.withdraw();configure_styles(root)
        batch=ImageBatch();item=batch.add(Image.new('RGB',(50,50)),'Camera.jpg','OV5640')
        panel=QueueProgress(root,lambda _:None)
        try:
            panel.update(batch.items,{})
            self.assertTrue(panel.visible)
            panel.hide();item.status='processing';panel.update(batch.items,{item.id:.5})
            self.assertFalse(panel.visible)
            new=batch.add(Image.new('RGB',(50,50)),'Second.jpg','OV5640');panel.update(batch.items,{})
            self.assertTrue(panel.visible)
            item.status=new.status='done';panel.update(batch.items,{})
            self.assertIsNotNone(panel._hide_timer)
            # Execute the actual Tk timer callback early; no 5-second test sleep.
            script=root.tk.call('after','info',panel._hide_timer)[0]
            root.tk.eval(script)
            self.assertFalse(panel.visible)
            panel.update(batch.items,{})
            self.assertFalse(panel.visible)
        finally:
            root.destroy();batch.clear();batch._directory.cleanup()
