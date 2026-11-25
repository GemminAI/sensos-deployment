"""Deployment Report: JSON is the record; saved outside every Formal Store.

``<home>/reports/<release_id>/deployment.json`` is written once and never overwritten. A later deployment of
the same release goes to ``redeploy/<time>.json``; a failed attempt to ``failed/<time>.json``. Operational
Health Check results (``health/<time>.json``) belong to a later stage and are not written here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common import uniquename

REPORT_VERSION = "deployment-report/0"

#: Items this Installer never confirms, whatever happens at run time.
ALWAYS_UNVERIFIED = [
    "Validator checks beyond the Acceptance Test, the Updater and Recovery do not exist yet.",
    "Operational Health Check is not implemented.",
    "hekb-vnext's HTTP service (fastapi, uvicorn, cryptography) is not installed; only the Formal Store library path is.",
]


def host_unverified(host: dict[str, str], installed: bool) -> list[str]:
    """Statements about the lock that follow from THIS run's host facts (not a fixed claim about any machine).

    Only a run that ended ``installed`` (Acceptance Test passed, so ``pip install --require-hashes`` succeeded here)
    may say what was confirmed; everything beyond this host stays unverified.
    """
    where = f"{host.get('machine', '?')} / {host.get('os_id', '?')} {host.get('os_version_id', '?')} / Python {host.get('python', '?')}"
    beyond = "Other CPU architectures, other Python versions and other OS versions were not tried in this run."
    if installed:
        return [f"pip install --require-hashes from the lock succeeded on this host ({where}). {beyond}"]
    return [f"The lock was not confirmed on this host ({where}): this run did not finish installed. {beyond}"]


def now_stamp() -> str:
    return uniquename.utc_stamp()


def reports_dir(home: Path, release_id: str) -> Path:
    return home / "reports" / release_id


def build(
    *,
    release_id: str,
    core_sha256: str,
    platform_sha256: str,
    lock_sha256: str,
    repositories: list[dict[str, Any]],
    packages: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    unverified: list[str],
    host: dict[str, str],
    formal_store: dict[str, Any] | None,
    gate: dict[str, Any] | None,
    compute_environment: str,
    result: str,
    stage: str,
    error: str | None = None,
) -> dict[str, Any]:
    by_id = {c["id"]: c for c in checks}
    return {
        "report_version": REPORT_VERSION,
        "created_at": now_stamp(),
        "result": result,
        "stage": stage,
        "error": error,
        "release_id": release_id,
        "core_manifest_sha256": core_sha256,
        "observation_manifest_sha256": None,
        "platform_manifest_sha256": platform_sha256,
        "lock_sha256": lock_sha256,
        "host": host,
        "repositories": repositories,
        "packages": packages,
        "contracts": by_id.get(3, {}).get("detail", {}).get("rows", []),
        "gate": gate,
        "formal_store": formal_store,
        "adapter": {
            "inference_engine": None,
            "observation_adapter": None,
            "observation_scope": "none (linux-cpu)",
            "compute_environment": compute_environment,
        },
        "e2e": by_id.get(7),
        "acceptance": {"checks": checks, "passed": result == "installed"},
        "unverified": sorted(set(unverified) | set(ALWAYS_UNVERIFIED) | set(host_unverified(host, result == "installed"))),
    }


def save(home: Path, report: dict[str, Any]) -> Path:
    """Write the report without overwriting anything. Returns the path."""
    folder = reports_dir(home, report["release_id"])
    stamp = report["created_at"]
    text = json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if report["result"] != "installed":
        target, handle = uniquename.create_unique_file(folder / "failed", stamp)
    elif (folder / "deployment.json").exists():
        target, handle = uniquename.create_unique_file(folder / "redeploy", stamp)
    else:
        target = folder / "deployment.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = open(target, "x", encoding="utf-8")  # exclusive: never overwrites
    with handle:
        handle.write(text)
    return target
