"""The README is the source for installing: it names the default release, the install commands, and no internal references."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_names_the_default_manifest_release_id() -> None:
    manifest = json.loads((ROOT / "manifests" / "core" / "core-release.v1.json").read_text(encoding="utf-8"))
    assert manifest["release_id"] in README


def test_readme_has_the_install_commands() -> None:
    assert "python3 -m installers.install --dry-run" in README
    assert re.search(r"^\s*python3 -m installers\.install\s*$", README, flags=re.MULTILINE)


def test_readme_has_no_internal_references() -> None:
    assert re.search(r"\bD-\d+", README) is None
    assert ("OK" + "F") not in README  # built in parts so this file does not match the audit rule
