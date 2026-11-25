"""Generate the hash-pinned lock of the linux-cpu platform and record where it was made.

Requires ``uv`` and network access to PyPI. Standard library only. It never guesses a hash: every
hash comes from ``uv pip compile --generate-hashes`` (which reads PyPI), and the result is checked
with ``uv pip sync --dry-run --require-hashes`` for each (architecture, Python) pair of the platform.

Usage (from the repository root)::

    python tools/generate_linux_cpu_lock.py

Writes ``manifests/platforms/linux-cpu.lock`` and ``manifests/platforms/linux-cpu.lock.record.json``.
It overwrites those two files only; update ``manifests/platforms/linux-cpu.json`` (lock sha256) and
``manifests/SHA256SUMS`` afterwards -- a lock change is a Platform Manifest change.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ROOT / "manifests" / "platforms"
INPUT = PLATFORMS / "linux-cpu.lock.in"
LOCK = PLATFORMS / "linux-cpu.lock"
RECORD = PLATFORMS / "linux-cpu.lock.record.json"

PYTHON_FLOOR = "3.12"
CHECK_PYTHONS = ("3.12", "3.13", "3.14")
CHECK_PLATFORMS = ("x86_64-manylinux_2_39", "aarch64-manylinux_2_39")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restrict_core_packages(text: str, wheels: dict[str, str]) -> str:
    """Keep, for each Core package, only the hash line equal to the Core manifest's wheel sha256.

    ``uv`` lists the sdist hash too; the wheel-only pin is what the manifest promises. A package whose wheel
    sha256 is not among the hashes makes the whole generation fail (nothing is guessed).
    """
    out: list[str] = []
    current: str | None = None
    seen: set[str] = set()
    for line in text.splitlines(keepends=True):
        head = line.split("==", 1)[0].strip().lower().replace("_", "-")
        if "==" in line and not line.startswith(" "):
            current = head
        if line.strip().startswith("--hash=sha256:") and current in wheels:
            digest = line.strip().removeprefix("--hash=sha256:").rstrip(" \\")
            if digest != wheels[current]:
                continue
            seen.add(current)
        out.append(line)
    missing = set(wheels) - seen
    if missing:
        raise SystemExit(f"wheel sha256 of {sorted(missing)} is not among the resolved hashes; nothing was written")
    text = "".join(out)
    # a requirement block must end without a trailing backslash after filtering
    fixed: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line.rstrip().endswith("\\") and not nxt.strip().startswith("--hash="):
            line = line.rstrip().removesuffix("\\").rstrip()
        fixed.append(line)
    return "\n".join(fixed) + "\n"


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def main() -> int:
    version = run(["uv", "--version"])
    if version.returncode != 0:
        print("uv is not available; the lock is NOT generated (nothing was written).", file=sys.stderr)
        return 2
    compile_cmd = [
        "uv", "pip", "compile", str(INPUT.relative_to(ROOT)),
        "--universal", "--python-version", PYTHON_FLOOR,
        "--generate-hashes", "--only-binary", ":all:", "--no-header",
    ]
    done = subprocess.run(compile_cmd, capture_output=True, text=True, cwd=ROOT, check=False)
    if done.returncode != 0:
        print(done.stderr, file=sys.stderr)
        print("lock generation failed; nothing was written.", file=sys.stderr)
        return 1
    core = json.loads((ROOT / "manifests" / "core" / "core-release.v0.json").read_text(encoding="utf-8"))
    wheels = {p["name"]: p["wheel_sha256"] for p in core["packages"]}
    lock_text = restrict_core_packages(done.stdout, wheels)
    # Verify BEFORE writing anything into the repository.
    with tempfile.TemporaryDirectory() as scratch:
        candidate = Path(scratch) / "candidate.lock"
        candidate.write_text(lock_text, encoding="utf-8")
        checks = []
        for plat in CHECK_PLATFORMS:
            for py in CHECK_PYTHONS:
                cmd = [
                    "uv", "pip", "sync", str(candidate), "--require-hashes", "--only-binary", ":all:",
                    "--python-platform", plat, "--python-version", py, "--dry-run",
                    "--target", str(Path(scratch) / "target"),
                ]
                r = run(cmd)
                checks.append({"platform": plat, "python": py, "ok": r.returncode == 0})
        if not all(c["ok"] for c in checks):
            print(json.dumps(checks, indent=1), file=sys.stderr)
            print("the candidate lock does not resolve for every pair; nothing was written.", file=sys.stderr)
            return 1
    LOCK.write_text(lock_text, encoding="utf-8")
    record = {
        "record_version": "linux-cpu-lock-record/1",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_on": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "tool": version.stdout.strip(),
        },
        "command": compile_cmd,
        "mode": "universal (all platforms; one lock for every OS/arch/Python >= floor)",
        "python_floor": PYTHON_FLOOR,
        "input_sha256": sha256_file(INPUT),
        "lock_sha256": sha256_file(LOCK),
        "dry_run_resolution_checks": checks,
        "not_checked": [
            "No package was installed or imported on any Linux machine.",
            "uv's resolver was used for the dry-run; the installer uses pip (--require-hashes).",
        ],
    }
    RECORD.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {LOCK.relative_to(ROOT)} sha256={record['lock_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
