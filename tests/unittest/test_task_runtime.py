from pathlib import Path

import pytest

from mineru.cli.task_runtime import (
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_PENDING,
    build_upload_destination,
    env_flag_enabled,
    get_int_env,
    is_task_terminal,
)


def test_task_terminal_policy_is_shared() -> None:
    assert is_task_terminal(TASK_COMPLETED)
    assert is_task_terminal(TASK_FAILED)
    assert not is_task_terminal(TASK_PENDING)


def test_environment_policies_use_defaults_and_minimums(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MINERU_TEST_FLAG", raising=False)
    assert env_flag_enabled("MINERU_TEST_FLAG", default=True)

    monkeypatch.setenv("MINERU_TEST_INT", "not-an-int")
    assert get_int_env("MINERU_TEST_INT", default=7) == 7
    monkeypatch.setenv("MINERU_TEST_INT", "0")
    assert get_int_env("MINERU_TEST_INT", default=7, minimum=1) == 7


def test_upload_destination_collision_policy_is_shared(tmp_path: Path) -> None:
    original = Path(tmp_path) / "document.pdf"
    original.write_bytes(b"existing")
    second = build_upload_destination(str(tmp_path), original.name)
    assert second == Path(tmp_path) / "document__upload_2.pdf"
