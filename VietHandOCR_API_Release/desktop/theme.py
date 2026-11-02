"""Shared palettes and the desktop's saved appearance preference."""

import sys
import tkinter as tk
from contextlib import contextmanager
from pathlib import Path
from tkinter import ttk

from .preferences import read_preferences, update_preferences

LIGHT = {
    "bg": "#F3F4F6", "white": "#FFFFFF", "ink": "#18202B",
    "muted": "#596576", "green": "#005FB8", "green_dark": "#004D96",
    "pale": "#EBF3FC", "border": "#DDE2E8", "error": "#B42335",
    "error_bg": "#FFF0F2", "amber": "#91600C", "on_accent": "#FFFFFE",
    "preview": "#E9EDF2", "selection": "#DCEBFA", "disabled_bg": "#ECEFF3",
    "disabled_fg": "#8993A0", "primary_disabled_bg": "#CAD7E5",
    "primary_disabled_fg": "#63768B", "scroll": "#BCC5D0", "shadow": "#D6DFEA",
    "paper_border": "#A6B7CC", "paper_line": "#8096B2",
}

DARK = {
    "bg": "#1C1C1C", "white": "#252525", "ink": "#F2F4F8",
    "muted": "#ABB3BF", "green": "#57C8FF", "green_dark": "#7ED5FF",
    "pale": "#233342", "border": "#393B40", "error": "#FF9CA8",
    "error_bg": "#42282E", "amber": "#EBC277", "on_accent": "#102333",
    "preview": "#17191D", "selection": "#293F53", "disabled_bg": "#2D2E31",
    "disabled_fg": "#7D8590", "primary_disabled_bg": "#334451",
    "primary_disabled_fg": "#91A6B5", "scroll": "#525862", "shadow": "#181E25",
    "paper_border": "#52657B", "paper_line": "#849BB5",
}

PALETTES = {"light": LIGHT, "dark": DARK}
# Keep this dictionary's identity: widgets and camera import the same object.
COLORS = DARK.copy()
PREFERENCES_PATH = Path(__file__).resolve().parents[1] / ".desktop-preferences.json"


def enable_crisp_scaling():
    """Request native Windows pixels before Tk creates any windows.

    System DPI awareness avoids bitmap-stretched text at 125/150% scaling.
    Tk 8.6 uses the startup monitor's DPI; leave per-monitor DPI to a future
    Tk upgrade rather than resize the whole widget tree while dragging windows.
    """
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def _pause_windows_redraw(root):
    """Freeze only visible HWNDs. Re-enabling hidden HWNDs would unhide them.

    https://learn.microsoft.com/windows/win32/gdi/wm-setredraw
    Collect everything before WM_SETREDRAW changes WS_VISIBLE.
    """
    if sys.platform != "win32" or not root.winfo_ismapped():
        return lambda: None
    import ctypes
    from ctypes import wintypes

    user = ctypes.windll.user32
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    for name in ("IsWindowVisible", "IsWindow"):
        method = getattr(user, name)
        method.argtypes, method.restype = [wintypes.HWND], wintypes.BOOL
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = wintypes.LPARAM
    user.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    user.RedrawWindow.restype = wintypes.BOOL
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
    user.EnumChildWindows.restype = wintypes.BOOL
    handles, top_levels = [], []

    @callback_type
    def collect(hwnd, _):
        if user.IsWindowVisible(hwnd) and hwnd not in handles:
            handles.append(hwnd)
        return True

    def collect_top(widget):
        if isinstance(widget, (tk.Tk, tk.Toplevel)) and widget.winfo_ismapped():
            hwnd = user.GetParent(widget.winfo_id()) or widget.winfo_id()
            if user.IsWindowVisible(hwnd):
                collect(hwnd, 0)
                top_levels.append(hwnd)
                user.EnumChildWindows(hwnd, collect, 0)
        for child in widget.winfo_children():
            collect_top(child)

    collect_top(root)
    frozen = []

    def restore():
        for hwnd in reversed(frozen):
            if user.IsWindow(hwnd):
                user.SendMessageW(hwnd, 0x000B, True, 0)
        # Invalidate background, frame and descendants, then paint the final palette.
        for hwnd in top_levels:
            if user.IsWindow(hwnd):
                user.RedrawWindow(hwnd, None, None, 0x0585)

    try:
        for hwnd in handles:
            user.SendMessageW(hwnd, 0x000B, False, 0)
            frozen.append(hwnd)
    except BaseException:
        restore()
        raise
    return restore


