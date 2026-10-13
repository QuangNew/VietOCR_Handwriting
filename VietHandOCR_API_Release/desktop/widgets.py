"""Small Tk widgets used by the desktop client."""

import math
import tkinter as tk
from tkinter import ttk

from .domain import AssistantState
from .theme import COLORS


def configure_styles(root: tk.Tk) -> None:
    root.option_add("*Font", ("Segoe UI", 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TButton", font=("Segoe UI", 10), padding=(13, 9),
                    background=COLORS["white"], foreground=COLORS["ink"],
                    bordercolor=COLORS["border"], lightcolor=COLORS["white"],
                    darkcolor=COLORS["white"], focuscolor=COLORS["pale"])
    style.map("TButton", background=[("disabled", COLORS["disabled_bg"]), ("active", COLORS["pale"])],
              foreground=[("disabled", COLORS["disabled_fg"])])
    style.configure("Primary.TButton", background=COLORS["green"], foreground=COLORS["on_accent"],
                    bordercolor=COLORS["green"], lightcolor=COLORS["green"], darkcolor=COLORS["green"],
                    font=("Segoe UI", 10, "bold"))
    style.map("Primary.TButton", background=[("disabled", COLORS["primary_disabled_bg"]), ("active", COLORS["green_dark"])],
              foreground=[("disabled", COLORS["primary_disabled_fg"])])
    style.configure("Small.TButton", padding=(8, 5), font=("Segoe UI", 9))
    style.configure("TCombobox", padding=6, foreground=COLORS["ink"],
                    fieldbackground=COLORS["white"], background=COLORS["white"], bordercolor=COLORS["border"],
                    arrowcolor=COLORS["muted"], lightcolor=COLORS["white"], darkcolor=COLORS["white"],
                    selectbackground=COLORS["selection"], selectforeground=COLORS["ink"])
    style.map("TCombobox", fieldbackground=[("disabled", COLORS["disabled_bg"]), ("readonly", COLORS["white"])],
              foreground=[("disabled", COLORS["disabled_fg"]), ("readonly", COLORS["ink"])],
              selectbackground=[("readonly", COLORS["selection"])],
              selectforeground=[("readonly", COLORS["ink"])])
    for name in ("TEntry", "TSpinbox"):
        style.configure(name, fieldbackground=COLORS["white"], background=COLORS["white"],
                        foreground=COLORS["ink"], bordercolor=COLORS["border"], insertcolor=COLORS["ink"],
                        lightcolor=COLORS["white"], darkcolor=COLORS["white"], arrowcolor=COLORS["muted"],
                        selectbackground=COLORS["selection"], selectforeground=COLORS["ink"])
        style.map(name, fieldbackground=[("disabled", COLORS["disabled_bg"])],
                  foreground=[("disabled", COLORS["disabled_fg"])])
    root.option_add("*TCombobox*Listbox.background", COLORS["white"])
    root.option_add("*TCombobox*Listbox.foreground", COLORS["ink"])
    root.option_add("*TCombobox*Listbox.selectBackground", COLORS["selection"])
    root.option_add("*TCombobox*Listbox.selectForeground", COLORS["ink"])
    style.configure("Green.Horizontal.TProgressbar", troughcolor=COLORS["pale"],
                    background=COLORS["green"], borderwidth=0, thickness=5)
    style.configure("Vertical.TScrollbar", background=COLORS["scroll"], troughcolor=COLORS["white"],
                    bordercolor=COLORS["white"], lightcolor=COLORS["scroll"], darkcolor=COLORS["scroll"],
                    arrowcolor=COLORS["ink"], borderwidth=0, arrowsize=10)
    style.map("Vertical.TScrollbar", background=[("active", COLORS["green"])])


def label(parent, text: str = "", *, size: int = 10, bold: bool = False,
          color: str | None = None, bg: str | None = None, **kwargs) -> tk.Label:
    return tk.Label(parent, text=text, font=("Segoe UI", size, "bold" if bold else "normal"),
                    fg=color or COLORS["ink"], bg=bg or parent.cget("bg"), **kwargs)


def card(parent, **kwargs) -> tk.Frame:
    return tk.Frame(parent, bg=COLORS["white"], highlightbackground=COLORS["border"],
                    highlightthickness=1, **kwargs)


class ScrollableFrame(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["white"])
        self.canvas = tk.Canvas(self, bg=COLORS["white"], highlightthickness=0, width=210, height=1)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=COLORS["white"])
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))

    def bind_scroll(self, widget) -> None:
        widget.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-int(event.delta / 120), "units"))
        widget.bind("<Button-4>", lambda _: self.canvas.yview_scroll(-1, "units"))
        widget.bind("<Button-5>", lambda _: self.canvas.yview_scroll(1, "units"))


