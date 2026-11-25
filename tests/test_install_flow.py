from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from common import gitops, uniquename
from common.manifest import Loaded, Repo, load
from installers import acceptance, install, store, venv
from tests.conftest import make_fake_repo, rewrite_sums, set_core

UBUNTU = {"system": "Linux", "os_id": "ubuntu", "os_version_id": "24.04", "machine": "x86_64", "python": "3.12.3"}


@pytest.fixture(autouse=True)
def ubuntu_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acceptance, "host_facts", lambda: dict(UBUNTU))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(acceptance, "ensurepip_available", lambda: True)


def build_world(tmp_path: Path, *, pin: str = "c2") -> tuple[Loaded, dict[str, Path], Path]:
    """Four fake origins; a manifests copy whose commits point into them (``pin`` names which commit is pinned)."""
    shas: dict[str, dict[str, str]] = {}
    origins: dict[str, Path] = {}
    for name in ("sensos", "hekb-vnext", "meaning-mapper", "meaning-space-runtime"):
        origins[name] = tmp_path / "origins" / name
        shas[name] = make_fake_repo(origins[name])
    mdir = tmp_path / "manifests"
    shutil.copytree(Path(__file__).resolve().parent.parent / "manifests", mdir)

    def mutate(doc: dict[str, object]) -> None:
        for repo in doc["repositories"]:  # type: ignore[attr-defined]
            repo["commit"] = shas[repo["name"]][pin]

    set_core(mdir, mutate)
    rewrite_sums(mdir)
    return load(mdir, "core/core-release.v0.json", "platforms/linux-cpu.json"), origins, mdir


def local_acquire(origins: dict[str, Path]):  # type: ignore[no-untyped-def]
    return lambda repo, dest: dict(gitops.acquire(repo.name, str(origins[repo.name]), repo.branch, repo.commit, dest))


def stop_after_venv(venv_dir: Path, lock: Path) -> None:
    raise venv.VenvError("stub: no network, no pip install")


def test_matching_shas_proceed_to_the_venv_stage(tmp_path: Path) -> None:
    loaded, origins, _ = build_world(tmp_path)
    home = tmp_path / "home"
    steps = install.Steps(acquire=local_acquire(origins), build_venv=stop_after_venv)
    messages: list[str] = []
    assert install.install(loaded, home, steps, messages.append) == 1
    assert any("STOP at venv" in m for m in messages)
    for repo in loaded.repos:  # all four were acquired and verified
        assert gitops.head(home / "releases" / loaded.core["release_id"] / "src" / repo.name) == repo.commit
    report = json.loads(next((home / "reports").rglob("*.json")).read_text())
    assert report["stage"] == "venv" and report["result"] == "stopped"
    assert [r["head"] for r in report["repositories"]] == [r.commit for r in loaded.repos]
    assert not (home / "stores").exists() and not (home / "reports" / loaded.core["release_id"] / "deployment.json").exists()


def test_sha_mismatch_stops_before_anything_is_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loaded, origins, _ = build_world(tmp_path)
    home = tmp_path / "home"
    real = gitops.head
    calls = {"n": 0}

    def wrong_head(repo: Path) -> str:
        calls["n"] += 1
        return "f" * 40 if "hekb-vnext" in str(repo) else real(repo)

    monkeypatch.setattr(gitops, "head", wrong_head)
    built: list[str] = []
    steps = install.Steps(acquire=local_acquire(origins), build_venv=lambda v, lock: built.append("venv"))
    messages: list[str] = []
    assert install.install(loaded, home, steps, messages.append) == 1
    assert built == []  # the venv stage was never reached
    assert any("HEAD after checkout" in m for m in messages)
    assert not (home / "releases" / loaded.core["release_id"] / "venv").exists()
    assert (home / "reports" / loaded.core["release_id"] / "failed").is_dir()


def test_commit_not_on_main_stops(tmp_path: Path) -> None:
    loaded, origins, mdir = build_world(tmp_path)
    side = {n: make_fake_repo(tmp_path / "x" / n)["c3"] for n in origins}  # commits that exist nowhere in the origins' main
    set_core(mdir, lambda d: [r.update(commit=side[r["name"]]) for r in d["repositories"]])
    loaded = load(mdir, "core/core-release.v0.json", "platforms/linux-cpu.json")
    built: list[str] = []
    steps = install.Steps(acquire=local_acquire(origins), build_venv=lambda v, lock: built.append("venv"))
    assert install.install(loaded, tmp_path / "home", steps, lambda m: None) == 1
    assert built == []


def test_unsupported_host_refuses_before_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loaded, origins, _ = build_world(tmp_path)
    monkeypatch.setattr(acceptance, "host_facts", lambda: UBUNTU | {"os_version_id": "22.04"})
    home = tmp_path / "home"
    out: list[str] = []
    assert install.install(loaded, home, install.Steps(acquire=local_acquire(origins)), out.append) == 2
    assert not home.exists()
    assert "22.04" in out[0]


def test_missing_ensurepip_stops_before_any_acquisition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loaded, _, _ = build_world(tmp_path)
    monkeypatch.setattr(acceptance, "ensurepip_available", lambda: False)
    home = tmp_path / "home"
    out: list[str] = []
    acquired: list[str] = []

    def acquire(repo: Repo, dest: Path) -> dict[str, object]:
        acquired.append(repo.name)
        return {"head": "", "reused": False}

    steps = install.Steps(acquire=acquire)
    assert install.install(loaded, home, steps, out.append) == 2
    assert acquired == [] and not home.exists()  # nothing fetched, nothing written
    assert f"python3.{sys.version_info.minor}-venv" in out[0] and "ensurepip" in out[0]


