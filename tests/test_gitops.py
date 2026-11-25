from __future__ import annotations

from pathlib import Path

import pytest

from common import gitops
from tests.conftest import git, make_fake_repo


def test_acquire_checks_out_the_pinned_commit(tmp_path: Path) -> None:
    shas = make_fake_repo(tmp_path / "origin")
    got = gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c1"], tmp_path / "dst" / "x")
    assert got == {"head": shas["c1"], "reused": False}
    assert gitops.head(tmp_path / "dst" / "x") == shas["c1"]


def test_main_is_named_even_when_the_default_branch_differs(tmp_path: Path) -> None:
    shas = make_fake_repo(tmp_path / "origin", default_branch="develop")
    assert git(tmp_path / "origin", "rev-parse", "--abbrev-ref", "HEAD") == "develop"
    gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c2"], tmp_path / "x")
    assert gitops.head(tmp_path / "x") == shas["c2"]  # not the default branch's HEAD (c3)


def test_commit_not_on_main_stops(tmp_path: Path) -> None:
    shas = make_fake_repo(tmp_path / "origin")
    with pytest.raises(gitops.AcquisitionError, match="not on origin/main"):
        gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c3"], tmp_path / "x")
    assert not (tmp_path / "x").exists()


def test_unknown_commit_stops(tmp_path: Path) -> None:
    make_fake_repo(tmp_path / "origin")
    with pytest.raises(gitops.AcquisitionError):
        gitops.acquire("x", str(tmp_path / "origin"), "main", "0" * 40, tmp_path / "x")
    assert not (tmp_path / "x").exists()


def test_head_mismatch_after_checkout_stops_and_nothing_is_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shas = make_fake_repo(tmp_path / "origin")
    monkeypatch.setattr(gitops, "head", lambda repo: shas["c1"])  # the checkout "landed" elsewhere
    with pytest.raises(gitops.AcquisitionError, match="HEAD after checkout"):
        gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c2"], tmp_path / "x")
    assert not (tmp_path / "x").exists()


def test_existing_checkout_is_reused_only_when_it_matches_and_is_clean(tmp_path: Path) -> None:
    shas = make_fake_repo(tmp_path / "origin")
    dest = tmp_path / "x"
    gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c1"], dest)
    assert gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c1"], dest)["reused"] is True
    with pytest.raises(gitops.AcquisitionError, match="refusing to overwrite"):
        gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c2"], dest)
    (dest / "f.txt").write_text("dirty")
    with pytest.raises(gitops.AcquisitionError, match="clean=False"):
        gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c1"], dest)
    assert (dest / "f.txt").read_text() == "dirty"  # never touched


def test_existing_non_repository_is_not_touched(tmp_path: Path) -> None:
    shas = make_fake_repo(tmp_path / "origin")
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "keep.txt").write_text("keep")
    with pytest.raises(gitops.AcquisitionError):
        gitops.acquire("x", str(tmp_path / "origin"), "main", shas["c1"], tmp_path / "x")
    assert (tmp_path / "x" / "keep.txt").read_text() == "keep"
