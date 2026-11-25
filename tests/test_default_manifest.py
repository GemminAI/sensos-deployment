"""The Installer's default Core Release Manifest is v1; v0 stays readable with an explicit --core."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.hashing import parse_sums, sha256_file
from installers import install

V1 = "core/core-release.v1.json"


def test_default_is_v1_which_exists_and_matches_its_sums_line(real_manifests: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SENSOS_HOME", str(home))
    assert install.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "release_id=core-2026.11.25-1" in out and "checkout --detach eadae4e866584aba6fc33ef1ee1f8985abcedca5" in out
    assert not home.exists()
    sums = parse_sums((real_manifests / "SHA256SUMS").read_text())
    assert (real_manifests / V1).is_file() and sums[V1] == sha256_file(real_manifests / V1)


def test_v0_is_still_readable_when_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("SENSOS_HOME", str(tmp_path / "home"))
    assert install.main(["--dry-run", "--core", "core/core-release.v0.json"]) == 0
    out = capsys.readouterr().out
    assert "release_id=core-2026.11.25-0" in out and "checkout --detach ee26c7c172ae321c766bf49361b003dd3914ddd8" in out