@pytest.mark.parametrize("minor", [12, 14])
def test_ensurepip_hint_names_the_running_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minor: int) -> None:
    loaded, _, _ = build_world(tmp_path)
    monkeypatch.setattr(acceptance, "ensurepip_available", lambda: False)
    check = acceptance.check_dependencies_host(loaded, dict(UBUNTU), python_minor=(3, minor))
    message = " ".join(check.detail["failures"])
    assert check.status == "fail" and f"python3.{minor}-venv" in message
    assert all(f"python3.{other}-venv" not in message for other in (12, 14) if other != minor)
    assert "Debian/Ubuntu" in message and "does not install it" in message


def test_dry_run_writes_nothing_and_prints_the_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SENSOS_HOME", str(home))
    assert install.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and "checkout --detach f700a3d3ba4e7e9013e42d515071cd38bf8e99e4" in out
    assert "--require-hashes" in out and "never overwritten" in out
    assert not home.exists()


def test_main_refuses_a_tampered_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, mdir = build_world(tmp_path)
    (mdir / "core" / "core-release.v0.json").write_text("{}")
    monkeypatch.setenv("SENSOS_HOME", str(tmp_path / "home"))
    assert install.main(["--manifests", str(mdir)]) == 2
    assert not (tmp_path / "home").exists()


def test_repo_dataclass_is_what_acquire_receives(tmp_path: Path) -> None:
    loaded, _, _ = build_world(tmp_path)
    assert all(isinstance(r, Repo) and r.branch == "main" for r in loaded.repos)


def test_dependency_check_reports_each_cause(tmp_path: Path) -> None:
    loaded, _, _ = build_world(tmp_path)
    bad = acceptance.check_dependencies_host(loaded, {"system": "Darwin", "os_id": "", "os_version_id": "", "machine": "arm64", "python": "3.11.0"})
    assert bad.status == "fail" and len(bad.detail["failures"]) >= 3
    assert acceptance.check_dependencies_host(loaded, dict(UBUNTU)).status == "pass"


def test_declaration_mismatch_stops_and_the_failed_record_names_the_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loaded, origins, _ = build_world(tmp_path)
    home = tmp_path / "home"
    sha = "a" * 64
    old = {"unverifiable_catalog": {"sha256": sha}, "accepted_versions": ["1.1.0", "1.2.0"]}
    (home / "stores" / "gen-x" / "graph").mkdir(parents=True)
    (home / "stores" / "gen-x" / store.DECLARATION_FILE).write_text(json.dumps(old))
    monkeypatch.setattr(venv, "write_pth", lambda *a, **k: None)
    monkeypatch.setattr(venv, "package_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(store, "gate_catalog", lambda *a, **k: store.GateCatalog([], sha))
    monkeypatch.setattr(store, "expected_declaration", lambda *a, **k: {**old, "accepted_versions": ["1.1.0"]})
    steps = install.Steps(acquire=local_acquire(origins), build_venv=lambda v, lock: None)
    messages: list[str] = []
    assert install.install(loaded, home, steps, messages.append) == 1
    assert any("STOP at store" in m and "accepted_versions" in m for m in messages)
    rel = home / "reports" / loaded.core["release_id"]
    assert not (rel / "deployment.json").exists()
    fs = json.loads(next((rel / "failed").glob("*.json")).read_text())["formal_store"]
    assert fs["status"] == "declaration-mismatch" and fs["differing_fields"] == ["accepted_versions"]
    assert fs["differences"]["accepted_versions"] == {"expected": ["1.1.0"], "actual": ["1.1.0", "1.2.0"]}


def test_check_7_twice_in_the_same_second_uses_two_fresh_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    decl = {"unverifiable_catalog": {"version": "1"}, "x": 1}
    prod = tmp_path / "stores" / "gen-x"
    prod.mkdir(parents=True)
    (prod / store.DECLARATION_FILE).write_text(json.dumps(decl), encoding="utf-8")
    (prod / store.CHAIN_FILE).parent.mkdir(parents=True, exist_ok=True)
    (prod / store.CHAIN_FILE).write_text("chain", encoding="utf-8")

    def fake_create(venv_dir: Path, hekb: Path, store_dir: Path, catalog: object, version: str) -> dict[str, object]:
        # what hekb does: a formal store may only be made in an empty folder
        if store_dir.exists() and any(store_dir.iterdir()):
            raise store.StoreError("formal_store_not_empty")
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "marker").write_text("x", encoding="utf-8")
        return decl

    monkeypatch.setattr(store, "create_store", fake_create)
    monkeypatch.setattr(store, "inspect_store", lambda v, h, d: {"quarantined": 0, "records": 0, "declaration": decl})
    monkeypatch.setattr(uniquename, "utc_stamp", lambda: "20261125T045639Z")
    facts = SimpleNamespace(
        store_path=prod, home=tmp_path, venv_dir=tmp_path / "venv", src={"hekb-vnext": tmp_path / "hekb"},
        catalog=None, loaded=SimpleNamespace(core={"release_id": "rel"}),
    )
    first = acceptance.check_e2e(facts)  # type: ignore[arg-type]
    second = acceptance.check_e2e(facts)  # type: ignore[arg-type]
    assert first.status == "pass" and second.status == "pass"
    base = tmp_path / "acceptance" / "rel"
    assert sorted(p.name for p in base.iterdir()) == ["20261125T045639Z", "20261125T045639Z-001"]
    assert first.detail["test_store"] == str(base / "20261125T045639Z" / "store")
    assert second.detail["test_store"] == str(base / "20261125T045639Z-001" / "store")
    assert (base / "20261125T045639Z" / "store" / "marker").exists()
