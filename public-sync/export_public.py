#!/usr/bin/env python3
"""Export the allowlisted files of this repository into a new folder (no git history).

* Files are read from the commit ``HEAD``, not from the working tree. The working tree must be clean
  (no modified, staged or untracked-but-not-ignored files), and the target folder must be new or empty
  and outside the repository.
* Only files named in ``public-sync/allowlist.txt`` are exported, and the allowlist must match the
  tracked files exactly (the same check as ``check_allowlist.py``). Symlinks and submodules are refused.
* ``public-sync/manifest.json`` is written into the export: the source commit, the sha256 of every
  exported file (the manifest cannot hold its own), and the sha256 of the audit rules and of the tools.
  The output is deterministic: the same commit gives byte-identical files and manifest (no timestamps).
* ``manifests/SHA256SUMS`` of the export is verified against the exported files; a mismatch stops the
  export with an error.
* ``--audit`` then applies audit rules to the export (the exported public rules, plus every ``--rules``
  given, for example a rules file kept outside the repository). Hits are counted by layer and rule;
  matched text is never printed.

Standard library only. Exit status: 0 = done, 1 = a problem (on stderr), 2 = bad rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import audit_rules
import check_allowlist

ALLOWLIST_REL = "public-sync/allowlist.txt"
RULES_REL = "public-sync/audit-rules.toml"
MANIFEST_REL = "public-sync/manifest.json"
TOOL_RELS = (
    "public-sync/check_allowlist.py",
    "public-sync/export_public.py",
    "public-sync/audit_rules.py",
)
SUMS_REL = "manifests/SHA256SUMS"


class ExportError(Exception):
    """The export cannot be made, with a short reason."""


def _git(root: Path, *args: str) -> bytes:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if done.returncode != 0:
        raise ExportError(f"git {args[0]} failed")
    return done.stdout


def head_commit(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").decode().strip()


def head_tree(root: Path) -> dict[str, tuple[str, str]]:
    """Map every path of HEAD to (mode, blob id)."""
    tree: dict[str, tuple[str, str]] = {}
    for record in _git(root, "ls-tree", "-r", "-z", "HEAD").decode("utf-8").split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        mode, kind, blob = meta.split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ExportError(f"not a plain file (symlink or submodule): {path}")
        tree[path] = (mode, blob)
    return tree


def blob_bytes(root: Path, blob: str) -> bytes:
    return _git(root, "cat-file", "blob", blob)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_clean(root: Path) -> None:
    if _git(root, "status", "--porcelain").strip():
        raise ExportError("the working tree is not clean (commit or remove changes first)")


def ensure_target(root: Path, out: Path) -> Path:
    out = out.resolve()
    if out == root or root in out.parents or out in root.parents:
        raise ExportError("the target folder must be outside the repository")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ExportError("the target folder must be new or empty")
    return out


def verify_sums(files: dict[str, bytes]) -> list[str]:
    """Check ``manifests/SHA256SUMS`` against the exported files (paths are relative to manifests/)."""
    sums = files.get(SUMS_REL)
    if sums is None:
        return []
    problems: list[str] = []
    for line in sums.decode("utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        member = f"manifests/{name}"
        data = files.get(member)
        if data is None:
            problems.append(f"SHA256SUMS names a file that is not exported: {name}")
        elif sha256_hex(data) != digest:
            problems.append(f"SHA256SUMS does not match the exported file: {name}")
    return problems


def build(root: Path) -> tuple[dict[str, tuple[str, bytes]], dict[str, object]]:
    """Return {path: (mode, bytes)} and the manifest for the allowlisted files of HEAD."""
    tree = head_tree(root)
    allow_data = blob_bytes(root, tree[ALLOWLIST_REL][1]) if ALLOWLIST_REL in tree else None
    if allow_data is None:
        raise ExportError(f"{ALLOWLIST_REL} is not tracked")
    listed: list[str] = []
    for raw in allow_data.decode("utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            listed.append(line)
    problems = check_allowlist.check_entries(listed, sorted(tree))
    if problems:
        raise ExportError("allowlist does not match the tracked files: " + "; ".join(problems))
    files = {p: (tree[p][0], blob_bytes(root, tree[p][1])) for p in sorted(listed)}
    plain = {p: data for p, (_, data) in files.items()}
    sum_problems = verify_sums(plain)
    if sum_problems:
        raise ExportError("; ".join(sum_problems))
    for rel in (RULES_REL, *TOOL_RELS):
        if rel not in files:
            raise ExportError(f"{rel} is not in the allowlist")
    manifest: dict[str, object] = {
        "format": 1,
        "source_commit": head_commit(root),
        "file_count": len(files),
        "files": {p: sha256_hex(data) for p, data in plain.items()},
        "rules_sha256": sha256_hex(plain[RULES_REL]),
        "tools_sha256": {rel: sha256_hex(plain[rel]) for rel in TOOL_RELS},
    }
    return files, manifest


def render_manifest(manifest: dict[str, object]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def export(root: Path, out: Path) -> dict[str, object]:
    """Export HEAD's allowlisted files into ``out``; return the manifest."""
    root = root.resolve()
    ensure_clean(root)
    out = ensure_target(root, out)
    files, manifest = build(root)
    out.mkdir(parents=True, exist_ok=True)
    for rel, (mode, data) in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if mode == "100755" else 0o644)
    manifest_path = out / MANIFEST_REL
    manifest_path.write_bytes(render_manifest(manifest))
    manifest_path.chmod(0o644)
    return manifest


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="the new folder to export into (outside the repository)")
    parser.add_argument("--repo", type=Path, default=here.parent)
    parser.add_argument("--audit", action="store_true", help="audit the export with its public rules and every --rules")
    parser.add_argument("--rules", type=Path, action="append", default=[], help="extra rules TOML (kept outside the repository)")
    args = parser.parse_args(argv)
    try:
        manifest = export(args.repo, args.out)
    except ExportError as exc:
        print(f"export refused: {exc}", file=sys.stderr)
        return 1
    print(f"exported {manifest['file_count']} files (+ manifest) to {args.out}")
    if not args.audit:
        return 0
    try:
        rules = audit_rules.load_rules(args.out.resolve() / RULES_REL)
        rules += [r for path in args.rules for r in audit_rules.load_rules(path)]
    except audit_rules.RulesError as exc:
        print(exc, file=sys.stderr)
        return 2
    findings, skipped = audit_rules.scan_folder(args.out.resolve(), rules)
    print(audit_rules.report(findings, skipped, detail=False))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
