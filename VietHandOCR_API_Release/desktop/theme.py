"""Shared palettes and the desktop's saved appearance preference."""

import sys
import tkinter as tk
from contextlib import contextmanager
from pathlib import Path
from tkinter import ttk

from .preferences import read_preferences, update_preferences

LIGHT = {
    "bg": "#F4F7F5", "white": "#FFFFFF", "ink": "#19392E",
    "muted": "#728178", "green": "#258362", "green_dark": "#176347",
    "pale": "#EAF5EF", "border": "#DFE8E2", "error": "#B64545",
    "error_bg": "#FFF1EF", "amber": "#AA742B", "on_accent": "white",
    "preview": "#F6F8F6", "selection": "#D7EDDF", "disabled_bg": "#F0F3F1",
    "disabled_fg": "#A0AAA4", "primary_disabled_bg": "#B7CDC1",
    "primary_disabled_fg": "#F9FBFA", "scroll": "#D5E1D9", "shadow": "#D5E6DB",
    "paper_border": "#C6D9CB", "paper_line": "#B6CFBF",
}

DARK = {
    "bg": "#111916", "white": "#1B2721", "ink": "#E5EEE8",
    "muted": "#A5B7AC", "green": "#7AC99B", "green_dark": "#94D8B0",
    "pale": "#203A2B", "border": "#35483C", "error": "#F39A92",
    "error_bg": "#3F2726", "amber": "#E4BE81", "on_accent": "#102419",
    "preview": "#131E18", "selection": "#315740", "disabled_bg": "#1E2D24",
    "disabled_fg": "#7E9285", "primary_disabled_bg": "#2A4033",
    "primary_disabled_fg": "#829A8C", "scroll": "#41614C", "shadow": "#15271C",
    "paper_border": "#4B6D56", "paper_line": "#86A991",
}

PALETTES = {"light": LIGHT, "dark": DARK}
# Keep this dictionary's identity: widgets and camera import the same object.
COLORS = DARK.copy()
PREFERENCES_PATH = Path(__file__).resolve().parents[1] / ".desktop-preferences.json"


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
