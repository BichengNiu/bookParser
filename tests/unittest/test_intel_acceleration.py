import os
import unittest
from unittest.mock import patch

from mineru.utils.intel_acceleration import (
    IntelDeviceInfo,
    OpenVINOCompilation,
    clear_compilation_report,
    compilation_report,
    normalize_openvino_device,
    observe_openvino_provider,
    validate_openvino_device,
)
from mineru.model.table.rec.onnxruntime_provider import (
    build_table_onnx_providers,
    create_table_onnx_session,
)


class IntelAccelerationContractTests(unittest.TestCase):
    def tearDown(self):
        clear_compilation_report()

    def test_normalize_openvino_device(self):
        self.assertEqual(normalize_openvino_device(" gpu.0 "), "GPU.0")
        self.assertEqual(normalize_openvino_device("npu"), "NPU")
        with self.assertRaises(ValueError):
            normalize_openvino_device("cuda")

    def test_validate_uses_live_visible_devices(self):
        infos = (
            IntelDeviceInfo("CPU", "Intel CPU"),
            IntelDeviceInfo("GPU", "Intel Arc"),
            IntelDeviceInfo("NPU", "Intel AI Boost"),
        )
        with patch(
            "mineru.utils.intel_acceleration.query_openvino_devices",
            return_value=infos,
        ):
            self.assertEqual(validate_openvino_device("GPU").full_name, "Intel Arc")
            with self.assertRaises(RuntimeError):
                validate_openvino_device("GPU.1")

    def test_compilation_report_is_immutable_snapshot(self):
        clear_compilation_report()
        from mineru.utils.intel_acceleration import record_compilation

        record_compilation(
            OpenVINOCompilation("layout", "GPU", accelerated=True)
        )
        report = compilation_report()
        self.assertEqual(report[0].model_name, "layout")
        self.assertIsInstance(report, tuple)

    def test_cpu_without_openvino_does_not_require_runtime(self):
        with patch.dict(os.environ, {}, clear=True):
            from mineru.utils.intel_acceleration import compile_torch_module

            marker = object()
            self.assertIs(compile_torch_module(marker, model_name="test"), marker)

    def test_table_provider_uses_npu_fp16(self):
        with patch(
            "mineru.model.table.rec.onnxruntime_provider.get_device",
            return_value="cpu",
        ), patch(
            "mineru.model.table.rec.onnxruntime_provider.configured_openvino_device",
            return_value="NPU",
        ), patch(
            "mineru.model.table.rec.onnxruntime_provider.ensure_openvino_runtime_libraries",
        ):
            providers = build_table_onnx_providers(
                ["OpenVINOExecutionProvider", "CPUExecutionProvider"]
            )
        self.assertEqual(providers[0][0], "OpenVINOExecutionProvider")
        self.assertEqual(providers[0][1]["device_type"], "NPU")
        self.assertEqual(providers[0][1]["precision"], "FP16")

    def test_table_session_falls_back_to_cpu_when_openvino_compile_fails(self):
        calls = []

        def fake_session(model_path, *, sess_options=None, providers=None):
            calls.append((model_path, providers))
            if providers[0][0] == "OpenVINOExecutionProvider":
                raise RuntimeError("dynamic shape is not supported")
            return "cpu-session"

        with patch(
            "onnxruntime.InferenceSession",
            side_effect=fake_session,
        ):
            session = create_table_onnx_session(
                "table.onnx",
                providers=[
                    ("OpenVINOExecutionProvider", {"device_type": "GPU"}),
                    ("CPUExecutionProvider", {}),
                ],
                model_name="SLANetPlus",
            )

        self.assertEqual(session, "cpu-session")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1][1][0][0], "CPUExecutionProvider")

    def test_inactive_provider_is_observable(self):
        class Session:
            @staticmethod
            def get_providers():
                return ["CPUExecutionProvider"]

        with patch.dict(os.environ, {"MINERU_OPENVINO_DEVICE": "GPU"}):
            self.assertFalse(observe_openvino_provider(Session(), model_name="table"))


if __name__ == "__main__":
    unittest.main()
