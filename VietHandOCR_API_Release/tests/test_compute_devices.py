import json
import tempfile
import unittest
from pathlib import Path

from desktop.compute_devices import CPU, ComputeDevice, select_devices, validate_device
from desktop.onnx_directml import digest, find_export
from desktop.windows_gpu import resolve_adapter


class DevicePolicyTests(unittest.TestCase):
    def test_gpu_is_resolved_by_identity_after_dxgi_indices_change(self):
        adapters = [{"index": 0, "luid": "discrete"}, {"index": 1, "luid": "integrated"}]
        self.assertEqual(resolve_adapter("integrated", adapters)["index"], 1)
        adapters.reverse()
        for index, adapter in enumerate(adapters):
            adapter["index"] = index
        self.assertEqual(resolve_adapter("integrated", adapters)["index"], 0)
        with self.assertRaisesRegex(RuntimeError, "không còn"):
            resolve_adapter("removed", adapters)

    def test_integrated_adapter_zero_never_outranks_discrete_gpu(self):
        integrated = ComputeDevice("directml:0", "Intel UHD", "integrated")
        discrete = ComputeDevice("cuda:0", "RTX 4050", "discrete")
        discrete_dml = ComputeDevice("directml:1", "RTX 4050", "discrete")
        self.assertEqual(select_devices([CPU, integrated, discrete_dml, discrete], "auto"),
                         [discrete, discrete_dml, integrated, CPU])

    def test_explicit_selection_does_not_silently_use_a_different_device(self):
        devices = [CPU, ComputeDevice("cuda:1", "GPU", "discrete"),
                   ComputeDevice("directml:0", "iGPU", "integrated")]
        self.assertEqual(select_devices(devices, "cuda:0"), [])
        self.assertEqual([d.id for d in select_devices(devices, "integrated")], ["directml:0"])
        self.assertEqual(select_devices([], "auto"), [CPU])
        self.assertEqual(select_devices(devices, "cpu"), [CPU])

    def test_invalid_devices_are_rejected(self):
        for value in ("cuda:-1", "directml:abc", "AUTO", "metal:0"):
            with self.assertRaises(ValueError):
                validate_device(value)

    def test_directml_export_must_match_selected_weights_and_model_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            weights = folder / "chosen.pth"
            weights.write_bytes(b"chosen checkpoint")
            encoder, decoder = folder / "encoder.onnx", folder / "decoder.onnx"
            encoder.write_bytes(b"encoder")
            decoder.write_bytes(b"decoder")
            manifest = {"source_sha256": digest(weights), "models": {
                "encoder": {"file": encoder.name, "sha256": digest(encoder)},
                "decoder": {"file": decoder.name, "sha256": digest(decoder)}}}
            (folder / "manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(find_export(weights, folder)[0], folder)
            encoder.write_bytes(b"corrupt export")
            with self.assertRaisesRegex(RuntimeError, "SHA256"):
                find_export(weights, folder)
            weights.write_bytes(b"a different checkpoint")
            with self.assertRaisesRegex(RuntimeError, "khớp"):
                find_export(weights, folder)
