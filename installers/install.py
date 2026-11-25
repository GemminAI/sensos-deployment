"""Installer for the linux-cpu platform (Core only). Standard library only (Python 3.12+).

    python -m installers.install [--manifests manifests] [--core core/core-release.v1.json]
                                 [--platform platforms/linux-cpu.json] [--dry-run]

``SENSOS_HOME`` (default ``~/.sensos``) is the only place written. Nothing is deleted or overwritten.
Exit status: 0 installed (or dry-run), 1 stopped/failed (a report is written), 2 refused before writing anything.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import gitops
from common.manifest import Loaded, ManifestError, Repo, load
from installers import acceptance, store, venv
from reports import deployment

DEFAULT_MANIFESTS = Path(__file__).resolve().parent.parent / "manifests"
CHILD_RELATIVE = Path("hidden_trajectory") / "_gate_child.py"


@dataclass
class Steps:
    """The side-effecting steps, replaceable in tests (the real ones are the defaults)."""

    acquire: Callable[[Repo, Path], dict[str, Any]] = lambda repo, dest: dict(
        gitops.acquire(repo.name, repo.url, repo.branch, repo.commit, dest)
    )
    build_venv: Callable[[Path, Path], None] = lambda venv_dir, lock: _build_venv(venv_dir, lock)
    run_acceptance: Callable[[acceptance.Facts], list[acceptance.Check]] = acceptance.run_all


@dataclass
class Layout:
    home: Path
    release_id: str
    release: Path = field(init=False)
    src: Path = field(init=False)
    venv_dir: Path = field(init=False)
    stores: Path = field(init=False)

    def __post_init__(self) -> None:
        self.release = self.home / "releases" / self.release_id
        self.src = self.release / "src"
        self.venv_dir = self.release / "venv"
        self.stores = self.home / "stores"


def _build_venv(venv_dir: Path, lock: Path) -> None:
    venv.create(venv_dir)
    venv.install_lock(venv_dir, lock)


def sensos_home() -> Path:
    return Path(os.environ.get("SENSOS_HOME") or Path.home() / ".sensos")


def plan(loaded: Loaded, layout: Layout) -> list[str]:
    steps = [
        f"verify manifests/SHA256SUMS, schemas, and that the lock covers {', '.join(p.name for p in loaded.packages)} (read only)",
        "dependency check: OS, CPU architecture, Python version, git",
    ]
    for r in loaded.repos:
        steps.append(
            f"acquire {r.name}: git clone --single-branch --branch {r.branch} {r.url} -> {layout.src / r.name}; "
            f"checkout --detach {r.commit}; require HEAD == {r.commit} (stop on mismatch)"
        )
    steps += [
        f"create venv {layout.venv_dir}",
        f"pip install --require-hashes --only-binary=:all: --no-deps -r {loaded.lock_path.name} (sha256 {loaded.lock_sha256[:12]}...)",
        "add sensos-core.pth for meaning-mapper/src and meaning-space-runtime/src",
        f"ask the Gate child for its UNVERIFIABLE catalogue; reuse the Formal Store of that generation under {layout.stores}, "
        "or create one (two of one generation: stop)",
        "Acceptance Test checks 1-7 (check 7 uses a throwaway store under <home>/acceptance/)",
        f"write {deployment.reports_dir(layout.home, layout.release_id) / 'deployment.json'} (never overwritten)",
    ]
    return steps


def install(loaded: Loaded, home: Path, steps: Steps, out: Callable[[str], None] = print) -> int:
    release_id = str(loaded.core["release_id"])
    layout = Layout(home, release_id)
    host = acceptance.host_facts()
    repositories: list[dict[str, Any]] = []
    packages = [{"name": p.name, "version": p.version, "wheel_sha256": p.wheel_sha256} for p in loaded.packages]
    state: dict[str, Any] = {"formal_store": None, "gate": None, "checks": []}
    stage = "dependency-check"

    def report(result: str, error: str | None = None) -> int:
        path = deployment.save(home, deployment.build(
            release_id=release_id, core_sha256=loaded.core_sha256, platform_sha256=loaded.platform_sha256,
            lock_sha256=loaded.lock_sha256, repositories=repositories, packages=packages, checks=state["checks"],
            unverified=state.get("unverified", []), host=host, formal_store=state["formal_store"], gate=state["gate"],
            compute_environment=str(loaded.platform.get("compute_environment", "")), result=result, stage=stage, error=error,
        ))
        out(f"report: {path}")
        return 0 if result == "installed" else 1

    pre = acceptance.check_dependencies_host(loaded, host)
    state["checks"].append(pre.as_json())
    if pre.status != "pass":
        out("STOP dependency check: " + "; ".join(pre.detail["failures"]))
        return 2  # nothing has been written
    try:
        stage = "acquire"
        for repo in loaded.repos:
            got = steps.acquire(repo, layout.src / repo.name)
            repositories.append({
                "name": repo.name, "url": repo.url, "branch": repo.branch, "commit": repo.commit,
                "head": got["head"], "reused": got["reused"],
            })
            out(f"acquired {repo.name} @ {repo.commit[:12]} ({'reused' if got['reused'] else 'cloned'})")
        stage = "venv"
        steps.build_venv(layout.venv_dir, loaded.lock_path)
        src = {r.name: layout.src / r.name for r in loaded.repos}
        venv.write_pth(layout.venv_dir, [src["meaning-mapper"] / "src", src["meaning-space-runtime"] / "src"])
        stage = "store"
        child = venv.package_dir(layout.venv_dir, "nvs_runtime") / CHILD_RELATIVE
        sensos_tools = src["sensos"] / "tools"
        catalog = store.gate_catalog(layout.venv_dir, child, sensos_tools)
        sensos_commit = gitops.head(src["sensos"])
        made = store.ensure_store(layout.venv_dir, src["hekb-vnext"], layout.stores, catalog, sensos_commit)
        decl = store.inspect_store(layout.venv_dir, src["hekb-vnext"], made["path"])["declaration"]
        state["formal_store"] = {
            "path": str(made["path"]), "status": made["status"], "generation": catalog.sha256,
            "declaration_sha256": store.declaration_sha256(decl), "catalog_version": decl["unverifiable_catalog"]["version"],
            "declaration_match": made["declaration_match"], "compared_declaration_sha256": made["declaration_sha256"],
        }
        state["gate"] = {"child_script": str(child), "catalog_sha256": catalog.sha256, "catalog_rows": len(catalog.rows)}
        stage = "acceptance"
        facts = acceptance.Facts(
            loaded=loaded, src=src, venv_dir=layout.venv_dir, store_path=made["path"], catalog=catalog, home=home,
            child_script=child, sensos_tools=sensos_tools, store_status=made["status"],
        )
        checks = steps.run_acceptance(facts)
        state["checks"] = [c.as_json() for c in checks]
        state["unverified"] = [u for c in checks for u in c.unverified]
        ok = all(c.status == "pass" for c in checks)
        for c in checks:
            out(f"check {c.id} {c.name}: {c.status}")
        stage = "report"
        return report("installed" if ok else "acceptance-failed", None if ok else "see acceptance.checks")
    except store.DeclarationMismatch as error:
        state["formal_store"] = {
            "path": str(error.store_path), "status": "declaration-mismatch", "generation": catalog.sha256,
            "declaration_match": "mismatch", "differing_fields": error.fields,
            "differences": {k: {"expected": e, "actual": a} for k, (e, a) in error.diffs.items()},
        }
        out(f"STOP at {stage}: {error}")
        return report("stopped", str(error))
    except (gitops.AcquisitionError, venv.VenvError, store.StoreError) as error:
        out(f"STOP at {stage}: {error}")
        return report("stopped", str(error))


def main(argv: list[str] | None = None, steps: Steps | None = None) -> int:
    ap = argparse.ArgumentParser(prog="installers.install", description=__doc__)
    ap.add_argument("--manifests", type=Path, default=DEFAULT_MANIFESTS)
    ap.add_argument("--core", default="core/core-release.v1.json")
    ap.add_argument("--platform", default="platforms/linux-cpu.json")
    ap.add_argument("--dry-run", action="store_true", help="print the steps; write nothing")
    args = ap.parse_args(argv)
    try:
        loaded = load(args.manifests, args.core, args.platform)
    except ManifestError as error:
        print(f"STOP manifests: {error}", file=sys.stderr)
        return 2
    home = sensos_home()
    layout = Layout(home, str(loaded.core["release_id"]))
    if args.dry_run:
        print(f"dry-run (nothing is written). SENSOS_HOME={home} release_id={layout.release_id}")
        for i, line in enumerate(plan(loaded, layout), 1):
            print(f"{i:2d}. {line}")
        host = acceptance.check_dependencies_host(loaded)
        print(f"dependency check on this host: {host.status}" + ("" if host.status == "pass" else " -- " + "; ".join(host.detail["failures"])))
        return 0
    return install(loaded, home, steps or Steps())


if __name__ == "__main__":
    raise SystemExit(main())
