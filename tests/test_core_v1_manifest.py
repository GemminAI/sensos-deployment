"""Core Release Manifest v1 differs from v0 only in release_id, the MSR commit and the note."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.hashing import parse_sums, verify_sums
from common.manifest import load

V0 = "core/core-release.v0.json"
V1 = "core/core-release.v1.json"
PLAT = "platforms/linux-cpu.json"
MSR_V0 = "ee26c7c172ae321c766bf49361b003dd3914ddd8"
MSR_V1 = "eadae4e866584aba6fc33ef1ee1f8985abcedca5"


def _doc(root: Path, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / name).read_text())
    return data


def test_v1_loads_and_is_covered_by_sums(real_manifests: Path) -> None:
    loaded = load(real_manifests, V1, PLAT)
    assert loaded.core["release_id"] == "core-2026.11.25-1"
    assert verify_sums(real_manifests) == []
    assert {V0, V1} <= set(parse_sums((real_manifests / "SHA256SUMS").read_text()))


def test_v1_differs_from_v0_only_in_id_msr_commit_and_note(real_manifests: Path) -> None:
    v0, v1 = _doc(real_manifests, V0), _doc(real_manifests, V1)
    assert v0["release_id"] == "core-2026.11.25-0" and v1["release_id"] != v0["release_id"]
    assert v1["note"] != v0["note"]
    for doc in (v0, v1):
        doc.pop("release_id")
        doc.pop("note")
    msr0 = next(r for r in v0["repositories"] if r["name"] == "meaning-space-runtime")
    msr1 = next(r for r in v1["repositories"] if r["name"] == "meaning-space-runtime")
    assert (msr0["commit"], msr1["commit"]) == (MSR_V0, MSR_V1)
    msr1["commit"] = MSR_V0
    assert v1 == v0  # sensos, hekb-vnext, meaning-mapper commits and both wheel hashes are identical
