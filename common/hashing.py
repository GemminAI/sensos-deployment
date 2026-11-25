"""SHA-256 helpers and the manifests/SHA256SUMS check."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_sha256(value: Any) -> str:
    """SHA-256 of ``json.dumps(sort_keys, compact, ensure_ascii=False)``. Not RFC 8785; used for the Installer's own records."""
    return sha256_bytes(canonical_json(value))


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def parse_sums(text: str) -> dict[str, str]:
    """Parse ``sha256sum``-style lines (``<hex>  <relative path>``)."""
    sums: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if len(digest) != 64 or not name:
            raise ValueError(f"malformed SHA256SUMS line: {raw!r}")
        sums[name.strip()] = digest
    return sums


def verify_sums(manifests_dir: Path) -> list[str]:
    """Problems found when checking every file listed in ``SHA256SUMS`` (empty list = all match)."""
    sums_file = manifests_dir / "SHA256SUMS"
    if not sums_file.is_file():
        return [f"{sums_file} does not exist"]
    problems: list[str] = []
    try:
        sums = parse_sums(sums_file.read_text(encoding="utf-8"))
    except ValueError as error:
        return [str(error)]
    for name, expected in sorted(sums.items()):
        path = manifests_dir / name
        if not path.is_file():
            problems.append(f"{name}: listed but missing")
        elif sha256_file(path) != expected:
            problems.append(f"{name}: sha256 differs from SHA256SUMS")
    return problems
