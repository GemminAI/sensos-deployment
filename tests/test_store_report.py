from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from installers import store
from reports import deployment


def make_store_dir(stores: Path, name: str, catalog_sha: str, *, declaration: bool = True) -> Path:
    d = stores / name
    (d / "graph").mkdir(parents=True)
    (d / "graph" / "ic00_envelopes.jsonl").write_text("{}\n")
    if declaration:
        (d / store.DECLARATION_FILE).write_text(json.dumps({"unverifiable_catalog": {"sha256": catalog_sha}}))
    return d


def expected_decl(catalog_sha: str, accepted: tuple[str, ...] = ("1.1.0",)) -> dict[str, Any]:
    """A stand-in for hekb-vnext's formal_declaration output (the real one runs only inside the release venv)."""
    return {
        "declaration": "formal-store/1", "accepted_versions": list(accepted), "allow_waived": False,
        "unverifiable_catalog": {"version": "v", "sha256": catalog_sha, "rows": [["s", "c", "r"]]},
        "missing_parents": "reject", "created_by": store.CREATED_BY,
    }


def make_full_store(stores: Path, name: str, declaration: dict[str, Any]) -> Path:
    d = make_store_dir(stores, name, declaration["unverifiable_catalog"]["sha256"])
    (d / store.DECLARATION_FILE).write_text(json.dumps(declaration))
    return d


def use_expected(monkeypatch: pytest.MonkeyPatch, declaration: dict[str, Any]) -> None:
    monkeypatch.setattr(store, "expected_declaration", lambda *a, **k: declaration)
    monkeypatch.setattr(store, "create_store", lambda *a, **k: pytest.fail("must not create"))


def test_matching_declaration_is_reused_and_hashed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decl = expected_decl("a" * 64)
    kept = make_full_store(tmp_path, "keep", decl)
    use_expected(monkeypatch, decl)
    got = store.ensure_store(tmp_path / "v", tmp_path / "h", tmp_path, store.GateCatalog([], "a" * 64), "c")
    assert got == {"status": "reused", "path": kept, "declaration_sha256": store.declaration_sha256(decl), "declaration_match": "match"}


def test_only_accepted_versions_differs_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kept = make_full_store(tmp_path, "keep", expected_decl("a" * 64, ("1.1.0", "1.2.0")))
    before = (kept / store.DECLARATION_FILE).read_bytes()
    use_expected(monkeypatch, expected_decl("a" * 64))
    with pytest.raises(store.DeclarationMismatch) as info:
        store.ensure_store(tmp_path / "v", tmp_path / "h", tmp_path, store.GateCatalog([], "a" * 64), "c")
    assert info.value.fields == ["accepted_versions"]
    assert (kept / store.DECLARATION_FILE).read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == ["keep"]


def test_other_catalogue_is_another_generation_and_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_full_store(tmp_path, "old", expected_decl("b" * 64, ("9.9.9",)))  # would mismatch if it were compared
    monkeypatch.setattr(store, "expected_declaration", lambda *a, **k: pytest.fail("no same-generation store: nothing to compare"))
    monkeypatch.setattr(store, "create_store", lambda v, h, d, c, ver: (d.mkdir(), expected_decl("a" * 64))[1])
    got = store.ensure_store(tmp_path / "v", tmp_path / "h", tmp_path, store.GateCatalog([], "a" * 64), "c")
    assert got["status"] == "created" and got["path"] == tmp_path / ("gen-" + "a" * 64)


