"""Formal Store generations (design v0.4 section 5) and the Gate child process.

How a store is made (read from the code at the pinned commits):

* hekb-vnext ``graph/formal.py``: ``formal_declaration(catalog_rows, catalog_version, created_by)``;
  ``graph/ic04.py``: ``IC04Store.create_formal(dir, declaration)`` writes the declaration as chain seq 0.
* The catalogue rows come from the Gate itself: ``nvs_runtime/hidden_trajectory/_gate_child.py`` (shipped in
  the nvs-runtime wheel), op ``catalog``, run with ``SENSOS_TOOLS`` = ``<sensos checkout>/tools``.
* The generation (the catalogue hash, ``declaration.unverifiable_catalog.sha256``) decides WHERE a store is looked for;
  the store's identity is checked against the WHOLE declaration. Two stores of one catalogue may differ elsewhere in the
  declaration (``accepted_versions`` ...), have another declaration hash and judge the same envelope differently.
  So a store found in the generation is reused only when its ``declaration.json`` equals the expected declaration
  (made by ``formal_declaration`` from the Core-pinned hekb-vnext and the measured catalogue); otherwise the install stops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.hashing import canonical_json_sha256
from common.proc import run
from installers import venv

HELPER = Path(__file__).with_name("_venv_store_helper.py")
DECLARATION_FILE = "declaration.json"
CHAIN_FILE = Path("graph") / "ic00_envelopes.jsonl"


#: Declaration fields left out of the comparison. EMPTY on purpose: at the pinned hekb-vnext (graph/formal.py
#: ``formal_declaration``) every field is a pure function of its arguments (no clock, no host, no random id), and
#: ``created_by`` is the fixed string this Installer passes. So a field that differs is a different declaration, not noise.
IGNORED_DECLARATION_FIELDS: frozenset[str] = frozenset()
CREATED_BY = "sensos-deployment installer"


class StoreError(Exception):
    """The Formal Store could not be made or trusted; the installation stops."""


class DeclarationMismatch(StoreError):
    """A store of the right generation whose declaration is not the expected one. Never reused, never rebuilt."""

    def __init__(self, store_path: Path, diffs: dict[str, tuple[Any, Any]]) -> None:
        self.store_path = store_path
        self.fields = sorted(diffs)
        self.diffs = diffs
        lines = "; ".join(f"{k}: expected {json.dumps(e, sort_keys=True)} actual {json.dumps(a, sort_keys=True)}" for k, (e, a) in sorted(diffs.items()))
        super().__init__(
            f"Formal Store {store_path} has the same catalogue but a different declaration (differing fields: {', '.join(self.fields)}): "
            f"{lines}; refusing to reuse it and not making another"
        )


@dataclass(frozen=True)
class GateCatalog:
    rows: list[list[str]]
    sha256: str


def gate_call(venv_dir: Path, child_script: Path, sensos_tools: Path, request: dict[str, Any]) -> dict[str, Any]:
    """One call of the Gate child process (JSON in, JSON out), the way nvs-runtime's ``GateProcess`` does it."""
    done = run(
        [str(venv.python_of(venv_dir)), str(child_script)],
        env={"PYTHONDONTWRITEBYTECODE": "1", "SENSOS_TOOLS": str(sensos_tools)},
        input_text=json.dumps(request),
        timeout=300,
    )
    if done.returncode != 0:
        tail = (done.stderr.strip().splitlines() or ["no output"])[-1]
        raise StoreError(f"Gate child exited {done.returncode}: {tail}")
    try:
        answer = json.loads(done.stdout)
    except ValueError as error:
        raise StoreError("Gate child output is not JSON") from error
    if not isinstance(answer, dict):
        raise StoreError("Gate child output is not a JSON object")
    return answer


def gate_catalog(venv_dir: Path, child_script: Path, sensos_tools: Path) -> GateCatalog:
    answer = gate_call(venv_dir, child_script, sensos_tools, {"op": "catalog"})
    return GateCatalog(rows=[list(r) for r in answer["rows"]], sha256=str(answer["sha256"]))


def _helper(venv_dir: Path, request: dict[str, Any]) -> dict[str, Any]:
    done = run([str(venv.python_of(venv_dir)), "-I", str(HELPER)], input_text=json.dumps(request), timeout=300)
    if done.returncode != 0:
        raise StoreError(f"store helper ({request['op']}) failed: {(done.stderr or done.stdout).strip()[-1500:]}")
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def expected_declaration(venv_dir: Path, hekb_root: Path, catalog: GateCatalog, catalog_version: str) -> dict[str, Any]:
    """The declaration a store of this release would be made with (same function as ``create``); makes no store."""
    answer = _helper(venv_dir, {
        "op": "expected_declaration", "hekb_root": str(hekb_root),
        "catalog_rows": catalog.rows, "catalog_version": catalog_version, "created_by": CREATED_BY,
    })
    declaration: dict[str, Any] = answer["declaration"]
    return declaration


