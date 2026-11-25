"""One place that runs subprocesses (no shell, explicit argument lists)."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


def run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    timeout: float | None = 600,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd), cwd=cwd, env=None if env is None else dict(env), input=input_text,
        capture_output=True, text=True, timeout=timeout, check=False,
    )
