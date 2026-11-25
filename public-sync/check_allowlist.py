#!/usr/bin/env python3
"""Check ``allowlist.txt`` against the files git tracks (what is listed but not tracked, and the reverse).

The allowlist names the only files that may be published; nothing is published by default. This check
passes (exit 0) only when the allowlist and the tracked files are exactly the same set, so a new tracked
file has to be added to the allowlist on purpose. Entries that are absolute, climb out of the repository
or point at a private location are refused. Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath

PRIVATE_PARTS = {".git", ".local", ".env", ".venv", "__pycache__"}
PRIVATE_NAME_MARKERS = ("audit-rules-private", ".pem", ".key")


def read_allowlist(path: Path) -> list[str]:
    """Return the entries of an allowlist file (comments and blank lines skipped)."""
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    return entries


def tracked_files(root: Path) -> list[str]:
    """Return the paths git tracks at the index, sorted."""
    done = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return sorted(p for p in done.stdout.decode("utf-8").split("\0") if p)


def entry_problems(entry: str) -> list[str]:
    """Return what is wrong with one entry, as short messages."""
    problems: list[str] = []
    pure = PurePosixPath(entry)
    if pure.is_absolute() or ".." in pure.parts or "\\" in entry:
        problems.append(f"not a relative path inside the repository: {entry}")
        return problems
    if any(part in PRIVATE_PARTS for part in pure.parts) or any(m in pure.name for m in PRIVATE_NAME_MARKERS):
        problems.append(f"entry is in a private location: {entry}")
    if any(c in entry for c in "*?["):
        problems.append(f"patterns are not allowed, list the file: {entry}")
    return problems


def check(root: Path, allowlist: Path, tracked: list[str] | None = None) -> list[str]:
    """Return the problems found (an empty list means the allowlist and the tracked files agree)."""
    tracked_list = tracked_files(root) if tracked is None else tracked
    return check_entries(read_allowlist(allowlist), tracked_list)


def check_entries(entries: list[str], tracked_list: list[str]) -> list[str]:
    """Compare allowlist entries with a list of tracked paths."""
    problems: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        problems.extend(entry_problems(entry))
        if entry in seen:
            problems.append(f"listed twice: {entry}")
        seen.add(entry)
    tracked_set = set(tracked_list)
    for entry in sorted(seen - tracked_set):
        problems.append(f"listed file is not tracked: {entry}")
    for path in sorted(tracked_set - seen):
        problems.append(f"tracked file is not listed: {path}")
    return problems


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=here.parent)
    parser.add_argument("--allowlist", type=Path, default=here / "allowlist.txt")
    args = parser.parse_args(argv)
    problems = check(args.repo.resolve(), args.allowlist)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"allowlist matches the tracked files exactly ({len(read_allowlist(args.allowlist))} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
