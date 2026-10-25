"""Tk integration tests. Run on a desktop session (no real webcam required)."""

import gc
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


class DesktopWorkflowTests(unittest.TestCase):
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
        self.root.update()
        self.warnings = patch("desktop.application.messagebox.showwarning")
        self.warning = self.warnings.start()

    def tearDown(self):
        if hasattr(self, "root"):
            self.app.close()
            self.pump_until(lambda: not self.root.winfo_exists(), destroyed=True)
            self.warnings.stop()
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

    def test_over_limit_selection_is_rejected_before_import(self):
        self.app.import_files([f"file-{i}.png" for i in range(11)])
        self.assertFalse(self.app.importing)
        self.assertEqual(len(self.app.batch.items), 0)
        self.warning.assert_called_once()

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

    def test_camera_reopen_waits_for_previous_capture_release(self):
        entered, release_gate, released = threading.Event(), threading.Event(), threading.Event()

        class SlowCapture:
            def __init__(self, *args):
                pass

            def isOpened(self):
                return True

            def set(self, *args):
                pass

            def read(self):
                entered.set()
                release_gate.wait(2)
                time.sleep(0.01)
                return True, np.full((64, 80, 3), 200, dtype=np.uint8)

            def release(self):
                released.set()

        with patch("desktop.camera.cv2.VideoCapture", SlowCapture):
            self.app.open_camera()
            self.pump_until(entered.is_set)
            self.app.camera.close()
            self.app.open_camera()
            self.assertIsNone(self.app.camera)
            self.assertTrue(self.app.camera_button.instate(["disabled"]))
            release_gate.set()
            self.pump_until(lambda: released.is_set() and not self.app.camera_button.instate(["disabled"]))
            self.app.open_camera()
            self.assertIsNotNone(self.app.camera)
            self.app.camera.close()

    def test_camera_captures_to_shared_queue_and_releases_on_close(self):
        released = threading.Event()

        class FakeCapture:
            def __init__(self, *args):
                pass

            def isOpened(self):
                return True

            def set(self, *args):
                pass

            def read(self):
                time.sleep(0.01)
                return True, np.full((64, 80, 3), 200, dtype=np.uint8)

            def release(self):
                released.set()

        with patch("desktop.camera.cv2.VideoCapture", FakeCapture):
            self.app.open_camera()
            camera = self.app.camera
            self.pump_until(lambda: camera.latest is not None)
            camera.capture()
            self.assertEqual(len(self.app.batch.items), 1)
            self.assertEqual(self.app.batch.items[0].source, "Camera")
            camera.close()
            self.pump_until(released.is_set)
        self.assertIsNone(self.app.camera)

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
