"""Compact, collapsible camera queue in the lower-right corner."""

import tkinter as tk
from tkinter import ttk

from .widgets import COLORS as C

LABELS = {'ready': 'Chờ nhận diện', 'processing': 'Đang nhận diện', 'done': 'Hoàn tất',
          'error': 'Có lỗi', 'cancelled': 'Đã dừng'}


class QueueProgress:
    def __init__(self, parent, on_select):
        self.frame = tk.Frame(parent, bg=C['white'], highlightthickness=1, highlightbackground=C['border'])
        self.title = tk.StringVar()
        self.expanded, self.key = True, None
        ttk.Button(self.frame, textvariable=self.title, command=self.toggle, style='Small.TButton').pack(fill='x')
        self.rows = tk.Frame(self.frame, bg=C['white'], padx=12, pady=6)
        self.rows.pack(fill='x')
        self.on_select = on_select
        self.visible = False

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.rows.pack(fill='x')
        else:
            self.rows.pack_forget()

    def update(self, items, progress):
        # Only recent rows are mounted. The queue itself has no count limit.
        count = sum(item.status == 'done' for item in items)
        key = tuple((item.id, item.status, item.version, round(progress.get(item.id, 0)*100)) for item in items)
        if self.key == key:
            return
        self.key = key
        self.title.set(f'Ảnh camera · {count}/{len(items)} hoàn tất  ▾')
        for row in self.rows.winfo_children():
            row.destroy()
        pending = [item for item in items if item.status not in ('done', 'cancelled')]
        shown = (pending[:4] if pending else items[-4:])
        for item in shown:
            row = tk.Frame(self.rows, bg=C['white'])
            row.pack(fill='x', pady=4)
            name = item.name if len(item.name) < 29 else item.name[:26]+'…'
            text = tk.Label(row, text=name, bg=C['white'], fg=C['ink'], anchor='w', width=32, cursor='hand2')
            text.pack(fill='x')
            text.bind('<Button-1>', lambda _, id=item.id: self.on_select(id))
            status = LABELS.get(item.status, item.status)
            fraction = 1 if item.status == 'done' else progress.get(item.id, 0) if item.status == 'processing' else 0
            tk.Label(row, text=status, bg=C['white'], fg=C['error'] if item.status == 'error' else C['muted'],
                     anchor='w', font=('Segoe UI', 8)).pack(fill='x')
            ttk.Progressbar(row, value=fraction*100, maximum=100, style='Green.Horizontal.TProgressbar').pack(fill='x', pady=(3, 0))
        if len(pending) > 4:
            tk.Label(self.rows, text=f'Và {len(pending)-4} ảnh đang chờ', bg=C['white'], fg=C['muted']).pack(anchor='w')
        if items and not self.visible:
            self.frame.place(relx=1, rely=1, x=-18, y=-86, anchor='se')
            self.visible = True
        elif not items:
            self.frame.place_forget()
            self.visible = False
        if self.visible:
            self.frame.lift()