@contextmanager
def atomic_repaint(root):
    """Apply a palette in one Windows paint without hiding/rebuilding widgets."""
    restore = _pause_windows_redraw(root)
    try:
        yield
        root.update_idletasks()
    finally:
        restore()


def recolor_canvas(canvas, previous):
    replacements = {value.lower(): COLORS[key] for key, value in previous.items()}
    for item in canvas.find_all():
        for option in ("fill", "outline"):
            try:
                value = str(canvas.itemcget(item, option)).lower()
                if value in replacements:
                    canvas.itemconfigure(item, **{option: replacements[value]})
            except tk.TclError:  # Images/windows have no fill or outline.
                pass


def load_theme(path: Path) -> str:
    name = read_preferences(path).get("theme")
    return name if isinstance(name, str) and name in PALETTES else "dark"


def save_theme(path: Path, name: str) -> None:
    update_preferences(path, theme=name)


def set_palette(name: str) -> dict[str, str]:
    previous = COLORS.copy()
    COLORS.clear()
    COLORS.update(PALETTES[name])
    return previous


def apply_titlebar(window: tk.Misc) -> None:
    """Use native Windows dark captions when supported; other platforms use Tk.

    Attributes: https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
    Unsupported attributes are harmless on older Windows releases.
    """
    if sys.platform != "win32" or not window.winfo_exists():
        return
    try:
        import ctypes
        from ctypes import wintypes

        get_parent = ctypes.windll.user32.GetParent
        get_parent.argtypes = [wintypes.HWND]
        get_parent.restype = wintypes.HWND
        hwnd = get_parent(window.winfo_id()) or window.winfo_id()
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        set_attribute.restype = wintypes.LONG
        dark = wintypes.BOOL(COLORS["bg"] == DARK["bg"])
        set_attribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        for attribute, key in ((35, "bg"), (36, "ink")):
            red, green, blue = (int(COLORS[key][start:start+2], 16) for start in (1, 3, 5))
            color = wintypes.DWORD(red | green << 8 | blue << 16)
            set_attribute(hwnd, attribute, ctypes.byref(color), ctypes.sizeof(color))
    except (AttributeError, OSError, tk.TclError):
        pass


def recolor_widgets(widget: tk.Misc, previous: dict[str, str]) -> None:
    """Recolor Tk surfaces in place, preserving text, undo history, and focus.

    ttk controls use named styles. Canvas artwork is redrawn by its owner;
    actual uploaded images and webcam frames are never recolored.
    """
    if isinstance(widget, ttk.Widget):
        if isinstance(widget, ttk.Combobox):
            popup = widget.tk.call("ttk::combobox::PopdownWindow", str(widget))
            widget.tk.call(f"{popup}.f.l", "configure", "-background", COLORS["white"],
                           "-foreground", COLORS["ink"], "-selectbackground", COLORS["selection"],
                           "-selectforeground", COLORS["ink"])
        # Notebook/ttk containers may own ordinary Tk canvases and labels.
        # Recolor those too, while the container itself follows its ttk theme.
        for child in widget.winfo_children():
            recolor_widgets(child, previous)
        return
    replacements = {value.lower(): COLORS[key] for key, value in previous.items()}
    changes = {}
    for option in ("background", "foreground", "highlightbackground", "highlightcolor",
                   "insertbackground", "selectbackground", "selectforeground", "disabledforeground"):
        if option in widget.keys():
            current = str(widget.cget(option)).lower()
            if current in replacements:
                changes[option] = replacements[current]
    if changes:
        widget.configure(**changes)
    if isinstance(widget, (tk.Tk, tk.Toplevel)):
        apply_titlebar(widget)
    for child in widget.winfo_children():
        recolor_widgets(child, previous)
