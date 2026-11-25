from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.hashing import parse_sums, sha256_file, verify_sums
from common.manifest import ManifestError, load, parse_lock
from common.schema import validate
from tests.conftest import rewrite_sums, set_core

CORE = "core/core-release.v0.json"
PLAT = "platforms/linux-cpu.json"
WHEEL_RT = "58061161b1a08e35d7a0fbbd3f05b58a15dcd2b7f0ae4380ca553be07b72e136"
WHEEL_OBS = "39e46599c3a3389756d22e7cc7c3f68a59fb4c0d8e1979f706dbc40cd392ca31"


def test_real_manifests_load_and_pin_design_table(real_manifests: Path) -> None:
    loaded = load(real_manifests, CORE, PLAT)
    commits = {r.name: r.commit for r in loaded.repos}
    assert commits == {
        "sensos": "f700a3d3ba4e7e9013e42d515071cd38bf8e99e4",
        "hekb-vnext": "5943a8d43ef1e63a818d40e10b52c61e334394be",
        "meaning-mapper": "f76dc2f7692fd2dbacc9efe833ba083338dbc57e",
        "meaning-space-runtime": "ee26c7c172ae321c766bf49361b003dd3914ddd8",
    }
    assert {p.name: (p.version, p.wheel_sha256) for p in loaded.packages} == {
        "nvs-runtime": ("1.0.0", WHEEL_RT), "nvs-observation": ("0.1.0.dev0", WHEEL_OBS),
    }
    assert all(r.branch == "main" for r in loaded.repos)


def test_sums_cover_every_manifest_file(real_manifests: Path) -> None:
    assert verify_sums(real_manifests) == []
    listed = set(parse_sums((real_manifests / "SHA256SUMS").read_text()))
    assert {"core/core-release.v0.json", "core/core-release.schema.json", "platforms/linux-cpu.json", "platforms/linux-cpu.lock"} <= listed


def test_edited_manifest_is_refused(manifests_copy: Path) -> None:
    path = manifests_copy / CORE
    path.write_text(path.read_text().replace("2.3.0", "2.3.1"))
    with pytest.raises(ManifestError, match="SHA256SUMS"):
        load(manifests_copy, CORE, PLAT)


def test_edited_schema_is_refused(manifests_copy: Path) -> None:
    path = manifests_copy / "core" / "core-release.schema.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ManifestError, match="core-release.schema.json"):
        load(manifests_copy, CORE, PLAT)


def test_missing_sums_file_is_refused(manifests_copy: Path) -> None:
    (manifests_copy / "SHA256SUMS").rename(manifests_copy / "SHA256SUMS.moved")
    with pytest.raises(ManifestError, match="does not exist"):
        load(manifests_copy, CORE, PLAT)


def test_schema_violation_is_refused(manifests_copy: Path) -> None:
    set_core(manifests_copy, lambda d: d["repositories"][0].update(commit="main"))
    with pytest.raises(ManifestError, match="commit"):
        load(manifests_copy, CORE, PLAT)


def test_lock_must_hold_the_manifest_wheel_hash(manifests_copy: Path) -> None:
    set_core(manifests_copy, lambda d: d["packages"][0].update(wheel_sha256="0" * 64))
    with pytest.raises(ManifestError, match="wheel sha256"):
        load(manifests_copy, CORE, PLAT)


def test_lock_version_must_match_manifest(manifests_copy: Path) -> None:
    set_core(manifests_copy, lambda d: d["packages"][1].update(version="9.9.9"))
    with pytest.raises(ManifestError, match="pins nvs-observation"):
        load(manifests_copy, CORE, PLAT)


def test_platform_lock_sha_is_checked(manifests_copy: Path) -> None:
    lock = manifests_copy / "platforms" / "linux-cpu.lock"
    lock.write_text(lock.read_text() + "\n# touched\n")
    rewrite_sums(manifests_copy)  # SHA256SUMS is consistent, the Platform Manifest's own pin is not
    with pytest.raises(ManifestError, match="lock sha256"):
        load(manifests_copy, CORE, PLAT)


def test_lock_file_matches_platform_manifest(real_manifests: Path) -> None:
    doc = json.loads((real_manifests / PLAT).read_text())
    assert sha256_file(real_manifests / "platforms" / doc["lock"]["file"]) == doc["lock"]["sha256"]


def test_parse_lock_requires_hashes() -> None:
    assert parse_lock("a==1 \\\n    --hash=sha256:" + "a" * 64 + "\n")["a"]["version"] == "1"
    with pytest.raises(ManifestError, match="no hash"):
        parse_lock("a==1\n")
    with pytest.raises(ManifestError, match="unrecognised"):
        parse_lock("git+https://example.invalid/x\n")


def test_real_lock_has_hashes_for_everything(real_manifests: Path) -> None:
    pins = parse_lock((real_manifests / "platforms" / "linux-cpu.lock").read_text())
    assert {"nvs-runtime", "nvs-observation", "pydantic", "numpy", "jsonschema", "httpx", "zstandard"} <= set(pins)
    assert pins["nvs-runtime"]["hashes"] == {WHEEL_RT}


def test_schema_validator_basics() -> None:
    schema = {"type": "object", "required": ["a"], "additionalProperties": False, "properties": {"a": {"type": "string", "pattern": "^x"}}}
    assert validate({"a": "xy"}, schema) == []
    assert validate({"a": "y"}, schema)
    assert validate({}, schema)
    assert validate({"a": "x", "b": 1}, schema)
    assert validate(True, {"type": "string"})
    assert validate({}, {"oneOf": []})  # unsupported keywords are refused, not ignored


def test_rewrite_sums_helper_is_consistent(manifests_copy: Path) -> None:
    rewrite_sums(manifests_copy)
    assert verify_sums(manifests_copy) == []
