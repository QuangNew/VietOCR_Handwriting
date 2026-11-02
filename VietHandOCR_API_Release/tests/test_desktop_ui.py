"""Tk integration tests. Run on a desktop session (no real webcam required)."""

import gc
import io
import signal
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import AsyncMock, patch

import numpy as np
from PIL import Image

from desktop.application import Application
from desktop.camera import CameraWindow
from desktop.domain import AssistantState
from desktop.preferences import read_preferences
from desktop.bluetooth_radio import RadioResult
from desktop.ocr_process import OCRProcessService
from desktop.ocr_service import OCRSettings, RecognitionCancelled
from ocr_fixtures import ProcessEngine
from test_robot_connection import FakeBLE


class StubService:
    def load(self, _, cancel=None):
        pass

    def recognize(self, image, settings, cancel, on_progress):
        on_progress(1, 1)
        time.sleep(0.03)
        if cancel.is_set():
            raise RecognitionCancelled()
        return "Xin chào Việt Nam"


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class UiCameraStream:
    def __init__(self, fixture, jpeg):
        self.fixture, self.jpeg = fixture, jpeg
        self.stopped, self.delivered = False, False

    def start(self):
        return self

    def stop(self):
        self.stopped = True

    def latest(self):
        if self.stopped or self.delivered or self.fixture.hold_camera_frames:
            return None
        self.delivered = True
        return self.jpeg

    def error(self):
        return self.fixture.camera_stream_error


