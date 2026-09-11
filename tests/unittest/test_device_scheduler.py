import asyncio
import unittest
from unittest.mock import patch

from mineru.cli.device_scheduler import (
    DeviceWorkerSpec,
    PipelineDevice,
    execute_device_jobs,
    resolve_device_specs,
)
from mineru.utils.intel_acceleration import IntelDeviceInfo


class DeviceSchedulerTests(unittest.TestCase):
    def test_auto_resolves_all_local_intel_devices(self):
        infos = (
            IntelDeviceInfo("CPU", "Intel CPU"),
            IntelDeviceInfo("GPU", "Intel Arc"),
            IntelDeviceInfo("NPU", "Intel AI Boost"),
        )
        specs = resolve_device_specs("auto", available=infos)
        self.assertEqual(
            tuple(spec.device for spec in specs),
            (PipelineDevice.CPU, PipelineDevice.GPU, PipelineDevice.NPU),
        )

    def test_missing_accelerator_is_explicit(self):
        infos = (IntelDeviceInfo("CPU", "Intel CPU"),)
        with self.assertRaisesRegex(RuntimeError, "GPU worker is unavailable"):
            resolve_device_specs("gpu", available=infos)

    def test_cpu_only_does_not_need_openvino_inventory(self):
        specs = resolve_device_specs("cpu", available=())
        self.assertEqual(specs[0].target, None)

    def test_auto_requires_openvino_inventory(self):
        with patch(
            "mineru.cli.device_scheduler.query_openvino_devices",
            side_effect=RuntimeError("OpenVINO is not installed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "OpenVINO is not installed"):
                resolve_device_specs("auto")

    def test_dynamic_queue_does_not_start_idle_workers(self):
        jobs = ["a", "b"]
        workers = (
            DeviceWorkerSpec(PipelineDevice.GPU, "GPU", "Arc"),
            DeviceWorkerSpec(PipelineDevice.NPU, "NPU", "AI Boost"),
            DeviceWorkerSpec(PipelineDevice.CPU, None, "CPU"),
        )
        seen = []

        async def run(job, worker):
            seen.append((job, worker.device))
            await asyncio.sleep(0)
            return f"{job}:{worker.device.value}"

        results, failures = asyncio.run(execute_device_jobs(jobs, workers, run))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual({device for _, device in seen}, {PipelineDevice.GPU, PipelineDevice.NPU})

    def test_one_failed_file_does_not_cancel_other_files(self):
        jobs = ["ok", "bad", "ok2"]
        workers = (DeviceWorkerSpec(PipelineDevice.CPU, None, "CPU"),)

        async def run(job, _worker):
            if job == "bad":
                raise ValueError("bad input")
            return job

        results, failures = asyncio.run(execute_device_jobs(jobs, workers, run))
        self.assertEqual(results, ["ok", "ok2"])
        self.assertEqual([job for job, _ in failures], ["bad"])

    def test_worker_filter_keeps_incompatible_job_off_npu(self):
        jobs = ["ocr", "txt"]
        workers = (
            DeviceWorkerSpec(PipelineDevice.GPU, "GPU", "Arc"),
            DeviceWorkerSpec(PipelineDevice.NPU, "NPU", "AI Boost"),
        )
        seen = []

        async def run(job, worker):
            seen.append((job, worker.device))
            return job

        results, failures = asyncio.run(
            execute_device_jobs(
                jobs,
                workers,
                run,
                can_run=lambda job, worker: not (
                    job == "txt" and worker.device is PipelineDevice.NPU
                ),
            )
        )
        self.assertEqual(failures, [])
        self.assertEqual(results, jobs)
        self.assertNotIn(("txt", PipelineDevice.NPU), seen)


if __name__ == "__main__":
    unittest.main()
