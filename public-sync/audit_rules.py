#!/usr/bin/env python3
"""Apply audit rules (TOML) to the text files of a folder and report hits by layer and rule.

Layers: 1 = information that must not be published, 2 = non-public structure (identifiers of
non-public products), 3 = secrets (patterns that do not depend on a language). The public rules file
of this repository holds layer 3 and the general part of layer 1 only. Layer 2 and the business-specific
words of layer 1 live in a rules file kept outside the repository and passed with ``--rules``.

A hit is reported by file, line, layer and rule id; the matched text is never printed. Exit status:
0 = no hits, 1 = hits, 2 = bad rules or input. Standard library only (``tomllib``).
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

LAYERS = (1, 2, 3)


class RulesError(Exception):
    """The rules file is not usable."""


@dataclass(frozen=True)
class Rule:
    id: str
    layer: int
    pattern: re.Pattern[str]
    description: str


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    layer: int
    rule: str


def load_rules(path: Path) -> list[Rule]:
    """Load the rules of one TOML file; raise ``RulesError`` on anything unexpected."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RulesError(f"{path.name}: cannot read rules ({type(exc).__name__})") from None
    rules: list[Rule] = []
    ids: set[str] = set()
    for index, raw in enumerate(data.get("rule", []), start=1):
        rid, layer, pattern = raw.get("id"), raw.get("layer"), raw.get("pattern")
        if not isinstance(rid, str) or not rid or rid in ids:
            raise RulesError(f"{path.name}: rule {index} has a missing or repeated id")
        if layer not in LAYERS or not isinstance(pattern, str):
            raise RulesError(f"{path.name}: rule {rid} needs layer 1-3 and a pattern")
        flags = re.IGNORECASE if raw.get("ignore_case", False) else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error:
            raise RulesError(f"{path.name}: rule {rid} has an invalid pattern") from None
        ids.add(rid)
        rules.append(Rule(rid, int(layer), compiled, str(raw.get("description", ""))))
    if not rules:
        raise RulesError(f"{path.name}: no rules")
    return rules


def scan_text(name: str, text: str, rules: list[Rule]) -> list[Finding]:
    """Return one finding per (line, rule) that matches."""
    found: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule in rules:
            if rule.pattern.search(line):
                found.append(Finding(name, number, rule.layer, rule.id))
    return found


def scan_folder(root: Path, rules: list[Rule]) -> tuple[list[Finding], list[str]]:
    """Scan every file under ``root``; return the findings and the files that are not UTF-8 text."""
    findings: list[Finding] = []
    skipped: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            skipped.append(rel)
            continue
        findings.extend(scan_text(rel, text, rules))
    return findings, skipped


def summarize(findings: list[Finding]) -> dict[int, dict[str, int]]:
    """Count hits by layer and rule id."""
    table = {layer: collections.Counter[str]() for layer in LAYERS}
    for f in findings:
        table[f.layer][f.rule] += 1
    return {layer: dict(sorted(counts.items())) for layer, counts in table.items()}


def report(findings: list[Finding], skipped: list[str], detail: bool) -> str:
    lines = [f"hits: {len(findings)}"]
    for layer, counts in summarize(findings).items():
        lines.append(f"  layer {layer}: {sum(counts.values())}")
        lines.extend(f"    {rid}: {n}" for rid, n in counts.items())
    if skipped:
        lines.append(f"not text (skipped): {len(skipped)}")
    if detail:
        lines.extend(f"{f.file}:{f.line}: layer {f.layer} {f.rule}" for f in findings)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="the folder to audit (for example an export)")
    parser.add_argument("--rules", type=Path, action="append", required=True, help="a rules TOML file (repeatable)")
    parser.add_argument("--detail", action="store_true", help="also list file:line:rule of every hit")
    args = parser.parse_args(argv)
    try:
        rules = [r for path in args.rules for r in load_rules(path)]
    except RulesError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not args.folder.is_dir():
        print("folder to audit does not exist", file=sys.stderr)
        return 2
    findings, skipped = scan_folder(args.folder, rules)
    print(report(findings, skipped, args.detail))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
