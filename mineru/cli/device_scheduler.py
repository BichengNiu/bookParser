"""Device-aware, whole-document scheduling for the local pipeline client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Iterable, Sequence, TypeVar

from loguru import logger

from mineru.utils.intel_acceleration import (
    IntelDeviceInfo,
    query_openvino_devices,
)


class PipelineDevice(str, Enum):
    CPU = "CPU"
    GPU = "GPU"
    NPU = "NPU"


DEFAULT_DEVICE_SELECTION = "auto"
SUPPORTED_DEVICE_SELECTIONS = tuple(device.value.lower() for device in PipelineDevice)


@dataclass(frozen=True)
class DeviceWorkerSpec:
    """A single long-lived pipeline worker target."""

    device: PipelineDevice
    target: str | None
    full_name: str

    @property
    def worker_id(self) -> str:
        return self.target or self.device.value


def _device_info_by_kind(
    infos: Sequence[IntelDeviceInfo],
    device: PipelineDevice,
) -> IntelDeviceInfo | None:
    for info in infos:
        name = info.name.upper()
        if name == device.value or (
            device is PipelineDevice.GPU and name.startswith("GPU.")
        ):
            return info
    return None


def resolve_device_specs(
    selection: str | Iterable[str] = DEFAULT_DEVICE_SELECTION,
    *,
    available: Sequence[IntelDeviceInfo] | None = None,
) -> tuple[DeviceWorkerSpec, ...]:
    """Resolve and validate the requested CPU/GPU/NPU worker set.

    ``auto`` means every device visible to the current runtime.  If the Intel
    extra is not installed, it deliberately resolves to a native CPU worker
    so existing CPU-only pipeline installations keep working.  Missing
    GPU/NPU devices are a startup error when explicitly requested.
    """

    is_auto = False
    if isinstance(selection, str):
        raw = selection.strip().lower()
        is_auto = raw == DEFAULT_DEVICE_SELECTION
        if is_auto:
            requested = []
        else:
            requested = []
            for item in raw.split(","):
                item = item.strip()
                if not item:
                    continue
                try:
                    requested.append(PipelineDevice(item.upper()))
                except ValueError as exc:
                    choices = ", ".join(SUPPORTED_DEVICE_SELECTIONS)
                    raise ValueError(
                        f"Unsupported pipeline device {item!r}; choose {choices} or auto"
                    ) from exc
    else:
        requested = []
        for item in selection:
            try:
                requested.append(
                    item if isinstance(item, PipelineDevice) else PipelineDevice(str(item).upper())
                )
            except ValueError as exc:
                raise ValueError(f"Unsupported pipeline device: {item!r}") from exc

    if not requested and not is_auto:
        raise ValueError("At least one pipeline device must be selected")
    if len(set(requested)) != len(requested):
        raise ValueError("Pipeline devices must be unique")

    requires_openvino = is_auto or any(
        device is not PipelineDevice.CPU for device in requested
    )
    if available is not None:
        infos = tuple(available)
    elif requires_openvino:
        try:
            infos = query_openvino_devices()
        except RuntimeError as exc:
            if not is_auto or "not installed" not in str(exc).lower():
                raise
            logger.warning(
                "OpenVINO is unavailable; --devices auto will use native CPU only."
            )
            infos = ()
    else:
        infos = ()

    if is_auto:
        requested = [PipelineDevice.CPU]
        for device in (PipelineDevice.GPU, PipelineDevice.NPU):
            if _device_info_by_kind(infos, device) is not None:
                requested.append(device)
    specs: list[DeviceWorkerSpec] = []
    for device in requested:
        if device is PipelineDevice.CPU:
            info = _device_info_by_kind(infos, device)
            full_name = info.full_name if info is not None else "native CPU"
            specs.append(DeviceWorkerSpec(device, None, full_name))
            continue

        info = _device_info_by_kind(infos, device)
        if info is None:
            visible = ", ".join(item.name for item in infos) or "none"
            raise RuntimeError(
                f"Requested {device.value} worker is unavailable; visible "
                f"OpenVINO devices: {visible}"
            )
        target = info.name if info.name.upper().startswith("GPU.") else device.value
        specs.append(DeviceWorkerSpec(device, target, info.full_name))

    return tuple(specs)


T = TypeVar("T")
R = TypeVar("R")


async def execute_device_jobs(
    jobs: Sequence[T],
    workers: Sequence[DeviceWorkerSpec],
    runner: Callable[[T, DeviceWorkerSpec], Awaitable[R]],
    can_run: Callable[[T, DeviceWorkerSpec], bool] | None = None,
) -> tuple[list[R], list[tuple[T, Exception]]]:
    """Run whole-file jobs through a dynamic queue of device workers.

    At most one worker is started per selected device and no idle worker is
    created when fewer files than devices are submitted.  Results retain input
    order; failures are returned with their originating job for clear CLI
    reporting.
    """

    if not workers:
        raise ValueError("At least one device worker is required")
    if not jobs:
        return [], []

    pending = list(enumerate(jobs))
    if can_run is not None:
        incompatible = [
            job
            for _, job in pending
            if not any(can_run(job, worker) for worker in workers)
        ]
        if incompatible:
            raise ValueError(
                "No selected device can process one or more scheduled jobs"
            )

    pending_condition = asyncio.Condition()
    worker_count = min(len(workers), len(jobs))

    results: list[R | None] = [None] * len(jobs)
    failures: list[tuple[T, Exception]] = []
    failure_lock = asyncio.Lock()

    async def worker_loop(spec: DeviceWorkerSpec) -> None:
        while True:
            async with pending_condition:
                while True:
                    candidate_pos = next(
                        (
                            position
                            for position, (_, job) in enumerate(pending)
                            if can_run is None or can_run(job, spec)
                        ),
                        None,
                    )
                    if candidate_pos is not None:
                        index, job = pending.pop(candidate_pos)
                        break
                    if not pending:
                        return
                    await pending_condition.wait()
            try:
                try:
                    results[index] = await runner(job, spec)
                except Exception as exc:  # isolate one file from the batch
                    async with failure_lock:
                        failures.append((job, exc))
                    logger.warning(
                        "Pipeline job failed on {}: {}",
                        spec.worker_id,
                        exc,
                    )
            finally:
                async with pending_condition:
                    pending_condition.notify_all()

    tasks = [
        asyncio.create_task(worker_loop(spec), name=f"mineru-device-{spec.worker_id}")
        for spec in workers[:worker_count]
    ]
    await asyncio.gather(*tasks)
    return [result for result in results if result is not None], failures