class DesktopWorkflowTests(unittest.TestCase):
    def test_wifi_status_arrives_on_connect_without_opening_settings_or_scan(self):
        with FakeBLE() as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(lambda: self.app._wifi_state is not None)
            self.assertEqual(self.app._wifi_state.state, 'ready')
            self.assertIn('127.0.0.1', self.app.wifi_connection_var.get())
            self.assertFalse(any(cmd == 'WIFI SCAN' for _, cmd in radio.commands))
            self.app.open_wifi_settings()
            self.assertEqual(self.app._wifi_widgets['ssid'].get(), 'a')
            next(button for button in self.app._wifi_widgets['buttons'] if button.cget('text') == 'Kết nối').invoke()
            self.assertIn('Mạng này đã kết nối', self.app._wifi_widgets['message'].get())
            self.assertFalse(any(cmd.startswith('WIFI SSID') for _, cmd in radio.commands))
            self.app._wifi_widgets['ssid'].set('different network')
            self.app._wifi_event('wifi_state', self.app._wifi_state, '')
            self.assertEqual(self.app._wifi_widgets['ssid'].get(), 'different network')
            self.app.disconnect_robot()
            self.assertNotIn('đã kết nối', self.app.wifi_connection_var.get())

    def test_footer_status_is_inside_window_at_small_height(self):
        self.root.deiconify()
        self.root.geometry('1180x700')
        self.app.operation_var.set('Đã cập nhật cài đặt · Model sẽ được nạp ở lượt nhận diện tiếp theo')
        self.root.update()
        for widget in (self.app.operation_label, self.app.model_label, self.app.recognize_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())

    def test_repeated_connect_keeps_same_attempt_and_opening_dialog_does_not_scan(self):
        with FakeBLE(find_delay=0.3) as radio:
            self.app.connect_robot(radio.address)
            first = self.app.robot_link
            for _ in range(5): self.app.connect_robot(radio.address)
            self.assertIs(self.app.robot_link, first)
            with patch("desktop.application._scan_robot_devices") as scan:
                self.app.open_robot_settings()
                scan.assert_not_called()
                self.assertTrue(self.app._robot_dialog["connect_button"].instate(["disabled"]))
                self.pump_until(first.connected.is_set)
                self.assertEqual(radio.sessions, 1)
                self.assertIs(self.app.robot_link, first)

    def test_manual_scan_stops_connection_and_waits_for_native_cleanup(self):
        with FakeBLE(disconnect_delay=0.35) as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_robot_settings()
            original = radio.scanner.discover
            async def checked(**kwargs):
                self.assertFalse(radio.clients[0].is_connected, "Scan overlapped native GATT cleanup")
                return await original(**kwargs)
            with patch.object(radio.scanner, "discover", side_effect=checked):
                self.app._robot_dialog["scan"]()
                self.pump_until(lambda: self.app._robot_dialog["token"] is None)
                self.assertIsNone(self.app.robot_link)
                self.assertTrue(self.app._robot_dialog["devices"])

    def test_visible_theme_keeps_photo_canvas_geometry_and_hidden_controls(self):
        self.app.select_item(self.app.batch.add(self.image, "sample.png").id)
        self.root.geometry("1000x700+3000+0")
        self.root.deiconify()
        self.root.update()
        self.app._draw_preview()
        photo = self.app._preview_photo
        items = self.app.preview.find_all()
        geometry = self.app.preview.winfo_geometry()
        hidden = tk.Label(self.root, text="hidden")
        for _ in range(4):
            self.app.toggle_theme()
            self.root.update()
            self.assertIs(self.app._preview_photo, photo)
            self.assertEqual(self.app.preview.find_all(), items)
            self.assertEqual(self.app.preview.winfo_geometry(), geometry)
            self.assertTrue(self.root.winfo_ismapped())
            self.assertFalse(hidden.winfo_ismapped())
        self.root.withdraw()

    def test_theme_redraw_is_restored_even_if_update_fails(self):
        from desktop.theme import atomic_repaint
        with patch("desktop.theme._pause_windows_redraw") as pause:
            with self.assertRaises(RuntimeError), atomic_repaint(self.root):
                raise RuntimeError("test failure")
            pause.return_value.assert_called_once()

    def test_first_isolated_scan_crash_keeps_dialog_alive_and_can_reopen(self):
        from desktop.bluetooth_process import _Session
        from test_bluetooth_process import crash_worker
        self.app.isolate_bluetooth = True
        with patch("desktop.bluetooth_process._Session", side_effect=lambda: _Session(target=crash_worker)):
            self.app.open_robot_settings()
            self.pump_until(lambda: "tiến trình Bluetooth" in self.app._robot_dialog["scan_status"].get())
            self.assertTrue(self.root.winfo_exists())
            self.assertTrue(self.app._robot_dialog["window"].winfo_exists())
            next(child for child in descendants(self.app._robot_dialog["window"])
                 if isinstance(child, ttk.Button) and child.cget("text") == "Đóng").invoke()
        self.app.isolate_bluetooth = False
        with FakeBLE():
            self.app.open_robot_settings()
            self.pump_until(lambda: self.app._robot_dialog["devices"])
            self.assertTrue(self.root.winfo_exists())

    def test_theme_preserves_queue_editor_and_button_geometry(self):
        item = self.app.batch.add(self.image, "mẫu.png")
        item.status = "done"
        item.text = "Giữ nguyên dấu và vị trí con trỏ"
        self.app.select_item(item.id)
        rows = tuple(self.app.queue_list.inner.winfo_children())
        self.app.result_text.mark_set("insert", "1.5")
        self.root.update_idletasks()
        width = self.app.theme_button.winfo_reqwidth()
        with patch.object(self.app, "_draw_preview"):
            self.app.toggle_theme()
        self.root.update_idletasks()
        self.assertEqual(tuple(self.app.queue_list.inner.winfo_children()), rows)
        self.assertEqual(self.app.result_text.index("insert"), "1.5")
        self.assertEqual(self.app.theme_button.winfo_reqwidth(), width)
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Desktop session required: {exc}")
        self.root.withdraw()
        self.preferences = tempfile.TemporaryDirectory()
        self.app = Application(self.root, "unused.pth", preferences_path=Path(self.preferences.name) / "preferences.json",
                               isolate_bluetooth=False)
        self.app.service = StubService()
        self.image = Image.new("RGB", (120, 90), "white")
        self.camera_streams = []
        self.hold_camera_frames = False
        self.camera_stream_error = None
        output = io.BytesIO(); Image.new('RGB', (640, 480), 'white').save(output, format='JPEG')
        def make_stream(endpoint):
            self.assertEqual(endpoint.ip, '127.0.0.1')
            stream = UiCameraStream(self, output.getvalue())
            self.camera_streams.append(stream)
            return stream
        self.stream_patcher = patch('desktop.application.CameraStream', side_effect=make_stream)
        self.stream_patcher.start()
        self.http_patcher = patch('desktop.wifi_camera.check_http', return_value={'http': True})
        self.http_patcher.start()
        self.root.update()
        self.warnings = patch("desktop.application.messagebox.showwarning")
        self.warning = self.warnings.start()

    def tearDown(self):
        if hasattr(self, "root"):
            self.app.close()
            self.pump_until(lambda: not self.root.winfo_exists(), destroyed=True)
            self.warnings.stop()
            self.stream_patcher.stop()
            self.http_patcher.stop()
            # Dispose Tk objects on the UI thread before the next test's workers.
            del self.app
            del self.root
            gc.collect()
            self.preferences.cleanup()

    def pump_until(self, predicate, destroyed=False):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                self.root.update()
                if predicate():
                    return
            except tk.TclError:
                if destroyed:
                    return
                raise
            time.sleep(0.01)
        self.fail("Desktop operation did not finish in time")

    def test_upload_ocr_edit_copy_and_utf8_export(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [str(Path(directory) / f"ảnh-{i}.png") for i in range(2)]
            for path in paths:
                self.image.save(path)
            self.app.import_files(paths)
            self.pump_until(lambda: not self.app.importing)
            self.assertEqual(len(self.app.batch.items), 2)
            self.assertEqual(self.app.robot.state, AssistantState.RECEIVED)
            self.app.start_recognition()
            self.pump_until(lambda: not self.app.running)
            self.assertTrue(all(item.status == "done" for item in self.app.batch.items))
            self.assertEqual(self.app.robot.state, AssistantState.DONE)
            self.app.result_text.delete("1.0", "end")
            self.app.result_text.insert("1.0", "Văn bản đã chỉnh sửa")
            self.root.update()
            self.app.select_item(self.app.batch.items[0].id)
            self.app.select_item(self.app.batch.items[1].id)
            self.assertEqual(self.app.result_text.get("1.0", "end-1c"), "Văn bản đã chỉnh sửa")
            self.app.copy_selected()
            self.assertEqual(self.root.clipboard_get(), "Văn bản đã chỉnh sửa")
            target = Path(directory) / "kết quả.txt"
            with patch("desktop.application.filedialog.asksaveasfilename", return_value=str(target)):
                self.app.save_results()
            self.assertIn("Văn bản đã chỉnh sửa", target.read_text(encoding="utf-8"))
            self.assertIn("Xin chào Việt Nam", target.read_text(encoding="utf-8"))

    def test_ble_robot_follows_camera_ocr_and_app_close(self):
        with FakeBLE() as server:
            self.app.open_robot_settings()
            self.pump_until(lambda: self.app._robot_dialog["devices"])
            dialog = self.app._robot_dialog
            self.assertIn("VietOCR-Assistant", dialog["choice"].get())
            buttons = {child.cget("text"): child for child in descendants(dialog["window"])
                       if isinstance(child, ttk.Button)}
            buttons["Kết nối"].invoke()
            self.pump_until(lambda: "Đã kết nối" in self.app.robot_connection_var.get())
            self.assertEqual(self.app.robot_address, server.address)
            buttons["Đóng"].invoke()
            server.wait_for("WAKE")
            self.app._on_capture(self.image, "camera.png")
            self.pump_until(lambda: any(text == "RECEIVED 1" for _, text in server.commands))
            self.app._on_capture(self.image, "camera-2.png")
            self.pump_until(lambda: any(text == "RECEIVED 2" for _, text in server.commands))
            self.app.remove_selected()
            self.pump_until(lambda: sum(text == "RECEIVED 1" for _, text in server.commands) >= 2)
            self.app.start_recognition()
            self.pump_until(lambda: not self.app.running)
            self.pump_until(lambda: any(text == "DONE" for _, text in server.commands))
            server.wait_for("PROCESS")
            self.app.close()
            self.pump_until(lambda: not self.root.winfo_exists(), destroyed=True)
            server.wait_for("SLEEP")

    def test_invalid_image_does_not_prevent_valid_images_from_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / "good.png"
            bad = Path(directory) / "broken.png"
            self.image.save(good)
            bad.write_text("not an image", encoding="utf-8")
            self.app.import_files([str(good), str(bad)])
            self.pump_until(lambda: not self.app.importing)
        self.assertEqual(len(self.app.batch.items), 1)
        self.warning.assert_called_once()

    def test_more_than_ten_images_can_be_imported_for_ocr_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'valid.png'
            self.image.save(path)
            self.app.import_files([str(path)] * 12)
            self.pump_until(lambda: not self.app.importing)
        self.assertEqual(len(self.app.batch.items), 12)
        self.warning.assert_not_called()

    def test_primary_controls_fit_inside_a_small_desktop_window(self):
        self.root.deiconify()
        self.root.update()
        bottom = self.root.winfo_rooty() + self.root.winfo_height()
        for control in (self.app.recognize_button, self.app.save_button, self.app.progress):
            self.assertLessEqual(control.winfo_rooty() + control.winfo_height(), bottom)
        self.app._draw_preview()
        bounds = self.app.preview.bbox("all")
        self.assertGreaterEqual(bounds[1], 0)
        self.assertLessEqual(bounds[3], self.app.preview.winfo_height())
        self.root.withdraw()

    def test_ble_dialog_keeps_controls_visible_when_connection_fails(self):
        self.root.deiconify()
        with FakeBLE():
            self.app.open_robot_settings()
            self.pump_until(lambda: self.app._robot_dialog["devices"])
        window = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
        self.app.robot_connection_var.set("Chưa kết nối BLE · Thiết bị chưa chạy firmware VietOCR. Bật Bluetooth và thử lại.")
        self.root.update()

        buttons = [child for child in descendants(window) if isinstance(child, ttk.Button)]
        self.assertEqual({button.cget("text") for button in buttons},
                         {"Bật Bluetooth", "Quét Bluetooth", "Kết nối", "Ngắt kết nối", "Thử còi", "Đóng"})
        bottom = window.winfo_rooty() + window.winfo_height()
        for button in buttons:
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), bottom)
        window.destroy()
        self.root.withdraw()

    def test_cancellation_preserves_finished_images_and_allows_resume(self):
        for i in range(3):
            self.app.batch.add(self.image, f"{i}.png")
        first = self.app.batch.items[0]
        first.status, first.text = "done", "Giữ kết quả này"
        self.app.select_item(first.id)
        self.app.start_recognition()
        self.app.cancel_recognition()
        self.pump_until(lambda: not self.app.running)
        self.assertEqual(first.text, "Giữ kết quả này")
        self.assertTrue(any(item.status != "done" for item in self.app.batch.items))
        self.app.start_recognition()
        self.pump_until(lambda: not self.app.running)
        self.assertTrue(all(item.status == "done" for item in self.app.batch.items))

    def test_model_failure_leaves_the_app_ready_to_retry(self):
        self.app.batch.add(self.image, "photo.png")

        def fail(_, cancel=None):
            raise RuntimeError("Model missing")

        self.app.service.load = fail
        with patch("desktop.application.messagebox.showerror") as error:
            self.app.start_recognition()
            self.pump_until(lambda: not self.app.running)
        error.assert_called_once()
        self.assertEqual(self.app.robot.state, AssistantState.ERROR)
        self.assertFalse(self.app.recognize_button.instate(["disabled"]))

    def test_ai_process_crash_preserves_window_and_same_job_can_retry(self):
        weights = Path(self.preferences.name) / "crash-load.pth"
        weights.write_bytes(b"fixture")
        self.app.service = OCRProcessService(engine_factory=ProcessEngine,
                                             log_directory=Path(self.preferences.name) / "logs")
        self.app.settings = OCRSettings(str(weights))
        self.app.batch.add(self.image, "camera.png")
        with patch("desktop.application.messagebox.showerror") as error:
            self.app.start_recognition()
            self.pump_until(lambda: not self.app.running)
        error.assert_called_once()
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(self.app.robot.state, AssistantState.ERROR)
        self.app.start_recognition()
        self.pump_until(lambda: not self.app.running)
        self.assertEqual(self.app.batch.items[0].status, "done")
        self.assertIn("Tiếng Việt", self.app.batch.items[0].text)

    def test_cancel_while_loading_model_returns_ui_to_ready(self):
        weights = Path(self.preferences.name) / "slow.pth"
        weights.write_bytes(b"fixture")
        self.app.service = OCRProcessService(engine_factory=ProcessEngine,
                                             log_directory=Path(self.preferences.name) / "logs")
        self.app.settings = OCRSettings(str(weights))
        self.app.batch.add(self.image, "camera.png")
        with patch("desktop.application.messagebox.showerror") as error:
            self.app.start_recognition()
            self.pump_until(lambda: weights.with_suffix(".started").is_file())
            self.app.cancel_recognition()
            self.pump_until(lambda: not self.app.running)
        error.assert_not_called()
        self.assertIsNone(self.app.service._process)
        self.assertFalse(self.app.recognize_button.instate(["disabled"]))

    def test_event_callback_error_does_not_stop_ocr_result_polling(self):
        original = self.app._handle_event

        def handle(event):
            if event[0] == "broken_event":
                raise RuntimeError("test UI event failure")
            original(event)

        self.app.batch.add(self.image, "camera.png")
        with patch.object(self.app, "_handle_event", side_effect=handle), \
                patch.object(self.app, "report_callback_exception") as report:
            self.app.events.put(("broken_event",))
            self.app.start_recognition()
            self.pump_until(lambda: not self.app.running)
            report.assert_called_once()
        self.assertEqual(self.app.batch.items[0].status, "done")
        self.assertIsNotNone(self.app._poll_timer)

    def test_close_finishes_even_when_a_cleanup_operation_fails(self):
        self.app.service.close = lambda: (_ for _ in ()).throw(RuntimeError("test cleanup failure"))
        with self.assertLogs("vietocr_desktop.ui", level="ERROR") as logs:
            self.app.close()
            self.pump_until(lambda: not self.root.winfo_exists(), destroyed=True)
        self.assertIn("test cleanup failure", "\n".join(logs.output))
        self.assertNotIn("report_callback_exception", self.root.__dict__)

    def test_ctrl_c_uses_normal_shutdown_without_keyboardinterrupt_traceback(self):
        from app import run_mainloop
        previous = signal.getsignal(signal.SIGINT)
        self.root.after(25, lambda: signal.raise_signal(signal.SIGINT))
        run_mainloop(self.root, self.app)
        self.assertTrue(self.app.closing)
        self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_enable_bluetooth_marshals_consent_to_ui_then_scans(self):
        ui_thread = threading.get_ident()
        consent_threads = []

        def begin_access():
            consent_threads.append(threading.get_ident())
            return AsyncMock(return_value="allowed")()

        async def enable(request_access=None):
            self.assertEqual(await request_access(), "allowed")
            return RadioResult(True, "Đã bật Bluetooth")

        with FakeBLE(), patch("desktop.application.enable_bluetooth", side_effect=enable) as request, \
                patch("desktop.application.begin_bluetooth_access", side_effect=begin_access), \
                patch("desktop.application.open_bluetooth_settings") as settings:
            self.app.open_robot_settings()
            self.pump_until(lambda: self.app._robot_dialog["devices"])
            dialog = self.app._robot_dialog
            first_scan = self.app._robot_scan_token
            dialog["enable_button"].invoke()
            self.pump_until(lambda: self.app._robot_scan_token > first_scan and not dialog["scan_button"].instate(["disabled"]))
            self.assertEqual(consent_threads, [ui_thread])
            settings.assert_not_called()
            request.return_value = RadioResult(False, "Windows từ chối", True)
            request.side_effect = None
            dialog["enable_button"].invoke()
            self.pump_until(lambda: settings.called)
            self.assertIn("Windows từ chối", dialog["scan_status"].get())

    def test_closed_bluetooth_dialog_does_not_start_late_consent(self):
        async def enable(request_access=None):
            await request_access()
            return RadioResult(True, "Đã bật")

        with FakeBLE(), patch("desktop.application.enable_bluetooth", side_effect=enable), \
                patch("desktop.application.begin_bluetooth_access") as begin_access:
            self.app.open_robot_settings()
            self.pump_until(lambda: self.app._robot_dialog["devices"])
            dialog = self.app._robot_dialog
            dialog["enable_button"].invoke()
            # Keep Tk unpumped until the worker has queued its consent request.
            deadline = time.monotonic() + 1
            while self.app.events.empty() and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertFalse(self.app.events.empty())
            next(child for child in descendants(dialog["window"])
                 if isinstance(child, ttk.Button) and child.cget("text") == "Đóng").invoke()
            self.pump_until(lambda: not any(job.is_alive() for job in self.app._jobs))
            begin_access.assert_not_called()
            self.assertTrue(self.root.winfo_exists())

    def test_desktop_camera_requires_ble_and_does_not_open_webcam(self):
        with patch('desktop.application.CameraWindow') as webcam:
            self.app.open_camera()
            self.assertIn('Kết nối', self.app.operation_var.get())
            with FakeBLE() as radio:
                self.app.connect_robot(radio.address)
                self.pump_until(self.app.robot_link.connected.is_set)
                self.app.open_camera()
                self.pump_until(lambda: any(command == 'CAM OPEN' for _, command in radio.commands))
                self.assertIsNotNone(self.app._ov_dialog)
                self.assertIsNone(self.app.camera)
                self.assertFalse(self.app.upload_button.winfo_ismapped())
            webcam.assert_not_called()

    def test_shutter_first_opens_preview_and_only_enables_after_ready(self):
        self.hold_camera_frames = True
        with FakeBLE(camera_status='OPENING') as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.capture_ov()
            self.assertIsNotNone(self.app._ov_dialog)
            self.pump_until(lambda: bool(self.camera_streams))
            self.assertTrue(self.app._ov_widgets['capture'].instate(['disabled']))
            self.assertFalse(any(c.startswith('CAM SHOT') for _, c in radio.commands))
            self.hold_camera_frames = False
            self.pump_until(lambda: self.app._ov_preview_ready)
            self.assertFalse(self.app._ov_widgets['capture'].instate(['disabled']))
            self.assertFalse(any(c == 'CAM STATUS' for _, c in radio.commands))

    def test_vga_preview_and_orientation_changes_reopen_stream_and_save_preferences(self):
        with FakeBLE() as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera()
            self.pump_until(lambda: self.app._ov_preview_ready)
            self.assertEqual(self.app._ov_live_image.size, (640, 480))
            previous = self.camera_streams[-1]
            self.app._ov_widgets['mirror'].invoke()
            self.assertTrue(previous.stopped)
            self.assertTrue(self.app._ov_widgets['capture'].instate(['disabled']))
            self.pump_until(lambda: self.app._ov_preview_ready and len(self.camera_streams) == 2)
            self.assertIn((1, 'CAM ORIENT 1 0'), radio.commands)
            self.app._ov_widgets['flip'].invoke()
            self.pump_until(lambda: self.app._ov_preview_ready and len(self.camera_streams) == 3)
            self.assertIn((1, 'CAM ORIENT 1 1'), radio.commands)
            saved = read_preferences(self.app.preferences_path)
            self.assertTrue(saved['camera_mirror'])
            self.assertTrue(saved['camera_flip'])
            self.assertEqual(len(self.app.batch.items), 0)

    def test_camera_config_apply_preserves_capture_size_and_restarts_preview(self):
        from desktop.camera_settings import DEFAULTS
        from test_camera_settings import config
        profile=config()
        def transport(endpoint,settings=None,*,persist=False):
            nonlocal profile
            if settings is not None:
                profile=config(settings=settings,revision=2,applied_revision=2,saved=persist)
            return profile
        with FakeBLE() as radio,patch('desktop.camera_settings.request_config',side_effect=transport) as network:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera();self.pump_until(lambda:self.app._ov_preview_ready)
            previous=self.camera_streams[-1]
            self.app.open_camera_settings()
            self.pump_until(lambda:self.app._camera_config_window.loaded and not self.app._camera_config_busy)
            window=self.app._camera_config_window
            self.assertEqual(str(window.inputs['aec_value'].cget('state')),'disabled')
            window.set_values({**DEFAULTS,'aec':0,'hmirror':1,'brightness':2})
            self.assertEqual(str(window.inputs['aec_value'].cget('state')),'normal')
            window.preset('Mượt')
            window.apply.invoke()
            self.assertTrue(previous.stopped)
            self.pump_until(lambda:not self.app._camera_config_busy and self.app._ov_preview_ready and len(self.camera_streams)==2)
            self.assertEqual(profile['settings']['preview_width'],640)
            self.assertEqual(profile['settings']['still_quality'],8)
            self.assertTrue(profile['saved'])
            self.assertTrue(self.app._ov_mirror.get())
            self.assertEqual(len(self.app.batch.items),0)
            self.assertTrue(any(call.args[1] is not None for call in network.call_args_list if len(call.args)>1))

    def test_camera_config_invalid_edit_is_not_sent(self):
        from test_camera_settings import config
        with FakeBLE() as radio,patch('desktop.camera_settings.request_config',return_value=config()) as network:
            self.app.connect_robot(radio.address);self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera_settings();self.pump_until(lambda:self.app._camera_config_window.loaded)
            window=self.app._camera_config_window; count=network.call_count
            window.values['still_quality'].set(0)
            window.apply.invoke();self.root.update()
            self.assertEqual(network.call_count,count)
            self.assertIn('không hợp lệ',window.message.get())

    def test_camera_error_is_shown_and_does_not_enable_capture(self):
        self.camera_stream_error = 'Camera HTTP 503: sensor failed'
        with FakeBLE(camera_status='ERROR CAMERA_INIT: sensor failed') as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera()
            self.pump_until(lambda: self.app._ov_state == 'failed')
            self.assertIn('sensor failed', self.app._ov_widgets['message'].get())
            self.assertTrue(self.app._ov_widgets['capture'].instate(['disabled']))
            self.assertTrue(self.app.robot_link.connected.is_set())

    def test_legacy_camera_without_mjpeg_requests_firmware_upgrade(self):
        self.camera_stream_error = 'Nạp firmware 2.2.0-stream để xem camera liên tục.'
        with FakeBLE(camera_status=None) as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera()
            self.pump_until(lambda: self.app._ov_state == 'failed')
            self.assertIn('2.2.0-stream', self.app._ov_widgets['message'].get())
            self.assertFalse(self.app._ov_preview_ready)
            self.assertTrue(self.app.robot_link.connected.is_set())

    def test_closing_or_disconnect_stops_stream_and_no_snapshot_polling(self):
        from desktop.wifi_camera import WifiEndpoint
        with FakeBLE() as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera()
            self.pump_until(lambda: self.app._ov_preview_ready)
            first = self.camera_streams[-1]
            old_token = self.app._ov_generation
            self.app._close_ov_camera()
            self.assertTrue(first.stopped)
            self.assertIsNone(self.app._ov_stream)
            self.app.open_camera()
            # An old endpoint response must not start HTTP while CAM CLOSE /
            # the new CAM OPEN are still queued in the BLE worker.
            self.app.events.put(('robot_camera', self.app.robot_link, 'open',
                                 (old_token, WifiEndpoint('127.0.0.1', 'a' * 32)), ''))
            self.assertEqual(len(self.camera_streams), 1)
            self.pump_until(lambda: self.app._ov_preview_ready)
            self.assertEqual(len(self.camera_streams), 2)
            second = self.camera_streams[-1]
            self.app.events.put(('robot_connection', self.app.robot_link, 'offline', 'disconnected'))
            self.pump_until(lambda: second.stopped)
            self.assertFalse(self.app._ov_preview_ready)
            self.assertFalse(any(c == 'CAM STATUS' for _, c in radio.commands))

    def test_wifi_failure_never_starts_sensor_and_does_not_close_app_or_ble(self):
        with FakeBLE() as radio:
            radio.wifi_response = 'WIFI STATUS OFFLINE 1 201'
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera()
            self.pump_until(lambda: self.app._ov_state == 'failed')
            self.assertIn('Wi-Fi', self.app._ov_widgets['message'].get())
            self.assertFalse(any(c == 'CAM OPEN' for _, c in radio.commands))
            self.assertEqual(self.camera_streams, [])
            self.assertTrue(self.app.robot_link.connected.is_set())
            self.assertFalse(self.app.closing)
            radio.wifi_response = 'WIFI STATUS READY 127.0.0.1 ' + 'a' * 32 + ' 61'
            self.app._request_ov_preview()
            self.pump_until(lambda: self.app._ov_preview_ready)
            self.assertEqual(sum(c == 'CAM OPEN' for _, c in radio.commands), 1)

    def test_camera_window_keeps_shutter_visible_at_large_font_scaling(self):
        scaling = self.root.tk.call('tk', 'scaling')
        try:
            self.root.tk.call('tk', 'scaling', 2.5)
            self.root.deiconify()
            with FakeBLE() as radio:
                self.app.connect_robot(radio.address)
                self.pump_until(self.app.robot_link.connected.is_set)
                self.app.open_camera()
                self.pump_until(lambda: self.app._ov_preview_ready)
                button = self.app._ov_widgets['capture']
                window = self.app._ov_dialog
                self.assertTrue(button.winfo_ismapped())
                self.assertGreaterEqual(button.winfo_rooty(), window.winfo_rooty())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                     window.winfo_rooty() + window.winfo_height())
        finally:
            self.root.tk.call('tk', 'scaling', scaling)

    def test_camera_review_skip_queues_once_and_automatically_resumes_same_window(self):
        import io
        import zlib
        from desktop.camera_transfer import CameraMetadata
        stream = io.BytesIO()
        self.image.save(stream, format='JPEG')
        jpeg = stream.getvalue()
        async def capture(protocol, on_progress=None):
            await protocol.request('CAM SHOT 42')
            if on_progress:
                on_progress(len(jpeg), len(jpeg))
            return CameraMetadata(42, len(jpeg), zlib.crc32(jpeg), *self.image.size), jpeg
        with FakeBLE() as radio, patch('desktop.wifi_camera.capture_fast', capture):
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera()
            self.pump_until(lambda: self.app._ov_preview_ready)
            window = self.app._ov_dialog
            self.app._ov_widgets['capture'].invoke()
            self.assertTrue(self.camera_streams[-1].stopped)
            self.pump_until(lambda: self.app._ov_state == 'reviewing')
            self.assertEqual(len(self.app.batch.items), 0)
            self.assertGreater(self.app._ov_review_deadline, time.monotonic())
            self.app.open_camera()  # Lifting a review must not prematurely skip it.
            self.assertEqual(self.app._ov_state, 'reviewing')
            self.app._ov_widgets['skip'].invoke()
            self.app._finish_ov_review()  # A delayed second click/timer is harmless.
            self.pump_until(lambda: self.app._ov_preview_ready and len(self.app.batch.items) == 1 and not self.app.running)
            self.assertIs(self.app._ov_dialog, window)
            self.assertEqual(sum(c == 'CAM OPEN' for _, c in radio.commands), 2)
            self.assertTrue(any(c == 'CAM SHOT 42' for _, c in radio.commands))

    def test_camera_images_arriving_during_ocr_are_queued_and_auto_drained(self):
        import io
        import zlib
        from desktop.camera_transfer import CameraMetadata
        stream = io.BytesIO(); self.image.save(stream, format='JPEG')
        jpeg = stream.getvalue()
        with FakeBLE() as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            link = self.app.robot_link
            for frame in range(1, 14):
                metadata = CameraMetadata(frame, len(jpeg), zlib.crc32(jpeg), *self.image.size)
                self.app.events.put(('robot_camera', link, 'capture', (metadata, jpeg), ''))
            self.pump_until(lambda: len(self.app.batch.items) == 13 and
                            all(item.status == 'done' for item in self.app.batch.items))
            self.assertTrue(all(item.image_path.is_file() for item in self.app.batch.items))
            self.assertTrue(all(item.source == 'OV5640 Wi-Fi' for item in self.app.batch.items))
            self.assertTrue(self.root.winfo_exists())

    def test_review_timeout_and_close_commit_the_original_without_closing_camera_early(self):
        from desktop.camera_transfer import CameraMetadata
        import zlib
        stream = io.BytesIO()
        Image.new('RGB', (2048, 1536), 'white').save(stream, 'JPEG')
        jpeg = stream.getvalue()
        value = (CameraMetadata(42, len(jpeg), zlib.crc32(jpeg), 2048, 1536), jpeg)
        self.app._auto_queue_halted = True
        with FakeBLE() as radio:
            self.app.connect_robot(radio.address)
            self.pump_until(self.app.robot_link.connected.is_set)
            self.app.open_camera()
            self.pump_until(lambda: self.app._ov_preview_ready)
            window = self.app._ov_dialog
            self.app._stop_ov_stream()
            self.app._start_ov_review(value)
            self.assertEqual(len(self.app.batch.items), 0)
            self.root.update()
            self.assertEqual(self.app._ov_live_image.size, (2048, 1536))
            self.app._ov_review_deadline = time.monotonic()-1
            # Keep only the real scheduled callback, but move its deadline forward.
            self.pump_until(lambda: len(self.app.batch.items) == 1 and self.app._ov_preview_ready)
            self.assertIs(self.app._ov_dialog, window)
            self.assertTrue(self.app._queue_panels[-1].visible)
            self.app._stop_ov_stream()
            self.app._start_ov_review(value)
            self.app._close_ov_camera()  # Close during review must preserve this photo.
            self.assertEqual(len(self.app.batch.items), 2)
            self.assertIsNone(self.app._ov_pending_photo)
            self.assertIsNone(self.app._ov_review_timer)
            self.assertIsNone(self.app._ov_dialog)

    def test_original_preview_reports_native_pixels_and_viewer_crops_native_image(self):
        item = self.app.batch.add(Image.new('RGB', (2048, 1536), 'white'), 'full.png')
        self.app.select_item(item.id)
        self.root.update()
        self.app._draw_preview()
        self.assertTrue(self.app.image_info.cget('text').startswith('2048 × 1536 px'))
        self.app.open_image_viewer()
        viewer = self.app._image_viewer
        self.root.update()
        viewer.actual_size()
        viewer.zoom(2)
        viewer.selection = ((200, 100), (1800, 1400))
        viewer.apply_crop()
        self.assertEqual(item.image.size, (1600, 1300))
        with Image.open(item.original_path) as image:
            self.assertEqual(image.size, (2048, 1536))
        self.assertTrue(self.app.image_info.cget('text').startswith('1600 × 1300 px'))
        viewer.close()
        self.assertIsNone(self.app._image_viewer)

    def test_camera_failure_is_visible_and_capture_stays_disabled(self):
        class UnavailableCapture:
            def __init__(self, *args):
                pass

            def isOpened(self):
                return False

            def release(self):
                pass

        with patch("desktop.camera.cv2.VideoCapture", UnavailableCapture):
            camera = CameraWindow(self.root, self.app.batch, self.app._on_capture, lambda: None)
            self.pump_until(lambda: "Không mở được webcam" in camera.preview.cget("text"))
            self.assertIsNone(camera.latest)
            self.assertTrue(camera.capture_button.instate(["disabled"]))
            camera.close()


if __name__ == "__main__":
    unittest.main()
