"""Run a MinerU command in a Windows job that is closed with this guard.

The batch launcher uses this small wrapper so closing its console cannot leave a
local MinerU API server or inference worker running in the background.  Windows
job objects terminate all assigned descendants when the guard process exits.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from typing import Sequence


JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operations", ctypes.c_ulonglong),
        ("write_operations", ctypes.c_ulonglong),
        ("other_operations", ctypes.c_ulonglong),
        ("read_bytes", ctypes.c_ulonglong),
        ("write_bytes", ctypes.c_ulonglong),
        ("other_bytes", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_longlong),
        ("per_job_user_time_limit", ctypes.c_longlong),
        ("limit_flags", wintypes.DWORD),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _BasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


def _create_kill_on_close_job() -> int | None:
    """Create a job object that kills its descendants when this process exits."""

    if os.name != "nt":
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    limits = _ExtendedLimitInformation()
    limits.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        kernel32.CloseHandle(job)
        return None
    return int(job)


def _close_handle(handle: int | None) -> None:
    if handle is None or os.name != "nt":
        return
    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(wintypes.HANDLE(handle))


def _terminate_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(pid, 9)
        except (ProcessLookupError, OSError):
            pass


def _command_from_args(args: Sequence[str]) -> list[str]:
    if not args:
        raise SystemExit("Usage: mineru_process_guard.py -- <python module or script> [args]")

    command = list(args)
    first = command[0].lower()
    if first in {"-m", "-c"} or first.endswith(".py"):
        command.insert(0, sys.executable)
    return command


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    try:
        separator = raw_args.index("--")
    except ValueError as exc:
        raise SystemExit(
            "Usage: mineru_process_guard.py -- <python module or script> [args]"
        ) from exc

    command = _command_from_args(raw_args[separator + 1 :])
    job_handle = _create_kill_on_close_job()
    process: subprocess.Popen[bytes] | None = None
    job_assigned = False
    try:
        process = subprocess.Popen(command)
        if job_handle is not None:
            assign = ctypes.WinDLL("kernel32", use_last_error=True).AssignProcessToJobObject
            assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            assign.restype = wintypes.BOOL
            if not assign(wintypes.HANDLE(job_handle), wintypes.HANDLE(process._handle)):
                _close_handle(job_handle)
                job_handle = None
            else:
                job_assigned = True
        return process.wait()
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            if job_assigned:
                process.terminate()
            else:
                _terminate_process_tree(process.pid)
        return 130
    finally:
        if process is not None and process.poll() is None:
            if job_assigned:
                process.kill()
            else:
                _terminate_process_tree(process.pid)
        _close_handle(job_handle)


if __name__ == "__main__":
    raise SystemExit(main())
