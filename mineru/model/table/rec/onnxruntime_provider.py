# Copyright (c) Opendatalab. All rights reserved.
from pathlib import Path
from typing import Any, List, Sequence, Tuple

from mineru.utils.config_reader import get_device
from mineru.utils.intel_acceleration import (
    configured_openvino_device,
    configured_openvino_table_device,
    ensure_openvino_runtime_libraries,
    openvino_cache_dir,
)


CPU_PROVIDER = "CPUExecutionProvider"
CUDA_PROVIDER = "CUDAExecutionProvider"
CPU_PROVIDER_OPTS = {
    "arena_extend_strategy": "kSameAsRequested",
}
CUDA_PROVIDER_OPTS = {
    "cudnn_conv_algo_search": "HEURISTIC",
}
OPENVINO_PROVIDER = "OpenVINOExecutionProvider"


def _normalize_device(device: object) -> str:
    """归一化 MinerU 设备名。"""
    if not isinstance(device, str):
        raise TypeError("Configured device must be a string")
    normalized = device.strip().lower()
    if not normalized:
        raise ValueError("Configured device must not be empty")
    return normalized


def _build_cpu_provider() -> Tuple[str, dict[str, Any]]:
    """构建 CPU provider 配置，避免复用可变的模块级字典。"""
    return (CPU_PROVIDER, dict(CPU_PROVIDER_OPTS))


def _build_cuda_provider() -> Tuple[str, dict[str, Any]]:
    return (CUDA_PROVIDER, dict(CUDA_PROVIDER_OPTS))


def _build_openvino_provider(device: str) -> Tuple[str, dict[str, Any]]:
    # Intel NPU currently accepts FP16/ACCURACY only; GPU/CPU use FP32 here
    # to preserve the pipeline's numerical behavior.
    precision = "FP16" if device.startswith("NPU") else "FP32"
    return (
        OPENVINO_PROVIDER,
        {
            "device_type": device,
            "precision": precision,
            "num_streams": "1",
            "cache_dir": str(openvino_cache_dir()),
        },
    )


def build_table_onnx_providers(
    available_providers: Sequence[str],
) -> List[Tuple[str, dict[str, Any]]]:
    """根据 MinerU 当前设备为表格 ONNX 模型选择 onnxruntime providers。"""
    cpu_provider = _build_cpu_provider()
    cuda_provider = _build_cuda_provider()
    device = _normalize_device(get_device())
    openvino_device = configured_openvino_device()
    table_device = configured_openvino_table_device()

    if table_device == "CPU":
        return [cpu_provider]

    if openvino_device is not None and openvino_device != "CPU":
        ensure_openvino_runtime_libraries()
        if OPENVINO_PROVIDER not in available_providers:
            raise RuntimeError(
                f"OpenVINOExecutionProvider is unavailable for {openvino_device}"
            )
        return [_build_openvino_provider(openvino_device)]

    # 只有 MinerU 设备明确为 CUDA 时才尝试 CUDAExecutionProvider，保持默认 CPU 行为。
    if device != "cuda":
        return [cpu_provider]

    if CUDA_PROVIDER not in available_providers:
        raise RuntimeError("CUDAExecutionProvider is unavailable for CUDA parsing")
    return [cuda_provider]


def create_table_onnx_session(
    model_path: str | Path,
    *,
    sess_options: Any = None,
    providers: Sequence[Tuple[str, dict[str, Any]]] | None = None,
):
    """Create a table ONNX session using the selected provider only."""

    import onnxruntime

    selected = list(
        providers
        or build_table_onnx_providers(onnxruntime.get_available_providers())
    )
    return onnxruntime.InferenceSession(
        str(model_path),
        sess_options=sess_options,
        providers=selected,
    )
