"""Intel OpenVINO device discovery and optional PyTorch acceleration.

MinerU's native ``get_device`` contract is intentionally left unchanged.  The
pipeline models still receive a real PyTorch device (normally CPU), while
OpenVINO is used as an inference backend for supported PyTorch subgraphs.  This
keeps preprocessing and postprocessing semantics stable and makes unsupported
operators explicit instead of pretending that an Intel device ran the whole
model.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger


OPENVINO_DEVICE_ENV = "MINERU_OPENVINO_DEVICE"
OPENVINO_CACHE_DIR_ENV = "MINERU_OPENVINO_CACHE_DIR"
OPENVINO_SKIP_MODELS_ENV = "MINERU_OPENVINO_SKIP_MODELS"
EXPERIMENTAL_NPU_ENV = "MINERU_ENABLE_EXPERIMENTAL_NPU"
OPENVINO_PROVIDER_NAME = "OpenVINOExecutionProvider"

SUPPORTED_OPENVINO_DEVICES = ("CPU", "GPU", "NPU")


@dataclass(frozen=True)
class IntelDeviceInfo:
    """A device exposed by the OpenVINO runtime."""

    name: str
    full_name: str


@dataclass(frozen=True)
class OpenVINOCompilation:
    """Result of compiling one PyTorch submodel."""

    model_name: str
    device: str
    accelerated: bool


_compilation_lock = threading.RLock()
_compilations: list[OpenVINOCompilation] = []
_openvino_dll_handles: list[Any] = []


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _skip_model_compilation(model_name: str) -> bool:
    configured = os.getenv(OPENVINO_SKIP_MODELS_ENV, "")
    skipped = {item.strip() for item in configured.split(",") if item.strip()}
    return model_name in skipped


def experimental_npu_enabled() -> bool:
    """Return whether the unverified Intel NPU pipeline is explicitly enabled."""
    return _truthy_env(EXPERIMENTAL_NPU_ENV)


def normalize_openvino_device(device: str) -> str:
    """Normalize a user-facing OpenVINO device name.

    ``GPU.0`` is preserved because OpenVINO uses qualified names when more
    than one GPU is visible.  ``GPU`` and ``NPU`` are canonical aliases.
    """

    if not isinstance(device, str):
        raise TypeError("OpenVINO device must be a string")
    normalized = device.strip().upper()
    if not normalized:
        raise ValueError("OpenVINO device must not be empty")
    if normalized.startswith("GPU."):
        suffix = normalized.removeprefix("GPU.")
        if not suffix.isdigit():
            raise ValueError(f"Invalid OpenVINO GPU device: {device}")
        return normalized
    if normalized not in SUPPORTED_OPENVINO_DEVICES:
        choices = ", ".join(SUPPORTED_OPENVINO_DEVICES)
        raise ValueError(f"Unsupported OpenVINO device {device!r}; choose {choices}")
    return normalized


def configured_openvino_device() -> str | None:
    """Return the configured Intel device, or ``None`` for native execution."""

    value = os.getenv(OPENVINO_DEVICE_ENV)
    if value is None or not value.strip():
        return None
    return normalize_openvino_device(value)


def _device_matches(requested: str, available: str) -> bool:
    if requested == available:
        return True
    if requested == "GPU" and available.startswith("GPU."):
        return True
    return False


def query_openvino_devices() -> tuple[IntelDeviceInfo, ...]:
    """Return devices currently visible to OpenVINO.

    Import is lazy so normal CPU-only MinerU installation does not acquire an
    OpenVINO dependency or change startup behavior.
    """

    try:
        import openvino as ov
    except ImportError as exc:  # pragma: no cover - exercised by environment
        raise RuntimeError(
            "OpenVINO is not installed; install the 'intel' extra to use "
            "Intel GPU/NPU acceleration."
        ) from exc

    core = ov.Core()
    devices = []
    for name in core.available_devices:
        full_name = str(core.get_property(name, "FULL_DEVICE_NAME"))
        devices.append(IntelDeviceInfo(name=str(name), full_name=full_name))
    return tuple(devices)


def ensure_openvino_runtime_libraries() -> Path | None:
    """Make the pip OpenVINO DLLs discoverable by ONNX Runtime on Windows.

    ``onnxruntime-openvino`` loads its execution-provider DLL lazily.  The
    provider wheel does not automatically add the sibling ``openvino/libs``
    directory installed by the ``openvino`` wheel to the Windows DLL search
    path, which otherwise causes a provider load error (error 126).
    The handle returned by :func:`os.add_dll_directory` must stay alive for
    the lifetime of the process, so handles are retained in module state.
    """

    if os.name != "nt":
        return None
    import openvino

    libs_dir = Path(openvino.__file__).resolve().parent / "libs"
    if not libs_dir.is_dir():
        raise RuntimeError(f"OpenVINO runtime library directory is missing: {libs_dir}")

    libs_text = str(libs_dir)
    handle = os.add_dll_directory(libs_text)
    _openvino_dll_handles.append(handle)

    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if libs_text not in path_entries:
        os.environ["PATH"] = libs_text + os.pathsep + os.environ.get("PATH", "")
    return libs_dir


def observe_openvino_provider(session: Any, *, model_name: str) -> bool:
    """Log whether an ONNX Runtime session actually activated OpenVINO."""

    target = configured_openvino_device()
    if target is None or target == "CPU":
        return True

    providers = tuple(session.get_providers())
    if OPENVINO_PROVIDER_NAME in providers:
        logger.info(
            "OpenVINO execution provider active for {} on {}",
            model_name,
            target,
        )
        return True

    raise RuntimeError(
        f"OpenVINO execution provider did not activate for {model_name} on "
        f"{target}; active providers: {', '.join(providers) or 'none'}."
    )


def validate_openvino_device(device: str) -> IntelDeviceInfo:
    """Validate a requested device against the live OpenVINO runtime."""

    requested = normalize_openvino_device(device)
    available = query_openvino_devices()
    for info in available:
        if _device_matches(requested, info.name.upper()):
            return info
    visible = ", ".join(info.name for info in available) or "none"
    raise RuntimeError(
        f"Requested OpenVINO device {requested} is unavailable; visible devices: {visible}"
    )


def openvino_cache_dir() -> Path:
    """Resolve and create the per-process model cache directory."""

    configured = os.getenv(OPENVINO_CACHE_DIR_ENV)
    path = Path(configured) if configured else Path.cwd() / ".mineru-openvino-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_compilation(result: OpenVINOCompilation) -> None:
    with _compilation_lock:
        _compilations.append(result)


def compilation_report() -> tuple[OpenVINOCompilation, ...]:
    with _compilation_lock:
        return tuple(_compilations)


def clear_compilation_report() -> None:
    with _compilation_lock:
        _compilations.clear()


def compile_torch_module(module: Any, *, model_name: str) -> Any:
    """Compile a PyTorch module for the configured OpenVINO device.

    OpenVINO's Torch backend partitions supported operations for the requested
    device. Compilation errors are surfaced to the caller.
    """

    device = configured_openvino_device()
    if device is None or device == "CPU":
        return module
    if _skip_model_compilation(model_name):
        logger.info(
            "OpenVINO compilation skipped for {} on {} by {}",
            model_name,
            device,
            OPENVINO_SKIP_MODELS_ENV,
        )
        return module

    validate_openvino_device(device)
    import openvino.torch  # noqa: F401  # registers the torch backend
    import torch

    compiled = torch.compile(
        module,
        backend="openvino",
        dynamic=False,
        options={
            "device": device,
            "model_caching": True,
            "cache_dir": str(openvino_cache_dir()),
        },
    )

    record_compilation(
        OpenVINOCompilation(model_name=model_name, device=device, accelerated=True)
    )
    logger.info("OpenVINO compiled {} for {}", model_name, device)
    return compiled


def require_configured_device() -> tuple[IntelDeviceInfo, ...]:
    """Validate the configured device and return the complete device list."""

    device = configured_openvino_device()
    if device is None:
        return ()
    validate_openvino_device(device)
    return query_openvino_devices()
