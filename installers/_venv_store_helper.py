"""Runs INSIDE the release venv (``python -I``): the only code that touches hekb-vnext's Formal Store.

Reads one JSON request on stdin, writes one JSON answer on stdout. The Installer itself stays standard-library only.

* ``{"op": "create", "hekb_root", "store_dir", "catalog_rows", "catalog_version", "created_by"}``
    -> ``{"declaration"}``   (``formal.formal_declaration`` + ``IC04Store.create_formal``, hekb-vnext graph/)
* ``{"op": "expected_declaration", "hekb_root", "catalog_rows", "catalog_version", "created_by"}``
    -> ``{"declaration"}``   (the same ``_declaration`` function as ``create``; no store is made, nothing is written)
* ``{"op": "inspect", "hekb_root", "store_dir"}``
    -> ``{"declaration", "records", "chain_verified_records", "quarantined", "violations"}``
       (``verify_all`` raises if a chain is broken: the helper then exits non-zero)
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _declaration(formal: Any, request: dict[str, Any]) -> dict[str, Any]:
    """The ONE place a declaration is built: ``create`` and ``expected_declaration`` both go through it."""
    declaration: dict[str, Any] = formal.formal_declaration(
        catalog_rows=request["catalog_rows"],
        catalog_version=request["catalog_version"],
        created_by=request["created_by"],
    )
    return declaration


def main() -> int:
    request: dict[str, Any] = json.load(sys.stdin)
    sys.path.insert(0, request["hekb_root"])
    from graph import formal
    from graph.ic04 import IC04Store

    if request["op"] == "expected_declaration":
        print(json.dumps({"declaration": _declaration(formal, request)}))
        return 0
    if request["op"] == "create":
        declaration = _declaration(formal, request)
        store = IC04Store.create_formal(request["store_dir"], declaration)
        print(json.dumps({"declaration": store.declaration}))
        return 0
    if request["op"] == "inspect":
        store = IC04Store(request["store_dir"], require_formal=True)
        verified = store.verify_all()  # raises ChainLogError if either chain is broken
        print(json.dumps({
            "declaration": store.declaration,
            "records": len(store),
            "chain_verified_records": len(verified),
            "quarantined": store.quarantined,
            "violations": store.violations,
        }))
        return 0
    print(json.dumps({"error": f"unknown op {request['op']!r}"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
