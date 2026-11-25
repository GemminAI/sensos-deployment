"""Git acquisition with a check that HEAD equals the pinned commit.

``main`` is named explicitly; the manifest's commit decides what is right. After ``checkout --detach``
the HEAD MUST equal the manifest's SHA, otherwise ``AcquisitionError`` stops the installation.
Nothing here deletes anything.
"""

from __future__ import annotations

import os
from pathlib import Path

from common.proc import run


class AcquisitionError(Exception):
    """A repository could not be acquired at the pinned commit; the installation stops."""


def _git(args: list[str], cwd: Path | None = None) -> str:
    done = run(["git", *args], cwd=cwd, timeout=1800)
    if done.returncode != 0:
        raise AcquisitionError(f"git {' '.join(args)}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout.strip()


def head(repo: Path) -> str:
    return _git(["rev-parse", "HEAD"], cwd=repo)


def is_clean(repo: Path) -> bool:
    return _git(["status", "--porcelain"], cwd=repo) == ""


def acquire(name: str, url: str, branch: str, commit: str, dest: Path) -> dict[str, str | bool]:
    """Make ``dest`` a checkout of ``commit``. Returns ``{"head", "reused"}``.

    * ``dest`` exists: reused only if its HEAD is ``commit`` and the tree is clean; otherwise stop
      (an existing directory is never overwritten or removed).
    * else: clone ``branch`` (``--single-branch``, full history) into a unique ``.incoming-*`` directory
      beside ``dest``, require ``commit`` to be an ancestor of ``origin/<branch>``, check it out
      detached, require ``HEAD == commit``, then rename into place. A failed attempt leaves its
      ``.incoming-*`` directory; it is ignored by later runs.
    """
    if dest.exists():
        try:
            current = head(dest)
            clean = is_clean(dest)
        except AcquisitionError as error:
            raise AcquisitionError(f"{name}: {dest} exists but is not a usable checkout ({error})") from error
        if current != commit or not clean:
            raise AcquisitionError(
                f"{name}: {dest} exists with HEAD {current} (clean={clean}), manifest wants {commit}; "
                "refusing to overwrite or remove it"
            )
        return {"head": current, "reused": True}
    dest.parent.mkdir(parents=True, exist_ok=True)
    incoming = dest.parent / f".incoming-{name}-{os.getpid()}"
    if incoming.exists():
        raise AcquisitionError(f"{name}: {incoming} already exists")
    _git(["clone", "--no-checkout", "--single-branch", "--branch", branch, url, str(incoming)])
    ancestor = run(["git", "merge-base", "--is-ancestor", commit, f"origin/{branch}"], cwd=incoming)
    if ancestor.returncode != 0:
        raise AcquisitionError(f"{name}: commit {commit} is not on origin/{branch}")
    _git(["checkout", "--detach", commit], cwd=incoming)
    actual = head(incoming)
    if actual != commit:
        raise AcquisitionError(f"{name}: HEAD after checkout is {actual}, manifest says {commit}")
    incoming.rename(dest)
    return {"head": actual, "reused": False}
