"""Acceptance Test: Validator checks 1-7 of design v0.4 section 3.1 (linux-cpu, Core only).

The checks only read. Check 7 writes, but only into a throwaway store under ``<home>/acceptance/``;
the production Formal Store is never opened for writing (its chain file is hashed before and after).
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import gitops, uniquename
from common.hashing import canonical_json_sha256, sha256_bytes, sha256_file
from common.manifest import Loaded, normalize, parse_lock
from installers import store, venv

L2_KINDS = {"hidden_trajectory", "ic02", "meaning_frame", "meaning_measurement"}
HEKB_SCHEMA = Path("vendor/sensos_gate_verdict/gate-verdict.schema.json")
SENSOS_SCHEMA = Path("docs/architecture/contracts/nvs/gate-verdict.schema.json")
# The only vendored file whose source is a path in a file we hold (the other LOCK entries name an old commit in free text).
SENSOS_SOURCE_OF = {"sensos_gate_verdict/gate-verdict.schema.json": SENSOS_SCHEMA}


@dataclass
class Check:
    id: int
    name: str
    status: str = "pass"
    detail: dict[str, Any] = field(default_factory=dict)
    unverified: list[str] = field(default_factory=list)

    def fail(self, why: str) -> None:
        self.status = "fail"
        self.detail.setdefault("failures", []).append(why)

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class Facts:
    loaded: Loaded
    src: dict[str, Path]
    venv_dir: Path
    store_path: Path
    catalog: store.GateCatalog
    home: Path
    child_script: Path
    sensos_tools: Path
    store_status: str


def host_facts() -> dict[str, str]:
    osr: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, _, val = line.partition("=")
            osr[key] = val.strip().strip('"')
    except OSError:
        pass
    machine = platform.machine().lower()
    return {
        "system": platform.system(),
        "os_id": osr.get("ID", ""),
        "os_version_id": osr.get("VERSION_ID", ""),
        "machine": {"arm64": "aarch64", "amd64": "x86_64"}.get(machine, machine),
        "python": platform.python_version(),
    }


def ensurepip_available() -> bool:
    """Whether the Python that runs the Installer (and so creates the venv) can import ``ensurepip``."""
    try:
        import ensurepip  # noqa: F401
    except ImportError:
        return False
    return True


def check_dependencies_host(loaded: Loaded, facts: dict[str, str] | None = None, python_minor: tuple[int, int] | None = None) -> Check:
    """Check 2 (also run before anything is written): OS, CPU, Python, git, ensurepip (for the venv)."""
    host = facts or host_facts()
    c = Check(2, "Dependency Check", detail={"host": host})
    plat = loaded.platform
    if host["system"] != "Linux":
        c.fail(f"system is {host['system']!r}, platform {plat['platform_id']} needs Linux")
    if host["os_id"] != plat["os"]["id"] or host["os_version_id"] != plat["os"]["version_id"]:
        c.fail(f"OS is {host['os_id']} {host['os_version_id']!r}, manifest wants {plat['os']['id']} {plat['os']['version_id']}")
    if host["machine"] not in plat["architectures"]:
        c.fail(f"CPU architecture {host['machine']} is not in {plat['architectures']}")
    low = tuple(int(x) for x in plat["python"]["min"].split("."))
    high = tuple(int(x) for x in plat["python"]["max"].split("."))
    have = tuple(int(x) for x in host["python"].split(".")[:2])
    if not low <= have <= high:
        c.fail(f"Python {host['python']} is outside {plat['python']['min']}-{plat['python']['max']}")
    for tool in ("git",):
        if shutil.which(tool) is None:
            c.fail(f"{tool} is not on PATH")
    if not ensurepip_available():
        major, minor = python_minor or (sys.version_info.major, sys.version_info.minor)
        c.fail(
            "ensurepip is not available to this Python, so a virtual environment cannot be created; "
            f"on Debian/Ubuntu install the package python{major}.{minor}-venv (the Installer does not install it)"
        )
    if plat.get("inference_engine") is None:
        c.detail["inference_engine"] = "not applicable (linux-cpu has no observation)"
    return c


def check_version_lock(f: Facts) -> Check:
    c = Check(1, "Version Lock")
    repos = []
    for repo in f.loaded.repos:
        actual = gitops.head(f.src[repo.name])
        repos.append({"name": repo.name, "manifest": repo.commit, "head": actual})
        if actual != repo.commit:
            c.fail(f"{repo.name}: HEAD {actual} != manifest {repo.commit}")
    c.detail["repositories"] = repos
    have = venv.installed(f.venv_dir)
    pins = parse_lock(f.loaded.lock_path.read_text(encoding="utf-8"))
    pk = []
    for pkg in f.loaded.packages:
        got = have.get(normalize(pkg.name))
        hashes = pins[normalize(pkg.name)]["hashes"]
        pk.append({"name": pkg.name, "manifest": pkg.version, "installed": got, "lock_hashes": sorted(hashes)})
        if got != pkg.version:
            c.fail(f"{pkg.name}: installed {got} != manifest {pkg.version}")
        if hashes != {pkg.wheel_sha256}:
            c.fail(f"{pkg.name}: lock hashes {sorted(hashes)} are not exactly the manifest wheel sha256")
    c.detail["packages"] = pk
    expected = {n: p["version"] for n, p in pins.items()}
    if have != expected:
        c.fail("installed distributions differ from the lock: " + json.dumps(
            {k: [have.get(k), expected.get(k)] for k in sorted(set(have) | set(expected)) if have.get(k) != expected.get(k)}))
    c.detail["dependencies_match_lock"] = have == expected
    c.unverified.append("The installed files were not re-hashed; the wheel sha256 is enforced only by pip --require-hashes at install time.")
    return c


def check_contracts(f: Facts) -> Check:
    c = Check(3, "Contract Check")
    rows: list[dict[str, Any]] = []
    hekb = f.src["hekb-vnext"]
    sensos = f.src["sensos"]
    unresolved: list[str] = []
    for lock_file in sorted(hekb.glob("vendor/*/LOCK.json")):
        lock = json.loads(lock_file.read_text(encoding="utf-8"))
        for name, entry in sorted(lock["files"].items()):
            path = lock_file.parent / name
            actual = sha256_file(path) if path.is_file() else None
            row: dict[str, Any] = {
                "lock": str(lock_file.relative_to(hekb)), "file": name, "vendored_sha256": entry["vendored_sha256"],
                "actual_sha256": actual, "vendored_ok": actual == entry["vendored_sha256"],
            }
            if not row["vendored_ok"]:
                c.fail(f"{lock_file.parent.name}/{name}: vendored sha256 does not match LOCK.json")
            src_rel = SENSOS_SOURCE_OF.get(f"{lock_file.parent.name}/{name}")
            if src_rel is not None and entry["source_sha256"]:
                src_actual = sha256_file(sensos / src_rel)
                row["source"] = f"sensos:{src_rel}"
                row["source_ok"] = src_actual == entry["source_sha256"]
                if not row["source_ok"]:
                    c.fail(f"{name}: sensos source sha256 {src_actual} != LOCK source_sha256")
            else:
                row["source"] = "not resolved"
                unresolved.append(f"{lock_file.parent.name}/{name}")
            rows.append(row)
    if not rows:
        c.fail("no vendor/*/LOCK.json found in hekb-vnext")
    c.detail["rows"] = rows
    c.unverified.append(
        "LOCK.json 'source' is free text (a sensos commit named in prose), not (repo, branch, commit, path, sha256); "
        f"only gate-verdict.schema.json was compared against its source. Not resolved: {', '.join(unresolved) or 'none'}."
    )
    return c


def check_store_setup(f: Facts) -> Check:
    c = Check(4, "Store Setup")
    info = store.inspect_store(f.venv_dir, f.src["hekb-vnext"], f.store_path)
    decl = info["declaration"]
    on_disk = json.loads((f.store_path / store.DECLARATION_FILE).read_text(encoding="utf-8"))
    c.detail.update({
        "store": str(f.store_path), "store_status": f.store_status,
        "catalog_sha256": decl["unverifiable_catalog"]["sha256"], "gate_catalog_sha256": f.catalog.sha256,
        "declaration_sha256": store.declaration_sha256(decl), "records": info["records"],
    })
    if decl["unverifiable_catalog"]["sha256"] != f.catalog.sha256:
        c.fail("declaration catalogue hash differs from the current Gate catalogue")
    if on_disk != decl:
        c.fail("declaration.json differs from the chain's seq 0 declaration")
    if info["quarantined"]:
        c.fail(f"the store is quarantined: {info['violations'][:3]}")
    return c


def check_gate_setup(f: Facts) -> Check:
    c = Check(5, "Gate Setup")
    kinds: dict[str, list[str]] = {}
    shas: dict[str, str] = {}
    for label, path in (("hekb-vnext", f.src["hekb-vnext"] / HEKB_SCHEMA), ("sensos", f.src["sensos"] / SENSOS_SCHEMA)):
        schema = json.loads(path.read_text(encoding="utf-8"))
        enum = schema["properties"]["layers"]["properties"]["L2"]["properties"]["kind"]["enum"]
        kinds[label] = sorted(k for k in enum if k)
        shas[label] = sha256_file(path)
        if not L2_KINDS <= set(kinds[label]):
            c.fail(f"{label}: gate-verdict L2.kind accepts {kinds[label]}, needs {sorted(L2_KINDS)}")
    if shas["hekb-vnext"] != shas["sensos"]:
        c.fail("the vendored gate-verdict schema is not byte-identical to sensos's")
    c.detail.update({"l2_kinds": kinds, "schema_sha256": shas})
    try:
        again = store.gate_catalog(f.venv_dir, f.child_script, f.sensos_tools)
        answer = store.gate_call(f.venv_dir, f.child_script, f.sensos_tools, {"op": "jcs_sha256", "value": {"a": 1}})
        c.detail["gate_child_started"] = True
        if answer.get("sha256") != sha256_bytes(b'{"a":1}'):
            c.fail("Gate child JCS hash of {'a': 1} is wrong")
        if again.sha256 != f.catalog.sha256:
            c.fail("Gate child returned a different catalogue hash the second time")
        c.detail["catalog_rows"] = len(again.rows)
    except store.StoreError as error:
        c.detail["gate_child_started"] = False
        c.fail(str(error))
    return c


def check_runtime_setup(f: Facts) -> Check:
    c = Check(6, "Runtime Setup")
    py = venv.python_of(f.venv_dir)
    from common.proc import run

    code = (
        "import json, importlib, importlib.metadata as m;"
        "mods=['nvs_runtime','nvs_observation','meaning_mapper','msr'];"
        "[importlib.import_module(x) for x in mods];"
        "print(json.dumps({'nvs-runtime':m.version('nvs-runtime'),'nvs-observation':m.version('nvs-observation')}))"
    )
    done = run([str(py), "-I", "-c", code])
    if done.returncode != 0:
        c.fail(f"import failed: {(done.stderr or done.stdout).strip()[-800:]}")
        return c
    versions = json.loads(done.stdout)
    c.detail["imported"] = ["nvs_runtime", "nvs_observation", "meaning_mapper", "msr"]
    for pkg in f.loaded.packages:
        if versions.get(pkg.name) != pkg.version:
            c.fail(f"{pkg.name} imports as {versions.get(pkg.name)}, manifest {pkg.version}")
    c.detail["package_versions"] = versions
    checkout_versions: dict[str, str | None] = {}
    for repo in f.loaded.repos:
        if repo.expected_version is None:
            continue
        data = tomllib.loads((f.src[repo.name] / "pyproject.toml").read_text(encoding="utf-8"))
        got = data.get("project", {}).get("version")
        checkout_versions[repo.name] = got
        if got != repo.expected_version:
            c.fail(f"{repo.name}: pyproject version {got} != manifest {repo.expected_version}")
    c.detail["checkout_versions"] = checkout_versions
    c.unverified.append("sensos and hekb-vnext declare no package version; only their commits are checked (check 1).")
    return c


def check_e2e(f: Facts) -> Check:
    """Check 7, linux-cpu scope: a throwaway store of the same declaration is made, reopened and verified.

    The artifact chain (Token Temporal -> window -> Frame -> Measurement) is NOT run: see ``unverified``.
    """
    c = Check(7, "E2E (store round trip, no observation)")
    prod_chain = f.store_path / store.CHAIN_FILE
    before = sha256_file(prod_chain)
    # a fresh, atomically created folder per run, even for two runs in the same second (-001, -002 ...); the store sits inside it
    run_dir = uniquename.make_unique_dir(f.home / "acceptance" / f.loaded.core["release_id"], uniquename.utc_stamp())
    test_dir = run_dir / "store"
    c.detail["test_store"] = str(test_dir)
    prod_decl = json.loads((f.store_path / store.DECLARATION_FILE).read_text(encoding="utf-8"))
    try:
        # the same catalogue and catalogue version as the production declaration, so the two declarations can be compared
        store.create_store(f.venv_dir, f.src["hekb-vnext"], test_dir, f.catalog, prod_decl["unverifiable_catalog"]["version"])
        info = store.inspect_store(f.venv_dir, f.src["hekb-vnext"], test_dir)
    except store.StoreError as error:
        c.fail(str(error))
        return c
    if info["quarantined"] or info["records"] != 0:
        c.fail(f"throwaway store state unexpected: {info}")
    c.detail["declaration_equal_to_production"] = info["declaration"] == prod_decl
    if info["declaration"] != prod_decl:
        c.fail("the throwaway store declaration differs from the production store's")
    after = sha256_file(prod_chain)
    c.detail["production_chain_unchanged"] = before == after
    if before != after:
        c.fail("the production store's chain changed during the test")
    c.unverified += [
        "Token Temporal -> window -> Frame -> Measurement save and re-read was NOT run (needs real artifacts from the producers).",
        "Observation (Hidden State capture) is outside linux-cpu.",
        "No Gate verdict was put into any store; only the store's declaration/chain lifecycle was exercised.",
    ]
    return c


def check_dependencies_installed(f: Facts) -> Check:
    """Check 2 again, after install: the host facts (the lock-vs-installed comparison is part of check 1)."""
    c = check_dependencies_host(f.loaded)
    c.detail["python_executable"] = sys.executable
    return c


CHECKS: list[Callable[[Facts], Check]] = [
    check_version_lock, check_dependencies_installed, check_contracts, check_store_setup,
    check_gate_setup, check_runtime_setup, check_e2e,
]


def run_all(f: Facts) -> list[Check]:
    results: list[Check] = []
    for fn in CHECKS:
        try:
            results.append(fn(f))
        except Exception as error:  # a check that cannot run is a failed check, recorded, not hidden
            idx = len(results) + 1
            bad = Check(idx, f"check {idx}")
            bad.fail(f"{type(error).__name__}: {error}")
            results.append(bad)
    results.sort(key=lambda c: c.id)
    return results


def digest(checks: list[Check]) -> str:
    return canonical_json_sha256([c.as_json() for c in checks])
