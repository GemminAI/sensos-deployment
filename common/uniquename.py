"""Time-named directories and files that never collide: ``<UTC second>``, then ``-001``, ``-002`` ... on a clash.

Creation itself is the existence test (``mkdir(exist_ok=False)`` / ``open(path, "x")``), so two runs in the same second
cannot both get one name. Nothing existing is opened, overwritten or removed.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import IO

MAX_SUFFIX = 999


class NameExhaustedError(RuntimeError):
    """Every name ``<stamp>``, ``<stamp>-001`` ... ``<stamp>-999`` is taken."""


def utc_stamp() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def _candidates(stamp: str) -> list[str]:
    return [stamp] + [f"{stamp}-{n:03d}" for n in range(1, MAX_SUFFIX + 1)]


def make_unique_dir(parent: Path, stamp: str) -> Path:
    """Create ``parent/<stamp>`` (or the first free ``-NNN`` variant) and return it. ``parent`` is created if missing."""
    parent.mkdir(parents=True, exist_ok=True)
    for name in _candidates(stamp):
        path = parent / name
        try:
            path.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return path
    raise NameExhaustedError(f"no free name for {stamp} under {parent} (tried up to -{MAX_SUFFIX:03d})")


def create_unique_file(parent: Path, stamp: str, extension: str = ".json", mode: int = 0o644) -> tuple[Path, IO[str]]:
    """Exclusively create ``parent/<stamp><extension>`` (or the first free ``-NNN`` variant); return its path and the open handle."""
    parent.mkdir(parents=True, exist_ok=True)
    for name in _candidates(stamp):
        path = parent / f"{name}{extension}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        except FileExistsError:
            continue
        return path, os.fdopen(fd, "w", encoding="utf-8")
    raise NameExhaustedError(f"no free name for {stamp}{extension} under {parent} (tried up to -{MAX_SUFFIX:03d})")
