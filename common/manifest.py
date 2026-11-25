"""Loading and cross-checking the Core Release Manifest, the Platform Manifest and the lock."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.hashing import sha256_file, verify_sums
from common.schema import validate


class ManifestError(Exception):
    """A manifest, schema, checksum or the lock is not what the installation requires; it stops."""


@dataclass(frozen=True)
class Repo:
    name: str
    url: str
    branch: str
    commit: str
    expected_version: str | None


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    wheel_sha256: str


@dataclass(frozen=True)
class Loaded:
    manifests_dir: Path
    core_path: Path
    platform_path: Path
    core: dict[str, Any]
    platform: dict[str, Any]
    repos: tuple[Repo, ...]
    packages: tuple[Package, ...]
    lock_path: Path
    core_sha256: str
    platform_sha256: str
    lock_sha256: str


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(text: str) -> dict[str, dict[str, Any]]:
    """``{name: {"version", "hashes": set}}`` from a ``pip-compile --generate-hashes`` style file."""
    pins: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip().rstrip("\\").strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash=sha256:"):
            if current is None:
                raise ManifestError("lock: a hash line before any requirement")
            pins[current]["hashes"].add(line.removeprefix("--hash=sha256:").strip())
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", line)
        if not match:
            raise ManifestError(f"lock: unrecognised line {raw!r}")
        current = normalize(match.group(1))
        pins.setdefault(current, {"version": match.group(2), "hashes": set()})
        if pins[current]["version"] != match.group(2):
            raise ManifestError(f"lock: {current} is pinned to two versions")
    for name, pin in pins.items():
        if not pin["hashes"]:
            raise ManifestError(f"lock: {name} has no hash")
    return pins


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ManifestError(f"{path}: cannot be read as JSON ({error})") from error
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: not a JSON object")
    return data


def load(manifests_dir: Path, core_file: str, platform_file: str) -> Loaded:
    """Verify SHA256SUMS, validate both manifests against their schemas, and close the references
    between them (every Core package is pinned by the lock to a set of hashes containing its wheel sha256)."""
    problems = verify_sums(manifests_dir)
    if problems:
        raise ManifestError("SHA256SUMS: " + "; ".join(problems))
    core_path = manifests_dir / core_file
    platform_path = manifests_dir / platform_file
    core = _load_json(core_path)
    platform_doc = _load_json(platform_path)
    for doc, path, schema_name in (
        (core, core_path, core_path.with_name("core-release.schema.json")),
        (platform_doc, platform_path, platform_path.with_name("linux-cpu.schema.json")),
    ):
        errors = validate(doc, _load_json(schema_name))
        if errors:
            raise ManifestError(f"{path.name}: " + "; ".join(errors))
    lock_info = platform_doc["lock"]
    lock_path = platform_path.parent / lock_info["file"]
    if not lock_path.is_file():
        raise ManifestError(f"lock file {lock_path} does not exist (not generated?)")
    lock_sha = sha256_file(lock_path)
    if lock_sha != lock_info["sha256"]:
        raise ManifestError(f"lock sha256 {lock_sha} differs from the Platform Manifest's {lock_info['sha256']}")
    pins = parse_lock(lock_path.read_text(encoding="utf-8"))
    packages = tuple(Package(**p) for p in core["packages"])
    for pkg in packages:
        pin = pins.get(normalize(pkg.name))
        if pin is None:
            raise ManifestError(f"lock does not contain {pkg.name}")
        if pin["version"] != pkg.version:
            raise ManifestError(f"lock pins {pkg.name}=={pin['version']}, Core manifest says {pkg.version}")
        if pkg.wheel_sha256 not in pin["hashes"]:
            raise ManifestError(f"lock has no hash equal to the Core manifest's wheel sha256 of {pkg.name}")
    repos = tuple(
        Repo(r["name"], r["url"], r["branch"], r["commit"], r.get("expected_version")) for r in core["repositories"]
    )
    if len({r.name for r in repos}) != len(repos):
        raise ManifestError("duplicate repository name in the Core manifest")
    return Loaded(
        manifests_dir=manifests_dir, core_path=core_path, platform_path=platform_path, core=core,
        platform=platform_doc, repos=repos, packages=packages, lock_path=lock_path,
        core_sha256=sha256_file(core_path), platform_sha256=sha256_file(platform_path), lock_sha256=lock_sha,
    )
