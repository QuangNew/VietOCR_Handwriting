"""Real spawned processes: model reuse, cancellation, crashes, retries and cleanup."""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from desktop.ocr_process import OCRProcessService
from desktop.ocr_service import OCRSettings, RecognitionCancelled, RecognitionError
from ocr_fixtures import ProcessEngine
from ocr_fixtures import AcceleratorEngine
from desktop.compute_devices import CPU, ComputeDevice


class OCRProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.service = OCRProcessService(log_directory=self.directory / "logs", engine_factory=ProcessEngine)
        self.image = Image.new("RGB", (12, 8), "red")

    def tearDown(self):
        self.service.close()
        self.assertTrue(self.service.closed.wait(3), "AI process did not exit")
        self.temp.cleanup()

    def settings(self, name="good"):
        path = self.directory / f"{name}.pth"
        path.write_bytes(b"test fixture")
        return OCRSettings(str(path), layout="line")

    def wait_for_file(self, path):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path.is_file():
                return
            time.sleep(0.02)
        self.fail("Child did not reach the expected operation")

    def test_reuses_loaded_model_and_reports_progress_and_rgb(self):
        settings = self.settings()
        progress = []
        first = self.service.recognize(self.image, settings, threading.Event(), lambda *value: progress.append(value))
        pid = self.service._process.pid
        self.service.load(settings)
        second = self.service.recognize(self.image, settings, threading.Event())
        self.assertEqual(self.service._process.pid, pid)
        self.assertIn("Tiếng Việt 1", first)
        self.assertIn("Tiếng Việt 2", second)
        self.assertIn("(255, 0, 0)", first)
        self.assertEqual(progress, [(1, 2), (2, 2)])

    def test_bad_model_logs_the_error_then_valid_model_can_load(self):
        with self.assertRaisesRegex(RecognitionError, "invalid checkpoint"):
            self.service.load(self.settings("bad"))
        self.assertIsNone(self.service._process)
        self.assertIn("invalid checkpoint", (self.directory / "logs/ocr-worker.log").read_text(encoding="utf-8"))
        self.assertIn("Tiếng Việt", self.service.recognize(self.image, self.settings(), threading.Event()))

    def test_ungraceful_load_exit_is_contained_and_same_model_can_retry(self):
        settings = self.settings("crash-load")
        with self.assertRaisesRegex(RecognitionError, "bất thường"):
            self.service.load(settings)
        self.assertIsNone(self.service._process)
        self.assertIn("Tiếng Việt", self.service.recognize(self.image, settings, threading.Event()))

    def test_ungraceful_inference_exit_is_contained_and_next_job_works(self):
        with self.assertRaisesRegex(RecognitionError, "bất thường"):
            self.service.recognize(self.image, self.settings("crash-inference"), threading.Event())
        self.assertIsNone(self.service._process)
        self.assertIn("Tiếng Việt", self.service.recognize(self.image, self.settings(), threading.Event()))

    def test_failed_inference_releases_poisoned_model_before_retrying_same_weights(self):
        settings = self.settings("error-inference")
        with self.assertRaisesRegex(RecognitionError, "simulated CUDA failure"):
            self.service.recognize(self.image, settings, threading.Event())
        self.assertIsNone(self.service._process)
        self.assertIn("Tiếng Việt 1", self.service.recognize(self.image, settings, threading.Event()))

    def test_failed_progress_callback_cannot_deliver_previous_image_result_to_next_job(self):
        settings = self.settings()

        def fail_progress(line, total):
            raise ValueError("progress consumer stopped")

        with self.assertRaisesRegex(ValueError, "progress consumer stopped"):
            self.service.recognize(self.image, settings, threading.Event(), fail_progress)
        self.assertIsNone(self.service._process)
        result = self.service.recognize(Image.new("RGB", (12, 8), "blue"), settings, threading.Event())
        self.assertIn("(0, 0, 255)", result)
        self.assertIn("Tiếng Việt 1", result)

    def test_process_start_failure_closes_pipe_handles_and_can_retry(self):
        parent, child = self.service._context.Pipe()
        process = Mock()
        process.start.side_effect = OSError("not enough system resources")
        with patch.object(self.service._context, "Pipe", return_value=(parent, child)), \
             patch.object(self.service._context, "Process", return_value=process):
            with self.assertRaisesRegex(RecognitionError, "khởi động tiến trình AI"):
                self.service.load(self.settings())
        self.assertTrue(parent.closed)
        self.assertTrue(child.closed)
        process.close.assert_called_once()
        self.assertIsNone(self.service._process)
        self.service.load(self.settings())

    def test_cancel_during_loading_kills_child_and_allows_retry(self):
        settings, cancel, errors = self.settings("slow"), threading.Event(), []

        def load():
            try:
                self.service.load(settings, cancel)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=load)
        thread.start()
        try:
            self.wait_for_file(Path(settings.weights).with_suffix(".started"))
        finally:
            cancel.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(errors[0], RecognitionCancelled)
        self.assertIsNone(self.service._process)
        self.service.load(self.settings())

    def test_hung_load_times_out_and_worker_is_released(self):
        self.service.load_timeout = 2
        with self.assertRaisesRegex(RecognitionError, "quá 2 giây"):
            self.service.load(self.settings("slow"))
        self.assertTrue((self.directory / "slow.started").is_file())
        self.assertIsNone(self.service._process)

    def test_hung_inference_times_out_and_next_job_can_run(self):
        settings = self.settings("slow-inference")
        self.service.recognition_timeout = 0.3
        with self.assertRaisesRegex(RecognitionError, "Nhận diện quá 0.3 giây"):
            self.service.recognize(self.image, settings, threading.Event())
        self.assertTrue(Path(settings.weights).with_suffix(".started").is_file())
        self.assertIsNone(self.service._process)
        self.assertIn("Tiếng Việt", self.service.recognize(self.image, self.settings(), threading.Event()))

    def test_cancel_during_inference_reaps_worker_and_allows_next_image(self):
        settings, cancel, errors = self.settings("slow-inference"), threading.Event(), []

        def recognize():
            try:
                self.service.recognize(self.image, settings, cancel)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=recognize)
        thread.start()
        try:
            self.wait_for_file(Path(settings.weights).with_suffix(".started"))
        finally:
            cancel.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RecognitionCancelled)
        self.assertIsNone(self.service._process)
        self.assertIn("Tiếng Việt", self.service.recognize(self.image, self.settings(), threading.Event()))

    def test_close_during_inference_is_nonblocking_and_reaps_child(self):
        settings, errors = self.settings("slow-inference"), []

        def recognize():
            try:
                self.service.recognize(self.image, settings, threading.Event())
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=recognize)
        thread.start()
        try:
            self.wait_for_file(Path(settings.weights).with_suffix(".started"))
        finally:
            before = time.monotonic()
            self.service.close()
            self.assertLess(time.monotonic()-before, 0.2)
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(self.service.closed.wait(1))
        self.assertIsInstance(errors[0], RecognitionCancelled)
        self.assertIsNone(self.service._process)

    def test_new_weights_at_same_path_replace_process_and_free_old_model(self):
        settings = self.settings()
        self.service.load(settings)
        first_pid = self.service._process.pid
        Path(settings.weights).write_bytes(b"replacement checkpoint with different length")
        self.service.load(settings)
        self.assertNotEqual(first_pid, self.service._process.pid)

    def test_missing_empty_model_or_pre_cancelled_job_starts_no_process(self):
        with self.assertRaisesRegex(RecognitionError, "Cài đặt model"):
            self.service.load(OCRSettings(str(self.directory / "missing.pth")))
        empty = self.directory / "empty.pth"
        empty.touch()
        with self.assertRaisesRegex(RecognitionError, "rỗng"):
            self.service.load(OCRSettings(str(empty)))
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(RecognitionCancelled):
            self.service.load(self.settings(), cancel)
        self.assertIsNone(self.service._process)

    def accelerator_settings(self, name):
        self.service._engine_factory = AcceleratorEngine
        self.service._discover_devices = lambda _: [
            ComputeDevice("directml:0", "iGPU", "integrated"), CPU,
            ComputeDevice("cuda:0", "dGPU", "discrete")]
        settings = self.settings(name)
        return OCRSettings(settings.weights, "auto", "line")

    def test_gpu_load_error_and_native_crash_fall_back_to_integrated(self):
        for name in ("gpu-load", "gpu-native-load"):
            with self.subTest(name=name):
                settings = self.accelerator_settings(name)
                result = self.service.recognize(self.image, settings, threading.Event())
                self.assertIn("directml:0", result)
                self.assertEqual(self.service.device_info["kind"], "integrated")

    def test_gpu_inference_error_and_native_crash_retry_same_image_on_cpu(self):
        for name in ("gpu-inference", "gpu-native-inference"):
            with self.subTest(name=name):
                settings = self.accelerator_settings(name)
                result = self.service.recognize(self.image, settings, threading.Event())
                self.assertIn("cpu", result)
                self.assertIn("(255, 0, 0)", result)
                self.assertEqual(self.service.device_info["id"], "cpu")
                pid = self.service._process.pid
                self.service.recognize(self.image, settings, threading.Event())
                self.assertEqual(self.service._process.pid, pid)

    def test_bad_image_does_not_trigger_device_fallback(self):
        settings = self.accelerator_settings("bad-image")
        with self.assertRaisesRegex(RecognitionError, "dòng chữ"):
            self.service.recognize(self.image, settings, threading.Event())
        self.assertEqual(self.service._candidate_index, 0)


if __name__ == "__main__":
    unittest.main()
