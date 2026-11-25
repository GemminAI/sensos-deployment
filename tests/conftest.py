from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from common.hashing import sha256_file

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def make_fake_repo(path: Path, default_branch: str = "main") -> dict[str, str]:
    """A local git repository: ``main`` has commits c1, c2; a side branch has c3 (not on main). No network."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("1")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "c1")
    c1 = git(path, "rev-parse", "HEAD")
    (path / "f.txt").write_text("2")
    git(path, "commit", "-q", "-am", "c2")
    c2 = git(path, "rev-parse", "HEAD")
    git(path, "checkout", "-q", "-b", "side")
    (path / "f.txt").write_text("3")
    git(path, "commit", "-q", "-am", "c3")
    c3 = git(path, "rev-parse", "HEAD")
    if default_branch != "main":
        git(path, "checkout", "-q", "-b", default_branch, "side")  # the "public default branch" differs from main
    return {"c1": c1, "c2": c2, "c3": c3}


@pytest.fixture
def real_manifests() -> Path:
    return REPO_ROOT / "manifests"


@pytest.fixture
def manifests_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "manifests"
    shutil.copytree(REPO_ROOT / "manifests", dest)
    return dest


def rewrite_sums(manifests: Path) -> None:
    lines = []
    for line in (manifests / "SHA256SUMS").read_text().splitlines():
        name = line.split("  ", 1)[1]
        lines.append(f"{sha256_file(manifests / name)}  {name}")
    (manifests / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def set_core(manifests: Path, mutate: Callable[[dict[str, Any]], object]) -> None:
    path = manifests / "core" / "core-release.v0.json"
    doc = json.loads(path.read_text())
    mutate(doc)
    path.write_text(json.dumps(doc, indent=1))
    rewrite_sums(manifests)
