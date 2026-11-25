from __future__ import annotations

import stat
from pathlib import Path

import pytest

from installers import venv


def _script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_creation_failure_carries_stdout_and_stderr(tmp_path: Path) -> None:
    base = _script(tmp_path / "base-python", "echo 'ensurepip is not available' ; echo 'apt install python3.12-venv' >&2; exit 1")
    with pytest.raises(venv.VenvError) as error:
        venv.create(tmp_path / "venv", str(base))
    text = str(error.value)
    assert "stdout: ensurepip is not available" in text and "stderr: apt install python3.12-venv" in text and "exit 1" in text


def test_creation_failure_with_no_output_says_so(tmp_path: Path) -> None:
    base = _script(tmp_path / "base-python", "exit 3")
    with pytest.raises(venv.VenvError, match="no output"):
        venv.create(tmp_path / "venv", str(base))


def test_python_without_pip_stops_and_is_not_removed(tmp_path: Path) -> None:
    venv_dir = tmp_path / "venv"
    python = _script(venv.python_of(venv_dir), "echo 'No module named pip' >&2; exit 1")
    base = _script(tmp_path / "base-python", "echo SHOULD-NOT-RUN >&2; exit 9")
    with pytest.raises(venv.VenvError, match="incomplete virtual environment") as error:
        venv.create(venv_dir, str(base))
    assert str(venv_dir) in str(error.value) and "No module named pip" in str(error.value)
    assert python.exists() and venv_dir.is_dir()  # neither reused nor deleted; the base python was not called


def test_venv_with_working_pip_is_reused(tmp_path: Path) -> None:
    venv_dir = tmp_path / "venv"
    _script(venv.python_of(venv_dir), "exit 0")
    base = _script(tmp_path / "base-python", "exit 9")  # would fail if creation were attempted
    assert venv.create(venv_dir, str(base)) is False
