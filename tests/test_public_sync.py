"""Tests of the public-sync tools: allowlist check, export and audit rules."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public-sync"))

import audit_rules  # noqa: E402
import check_allowlist  # noqa: E402
import export_public  # noqa: E402

REAL_RULES = Path(__file__).resolve().parents[1] / "public-sync" / "audit-rules.toml"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args], cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path, unlisted_file: bool = False) -> Path:
    root = tmp_path / "repo"
    (root / "public-sync").mkdir(parents=True)
    (root / "manifests").mkdir()
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    if unlisted_file:
        (root / "private.txt").write_text("not public\n", encoding="utf-8")
    (root / "manifests" / "m.json").write_text("{}\n", encoding="utf-8")
    digest = hashlib.sha256(b"{}\n").hexdigest()
    (root / "manifests" / "SHA256SUMS").write_text(f"{digest}  m.json\n", encoding="utf-8")
    ps = root / "public-sync"
    ps.joinpath("audit-rules.toml").write_text(REAL_RULES.read_text(encoding="utf-8"), encoding="utf-8")
    for name in ("check_allowlist.py", "export_public.py", "audit_rules.py"):
        ps.joinpath(name).write_text("# tool\n", encoding="utf-8")
    listed = [
        "src/a.py",
        "manifests/m.json",
        "manifests/SHA256SUMS",
        "public-sync/allowlist.txt",
        "public-sync/audit-rules.toml",
        "public-sync/check_allowlist.py",
        "public-sync/export_public.py",
        "public-sync/audit_rules.py",
    ]
    ps.joinpath("allowlist.txt").write_text("# c\n" + "\n".join(listed) + "\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "c")
    return root


def test_matching_allowlist_has_no_problems(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert check_allowlist.check(root, root / "public-sync" / "allowlist.txt") == []


def test_missing_unlisted_duplicate_and_private_entries_are_reported(tmp_path: Path) -> None:
    root = _repo(tmp_path, unlisted_file=True)
    allow = root / "public-sync" / "allowlist.txt"
    allow.write_text(allow.read_text() + "gone.py\nsrc/a.py\n../x\n.local/y\naudit-rules-private.toml\n", encoding="utf-8")
    problems = check_allowlist.check(root, allow)
    assert "listed file is not tracked: gone.py" in problems
    assert "listed twice: src/a.py" in problems
    assert "tracked file is not listed: private.txt" in problems
    assert any("not a relative path" in p for p in problems)
    assert any("private location" in p for p in problems)


def test_export_contains_only_listed_files_and_a_manifest(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    out = tmp_path / "out"
    manifest = export_public.export(root, out)
    names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert "private.txt" not in names and "src/a.py" in names and export_public.MANIFEST_REL in names
    assert not (out / ".git").exists()
    written = json.loads((out / export_public.MANIFEST_REL).read_text(encoding="utf-8"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    assert written == manifest and written["source_commit"] == head
    assert export_public.MANIFEST_REL not in written["files"]
    for rel, digest in written["files"].items():
        assert hashlib.sha256((out / rel).read_bytes()).hexdigest() == digest
    assert written["rules_sha256"] == hashlib.sha256(REAL_RULES.read_bytes()).hexdigest()


def test_same_input_gives_same_output(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    export_public.export(root, tmp_path / "o1")
    export_public.export(root, tmp_path / "o2")
    for p in (tmp_path / "o1").rglob("*"):
        if p.is_file():
            assert p.read_bytes() == (tmp_path / "o2" / p.relative_to(tmp_path / "o1")).read_bytes()


def test_dirty_tree_inside_repo_and_nonempty_target_are_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, unlisted_file=True)
    (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(export_public.ExportError, match="not clean"):
        export_public.export(root, tmp_path / "out")
    _git(root, "checkout", "--", "src/a.py")
    with pytest.raises(export_public.ExportError, match="outside the repository"):
        export_public.export(root, root / "out")
    full = tmp_path / "full"
    full.mkdir()
    (full / "f").write_text("x", encoding="utf-8")
    with pytest.raises(export_public.ExportError, match="new or empty"):
        export_public.export(root, full)


def test_export_refuses_an_allowlist_that_does_not_match_tracked_files(tmp_path: Path) -> None:
    root = _repo(tmp_path, unlisted_file=True)  # private.txt is tracked but not listed
    with pytest.raises(export_public.ExportError, match="tracked file is not listed: private.txt"):
        export_public.export(root, tmp_path / "out")


def test_sums_mismatch_stops_the_export(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "manifests" / "m.json").write_text('{"a": 1}\n', encoding="utf-8")
    _git(root, "commit", "-qam", "change")
    with pytest.raises(export_public.ExportError, match="SHA256SUMS does not match"):
        export_public.export(root, tmp_path / "out")


def test_audit_reports_layers_without_the_matched_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rules = audit_rules.load_rules(REAL_RULES)
    folder = tmp_path / "f"
    folder.mkdir()
    secret = "ghp_" + "A1" * 15
    mail = "someone" + "@" + "corp-mail.io"  # built in parts so this file does not match the rule
    (folder / "a.txt").write_text(f"token {secret}\nmail {mail}\nclean\n", encoding="utf-8")
    (folder / "b.bin").write_bytes(b"\xff\xfe\x00")
    findings, skipped = audit_rules.scan_folder(folder, rules)
    table = audit_rules.summarize(findings)
    assert table[3] == {"secret.known-token-shape": 1} and table[1] == {"identity.email-address": 1}
    assert skipped == ["b.bin"]
    text = audit_rules.report(findings, skipped, detail=True)
    assert secret not in text and mail not in text and "a.txt:1" in text
    assert audit_rules.main([str(folder), "--rules", str(REAL_RULES)]) == 1
    assert secret not in capsys.readouterr().out


def test_public_rules_do_not_match_themselves() -> None:
    rules = audit_rules.load_rules(REAL_RULES)
    assert audit_rules.scan_text("r", REAL_RULES.read_text(encoding="utf-8"), rules) == []


def test_bad_rules_are_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[[rule]]\nid = "x"\nlayer = 9\npattern = "a"\n', encoding="utf-8")
    with pytest.raises(audit_rules.RulesError):
        audit_rules.load_rules(bad)
    bad.write_text('[[rule]]\nid = "x"\nlayer = 2\npattern = "("\n', encoding="utf-8")
    with pytest.raises(audit_rules.RulesError):
        audit_rules.load_rules(bad)
