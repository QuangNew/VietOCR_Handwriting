"""Regression coverage for the document workspace at Windows 150% font scaling."""
import tempfile
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import unittest
from PIL import Image
from desktop.application import Application
from desktop.theme import COLORS


class WorkspaceLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.tk.call('tk', 'scaling', 2.0)
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.root, 'unused.pth', preferences_path=Path(self.temp.name)/'prefs.json')
        self.root.geometry('1120x680+3000+0')
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.root.mainloop()
        self.temp.cleanup()

    def test_compact_workspace_retains_queue_and_fully_visible_actions(self):
        item = self.app.batch.add(Image.new('RGB',(800,600),'white'),'Trang giấy.jpg')
        self.app.select_item(item.id)
        self.root.update()
        self.assertGreaterEqual(self.app.queue_list.winfo_height(), 80)
        for control in (self.app.robot_button,self.app.theme_button,self.app.clear_button,
                        self.app.recognize_button,self.app.save_button,self.app.camera_button):
            self.assertTrue(control.winfo_ismapped())
            self.assertGreaterEqual(control.winfo_width(), control.winfo_reqwidth())
            self.assertGreaterEqual(control.winfo_height(), control.winfo_reqheight())
        self.assertGreater(self.app.preview.winfo_height(), 100)

    def test_dragged_split_and_editor_are_preserved_across_themes(self):
        item = self.app.batch.add(Image.new('RGB',(800,600),'white'),'Ảnh.jpg')
        item.status='done';item.text='Văn bản có dấu'
        self.app.select_item(item.id)
        self.root.update()
        split=self.app.workspace_split
        split.sash_place(0,350,0)
        self.root.update()
        position=split.sash_coord(0)
        self.app.result_text.insert('end',' đã sửa')
        self.app.result_text.mark_set('insert','1.5')
        for _ in range(4):
            self.app.toggle_theme();self.root.update()
            self.assertEqual(split.sash_coord(0), position)
            self.assertEqual(self.app.result_text.index('insert'),'1.5')
        self.assertIn('đã sửa', self.app.result_text.get('1.0','end'))

    def test_notebook_tk_children_follow_palette_without_recreation(self):
        notebook=ttk.Notebook(self.root)
        page=tk.Frame(notebook,bg=COLORS['white']);notebook.add(page,text='Cấu hình')
        text=tk.Label(page,text='Phơi sáng',bg=COLORS['white'],fg=COLORS['ink']);text.pack()
        self.app.toggle_theme();self.root.update()
        self.assertEqual(text.cget('bg'),COLORS['white'])
        self.assertEqual(text.cget('fg'),COLORS['ink'])
        self.assertTrue(text.winfo_exists())