class RobotFace(tk.Canvas):
    """Vector mascot with blinking, processing, happy, and sleeping expressions."""

    def __init__(self, parent, size: int = 142, bg: str | None = None):
        super().__init__(parent, width=size, height=size, bg=bg or COLORS["pale"], highlightthickness=0)
        self.size = size
        self.state = AssistantState.AWAKE
        self.tick = 0
        self._timer = None
        self._animate()

    def set_state(self, state: AssistantState) -> None:
        self.state = state
        self._draw()

    def stop(self) -> None:
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
                  x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
                  x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
        return self.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _animate(self):
        self.tick += 1
        self._draw()
        self._timer = self.after(100, self._animate)

    def _draw(self):
        self.delete("all")
        s = self.size / 142
        self.create_oval(26*s, 126*s, 119*s, 135*s, fill=COLORS["shadow"], outline="")
        bob = 1.5 * math.sin(self.tick / 5) if self.state != AssistantState.SLEEP else 0
        self.create_line(71*s, (28+bob)*s, 71*s, (16+bob)*s, fill="#6AAA67", width=4*s)
        self.create_oval(66*s, (9+bob)*s, 76*s, (19+bob)*s, fill="#9DCE70", outline="")
        self._round_rect(41*s, 91*s, 102*s, 130*s, 15*s, fill="#85BD65", outline="")
        for x in (27, 106):
            self._round_rect(x*s, 95*s, (x+12)*s, 122*s, 6*s, fill="#71AA59", outline="")
        self._round_rect(22*s, (28+bob)*s, 121*s, (100+bob)*s, 21*s, fill="#9DCE70", outline="")
        self._round_rect(30*s, (36+bob)*s, 113*s, (91+bob)*s, 15*s, fill="#1B3B36", outline="")
        eye_color = "#D8F9C7"
        blink = self.tick % 44 in (0, 1)
        y = (59+bob)*s
        for x in (52, 90):
            if self.state in (AssistantState.DONE, AssistantState.RECEIVED):
                self.create_arc((x-8)*s, y-6*s, (x+8)*s, y+10*s, start=15, extent=150,
                                style="arc", outline=eye_color, width=3*s)
            elif self.state == AssistantState.SLEEP or blink:
                self.create_line((x-7)*s, y, (x+7)*s, y, fill=eye_color, width=3*s, capstyle="round")
            elif self.state == AssistantState.ERROR:
                self.create_line((x-6)*s, y+2*s, (x+6)*s, y-3*s, fill="#FFD49C", width=3*s)
            else:
                dx = 2 * math.sin(self.tick / 6) if self.state == AssistantState.PROCESSING else 0
                self._round_rect((x-5+dx)*s, y-8*s, (x+5+dx)*s, y+5*s, 4*s, fill=eye_color, outline="")
        if self.state == AssistantState.SLEEP:
            self.create_text(115*s, 25*s, text="z Z", fill=COLORS["muted"], font=("Segoe UI", int(11*s), "bold"))
        elif self.state == AssistantState.PROCESSING:
            for i in range(3):
                x = (62 + i*9)*s
                self.create_oval(x-2*s, 79*s, x+2*s, 83*s,
                                 fill=eye_color if self.tick % 3 == i else "#597865", outline="")
        else:
            self.create_arc(62*s, (66+bob)*s, 81*s, (81+bob)*s, start=195, extent=150,
                            style="arc", outline=eye_color, width=2*s)
        self.create_oval(66*s, 109*s, 77*s, 120*s, fill="#C3E59A", outline="")
