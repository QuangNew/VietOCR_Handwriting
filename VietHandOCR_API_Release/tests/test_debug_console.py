import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from debug_console import run_once, supervise


class DebugConsoleTests(unittest.TestCase):
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