def test_mismatch_message_names_path_fields_expected_and_actual(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    actual = expected_decl("a" * 64, ("2.0.0",)) | {"created_by": "someone else"}
    kept = make_full_store(tmp_path, "keep", actual)
    use_expected(monkeypatch, expected_decl("a" * 64))
    with pytest.raises(store.DeclarationMismatch) as info:
        store.ensure_store(tmp_path / "v", tmp_path / "h", tmp_path, store.GateCatalog([], "a" * 64), "c")
    text = str(info.value)
    assert str(kept) in text and "accepted_versions, created_by" in text
    assert '["1.1.0"]' in text and '["2.0.0"]' in text and '"someone else"' in text and store.CREATED_BY in text
    assert info.value.diffs["accepted_versions"] == (["1.1.0"], ["2.0.0"])


def test_compare_counts_missing_and_extra_fields() -> None:
    exp = expected_decl("a" * 64)
    assert store.compare_declarations(exp, dict(exp)) == {}
    assert store.compare_declarations(exp, {k: v for k, v in exp.items() if k != "missing_parents"}) == {"missing_parents": ("reject", None)}
    assert store.compare_declarations(exp, exp | {"extra": 1}) == {"extra": (None, 1)}
    assert store.compare_declarations(exp, ["x"]) == {"<declaration>": (exp, ["x"])}
    assert store.IGNORED_DECLARATION_FIELDS == frozenset()


def test_generation_is_the_whole_catalogue_hash(tmp_path: Path) -> None:
    a = make_store_dir(tmp_path, "old", "a" * 64)
    make_store_dir(tmp_path, "other", "b" * 64)
    assert store.find_generation(tmp_path, "a" * 64) == [a]
    assert store.find_generation(tmp_path, "c" * 64) == []
    assert store.find_generation(tmp_path / "missing", "a" * 64) == []


def test_two_stores_of_one_generation_stop(tmp_path: Path) -> None:
    make_store_dir(tmp_path, "one", "a" * 64)
    make_store_dir(tmp_path, "two", "a" * 64)
    cat = store.GateCatalog(rows=[], sha256="a" * 64)
    with pytest.raises(store.StoreError, match="refusing to choose"):
        store.ensure_store(tmp_path / "v", tmp_path / "h", tmp_path, cat, "c")


def test_unfinished_store_stops(tmp_path: Path) -> None:
    make_store_dir(tmp_path, "half", "a" * 64, declaration=False)
    with pytest.raises(store.StoreError, match="unfinished"):
        store.find_generation(tmp_path, "a" * 64)


def test_same_generation_is_reused_without_creating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decl = expected_decl("a" * 64)
    kept = make_full_store(tmp_path, "keep", decl)
    use_expected(monkeypatch, decl)
    got = store.ensure_store(tmp_path / "v", tmp_path / "h", tmp_path, store.GateCatalog([], "a" * 64), "c")
    assert got["status"] == "reused" and got["path"] == kept


def test_new_generation_creates_beside_the_old_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = make_store_dir(tmp_path, "old", "a" * 64)
    before = (old / "graph" / "ic00_envelopes.jsonl").read_bytes()
    created: list[Path] = []

    def fake_create(venv_dir: Path, hekb: Path, store_dir: Path, catalog: store.GateCatalog, version: str) -> dict[str, Any]:
        store_dir.mkdir(parents=True)
        (store_dir / store.DECLARATION_FILE).write_text("{}")
        created.append(store_dir)
        return {}

    monkeypatch.setattr(store, "create_store", fake_create)
    got = store.ensure_store(tmp_path / "v", tmp_path / "h", tmp_path, store.GateCatalog([], "b" * 64), "c")
    assert got["status"] == "created" and created == [tmp_path / ("gen-" + "b" * 64)]
    assert (old / "graph" / "ic00_envelopes.jsonl").read_bytes() == before  # the old generation is untouched


def _report(result: str, stamp: str) -> dict[str, Any]:
    return deployment.build(
        release_id="r1", core_sha256="1", platform_sha256="2", lock_sha256="3", repositories=[], packages=[], checks=[],
        unverified=["x"], host={}, formal_store=None, gate=None, compute_environment="linux-cpu", result=result, stage="s",
    ) | {"created_at": stamp}


def test_report_is_never_overwritten(tmp_path: Path) -> None:
    first = deployment.save(tmp_path, _report("installed", "T1"))
    assert first == tmp_path / "reports" / "r1" / "deployment.json"
    second = deployment.save(tmp_path, _report("installed", "T2"))
    assert second == tmp_path / "reports" / "r1" / "redeploy" / "T2.json"
    failed = deployment.save(tmp_path, _report("stopped", "T3"))
    assert failed == tmp_path / "reports" / "r1" / "failed" / "T3.json"
    assert json.loads(first.read_text())["created_at"] == "T1"
    # the same second again: a new name, the earlier report is untouched (this used to raise FileExistsError)
    again = deployment.save(tmp_path, _report("stopped", "T3"))
    assert again == tmp_path / "reports" / "r1" / "failed" / "T3-001.json"
    assert failed.exists() and again != failed
    redo = deployment.save(tmp_path, _report("installed", "T2"))
    assert redo == tmp_path / "reports" / "r1" / "redeploy" / "T2-001.json"
    assert second.exists()


def test_report_fields_and_unverified(tmp_path: Path) -> None:
    rep = _report("installed", "T1")
    for key in (
        "release_id", "core_manifest_sha256", "observation_manifest_sha256", "platform_manifest_sha256", "repositories",
        "contracts", "gate", "formal_store", "adapter", "e2e", "unverified",
    ):
        assert key in rep
    assert rep["observation_manifest_sha256"] is None
    assert rep["adapter"]["observation_adapter"] is None
    assert set(deployment.ALWAYS_UNVERIFIED) <= set(rep["unverified"]) and "x" in rep["unverified"]


def test_unverified_is_built_from_the_host_not_a_fixed_claim() -> None:
    arm = {"machine": "aarch64", "os_id": "ubuntu", "os_version_id": "24.04", "python": "3.12.3"}
    x86 = {"machine": "x86_64", "os_id": "ubuntu", "os_version_id": "24.04", "python": "3.13.1"}
    ok_arm = deployment.host_unverified(arm, True)[0]
    assert "succeeded on this host (aarch64 / ubuntu 24.04 / Python 3.12.3)" in ok_arm
    assert "Other CPU architectures, other Python versions" in ok_arm
    assert "x86_64" not in ok_arm
    assert "x86_64 / ubuntu 24.04 / Python 3.13.1" in deployment.host_unverified(x86, True)[0]
    assert "did not finish installed" in deployment.host_unverified(arm, False)[0]
    assert not any("No real-machine run" in u or "fake git" in u for u in deployment.ALWAYS_UNVERIFIED)
    rep = deployment.build(
        release_id="r", core_sha256="1", platform_sha256="2", lock_sha256="3", repositories=[], packages=[], checks=[],
        unverified=[], host=arm, formal_store=None, gate=None, compute_environment="c", result="installed", stage="report",
    )
    assert ok_arm in rep["unverified"]
    assert set(deployment.ALWAYS_UNVERIFIED) <= set(rep["unverified"])
