import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from debug_console import run_once, supervise


class DebugConsoleTests(unittest.TestCase):
    def test_old_crash_trace_is_not_reprinted_for_an_unrelated_new_exit(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(output):
            old = Path(directory) / 'ocr-crash.log'
            old.write_text('UNRELATED OLD CRASH', encoding='utf-8')
            os.utime(old, (1, 1))
            self.assertEqual(run_once([sys.executable, '-c', 'raise SystemExit(23)'], Path(directory)), 23)
        self.assertNotIn('UNRELATED OLD CRASH', output.getvalue())
    def test_gui_is_in_its_own_windows_console_group_without_terminal_stdin(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            with patch('debug_console.subprocess.Popen', wraps=subprocess.Popen) as start:
                self.assertEqual(run_once([sys.executable, '-c', 'print("ok")'], Path(directory)), 0)
        self.assertEqual(start.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(start.call_args.kwargs['creationflags'], subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
    def test_ide_activation_command_does_not_reopen_app(self):
        answers = iter([r"C:\project\.venv\Scripts\activate", "unexpected input", "q"])
        with patch("debug_console.run_once", return_value=0) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(supervise([], lambda _: next(answers)), 0)
        self.assertEqual(run.call_count, 1)

    def test_child_crash_is_logged_and_supervisor_survives(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(output):
            code = run_once([sys.executable, "-u", "-c", "import os; print('Tiếng Việt', flush=True); os._exit(23)"], Path(directory))
            files = list(Path(directory).glob("console-*.log"))
            self.assertEqual(len(files), 1)
            self.assertIn("Tiếng Việt", files[0].read_text(encoding="utf-8"))
        self.assertEqual(code, 23)
        self.assertIn("0x00000017", output.getvalue())
        self.assertIn("Console remains open", output.getvalue())

    def test_reopen_after_crash_then_explicit_quit(self):
        answers = iter(["", "q"])
        with patch("debug_console.run_once", return_value=23) as run:
            self.assertEqual(supervise(["--camera", "1"], lambda _: next(answers)), 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0][-2:], ["--camera", "1"])
