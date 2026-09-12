# Copyright (c) Opendatalab. All rights reserved.
"""Shared task-runtime policies used by the API and router adapters."""

import os
from datetime import datetime, timezone
from pathlib import Path


TASK_PENDING = "pending"
TASK_PROCESSING = "processing"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
TASK_TERMINAL_STATES = {TASK_COMPLETED, TASK_FAILED}
DEFAULT_TASK_RETENTION_SECONDS = 24 * 60 * 60
DEFAULT_TASK_CLEANUP_INTERVAL_SECONDS = 5 * 60


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_flag_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def get_int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


def get_task_retention_seconds() -> int:
    return get_int_env(
        "MINERU_API_TASK_RETENTION_SECONDS",
        DEFAULT_TASK_RETENTION_SECONDS,
        minimum=0,
    )


def get_task_cleanup_interval_seconds() -> int:
    return get_int_env(
        "MINERU_API_TASK_CLEANUP_INTERVAL_SECONDS",
        DEFAULT_TASK_CLEANUP_INTERVAL_SECONDS,
        minimum=1,
    )


def is_task_terminal(status: str) -> bool:
    return status in TASK_TERMINAL_STATES


def build_upload_destination(upload_dir: str, filename: str) -> Path:
    destination = Path(upload_dir) / filename
    if not destination.exists():
        return destination

    base_name = Path(filename).stem
    suffix = Path(filename).suffix
    index = 2
    while True:
        candidate = Path(upload_dir) / f"{base_name}__upload_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