def compare_declarations(expected: dict[str, Any], actual: Any) -> dict[str, tuple[Any, Any]]:
    """Top-level fields that differ (``field -> (expected, actual)``); empty = identical. Missing fields show as None."""
    if not isinstance(actual, dict):
        return {"<declaration>": (expected, actual)}
    keys = (set(expected) | set(actual)) - IGNORED_DECLARATION_FIELDS
    return {k: (expected.get(k), actual.get(k)) for k in sorted(keys) if expected.get(k) != actual.get(k) or (k in expected) != (k in actual)}


def create_store(
    venv_dir: Path, hekb_root: Path, store_dir: Path, catalog: GateCatalog, catalog_version: str
) -> dict[str, Any]:
    """Make a Formal Store in ``store_dir`` and write the Installer's copy of the declaration beside it."""
    store_dir.mkdir(parents=True, exist_ok=True)
    answer = _helper(venv_dir, {
        "op": "create", "hekb_root": str(hekb_root), "store_dir": str(store_dir),
        "catalog_rows": catalog.rows, "catalog_version": catalog_version, "created_by": CREATED_BY,
    })
    declaration: dict[str, Any] = answer["declaration"]
    (store_dir / DECLARATION_FILE).write_text(json.dumps(declaration, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return declaration


def inspect_store(venv_dir: Path, hekb_root: Path, store_dir: Path) -> dict[str, Any]:
    return _helper(venv_dir, {"op": "inspect", "hekb_root": str(hekb_root), "store_dir": str(store_dir)})


def declaration_sha256(declaration: dict[str, Any]) -> str:
    return canonical_json_sha256(declaration)


def find_generation(stores_dir: Path, catalog_sha256: str) -> list[Path]:
    """Every store under ``stores_dir`` whose ``declaration.json`` has this catalogue hash (its generation).

    A directory with a chain file but no ``declaration.json`` is an unfinished store: stop, never guess.
    """
    found: list[Path] = []
    if not stores_dir.is_dir():
        return found
    for child in sorted(p for p in stores_dir.iterdir() if p.is_dir()):
        decl_file = child / DECLARATION_FILE
        if not decl_file.is_file():
            if (child / CHAIN_FILE).exists():
                raise StoreError(f"{child} has a chain but no {DECLARATION_FILE} (unfinished store); not touching it")
            continue
        try:
            decl = json.loads(decl_file.read_text(encoding="utf-8"))
            sha = decl["unverifiable_catalog"]["sha256"]
        except (ValueError, KeyError, TypeError) as error:
            raise StoreError(f"{decl_file} is unreadable: {error}") from error
        if sha == catalog_sha256:
            found.append(child)
    return found


def ensure_store(
    venv_dir: Path, hekb_root: Path, stores_dir: Path, catalog: GateCatalog, catalog_version: str
) -> dict[str, Any]:
    """Reuse the store of this generation if its whole declaration is the expected one, or make one.

    Two stores of one generation: stop (never pick silently). One store with another declaration: stop (``DeclarationMismatch``).
    """
    same = find_generation(stores_dir, catalog.sha256)
    if len(same) > 1:
        raise StoreError(
            "more than one Formal Store of generation " + catalog.sha256 + ": " + ", ".join(str(p) for p in same)
            + "; refusing to choose"
        )
    if same:
        expected = expected_declaration(venv_dir, hekb_root, catalog, catalog_version)
        actual = json.loads((same[0] / DECLARATION_FILE).read_text(encoding="utf-8"))
        diffs = compare_declarations(expected, actual)
        if diffs:
            raise DeclarationMismatch(same[0], diffs)
        return {"status": "reused", "path": same[0], "declaration_sha256": declaration_sha256(actual), "declaration_match": "match"}
    store_dir = stores_dir / f"gen-{catalog.sha256}"
    if store_dir.exists() and any(store_dir.iterdir()):
        raise StoreError(f"{store_dir} exists but holds no declaration.json; not touching it")
    made = create_store(venv_dir, hekb_root, store_dir, catalog, catalog_version)
    return {
        "status": "created", "path": store_dir, "declaration_sha256": declaration_sha256(made),
        "declaration_match": "not-compared (store created by this run)",
    }
