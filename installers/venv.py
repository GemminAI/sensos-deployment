"""The dedicated virtual environment: created with ``venv``, filled from the hash-pinned lock only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from common.manifest import normalize
from common.proc import run


class VenvError(Exception):
    """The environment could not be built; the installation stops."""


_TOOLING = {"pip", "setuptools", "wheel"}

_DISTS = (
    "import importlib.metadata as m, json;"
    "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))"
)
_PURELIB = "import sysconfig;print(sysconfig.get_path('purelib'))"


def python_of(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _output(done: subprocess.CompletedProcess[str]) -> str:
    """Both streams of a finished process, labelled; which stream a tool uses for its explanation varies."""
    parts = [f"{label}: {text.strip()}" for label, text in (("stdout", done.stdout), ("stderr", done.stderr)) if text.strip()]
    return " | ".join(parts) or "no output"


def create(venv_dir: Path, base_python: str = sys.executable) -> bool:
    """Create the venv. Returns ``True`` if it was created, ``False`` if a usable one was already there (reused).

    An existing venv is reused only if its python is there **and** ``-m pip --version`` works in it. A python without
    a working pip (an interrupted creation) stops the installation; it is neither reused nor removed.
    """
    if python_of(venv_dir).exists():
        probe = run([str(python_of(venv_dir)), "-m", "pip", "--version"])
        if probe.returncode == 0:
            return False
        raise VenvError(
            f"{venv_dir} has a python but pip is not usable in it, so it is an incomplete virtual environment "
            f"(a failed earlier creation?); it is neither reused nor removed. Remove it yourself or use another SENSOS_HOME. "
            f"pip --version: {_output(probe)}"
        )
    if venv_dir.exists() and any(venv_dir.iterdir()):
        raise VenvError(f"{venv_dir} exists and is not a virtual environment; refusing to touch it")
    done = run([base_python, "-m", "venv", str(venv_dir)])
    if done.returncode != 0:
        raise VenvError(f"venv creation failed (exit {done.returncode}): {_output(done)}")
    return True


def install_lock(venv_dir: Path, lock_path: Path) -> None:
    """``pip install --require-hashes`` of the lock; binary wheels only; no dependency resolution."""
    done = run(
        [
            str(python_of(venv_dir)), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
            "--require-hashes", "--only-binary=:all:", "--no-deps", "-r", str(lock_path),
        ],
        timeout=3600,
    )
    if done.returncode != 0:
        raise VenvError(f"pip install from the lock failed: {(done.stderr or done.stdout).strip()[-2000:]}")


def purelib(venv_dir: Path) -> Path:
    done = run([str(python_of(venv_dir)), "-I", "-c", _PURELIB])
    if done.returncode != 0:
        raise VenvError(done.stderr.strip())
    return Path(done.stdout.strip())


def write_pth(venv_dir: Path, paths: list[Path]) -> Path:
    """``sensos-core.pth``: the ``src`` directories of the checked-out Core repositories (not pip-installable under --require-hashes)."""
    target = purelib(venv_dir) / "sensos-core.pth"
    target.write_text("".join(f"{p}\n" for p in paths), encoding="utf-8")
    return target


def installed(venv_dir: Path) -> dict[str, str]:
    """``{normalized name: version}`` of the distributions in the venv, without pip/setuptools/wheel."""
    done = run([str(python_of(venv_dir)), "-I", "-c", _DISTS])
    if done.returncode != 0:
        raise VenvError(done.stderr.strip())
    raw: dict[str, str] = json.loads(done.stdout)
    return {normalize(k): v for k, v in raw.items() if normalize(k) not in _TOOLING}


def package_dir(venv_dir: Path, module: str) -> Path:
    """Directory of ``module`` in the venv, found without importing it."""
    code = (
        "import importlib.util as u,sys;"
        f"s=u.find_spec({module!r});"
        "print(list(s.submodule_search_locations)[0] if s and s.submodule_search_locations else '')"
    )
    done = run([str(python_of(venv_dir)), "-I", "-c", code])
    out = done.stdout.strip()
    if done.returncode != 0 or not out:
        raise VenvError(f"module {module} is not importable in {venv_dir}")
    return Path(out)
