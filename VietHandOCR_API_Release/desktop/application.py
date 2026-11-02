"""Vietnamese desktop workflow: collect images, recognize, edit, and export."""

import asyncio
import io
import logging
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .bluetooth_transport import RobotDevice, scan_robots, validate_address
from .bluetooth_process import ProcessBLEProtocol, scan_robots_isolated
from .bluetooth_coordinator import radio_access
from .bluetooth_radio import begin_bluetooth_access, enable_bluetooth, open_bluetooth_settings
from .camera import CameraWindow
from .camera_udp import UdpCameraStream as CameraStream
from .domain import AssistantState, BatchFullError, ImageBatch
from .image_viewer import ImageViewer, save_image_dialog
from .queue_progress import QueueProgress
from .diagnostics import LOG_DIRECTORY
from .ocr_process import OCRProcessService
from .ocr_service import OCRSettings
from .preferences import read_preferences, update_preferences
from .robot_connection import RobotClient
from .tasks import import_images, recognize_images, warm_model
from .theme import (PREFERENCES_PATH, apply_titlebar, atomic_repaint, load_theme,
                    recolor_canvas, recolor_widgets, save_theme, set_palette)
from .widgets import COLORS as C, RobotFace, ScrollableFrame, card, configure_styles, label

STATUS_LABELS = {
    "ready": "Chờ nhận diện", "processing": "Đang nhận diện", "done": "Hoàn tất",
    "error": "Cần thử lại", "cancelled": "Đã dừng",
}
logger = logging.getLogger("vietocr_desktop.ui")
DEVICE_CHOICES = {
    "Tự động: GPU rời → GPU tích hợp → CPU": "auto",
    "GPU NVIDIA (CUDA)": "cuda",
    "GPU tích hợp": "integrated",
    "CPU": "cpu",
}


def device_label(device):
    return "Tự động chọn GPU" if device == "auto" else device.upper()


def _scan_robot_devices(events, token, cancel, isolated=True, radio_lock=None):
    # Only plain data crosses the worker/UI boundary; no Tk objects in this thread.
    try:
        scanner = scan_robots_isolated if isolated else scan_robots
        logger.info("Starting Bluetooth scan (isolated=%s)", isolated)
        async def run():
            async with radio_access(radio_lock, cancel):
                return await scanner(cancel=cancel)
        devices = asyncio.run(run())
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.exception("Bluetooth scan failed")
        events.put(("robot_scan", token, [], str(exc)))
    else:
        events.put(("robot_scan", token, devices, ""))


async def _complete_radio_access(operation, promise):
    try:
        result = await operation
    except Exception as exc:
        if not promise.done():
            promise.set_exception(exc)
    else:
        if not promise.done():
            promise.set_result(result)


def _enable_robot_radio(events, token, cancel, radio_lock=None):
    async def run():
        async def request_access():
            loop = asyncio.get_running_loop()
            promise = loop.create_future()
            events.put(("robot_radio_permission", token, loop, promise))
            return await promise

        operation = asyncio.create_task(enable_bluetooth(request_access=request_access))
        try:
            while not operation.done():
                if cancel.is_set():
                    raise asyncio.CancelledError
                await asyncio.wait([operation], timeout=0.1)
            return await operation
        finally:
            if not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def gated():
        async with radio_access(radio_lock, cancel):
            return await run()

    try:
        result = asyncio.run(gated())
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Bluetooth radio operation failed")
        from .bluetooth_radio import RadioResult
        result = RadioResult(False, "Không bật được Bluetooth. Mở Cài đặt Windows để bật lại.", True)
    events.put(("robot_radio", token, result))


class Application:
    def __init__(self, root: tk.Tk, weights: str, device: str = "auto", camera_index: int = 0,
                 preferences_path: Path | None = None, *, isolate_bluetooth: bool = True):
        self.root = root
        self.isolate_bluetooth = isolate_bluetooth
        self.preferences_path = preferences_path if preferences_path is not None else PREFERENCES_PATH
        self.theme = load_theme(self.preferences_path)
        set_palette(self.theme)
        self.settings = OCRSettings(weights, device)
        self.camera_index = camera_index
        self.batch = ImageBatch()
        self.service = OCRProcessService()
        self.events: queue.Queue = queue.Queue()
        self._shutdown = threading.Event()
        self._jobs = []
        self._error_dialog_pending = False
        self.robot_link: RobotClient | None = None
        self._robot_links: list[RobotClient] = []
        self._robot_progress: int | None = None
        self.robot_address = ""
        self.robot_name = ""
        self._robot_dialog = None
        self._robot_scan_token = 0
        self._robot_radio_token = 0
        self._robot_scan_cancel = threading.Event()
        self._robot_radio_cancel = threading.Event()
        self._robot_radio_lock = threading.Lock()
        self.assistant_state = AssistantState.AWAKE
        self.robot_connection_var = tk.StringVar(value="ESP32 chưa kết nối")
        self.wifi_connection_var = tk.StringVar(value='Wi-Fi · Kết nối Bluetooth để xem trạng thái')
        self.wifi_detail_var = tk.StringVar(value='ESP32 tự dùng mạng đã lưu; ứng dụng sẽ đọc trạng thái khi kết nối BLE.')
        self._wifi_state = None
        self.cancel_event = threading.Event()
        self.selected_id: str | None = None
        self.running = False
        self.importing = False
        self.closing = False
        self.camera: CameraWindow | None = None
        self._camera_workers = []
        self._ov_dialog = None
        self._ov_receiving = False
        self._ov_widgets = {}
        self._ov_state = 'closed'
        self._ov_preview_ready = False
        self._ov_stream = None
        self._ov_generation = 0
        self._ov_preview_timer = None
        self._ov_preview_deadline = 0
        self._ov_live_photo = None
        self._ov_live_image = None
        self._ov_pending_photo = None
        self._ov_review_timer = None
        self._ov_review_deadline = 0
        camera_preferences = read_preferences(self.preferences_path)
        self._ov_mirror = tk.BooleanVar(value=bool(camera_preferences.get('camera_mirror', False)))
        self._ov_flip = tk.BooleanVar(value=bool(camera_preferences.get('camera_flip', False)))
        self._ov_orientation_requested = None
        self._ov_frame_count = 0
        self._ov_focus_point = (50, 50)
        self._ov_display_box = None
        self._ov_fps_at = 0.0
        self._camera_config_window = None
        self._camera_config_busy = False
        self._image_viewer = None
        self._camera_progress = {}
        self._queue_panels = []
        self._wifi_dialog = None
        self._wifi_widgets = {}
        self._auto_queue_halted = False
        self._camera_release_timer = None
        self._preview_photo = None
        self._thumbs = []
        self._preview_timer = None
        self._poll_timer = None
        self._warm_timer = None
        self._rendering_text = False
        self._result_id: str | None = None
        self._run_total = 0
        self._run_index = 0
        self.root.title("VietOCR Handwriting · Trợ lý đọc chữ Việt")
        self.root.configure(bg=C["bg"])
        screen_width, screen_height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width, height = min(1380, screen_width-32), min(900, screen_height-72)
        self.compact = screen_height < 850
        self.root.geometry(f"{width}x{height}+16+16")
        self.root.minsize(min(1120, width), min(680, height))
        configure_styles(root)
        self._build_ui()
        self._queue_panels.append(QueueProgress(self.root, self.select_item))
        self.root.after_idle(lambda: apply_titlebar(self.root))
        self._sync_controls()
        self._render_queue()
        self._render_result()
        self._set_assistant(AssistantState.AWAKE, "Chào bạn, mình đã thức!", "Thêm ảnh để mình giúp bạn đọc chữ nhé.")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.report_callback_exception
        self.root.bind("<Control-o>", lambda _: self.import_files())
        self.root.bind("<Control-Return>", lambda _: self.start_recognition())
        self.root.bind("<Control-s>", lambda _: self.save_results())
        self.root.bind("<Escape>", lambda _: self.cancel_recognition())
        self._poll_events()
        if Path(self.settings.weights).is_file():
            self._warm_timer = self.root.after(400, self._warm_model)
        preferences = read_preferences(self.preferences_path)
        saved_address = preferences.get("robot_ble_address")
        if isinstance(saved_address, str) and saved_address:
            try:
                saved_name = preferences.get("robot_ble_name")
                self.connect_robot(saved_address, name=saved_name if isinstance(saved_name, str) else "VietOCR-Assistant", save=False)
            except ValueError:
                self.robot_connection_var.set("Quét Bluetooth để chọn lại ESP32")

    def _build_ui(self):
        from .workspace_view import build_workspace
        build_workspace(self)

    def _draw_brand(self):
        self.brand_mark.delete("all")
        self.brand_mark.create_oval(1, 1, 42, 42, fill=C["green"], outline="")
        self.brand_mark.create_text(22, 21, text="V", fill=C["on_accent"], font=("Segoe UI", 21, "bold"))

    def _theme_button_text(self) -> str:
        return "Dùng nền sáng" if self.theme == "dark" else "Dùng nền tối"

    def toggle_theme(self):
        if self.closing:
            return
        self._save_editor()
        with atomic_repaint(self.root):
            self.theme = "light" if self.theme == "dark" else "dark"
            previous = set_palette(self.theme)
            configure_styles(self.root)
            recolor_widgets(self.root, previous)
            self.theme_button.configure(text=self._theme_button_text())
            recolor_canvas(self.brand_mark, previous)
            recolor_canvas(self.preview, previous)
            self.robot._draw()
        logger.info("Theme changed to %s", self.theme)
        if self.robot_link is not None:
            self.robot_link.set_theme(self.theme)
        try:
            save_theme(self.preferences_path, self.theme)
        except OSError:
            self.operation_var.set("Đã đổi giao diện · Không ghi được lựa chọn cho lần mở sau")

    def _set_assistant(self, state: AssistantState, title: str, detail: str = ""):
        if state != self.assistant_state:
            self._robot_progress = None
        self.assistant_state = state
        badges = {AssistantState.AWAKE: "●  Sẵn sàng", AssistantState.RECEIVED: "●  Đã nhận ảnh",
                  AssistantState.PROCESSING: "●  Đang làm việc", AssistantState.DONE: "●  Hoàn tất",
                  AssistantState.ERROR: "●  Cần bạn giúp một chút", AssistantState.SLEEP: "●  Đang ngủ"}
        self.robot.set_state(state)
        self.assistant_title.configure(text=title)
        self.assistant_detail.configure(text=detail)
        self.assistant_badge.configure(text=badges[state], fg=C["error"] if state == AssistantState.ERROR else C["green"])
        self._publish_robot_state()

    def _publish_robot_state(self):
        if self.robot_link is not None:
            self.robot_link.set_state(self.assistant_state, len(self.batch.items))
            if self._robot_progress is not None:
                self.robot_link.set_progress(self._robot_progress)

    def _publish_robot_progress(self):
        self._robot_progress = max(0, min(100, int(float(self.progress["value"]))))
        if self.robot_link is not None:
            self.robot_link.set_progress(self._robot_progress)

    def connect_robot(self, address: str, *, name: str = "VietOCR-Assistant", save: bool = True):
        address = validate_address(address)
        if (self.robot_link is not None and not self.robot_link.closed.is_set()
                and not self.robot_link.stopping and self.robot_link.address.casefold() == address.casefold()):
            logger.info("Reusing Bluetooth connection attempt: address=%s phase=%s", address, self.robot_link.status)
            self.robot_link.retry_now()
            self._sync_robot_dialog_controls()
            return
        self._robot_scan_cancel.set()
        self._robot_radio_cancel.set()
        if self._robot_dialog:
            self._robot_dialog["token"] = self._robot_dialog["radio_token"] = None
        if self.robot_link is not None:
            self.robot_link.stop()
        self.robot_address = address
        self.robot_name = name or "VietOCR-Assistant"
        events = self.events  # Worker callbacks keep no reference to Tk widgets.
        from .bluetooth_transport import BLEProtocol
        link = RobotClient(address, lambda status, detail: events.put(("robot_connection", link, status, detail)),
                           name=self.robot_name,
                           protocol_factory=ProcessBLEProtocol if self.isolate_bluetooth else BLEProtocol,
                           radio_lock=self._robot_radio_lock,
                           on_camera=lambda action, value, error: events.put(('robot_camera', link, action, value, error)))
        link.set_theme(self.theme)
        self.robot_link = link
        self._robot_links = [old for old in self._robot_links if not old.closed.is_set()]
        self._robot_links.append(link)
        self._publish_robot_state()
        self.robot_connection_var.set(f"Đang kết nối Bluetooth · {self.robot_name}")
        self.robot_connection_label.configure(text="ESP32 · Đang kết nối…", fg=C["muted"])
        self._wifi_state = None
        self.wifi_connection_var.set('Wi-Fi · Đang chờ BLE để đọc trạng thái')
        self.wifi_detail_var.set('ESP32 tự dùng mạng đã lưu; không cần nhập lại mật khẩu.')
        link.start()
        self._sync_robot_dialog_controls()
        if save:
            self._save_robot_address(address, self.robot_name)

    def disconnect_robot(self):
        self._robot_scan_cancel.set()
        self._robot_radio_cancel.set()
        if self._robot_dialog:
            self._robot_dialog["token"] = self._robot_dialog["radio_token"] = None
        if self.robot_link is not None:
            self.robot_link.stop()
            self.robot_link = None
        self.robot_address = ""
        self.robot_name = ""
        self.robot_connection_var.set("ESP32 chưa kết nối")
        self.robot_connection_label.configure(text="ESP32 chưa kết nối", fg=C["muted"])
        self._wifi_state = None
        self.wifi_connection_var.set('Wi-Fi · Kết nối Bluetooth để xem trạng thái')
        self._save_robot_address("")
        self._sync_robot_dialog_controls()

    def _pause_robot_connection(self):
        if self.robot_link is not None:
            self.robot_link.stop()
            self.robot_link = None
        self.robot_connection_var.set("Đang tìm trợ lý Bluetooth…")
        self.robot_connection_label.configure(text="ESP32 · Chưa kết nối", fg=C["muted"])
        self._wifi_state = None
        self.wifi_connection_var.set('Wi-Fi · Đang chờ BLE để đọc trạng thái')

    def _sync_robot_dialog_controls(self):
        dialog = self._robot_dialog
        if not dialog or not dialog["window"].winfo_exists() or "connect_button" not in dialog:
            return
        link = self.robot_link
        active = link is not None and not link.closed.is_set() and not link.stopping
        connected = active and link.connected.is_set()
        connecting = active and link.status in ("connecting", "waiting")
        scanning, radio = dialog["token"] is not None, dialog["radio_token"] is not None
        dialog["connect_button"].configure(state="disabled" if connected or connecting or scanning or radio or not dialog["devices"] else "normal")
        dialog["scan_button"].configure(state="disabled" if scanning or radio else "normal")
        dialog["enable_button"].configure(state="disabled" if radio else "normal")
        dialog["beep_button"].configure(state="normal" if connected else "disabled")

    def _save_robot_address(self, address: str, name: str = ""):
        try:
            update_preferences(self.preferences_path, robot_ble_address=address, robot_ble_name=name)
        except OSError:
            self.operation_var.set("Đã cập nhật kết nối · Không lưu được thiết bị cho lần mở sau")

    def open_robot_settings(self):
        logger.info("Opening Bluetooth dialog")
        if self.closing:
            return
        if self._robot_dialog and self._robot_dialog["window"].winfo_exists():
            self._robot_dialog["window"].lift()
            return
        window = tk.Toplevel(self.root)
        window.title("VietOCR · Bluetooth ESP32")
        window.configure(bg=C["white"])
        window.geometry(f'{min(900,self.root.winfo_screenwidth()-60)}x{min(700,self.root.winfo_screenheight()-80)}')
        window.minsize(720, 520)
        window.resizable(True, True)
        window.transient(self.root)
        window.grab_set()
        apply_titlebar(window)
        buttons = tk.Frame(window, bg=C['white'], padx=24, pady=16)
        buttons.pack(fill='x', side='bottom')
        scroll = ScrollableFrame(window)
        scroll.pack(fill='both', expand=True)
        body = tk.Frame(scroll.inner, bg=C["white"], padx=24, pady=22)
        body.pack(fill="both", expand=True)
        label(body, "Trợ lý trên bàn của bạn", size=18, bold=True).pack(anchor="w")
        label(body, "Bật Bluetooth trên máy tính và cấp nguồn ESP32.\nChọn VietOCR-Assistant trong danh sách bên dưới.",
              size=10, color=C["muted"], justify="left").pack(anchor="w", pady=(8, 16))
        devices = [RobotDevice(self.robot_address, self.robot_name)] if self.robot_address else []
        row = tk.Frame(body, bg=C["white"])
        row.pack(fill="x")
        label(row, "Thiết bị Bluetooth BLE", bold=True).pack(side="left")
        scan_button = ttk.Button(row, text="Quét Bluetooth")
        scan_button.pack(side="right")
        enable_button = ttk.Button(row, text="Bật Bluetooth")
        enable_button.pack(side="right", padx=(0, 8))
        choice = ttk.Combobox(body, state="readonly", values=[device.description for device in devices])
        choice.pack(fill="x", pady=(10, 7), ipady=5)
        if devices:
            choice.current(0)
        scan_status = tk.StringVar(value="Quét để tìm thiết bị ở gần.")
        label(body, textvariable=scan_status, size=9, color=C["muted"],
              wraplength=540, justify="left").pack(anchor="w")
        status_label = label(body, textvariable=self.robot_connection_var, size=9, color=C["green"],
                             wraplength=760, justify="left", anchor='w')
        status_label.pack(fill='x', pady=(14, 15))
        def resize_labels(event):
            for child in body.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(wraplength=max(220, event.width-48))
        body.bind('<Configure>', resize_labels)
        for child in body.winfo_children():
            scroll.bind_scroll(child)
        self._robot_dialog = {"window": window, "devices": devices, "choice": choice,
                              "scan_button": scan_button, "scan_status": scan_status, "token": None,
                              "enable_button": enable_button, "radio_token": None}

        def scan():
            if self.closing or not window.winfo_exists():
                return
            self._robot_scan_cancel.set()
            self._pause_robot_connection()
            self._robot_scan_cancel = threading.Event()
            self._robot_scan_token += 1
            token = self._robot_scan_token
            self._robot_dialog["token"] = token
            scan_status.set("Đang quét Bluetooth…")
            scan_button.state(["disabled"])
            threading.Thread(target=_scan_robot_devices,
                             args=(self.events, token, self._robot_scan_cancel, self.isolate_bluetooth, self._robot_radio_lock),
                             name="VietOCR-BLE-scan", daemon=True).start()
            self._sync_robot_dialog_controls()

        def turn_on():
            self._robot_scan_cancel.set()
            self._pause_robot_connection()
            self._robot_radio_cancel.set()
            self._robot_radio_cancel = threading.Event()
            self._robot_dialog["token"] = None
            self._robot_radio_token += 1
            token = self._robot_radio_token
            self._robot_dialog["radio_token"] = token
            scan_button.state(["disabled"])
            enable_button.state(["disabled"])
            scan_status.set("Đang bật Bluetooth…")
            self._start_background(_enable_robot_radio, (self.events, token, self._robot_radio_cancel, self._robot_radio_lock), "VietOCR-Bluetooth-on")
            self._sync_robot_dialog_controls()

        def connect():
            if self._robot_dialog["connect_button"].instate(["disabled"]):
                return
            index = choice.current()
            available = self._robot_dialog["devices"]
            if index < 0 or index >= len(available):
                messagebox.showinfo("Chọn thiết bị", "Quét Bluetooth rồi chọn VietOCR-Assistant.", parent=window)
                return
            device = available[index]
            self.connect_robot(device.address, name=device.name)

        def beep():
            if self.robot_link is not None and self.robot_link.connected.is_set():
                self.robot_link.beep()
            else:
                messagebox.showinfo("Chưa kết nối", "Kết nối ESP32 thành công rồi thử còi nhé.", parent=window)

        def close_dialog():
            self._robot_scan_cancel.set()
            self._robot_radio_cancel.set()
            window.destroy()
            self._robot_dialog = None

        connect_button = ttk.Button(buttons, text="Kết nối", style="Primary.TButton", command=connect)
        connect_button.pack(side="left")
        ttk.Button(buttons, text="Ngắt kết nối", command=self.disconnect_robot).pack(side="left", padx=8)
        beep_button = ttk.Button(buttons, text="Thử còi", command=beep)
        beep_button.pack(side="left")
        ttk.Button(buttons, text="Đóng", command=close_dialog).pack(side="right")
        scan_button.configure(command=scan)
        enable_button.configure(command=turn_on)
        self._robot_dialog["scan"] = scan
        self._robot_dialog["connect_button"] = connect_button
        self._robot_dialog["beep_button"] = beep_button
        window.protocol("WM_DELETE_WINDOW", close_dialog)
        window.bind("<Return>", lambda _: connect())
        window.bind("<Escape>", lambda _: close_dialog())
        if self.robot_link is None or self.robot_link.closed.is_set() or self.robot_link.stopping:
            scan()
        else:
            scan_status.set("App đang kết nối thiết bị đã lưu. Quét Bluetooth để chọn thiết bị khác.")
            self._sync_robot_dialog_controls()

    def _receive_robot_permission(self, token, loop, promise):
        dialog = self._robot_dialog
        if loop.is_closed() or promise.done():
            return
        if (self.closing or not dialog or token != dialog["radio_token"]
                or self._robot_radio_cancel.is_set() or not dialog["window"].winfo_exists()):
            try:
                loop.call_soon_threadsafe(promise.cancel)
            except RuntimeError:
                pass
            return
        try:
            operation = begin_bluetooth_access()  # Windows consent must start on Tk's thread.
        except Exception as exc:
            def reject(error=exc):
                if not promise.done():
                    promise.set_exception(error)
            try:
                loop.call_soon_threadsafe(reject)
            except RuntimeError:
                pass
            return
        completion = _complete_radio_access(operation, promise)
        try:
            asyncio.run_coroutine_threadsafe(completion, loop)
        except RuntimeError:
            completion.close()
            cancel = getattr(operation, "cancel", None)
            if cancel is not None:
                cancel()

    def _receive_robot_radio(self, token, result):
        dialog = self._robot_dialog
        if (self.closing or not dialog or token != dialog["radio_token"]
                or not dialog["window"].winfo_exists()):
            return
        dialog["radio_token"] = None
        dialog["enable_button"].state(["!disabled"])
        dialog["scan_button"].state(["!disabled"])
        dialog["scan_status"].set(result.message)
        if result.enabled:
            dialog["scan"]()
        elif result.open_settings:
            try:
                open_bluetooth_settings()
            except OSError:
                logger.exception("Cannot open Windows Bluetooth settings")
        self._sync_robot_dialog_controls()

    def _receive_robot_scan(self, token, devices, error):
        dialog = self._robot_dialog
        if (self.closing or not dialog or token != dialog["token"]
                or not dialog["window"].winfo_exists()):
            return
        dialog["token"] = None
        dialog["scan_button"].state(["!disabled"])
        dialog["devices"] = devices
        choice = dialog["choice"]
        choice.set("")
        choice.configure(values=[device.description for device in devices])
        if devices:
            selected = next((index for index, device in enumerate(devices)
                             if device.address.casefold() == self.robot_address.casefold()), 0)
            choice.current(selected)
        if error:
            text = f"Không quét được. Bật Bluetooth và cho phép ứng dụng truy cập: {error}"
        elif devices:
            text = f"Tìm thấy {len(devices)} thiết bị. Chọn trợ lý rồi bấm Kết nối."
        else:
            text = "Chưa tìm thấy. Đưa ESP32 lại gần và ngắt điện thoại/app khác đang kết nối."
        dialog["scan_status"].set(text)
        self._sync_robot_dialog_controls()

    def _sync_controls(self):
        locked = self.running or self.importing or self.camera is not None or self.closing
        selected = self.batch.get(self.selected_id)
        pending = sum(item.status != "done" for item in self.batch.items)
        has_text = any(item.text.strip() for item in self.batch.items)
        self.upload_button.configure(state="disabled" if locked else "normal")
        camera_ready = self.robot_link is not None and self.robot_link.connected.is_set() and not self._ov_receiving and not self.importing and not self.closing and not self._camera_config_busy
        self.camera_button.configure(state="normal" if camera_ready else "disabled")
        self.ov_shot_button.configure(state="normal" if camera_ready else "disabled")
        if self._ov_widgets:
            self._ov_widgets['capture'].configure(state='normal' if camera_ready and self._ov_preview_ready else 'disabled',
                                                  text='Đang nhận ảnh…' if self._ov_receiving else 'Chụp OV5640')
            self._ov_widgets['view'].configure(state='normal' if camera_ready and self._ov_state not in ('opening', 'reviewing') else 'disabled')
            self._ov_widgets['skip'].configure(state='normal' if self._ov_pending_photo is not None else 'disabled')
            if 'settings' in self._ov_widgets:
                self._ov_widgets['settings'].configure(state='normal' if camera_ready and self._ov_state not in ('opening','reviewing') else 'disabled')
            for key in ('mirror', 'flip'):
                if key in self._ov_widgets:
                    self._ov_widgets[key].configure(state='normal' if camera_ready and self._ov_state == 'ready' else 'disabled')
        self.save_image_button.configure(state='normal' if selected else 'disabled')
        self.save_all_images_button.configure(state='normal' if self.batch.items and not self.importing and not self.closing else 'disabled')
        if self._image_viewer is not None:
            self._image_viewer.sync_controls()
        self._update_camera_progress()
        self.settings_button.configure(state="disabled" if locked else "normal")
        for button in (self.rotate_button, self.remove_button):
            button.configure(state="normal" if selected and not locked else "disabled")
        self.clear_button.configure(state="normal" if self.batch.items and not locked else "disabled")
        self.retry_button.configure(state="normal" if selected and not locked else "disabled")
        self.recognize_button.configure(state="normal" if pending and not locked else "disabled",
                                        text=f"Nhận diện {pending} ảnh" if pending else "Nhận diện ảnh")
        self.cancel_button.configure(state="normal" if self.running and not self.cancel_event.is_set() else "disabled")
        self.layout_combo.configure(state="disabled" if locked else "readonly")
        self.copy_button.configure(state="normal" if selected and selected.text.strip() else "disabled")
        self.copy_all_button.configure(state="normal" if has_text else "disabled")
        self.save_button.configure(state="normal" if has_text else "disabled")

    def _render_queue(self):
        position = self.queue_list.canvas.yview()[0]
        for child in self.queue_list.inner.winfo_children():
            child.destroy()
        self._thumbs.clear()
        self.queue_count.configure(text=f"{len(self.batch.items)} ảnh")
        if not self.batch.items:
            label(self.queue_list.inner, "Danh sách đang trống", size=9, color=C["muted"]).pack(pady=(35, 8))
            label(self.queue_list.inner, "Tải ảnh từ máy tính hoặc\nchụp bằng OV5640.", size=9,
                  color=C["muted"], justify="center").pack()
        selected_index = next((i for i, item in enumerate(self.batch.items) if item.id == self.selected_id), 0)
        first = selected_index // 50 * 50
        if len(self.batch.items) > 50:
            pages = tk.Frame(self.queue_list.inner, bg=C['white']); pages.pack(fill='x', pady=8)
            if first:
                ttk.Button(pages, text='←', width=3, command=lambda: self.select_item(self.batch.items[first-1].id)).pack(side='left')
            label(pages, f'{first+1}–{min(first+50, len(self.batch.items))}', size=8).pack(side='left', padx=8)
            if first + 50 < len(self.batch.items):
                ttk.Button(pages, text='→', width=3, command=lambda: self.select_item(self.batch.items[first+50].id)).pack(side='right')
        for index, item in enumerate(self.batch.items[first:first+50], first+1):
            bg = C["pale"] if item.id == self.selected_id else C["white"]
            row = tk.Frame(self.queue_list.inner, bg=bg, padx=8, pady=10, cursor="hand2")
            row.pack(fill="x", pady=2)
            thumb = item.thumbnail()
            thumb.thumbnail((54, 53), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(thumb, master=self.root)
            self._thumbs.append(photo)
            picture = tk.Label(row, image=photo, bg=bg, width=56, height=56)
            picture.pack(side="left", padx=(0, 8))
            info = tk.Frame(row, bg=bg)
            info.pack(side="left", fill="x", expand=True)
            title = label(info, '', size=8, bold=True, anchor="w")
            title.pack(fill='x')
            from tkinter import font as tkfont
            title_font = tkfont.Font(root=self.root, font=title.cget('font'))
            def fit_name(event, target=title, full=f'{index:02d}  {item.name}', font=title_font):
                text=full
                while len(text)>1 and font.measure(text+'…')>event.width:
                    text=text[:-1]
                target.configure(text=full if text==full else text+'…')
            title.bind('<Configure>', fit_name)
            color = C["error"] if item.status == "error" else C["green"] if item.status == "done" else C["muted"]
            status = label(info, STATUS_LABELS[item.status], size=8, color=color, anchor="w")
            status.pack(anchor="w", pady=(4, 0))
            for widget in (row, picture, info, title, status):
                widget.bind("<Button-1>", lambda _, item_id=item.id: self.select_item(item_id))
                self.queue_list.bind_scroll(widget)
        self.queue_list.canvas.update_idletasks()
        self.queue_list.canvas.yview_moveto(position)

    def select_item(self, item_id: str):
        self._save_editor()
        self.selected_id = item_id
        self._render_queue()
        self._draw_preview()
        self._render_result()
        self._sync_controls()

    def _schedule_preview(self, _=None):
        if self._preview_timer:
            self.root.after_cancel(self._preview_timer)
        self._preview_timer = self.root.after(80, self._draw_preview)

    def _draw_preview(self):
        if self._preview_timer:
            self.root.after_cancel(self._preview_timer)
        self._preview_timer = None
        width, height = max(1, self.preview.winfo_width()), max(1, self.preview.winfo_height())
        item = self.batch.get(self.selected_id)
        # Configure notifications also occur during ttk palette updates. A pending
        # resize must not rebuild the same PhotoImage after the atomic repaint.
        key = (item.id if item else None, item.version if item else None, width, height)
        if getattr(self, "_preview_key", None) == key and self.preview.find_all():
            return
        self._preview_key = key
        self.preview.delete("all")
        if item is None:
            if height < 115:
                # At high Windows scaling/small windows there is no room for
                # the document illustration plus two captions. Keep the action
                # visible rather than painting text beyond the canvas bounds.
                if height >= 24:
                    self.preview.create_text(width/2, height/2, text='Chụp OV5640 để thêm ảnh',
                                             fill=C['muted'], font=('Segoe UI', 9))
                self.preview_index.configure(text='')
                self.image_info.configure(text='Bấm Xem camera hoặc Chụp OV5640')
                return
            scale = min(1.0, max(0.5, (height-65)/125))
            x, y = width / 2, max(50*scale+8, height/2-30*scale)
            self.preview.create_rectangle(x-32*scale, y-50*scale, x+32*scale, y+28*scale,
                                          fill=C["white"], outline=C["paper_border"], width=2)
            for offset, length in ((-27, 40), (-13, 32), (1, 38)):
                self.preview.create_line(x-20*scale, y+offset*scale, x+(-20+length)*scale, y+offset*scale,
                                         fill=C["paper_line"], width=3)
            self.preview.create_oval(x+12*scale, y+5*scale, x+45*scale, y+38*scale, fill=C["green"], outline="")
            self.preview.create_text(x+28*scale, y+21*scale, text="+", fill=C["on_accent"], font=("Segoe UI", max(12, int(20*scale))))
            self.preview.create_text(x, y+70*scale, text="Bắt đầu với một tấm ảnh", fill=C["ink"],
                                     font=("Segoe UI", 10 if scale < 1 else 12, "bold"))
            self.preview.create_text(x, y+101*scale, text="Tải ảnh lên hoặc chụp bằng OV5640", fill=C["muted"],
                                     font=("Segoe UI", 8 if scale < 1 else 9))
            self.preview_index.configure(text="")
            self.image_info.configure(text="Tải ảnh từ máy tính hoặc chụp bằng OV5640")
            self.preview.configure(cursor="hand2")
            return
        original = item.image
        image = original.copy()
        image.thumbnail((max(1, width-24), max(1, height-24)), Image.Resampling.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(image, master=self.root)
        self.preview.create_rectangle((width-image.width)/2-1, (height-image.height)/2-1,
                                      (width+image.width)/2+1, (height+image.height)/2+1,
                                      fill=C["white"], outline=C["border"])
        self.preview.create_image(width/2, height/2, image=self._preview_photo)
        self.preview_index.configure(text=f"{self.batch.items.index(item)+1} / {len(self.batch.items)}")
        self.image_info.configure(text=f"{original.width} × {original.height} px · Bấm để zoom / crop · {item.name[:24]}")
        self.preview.configure(cursor="hand2")

    def open_image_viewer(self):
        item = self.batch.get(self.selected_id)
        if item is None or self.closing:
            return
        if self._image_viewer is not None:
            if self._image_viewer.item is item:
                self._image_viewer.window.lift()
                return
            self._image_viewer.close()
        self._image_viewer = ImageViewer(self.root, item, self._image_edited,
            lambda: not self.running and not self.importing and not self.closing and self.batch.get(item.id) is item,
            lambda: setattr(self, '_image_viewer', None))

    def _image_edited(self, item):
        self.select_item(item.id)
        self.operation_var.set('Đã crop ảnh · Nhận diện lại để cập nhật văn bản. Ảnh gốc được giữ nguyên.')

    def save_selected_image(self):
        item = self.batch.get(self.selected_id)
        if item:
            save_image_dialog(self.root, item, original=True)

    def save_all_images(self):
        if not self.batch.items or self.importing or self.closing:
            return
        folder = filedialog.askdirectory(parent=self.root, title='Lưu toàn bộ ảnh gốc vào thư mục')
        if not folder:
            return
        from .image_export import export_all_images
        try:
            paths = export_all_images(self.batch.items, Path(folder))
            self.operation_var.set(f'Đã lưu {len(paths)} ảnh gốc vào {folder}')
        except (OSError, ValueError) as error:
            messagebox.showerror('Không lưu được ảnh', str(error), parent=self.root)

    def _update_camera_progress(self):
        items = [item for item in self.batch.items if item.source.startswith('OV5640')]
        for panel in self._queue_panels:
            panel.update(items, self._camera_progress)

    def _render_result(self):
        item = self.batch.get(self.selected_id)
        self._rendering_text = True
        self._result_id = item.id if item else None
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        if item and item.text:
            self.result_text.insert("1.0", item.text)
        self.result_text.edit_reset()
        self.result_text.edit_modified(False)
        self.result_text.configure(state="normal" if item and item.status == "done" else "disabled")
        self._rendering_text = False
        if item and item.status == "done":
            self.empty_result.place_forget()
            self.result_hint.configure(text=f"{item.seconds:.1f} giây · Bạn có thể sửa văn bản trước khi lưu.", fg=C["muted"])
        else:
            title, detail = "Chưa có văn bản", "Thêm ảnh rồi nhấn Nhận diện.\nMình sẽ đọc từng dòng cho bạn."
            if item:
                title, detail = "Ảnh đã sẵn sàng", "Nhấn Nhận diện để chuyển\nchữ trong ảnh thành văn bản."
                if item.status == "processing":
                    title, detail = "Mình đang đọc chữ…", "Bạn có thể xem các ảnh khác\ntrong lúc chờ kết quả."
                elif item.status == "error":
                    title, detail = "Chưa đọc được ảnh này", item.error[:520]
                elif item.status == "cancelled":
                    title, detail = "Đã dừng nhận diện", "Nhấn Nhận diện để thử lại ảnh này."
            self.empty_result_title.configure(text=title, fg=C["error"] if item and item.status == "error" else C["ink"])
            self.empty_result_detail.configure(text=detail)
            self.empty_result.place(relx=0.5, rely=0.4, anchor="center", relwidth=0.88)
            self.result_hint.configure(text="Kết quả có thể chỉnh sửa trực tiếp ở đây.", fg=C["muted"])
        self._update_text_stats()

    def _save_editor(self):
        item = self.batch.get(self._result_id)
        if item and item.status == "done":
            item.text = self.result_text.get("1.0", "end-1c")

    def _on_text_modified(self, _):
        if self.result_text.edit_modified():
            if not self._rendering_text:
                self._save_editor()
                self._update_text_stats()
                self._sync_controls()
            self.result_text.edit_modified(False)

    def _update_text_stats(self):
        item = self.batch.get(self.selected_id)
        text = item.text if item else ""
        self.text_stats.configure(text=f"{len(text)} ký tự  ·  {len(text.split())} từ")

    @property
    def locked(self) -> bool:
        return self.running or self.importing or self.camera is not None or self.closing

    def import_files(self, paths: list[str] | None = None):
        if self.locked:
            return
        if paths is None:
            paths = list(filedialog.askopenfilenames(
                parent=self.root, title="Thêm ảnh từ máy tính",
                filetypes=[("Ảnh", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"), ("Tất cả file", "*.*")],
            ))
        if not paths:
            return
        try:
            self.batch.check_capacity(len(paths))
        except BatchFullError as exc:
            messagebox.showwarning("Không thể thêm ảnh", str(exc), parent=self.root)
            return
        self.importing = True
        self._sync_controls()
        self.operation_var.set(f"Đang đọc {len(paths)} ảnh…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._start_background(import_images, (paths, self.events, self._shutdown), "VietOCR-import")


    def open_wifi_settings(self):
        from .wifi_settings_view import open_wifi_settings
        open_wifi_settings(self)

    def _wifi_event(self, action, value, error):
        if action == 'wifi_state':
            if error:
                self._wifi_state = None
                self.wifi_connection_var.set('Wi-Fi · Chưa đọc được trạng thái')
                self.wifi_detail_var.set(str(error))
            else:
                self._wifi_state = value
                self.wifi_connection_var.set(value.summary)
                self.wifi_detail_var.set(value.detail)
                if self._wifi_widgets and not self._wifi_widgets['name_edited'] and not self._wifi_widgets['ssid'].get():
                    self._wifi_widgets['ssid'].set(value.ssid or value.saved_ssid)
            return
        if not self._wifi_widgets: return
        for button in self._wifi_widgets['buttons']: button.configure(state='normal')
        if error:
            self._wifi_widgets['message'].set(f'Wi-Fi: {error}'); return
        if action == 'wifi_profiles':
            self._wifi_widgets['receive_profiles'](value)
        elif action == 'wifi_scan':
            self._wifi_widgets['combo']['values'] = [row[0] for row in value]
            self._wifi_widgets['message'].set(f'Tìm thấy {len(value)} mạng. Chọn mạng rồi nhập mật khẩu.')
        elif action == 'wifi_status':
            fields = value.split()
            if value.startswith('WIFI STATUS READY '):
                self._wifi_widgets['message'].set(f'Đã kiểm tra đường LAN tới {fields[3]}:80. HTTP hoạt động; trạng thái cảm biến hiện ở cửa sổ camera.')
            else: self._wifi_widgets['message'].set('ESP32 đang kết nối, hãy đợi rồi kiểm tra lại.' if 'JOINING' in value else 'ESP32 chưa vào Wi-Fi. Kiểm tra mật khẩu và dùng mạng 2.4 GHz.')
        else: self._wifi_widgets['message'].set(value)

    def open_camera(self):
        if self.closing or self.robot_link is None or not self.robot_link.connected.is_set():
            self.operation_var.set('Kết nối trợ lý Bluetooth trước khi mở OV5640.')
            return
        if self._ov_dialog is not None and self._ov_dialog.winfo_exists():
            self._ov_dialog.lift()
            if self._ov_state not in ('opening', 'ready', 'receiving', 'reviewing'):
                self._request_ov_preview()
            return
        window = tk.Toplevel(self.root)
        self._ov_dialog = window
        window.title('Camera OV5640')
        window.configure(bg=C['bg'])
        window.resizable(True, True)
        window.geometry(f'{min(1160, window.winfo_screenwidth()-60)}x{min(880, window.winfo_screenheight()-100)}+30+30')
        # Reserve the footer before expandable content. A fixed 210px window
        # clipped the shutter button at Windows font/display scaling settings.
        footer = tk.Frame(window, bg=C['bg'], padx=18, pady=18)
        footer.pack(side='bottom', fill='x')
        shutter = ttk.Button(footer, text='Chụp OV5640', style='Primary.TButton', command=self.capture_ov)
        shutter.pack(side='left', padx=(0, 8))
        view = ttk.Button(footer, text='Xem lại camera', command=self._request_ov_preview)
        view.pack(side='left', padx=(0, 8))
        skip = ttk.Button(footer, text='Bỏ qua · Chụp tiếp', command=self._finish_ov_review, state='disabled')
        skip.pack(side='left', padx=(0, 8))
        ttk.Button(footer, text='Đóng', command=self._close_ov_camera).pack(side='right')
        body = tk.Frame(window, bg=C['bg'], padx=24, pady=20)
        body.pack(fill='both', expand=True)
        heading=tk.Frame(body,bg=C['bg']); heading.pack(fill='x')
        label(heading, 'Camera OV5640', size=18, bold=True).pack(side='left')
        settings_button=ttk.Button(heading,text='Cấu hình camera',command=self.open_camera_settings)
        settings_button.pack(side='right')
        label(body, textvariable=self.wifi_connection_var, justify='left', wraplength=800).pack(anchor='w', pady=(8, 0))
        camera_help = label(body, 'Ảnh chụp 5 MP · Bấm vào vùng chữ trên preview để lấy nét. Xem lại ảnh 3 giây rồi chụp tiếp.',
                            size=9, color=C['muted'], justify='left', wraplength=800)
        camera_help.pack(anchor='w', pady=(10, 8))
        orientation = tk.Frame(body, bg=C['bg']); orientation.pack(fill='x', pady=(0, 6))
        mirror = ttk.Checkbutton(orientation, text='Lật ngang', variable=self._ov_mirror, command=self._change_ov_orientation)
        mirror.pack(side='left', padx=(0, 18))
        flip = ttk.Checkbutton(orientation, text='Lật dọc', variable=self._ov_flip, command=self._change_ov_orientation)
        flip.pack(side='left')
        label(orientation, 'Áp dụng cho cả ảnh chụp', color=C['muted']).pack(side='left', padx=18)
        metrics = tk.StringVar(value='Đang đo tốc độ…')
        label(orientation, textvariable=metrics, color=C['muted']).pack(side='right')
        message = tk.StringVar(value='Đang mở camera…')
        status_label = label(body, textvariable=message, color=C['muted'], justify='left', wraplength=800)
        status_label.pack(anchor='w', pady=8)
        def resize_camera_labels(event):
            status_label.configure(wraplength=max(240, event.width-48))
            camera_help.configure(wraplength=max(240, event.width-48))
        body.bind('<Configure>', resize_camera_labels)
        live = tk.Canvas(body, bg=C['preview'], height=540, width=800, highlightthickness=0)
        live.pack(fill='both', expand=True)
        progress = ttk.Progressbar(body, mode='determinate', maximum=100, style='Green.Horizontal.TProgressbar')
        progress.pack(fill='x', pady=8)
        self._ov_widgets = {'capture': shutter, 'view': view, 'skip': skip, 'message': message, 'progress': progress, 'live': live,
                            'mirror': mirror, 'flip': flip, 'metrics': metrics, 'settings': settings_button}
        live.bind('<Configure>', lambda _: self._draw_ov_image())
        live.bind('<Button-1>', self._focus_camera_at)
        self._queue_panels.append(QueueProgress(window, self.select_item))
        self._update_camera_progress()
        window.update_idletasks()
        window.minsize(min(800, window.winfo_screenwidth()-40), min(520, window.winfo_screenheight()-80))
        window.after_idle(lambda: apply_titlebar(window))
        window.protocol('WM_DELETE_WINDOW', self._close_ov_camera)
        window.bind('<Escape>', lambda _: self._close_ov_camera())
        self._request_ov_preview()

    def _set_ov_status(self, state, message):
        self._ov_state = state
        self._ov_preview_ready = state == 'ready'
        if self._ov_widgets:
            self._ov_widgets['message'].set(message)

    def _cancel_ov_preview_timer(self):
        if self._ov_preview_timer is not None:
            self.root.after_cancel(self._ov_preview_timer)
            self._ov_preview_timer = None

    def _request_ov_preview(self):
        if self.closing or self._ov_receiving or self._camera_config_busy or self._ov_state == 'opening' or self._ov_pending_photo is not None:
            return
        self._stop_ov_stream()
        self._ov_generation += 1
        self._ov_frame_count = 0
        self._ov_fps_at = time.monotonic()
        mirror,flip = self._ov_orientation_requested or (None,None)
        if self.robot_link is None or not self.robot_link.camera('open', request_token=self._ov_generation,
                                                               mirror=mirror, flip=flip):
            self._set_ov_status('failed', 'Kết nối trợ lý Bluetooth trước khi mở camera.')
        else:
            self._ov_preview_deadline = time.monotonic() + 30
            self._set_ov_status('opening', 'Đang kiểm tra Wi-Fi trước khi mở cảm biến…')
            self.operation_var.set('Đang mở camera OV5640…')
            self._ov_preview_timer = self.root.after(20, self._poll_ov_preview)
        self._sync_controls()

    def _change_ov_orientation(self):
        self._ov_orientation_requested=(self._ov_mirror.get(),self._ov_flip.get())
        try:
            update_preferences(self.preferences_path, camera_mirror=self._ov_mirror.get(), camera_flip=self._ov_flip.get())
        except OSError:
            logger.warning('Cannot save camera orientation', exc_info=True)
        # Restart the reader so buffered JPEGs with the previous orientation
        # cannot appear after the new sensor settings are acknowledged.
        self._request_ov_preview()

    def open_camera_settings(self):
        if self._camera_config_window is not None and self._camera_config_window.alive:
            self._camera_config_window.window.lift(); return
        if self.robot_link is None or not self.robot_link.connected.is_set():
            self.operation_var.set('Kết nối ESP32 trước khi chỉnh camera.'); return
        from .camera_settings_view import CameraSettingsWindow
        self._camera_config_window=CameraSettingsWindow(self._ov_dialog or self.root,
            lambda:self._request_camera_settings('settings_get'), self._apply_camera_settings)
        self._request_camera_settings('settings_get')

    def _request_camera_settings(self, action, settings=None, persist=True):
        window=self._camera_config_window
        if self._camera_config_busy: return
        if self.robot_link is None or not self.robot_link.camera_settings(action,settings,persist=persist):
            if window is not None and window.alive: window.receive(error='Bluetooth đã ngắt hoặc đang bận.')
            return
        self._camera_config_busy=True
        if window is not None and window.alive: window.busy()
        self._sync_controls()

    def _apply_camera_settings(self, settings, persist):
        self._stop_ov_stream()
        self._ov_generation+=1
        if self._ov_dialog is not None: self._set_ov_status('configuring','Đang đổi cấu hình camera…')
        self._request_camera_settings('settings_set',settings,persist)

    def _focus_camera_at(self, event):
        if self._ov_state!='ready' or self._camera_config_busy or not self._ov_display_box:
            return
        left,top,width,height=self._ov_display_box
        if not (left<=event.x<=left+width and top<=event.y<=top+height):
            return
        x=round(100*(event.x-left)/width); y=round(100*(event.y-top)/height)
        self._stop_ov_stream(); self._ov_generation+=1
        self._ov_focus_point=(x,y)
        self._draw_ov_image()
        self._set_ov_status('configuring','Đang lấy nét tại điểm đã chọn…')
        self._request_camera_settings('settings_focus',{'focus_x':x,'focus_y':y},False)

    def _camera_settings_event(self, action, config, error):
        self._camera_config_busy=False
        if not error and not isinstance(config,dict): error='Không đọc được cấu hình camera. Hãy tải lại.'
        window=self._camera_config_window
        if window is not None and window.alive: window.receive(config,error)
        if not error:
            self._ov_mirror.set(bool(config['settings']['hmirror']))
            self._ov_flip.set(bool(config['settings']['vflip']))
            self._ov_focus_point=(config['settings'].get('focus_x',50),config['settings'].get('focus_y',50))
            if action in ('settings_set','settings_focus'):
                self._ov_orientation_requested=None
                try: update_preferences(self.preferences_path,camera_mirror=self._ov_mirror.get(),camera_flip=self._ov_flip.get())
                except OSError: logger.warning('Cannot save camera orientation',exc_info=True)
                if self._ov_dialog is not None and not self.closing: self._request_ov_preview()
        elif action in ('settings_set','settings_focus') and self._ov_dialog is not None:
            self._set_ov_status('failed',str(error))
        self._sync_controls()

    def _poll_ov_preview(self):
        self._ov_preview_timer = None
        if self.closing or self._ov_dialog is None or self._ov_state not in ('opening', 'ready') or self._ov_receiving:
            return
        stream = self._ov_stream
        was_ready = self._ov_preview_ready
        error, jpeg = (stream.error(), stream.latest()) if stream is not None else (None, None)
        if jpeg is not None and not error:
            try:
                with Image.open(io.BytesIO(jpeg)) as image:
                    if image.width * 3 != image.height * 4 or not (160 <= image.width <= 2592):
                        raise ValueError('Preview cần cùng tỷ lệ 4:3 với ảnh chụp OV5640.')
                    self._ov_live_image = image.convert('RGB')
                self._draw_ov_image()
                self._ov_frame_count += 1
                now = time.monotonic()
                elapsed = now - self._ov_fps_at
                if elapsed >= 1.0 and self._ov_widgets:
                    self._ov_widgets['metrics'].set(f'{self._ov_live_image.width} × {self._ov_live_image.height} · {self._ov_frame_count/elapsed:.1f} FPS')
                    self._ov_frame_count = 0; self._ov_fps_at = now
                if not was_ready:
                    self._ov_fps_at = now; self._ov_frame_count = 0
                    self._set_ov_status('ready', 'Preview UDP · Ảnh chụp 5 MP, cùng hướng với preview.')
                    self.operation_var.set('Đang xem stream OV5640 qua Wi-Fi.')
            except (OSError, ValueError) as exc:
                error = f'Không đọc được khung hình camera: {exc}'
        if not error and self._ov_state == 'opening' and time.monotonic() >= self._ov_preview_deadline:
            error = 'Chưa có khung hình. Cần firmware OV5640 3.0.0 trở lên; kiểm tra Wi-Fi và UDP 82.'
        if error:
            self._stop_ov_stream()
            self._set_ov_status('failed', error)
            self.operation_var.set(error)
        else:
            self._ov_preview_timer = self.root.after(20, self._poll_ov_preview)
        if error or self._ov_preview_ready != was_ready:
            self._sync_controls()

    def _stop_ov_stream(self):
        self._cancel_ov_preview_timer()
        if self._ov_stream is not None:
            self._ov_stream.stop()
            self._ov_stream = None

    def _draw_ov_image(self):
        if self._ov_live_image is None or not self._ov_widgets:
            return
        live = self._ov_widgets['live']
        width, height = max(1, live.winfo_width()), max(1, live.winfo_height())
        image = self._ov_live_image
        scale = min(width/image.width, height/image.height)
        display = image.resize((max(1, round(image.width*scale)), max(1, round(image.height*scale))), Image.Resampling.BILINEAR)
        self._ov_live_photo = ImageTk.PhotoImage(display, master=self.root)
        live.delete('all')
        live.create_image(width/2, height/2, image=self._ov_live_photo)
        dw,dh=display.size
        self._ov_display_box=((width-dw)/2,(height-dh)/2,dw,dh)
        if self._ov_state not in ('reviewing','receiving'):
            x=(width-dw)/2+dw*self._ov_focus_point[0]/100
            y=(height-dh)/2+dh*self._ov_focus_point[1]/100
            live.create_rectangle(x-18,y-18,x+18,y+18,outline=C['green'],width=2)

    def _start_ov_review(self, value):
        metadata, jpeg = value
        with Image.open(io.BytesIO(jpeg)) as image:
            if image.size != (metadata.width, metadata.height):
                raise ValueError('Kích thước JPEG không khớp metadata.')
            self._ov_live_image = image.convert('RGB')
        if self._ov_dialog is None:
            self._queue_ov_photo(value)
            return
        self._ov_pending_photo = value
        self._ov_review_deadline = time.monotonic() + 3
        self._draw_ov_image()
        self._review_ov_tick()

    def _review_ov_tick(self):
        self._ov_review_timer = None
        if self.closing or self._ov_pending_photo is None:
            return
        remaining = self._ov_review_deadline - time.monotonic()
        if remaining <= 0:
            self._finish_ov_review()
            return
        self._set_ov_status('reviewing', f'Ảnh vừa chụp · Tự vào hàng đợi sau {remaining:.1f}s. Bỏ qua để chụp tiếp.')
        self._sync_controls()
        self._ov_review_timer = self.root.after(100, self._review_ov_tick)

    def _finish_ov_review(self, resume=True):
        if self._ov_review_timer is not None:
            self.root.after_cancel(self._ov_review_timer)
            self._ov_review_timer = None
        value = self._ov_pending_photo
        if value is None:
            return
        try:
            self._queue_ov_photo(value)
        except (OSError, ValueError) as error:
            self._set_ov_status('reviewing', f'Chưa lưu được ảnh: {error}. Bấm Bỏ qua để thử lưu lại.')
            return
        self._ov_pending_photo = None
        self._ov_state = 'closed'
        if resume and self._ov_dialog is not None and not self.closing:
            self._request_ov_preview()
        self._sync_controls()

    def _queue_ov_photo(self, value):
        metadata, jpeg = value
        item = self.batch.add_jpeg(jpeg, f'OV5640_{metadata.id}.jpg')
        self.select_item(item.id)
        if not self.running and not self.closing:
            self._set_assistant(AssistantState.RECEIVED, 'Đã nhận ảnh OV5640!', 'Ảnh gốc đã vào hàng đợi. Bạn có thể chụp tiếp.')
            if not self._auto_queue_halted:
                self.root.after_idle(self.start_recognition)

    def _ov_preview_event(self, action, value, error):
        if self._ov_dialog is None or self._ov_receiving or self._ov_state != 'opening':
            return
        if error:
            self._stop_ov_stream()
            self._set_ov_status('failed', f'Không mở được camera: {error}')
            self.operation_var.set(f'OV5640: {error}')
            self._sync_controls()
            return
        if action == 'open':
            self._set_ov_status('opening', 'Đang kết nối stream Wi-Fi…')
            self._ov_orientation_requested=None
            if getattr(value,'mirror',None) is not None:self._ov_mirror.set(value.mirror)
            if getattr(value,'flip',None) is not None:self._ov_flip.set(value.flip)
            self._ov_stream = CameraStream(value).start()
            self._cancel_ov_preview_timer()
            self._ov_preview_timer = self.root.after(20, self._poll_ov_preview)
        self._sync_controls()

    def _close_ov_camera(self):
        self._finish_ov_review(resume=False)
        if self._ov_pending_photo is not None:
            return
        self._stop_ov_stream()
        self._ov_generation += 1
        if self.robot_link and self.robot_link.connected.is_set():
            self.robot_link.camera('close')
        window = self._ov_dialog
        self._ov_dialog = None
        self._ov_widgets = {}
        self._ov_state = 'closed'
        self._ov_preview_ready = False
        self._ov_live_photo = None
        self._ov_live_image = None
        if window is not None:
            self._queue_panels = [panel for panel in self._queue_panels if panel.frame.master is not window]
            window.destroy()

    def capture_ov(self):
        if self._ov_receiving or self.importing or self.closing or self._camera_config_busy:
            return
        if self._ov_dialog is None or not self._ov_preview_ready:
            self.open_camera()
            return
        self._stop_ov_stream()
        if self.robot_link is None or not self.robot_link.camera('capture'):
            self._set_ov_status('failed', 'Bluetooth đã ngắt hoặc đang bận. Mở lại camera để chụp.')
            self.operation_var.set('Chưa gửi được lệnh chụp OV5640.')
            self._sync_controls()
            return
        self._ov_receiving = True
        self._set_ov_status('receiving', 'Đang chụp và nhận ảnh gốc qua Wi-Fi…')
        self._ov_widgets['progress']['value'] = 0
        self.operation_var.set('Đang nhận JPEG gốc từ OV5640…')
        self._sync_controls()

    def _on_capture(self, image: Image.Image, name: str):
        try:
            item = self.batch.add(image, name)
        except (BatchFullError, ValueError) as exc:
            messagebox.showwarning("Không thể thêm ảnh", str(exc), parent=self.camera or self.root)
            return
        self.select_item(item.id)
        self._set_assistant(AssistantState.RECEIVED, "Đã nhận ảnh của bạn!", f"Có {len(self.batch.items)} ảnh đang chờ trong danh sách.")
        self.operation_var.set(f"Đã chụp {name} · {len(self.batch.items)} ảnh")

    def _on_camera_close(self):
        self.camera = None
        self._sync_controls()
        if not self.closing:
            self._wait_camera_release()

    def _wait_camera_release(self):
        self._camera_release_timer = None
        if self.closing:
            return
        self._camera_workers = [worker for worker in self._camera_workers if worker.is_alive()]
        self._sync_controls()
        if self._camera_workers:
            self._camera_release_timer = self.root.after(50, self._wait_camera_release)

    def rotate_selected(self):
        item = self.batch.get(self.selected_id)
        if not item or self.locked:
            return
        item.rotate()
        self.select_item(item.id)
        self.operation_var.set("Đã xoay ảnh 90° sang trái · Nhận diện lại để cập nhật văn bản")

    def remove_selected(self):
        if self.locked or self.selected_id is None:
            return
        index = next((i for i, item in enumerate(self.batch.items) if item.id == self.selected_id), 0)
        self.batch.remove(self.selected_id)
        self.selected_id = self.batch.items[min(index, len(self.batch.items)-1)].id if self.batch.items else None
        self._result_id = None
        self._refresh()
        if not self.batch.items:
            self._set_assistant(AssistantState.AWAKE, "Mình vẫn ở đây!", "Thêm ảnh để bắt đầu một lượt mới nhé.")
        else:
            self._publish_robot_state()
        self.operation_var.set(f"Danh sách hiện có {len(self.batch.items)} ảnh")

    def clear_batch(self):
        if self.locked:
            return
        self.batch.clear()
        self.selected_id = self._result_id = None
        self._refresh()
        self.progress["value"] = 0
        self._set_assistant(AssistantState.AWAKE, "Bắt đầu một lượt mới nhé!", "Mình đã sẵn sàng nhận thêm ảnh.")
        self.operation_var.set("Đã dọn danh sách · Sẵn sàng nhận ảnh mới")

    def _refresh(self):
        self._render_queue()
        self._draw_preview()
        self._render_result()
        self._sync_controls()

    def retry_selected(self):
        item = self.batch.get(self.selected_id)
        if item and not self.locked:
            self.start_recognition([item])

    def start_recognition(self, items=None):
        if self.locked:
            return
        self._save_editor()
        jobs = list(items) if items is not None else [item for item in self.batch.items if item.status != "done"]
        if not jobs:
            return
        self.running = True
        self._auto_queue_halted = False
        self.cancel_event = threading.Event()
        self._run_total = len(jobs)
        self._run_index = 0
        settings = OCRSettings(self.settings.weights, self.settings.device,
                               "auto" if self.layout_var.get() == "Tự tách dòng" else "line")
        self._sync_controls()
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.operation_var.set("Đang nạp model · Lần đầu có thể cần vài giây…")
        self._set_assistant(AssistantState.PROCESSING, "Để mình đọc giúp bạn…", "Đang chuẩn bị mô hình nhận diện trên máy.")
        # Queue membership and images stay fixed until the worker finishes.
        snapshots = [(item.id, item.image_path) for item in jobs]
        self._start_background(recognize_images, (snapshots, settings, self.cancel_event, self.service, self.events), "VietOCR-OCR")

    def _warm_model(self):
        self._warm_timer = None
        if self.closing or self.running or not Path(self.settings.weights).is_file(): return
        self.operation_var.set('Đang chuẩn bị model trong nền · Bạn có thể cấu hình Wi-Fi và xem camera.')
        self._start_background(warm_model, (self.settings, self.service, self.events, self._shutdown), 'VietOCR-model-warmup')


    def cancel_recognition(self):
        if not self.running or self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self._auto_queue_halted = True
        self._sync_controls()
        self.operation_var.set("Đang dừng nhận diện và giải phóng model…")
        self._set_assistant(AssistantState.PROCESSING, "Mình đang dừng lại…", "Kết quả đã hoàn tất được giữ lại.")

    def _start_background(self, target, args, name):
        self._jobs = [job for job in self._jobs if job.is_alive()]
        job = threading.Thread(target=target, args=args, name=name, daemon=True)
        self._jobs.append(job)
        job.start()

    def report_callback_exception(self, exception_type, exception, traceback):
        logger.error("UI callback failed", exc_info=(exception_type, exception, traceback))
        if self.closing:
            return
        self.operation_var.set("Có lỗi giao diện · Chi tiết đã lưu trong .logs/vietocr.log")
        if self._error_dialog_pending:
            return
        self._error_dialog_pending = True

        def show_error():
            try:
                if not self.closing:
                    messagebox.showerror("Lỗi ứng dụng", f"{str(exception)[:1200]}\n\nLog: {LOG_DIRECTORY / 'vietocr.log'}",
                                         parent=self.root)
            finally:
                self._error_dialog_pending = False

        self.root.after_idle(show_error)

    def _poll_events(self):
        if self.closing:
            return
        self._poll_timer = None
        try:
            # Bound work per tick, keeping camera and input events responsive.
            for _ in range(25):
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_event(event)
                except Exception as exc:
                    self.report_callback_exception(type(exc), exc, exc.__traceback__)
        finally:
            if not self.closing:
                self._poll_timer = self.root.after(65, self._poll_events)

    def _handle_event(self, event):
        kind, *data = event
        if kind == 'model_warmed':
            service, info, seconds, error = data
            if service is not self.service or self.running: return
            if error:
                self.operation_var.set('Model chưa sẵn sàng · Nhấn nhận diện để thử lại; xem .logs/ocr-worker.log.')
            elif info:
                self.model_label.configure(text=f'VietHandOCR · {info["name"]} · {info["id"]}')
                self.operation_var.set(f'Model sẵn sàng · Nạp nền {seconds:.1f} giây')
            return
        if kind == "robot_connection":
            link, status, detail = data
            if link is self.robot_link:
                self.robot_connection_var.set(detail)
                summary = {"connected": "ESP32 · Đã kết nối BLE", "connecting": "ESP32 · Đang kết nối…",
                           "waiting": "ESP32 · Đang chờ Bluetooth…"}.get(status, "ESP32 · Chưa kết nối")
                self.robot_connection_label.configure(text=summary, fg=C["green"] if status == "connected" else C["muted"])
                self._sync_robot_dialog_controls()
                if status != 'connected':
                    if self._camera_config_busy:
                        self._camera_config_busy=False
                        if self._camera_config_window is not None and self._camera_config_window.alive:
                            self._camera_config_window.receive(error='Bluetooth đã ngắt. Kết nối lại rồi tải cấu hình.')
                    self._wifi_state = None
                    self.wifi_connection_var.set('Wi-Fi · BLE chưa kết nối, chưa xác định trạng thái hiện tại')
                    self.wifi_detail_var.set('ESP32 vẫn giữ mạng đã lưu. Trạng thái sẽ cập nhật khi Bluetooth nối lại.')
                    self._ov_receiving = False
                    self._stop_ov_stream()
                    if self._ov_pending_photo is None:
                        self._set_ov_status('closed', 'Kết nối trợ lý Bluetooth để xem camera.')
                self._sync_controls()
        elif kind == 'robot_camera':
            link, action, value, error = data
            if link is not self.robot_link: return
            if action.startswith('settings_'):
                self._camera_settings_event(action,value,error); return
            if action.startswith('wifi_'):
                self._wifi_event(action, value, error); return
            if action == 'open':
                request_token, value = value
                if request_token != self._ov_generation: return
            if action == 'progress':
                received, total = value
                if total:
                    message = f'Đang nhận ảnh OV5640: {received * 100 // total}% · {received:,}/{total:,} byte'
                    self.operation_var.set(message)
                    if self._ov_widgets:
                        self._ov_widgets['message'].set(message)
                        self._ov_widgets['progress']['value'] = received * 100 / total
                return
            if action == 'open':
                self._ov_preview_event(action, value, error)
                return
            if action == 'capture': self._ov_receiving = False
            if error:
                self._set_ov_status('failed', f'OV5640: {error}')
                self.operation_var.set(f'OV5640: {error}')
                if not self.running: self._set_assistant(AssistantState.ERROR, 'Chưa nhận được ảnh camera', 'Xem log Bluetooth để biết lỗi gốc.')
            elif action == 'capture':
                if self._ov_widgets:
                    self._ov_widgets['progress']['value'] = 100
                self._start_ov_review(value)
            else:
                self.operation_var.set('Đang xem camera qua Wi-Fi.' if action == 'open' else 'Đã trở về trợ lý.')
            self._sync_controls()
        elif kind == "robot_scan":
            self._receive_robot_scan(*data)
        elif kind == "robot_radio":
            self._receive_robot_radio(*data)
        elif kind == "robot_radio_permission":
            self._receive_robot_permission(*data)
        elif kind == "import_item":
            path, image = data
            item = self.batch.add(image, Path(path).name, str(Path(path).resolve()))
            self.select_item(item.id)
        elif kind == "import_finished":
            self.importing = False
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self._sync_controls()
            errors = data[0]
            self.operation_var.set(f"Đã nhận {len(self.batch.items)} ảnh · Sẵn sàng nhận diện")
            if self.batch.items:
                self._set_assistant(AssistantState.RECEIVED, "Đã nhận ảnh của bạn!", f"Mình sẵn sàng đọc {len(self.batch.items)} ảnh trong danh sách.")
            if errors:
                self._set_assistant(AssistantState.ERROR, "Có ảnh mình chưa mở được", "Bạn có thể thêm ảnh khác rồi thử lại.")
                messagebox.showwarning("Một số ảnh không đọc được", "\n\n".join(errors[:5]), parent=self.root)
        elif kind == "model_loaded":
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
        elif kind == "model_device":
            device = data[0]
            text = f"{device['name']} · {device['id']}" if device else device_label(self.settings.device)
            self.model_label.configure(text=f"VietHandOCR  ·  {text}")
        elif kind == "started":
            item_id, self._run_index, total = data
            item = self.batch.get(item_id)
            if item:
                self._camera_progress[item_id] = 0
                item.status, item.text, item.error = "processing", "", ""
                self._render_queue()
                if self.selected_id == item_id:
                    self._render_result()
                self._sync_controls()
                self.operation_var.set(f"Đang nhận diện ảnh {self._run_index}/{total} · {item.name}")
                self._set_assistant(AssistantState.PROCESSING, f"Đang đọc ảnh {self._run_index}/{total}", "Từng dòng chữ đang trở thành văn bản.")
        elif kind == "line_progress":
            item_id, line, total = data
            self._camera_progress[item_id] = line / total if total else 0
            self._update_camera_progress()
            self.progress["value"] = (self._run_index-1 + (line-1)/total) / self._run_total * 100
            self._publish_robot_progress()
            if not self.cancel_event.is_set():
                self.operation_var.set(f"Ảnh {self._run_index}/{self._run_total} · Đang đọc dòng {line}/{total}")
        elif kind == "result":
            item_id, text, error, seconds = data
            item = self.batch.get(item_id)
            if item:
                item.text, item.error, item.seconds = text, error, seconds
                item.status = "error" if error else "done"
                self._render_queue()
                if self.selected_id == item_id:
                    self._render_result()
                self.progress["value"] = self._run_index / self._run_total * 100
                self._publish_robot_progress()
                self._sync_controls()
        elif kind == "cancelled":
            item = self.batch.get(data[0])
            if item:
                item.status = "cancelled"
                self._render_queue()
                if item.id == self.selected_id:
                    self._render_result()
        elif kind == "fatal":
            self._auto_queue_halted = True
            self.operation_var.set("Không thể nạp model · Kiểm tra Cài đặt model")
            messagebox.showerror("Không thể khởi động AI", data[0], parent=self.root)
        elif kind == "finished":
            successes, failures, cancelled = data
            self.running = False
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self._sync_controls()
            if cancelled:
                self.operation_var.set(f"Đã dừng · {successes} ảnh hoàn tất, {failures} ảnh lỗi · Kết quả đã có được giữ lại")
                self._set_assistant(AssistantState.AWAKE, "Đã dừng theo ý bạn", "Bạn có thể tiếp tục với các ảnh còn lại.")
            elif failures:
                self._auto_queue_halted = True
                self.operation_var.set(f"{successes} ảnh hoàn tất · {failures} lỗi · Kiểm tra ảnh hoặc Cài đặt model rồi thử lại")
                self._set_assistant(AssistantState.ERROR, "Có ảnh cần thử lại", "Xem thông báo ở phần văn bản hoặc kiểm tra model.")
            else:
                pending = [item for item in self.batch.items if item.status == 'ready']
                if pending and not self._auto_queue_halted:
                    self.root.after_idle(lambda: self.start_recognition(pending))
                    return
                if self._ov_receiving:
                    self._set_assistant(AssistantState.PROCESSING, 'Đang nhận ảnh tiếp theo…', 'Ảnh đã đọc xong được giữ lại.')
                    return
                self.progress["value"] = 100
                self.operation_var.set(f"Hoàn tất {successes} ảnh · Chỉnh sửa văn bản, sao chép hoặc lưu .txt")
                self._set_assistant(AssistantState.DONE, "Xong rồi, bạn ơi!", "Văn bản đã sẵn sàng. Mình chờ lượt tiếp theo nhé.")

    def copy_selected(self):
        self._save_editor()
        item = self.batch.get(self.selected_id)
        if item and item.text.strip():
            self._copy(item.text, "Đã sao chép văn bản của ảnh đang chọn")

    def copy_all(self):
        self._save_editor()
        text = self.batch.combined_text()
        if text:
            self._copy(text, "Đã sao chép toàn bộ văn bản theo thứ tự ảnh")

    def _copy(self, text: str, message: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.operation_var.set(message)

    def save_results(self):
        self._save_editor()
        text = self.batch.combined_text()
        if not text:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Lưu văn bản tất cả ảnh", defaultextension=".txt",
                                          initialfile=f"VietOCR_{datetime.now():%Y%m%d_%H%M}.txt",
                                          filetypes=[("Văn bản UTF-8", "*.txt")])
        if path:
            try:
                Path(path).write_text(text + "\n", encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Không lưu được file", str(exc), parent=self.root)
            else:
                self.operation_var.set(f"Đã lưu {Path(path).name} · Văn bản UTF-8")

    def open_settings(self):
        if self.locked:
            return
        window = tk.Toplevel(self.root)
        window.title("VietOCR · Cài đặt model")
        window.configure(bg=C["white"])
        window.geometry(f'{min(900,self.root.winfo_screenwidth()-60)}x{min(640,self.root.winfo_screenheight()-80)}')
        window.minsize(760,540)
        window.resizable(True, True)
        window.transient(self.root)
        window.grab_set()
        window.after_idle(lambda: apply_titlebar(window))
        body = tk.Frame(window, bg=C["white"], padx=25, pady=22)
        body.pack(fill="both", expand=True)
        label(body, "Mô hình nhận diện cục bộ", size=18, bold=True).pack(anchor="w")
        label(body, "Thiết lập cho phiên làm việc này. Model chỉ được nạp khi nhận diện.",
              size=9, color=C["muted"]).pack(anchor="w", pady=(5, 20))
        label(body, "File trọng số (.pth)", bold=True).pack(anchor="w")
        path_row = tk.Frame(body, bg=C["white"])
        path_row.pack(fill="x", pady=(6, 14))
        weights_var = tk.StringVar(value=self.settings.weights)
        ttk.Entry(path_row, textvariable=weights_var).pack(side="left", fill="x", expand=True, ipady=5)

        def browse():
            path = filedialog.askopenfilename(parent=window, title="Chọn model VietHandOCR", filetypes=[("PyTorch weights", "*.pth")])
            if path:
                weights_var.set(path)

        ttk.Button(path_row, text="Chọn file", command=browse).pack(side="left", padx=(8, 0))
        row = tk.Frame(body, bg=C["white"])
        row.pack(fill="x", pady=(0, 15))
        device_column = tk.Frame(row, bg=C["white"])
        device_column.pack(side="left", fill="x", expand=True)
        label(device_column, "Thiết bị xử lý", bold=True).pack(anchor="w", pady=(0, 6))
        choices = dict(DEVICE_CHOICES)
        if self.settings.device not in choices.values():
            choices[self.settings.device] = self.settings.device
        device_var = tk.StringVar(value=next(name for name, value in choices.items() if value == self.settings.device))
        ttk.Combobox(device_column, textvariable=device_var, values=tuple(choices), state="readonly", width=38).pack(anchor="w")
        camera_column = tk.Frame(row, bg=C["white"])
        camera_column.pack(side="left", fill="x", expand=True)
        label(camera_column, "Nguồn ảnh", bold=True).pack(anchor="w", pady=(0, 6))
        label(camera_column, "Ảnh trên máy tính hoặc camera OV5640", color=C['muted']).pack(anchor='w')
        label(body, "Tự động ưu tiên GPU rời, GPU tích hợp rồi CPU khi thiết bị không chạy được.\nThiết bị thực tế hiện ở thanh trạng thái sau khi nạp model.\nGPU tích hợp dùng DirectML và bộ ONNX tương ứng với trọng số đã chọn.",
              size=9, color=C["muted"], justify="left").pack(anchor="w", pady=(0, 20))

        def save():
            path = Path(weights_var.get()).expanduser()
            if not path.is_file():
                messagebox.showwarning("Chưa tìm thấy model", "Hãy chọn một file trọng số .pth có sẵn.", parent=window)
                return
            self.settings = OCRSettings(str(path.resolve()), choices[device_var.get()])
            self.model_label.configure(text=f"VietHandOCR  ·  {device_label(self.settings.device)}")
            self.operation_var.set("Đã cập nhật cài đặt · Model sẽ được nạp ở lượt nhận diện tiếp theo")
            window.destroy()

        ttk.Button(body, text="Lưu cài đặt", style="Primary.TButton", command=save).pack(side="right")
        ttk.Button(body, text="Đóng", command=window.destroy).pack(side="right", padx=10)
        window.bind("<Escape>", lambda _: window.destroy())

    def close(self, reason='window_close'):
        if self.closing:
            return
        logger.info("Desktop shutdown requested: reason=%s", reason)
        self.closing = True
        self._shutdown.set()
        self.cancel_event.set()
        self._robot_scan_cancel.set()
        self._robot_radio_cancel.set()

        def cleanup(description, action):
            try:
                action()
            except Exception:
                logger.exception("Shutdown cleanup failed: %s", description)

        close_service = getattr(self.service, "close", None)
        if close_service is not None:
            cleanup("AI process", close_service)
        cleanup("progress animation", self.progress.stop)
        cleanup("camera stream", self._stop_ov_stream)
        if self.camera is not None:
            cleanup("camera", self.camera.close)
        for timer in (self._poll_timer, self._preview_timer, self._camera_release_timer, self._ov_preview_timer, self._warm_timer, self._ov_review_timer):
            if timer is not None:
                cleanup("UI timer", lambda token=timer: self.root.after_cancel(token))
        cleanup("controls", self._sync_controls)
        cleanup("assistant", lambda: self._set_assistant(
            AssistantState.SLEEP, "Mình đi ngủ đây…", "Hẹn gặp bạn ở lần mở app tiếp theo."))
        for link in self._robot_links:
            cleanup("Bluetooth link", link.stop)
        self._close_deadline = time.monotonic() + 2.5
        try:
            self.root.after(100, self._finish_close)
        except tk.TclError:
            self._destroy()

    def _finish_close(self):
        service_closed = getattr(self.service, "closed", None)
        busy = (any(not link.closed.is_set() for link in self._robot_links)
                or any(job.is_alive() for job in self._jobs)
                or any(worker.is_alive() for worker in self._camera_workers)
                or (service_closed is not None and not service_closed.is_set()))
        if busy and time.monotonic() < self._close_deadline:
            self.root.after(50, self._finish_close)
        else:
            self._destroy()

    def _destroy(self):
        try:
            self.robot.stop()
        except tk.TclError:
            pass
        self._preview_photo = None
        self._thumbs.clear()
        self._robot_dialog = None
        self.root.__dict__.pop("report_callback_exception", None)
        try:
            self.root.destroy()
        except tk.TclError:
            pass  # A preceding Tcl error may already have destroyed the window.
