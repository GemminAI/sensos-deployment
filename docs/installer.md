# Installer (linux-cpu, Core only)

Status: **run once on a real machine (2026-11-25).** Host: Parallels VM, Ubuntu 24.04.3, aarch64, Python 3.12.3.
There the install ended with all Acceptance checks 1-7 passing, and a second run reused the same Formal Store
(`gen-568e4f0a...`, still one store). Everything else is unconfirmed: see "Not implemented / not verified".

Confirmed on that host only: git acquisition with the SHA check, `pip install --require-hashes` from the lock, the Gate child,
Formal Store creation and reuse, checks 1-7 (7 = store round trip).
Not confirmed: x86_64; Python 3.13 and 3.14; a fresh VM (clean install from scratch); the artifact chain
(Token Temporal -> window -> Frame -> Measurement); hekb-vnext's HTTP service dependencies.

## Use

```bash
python3 -m installers.install --dry-run     # prints the steps, writes nothing
python3 -m installers.install               # installs (needs network, git, Ubuntu 24.04, Python 3.12-3.14)
```

Everything is written under `SENSOS_HOME` (default `~/.sensos`); nothing is deleted or overwritten.

```
<SENSOS_HOME>/releases/<release_id>/src/<repo>      checkouts (detached at the manifest commit)
<SENSOS_HOME>/releases/<release_id>/venv            dedicated environment
<SENSOS_HOME>/stores/gen-<catalogue sha256>/        Formal Store (+ declaration.json)
<SENSOS_HOME>/acceptance/<release_id>/<time>/store  throwaway store used by Acceptance check 7
<SENSOS_HOME>/reports/<release_id>/deployment.json  Deployment Report (written once; later runs -> redeploy/, failures -> failed/)
```

Exit status: 0 installed or dry-run; 1 stopped or acceptance failed (a report is written); 2 refused before writing anything
(bad/tampered manifest, unsupported host).

## What it does

1. Verifies `manifests/SHA256SUMS`, validates the Core and Platform manifests against their schemas, and checks that the lock pins
   `nvs-runtime` / `nvs-observation` to exactly the manifest's wheel sha256.
2. Dependency check (OS, CPU, Python, git).
3. For each Core repository: `git clone --single-branch --branch main`, require the commit to be on `origin/main`,
   `checkout --detach <commit>`, require `HEAD == commit`. A mismatch stops the installation.
4. Creates the venv and runs `pip install --require-hashes --only-binary=:all: --no-deps -r linux-cpu.lock`.
   `meaning-mapper` and `meaning-space-runtime` (`src/`) are made importable with a `.pth` file, because pip forbids unhashed local
   requirements under `--require-hashes`. `sensos` and `hekb-vnext` are used from their checkouts (no package install).
5. Formal Store: the Gate child process (`nvs_runtime/hidden_trajectory/_gate_child.py`, `catalog` op) gives the UNVERIFIABLE catalogue.
   The generation (its sha256) decides where a store is looked for (`stores/gen-<64 hex>`); the store's identity is checked against the
   whole declaration. The expected declaration is made by hekb-vnext `formal_declaration` (helper op `expected_declaration`, the
   same function `create` uses; no store is made) from the measured catalogue, and compared field by field with the store's
   `declaration.json`. No field is excluded: at the pinned hekb-vnext the declaration has no clock/host/random field, and `created_by`
   is the fixed string the Installer passes. Same generation and identical declaration: reused (the compared declaration sha256 and
   `declaration_match: "match"` go into the report's `formal_store`). Same generation but another declaration (e.g. only
   `accepted_versions` differs): the install stops; the message gives the store path and, per differing field, the expected and actual
   value, and `failed/<time>.json` records `differing_fields` and `differences`. The store is neither reused, rewritten nor replaced.
   No store of the generation: one is created with `formal_declaration` + `IC04Store.create_formal`; two or more: stop. Older
   generations are never touched. The implementation uses all 64 hex digits for the directory name.
6. Acceptance Test (checks 1-7 of design v0.4 section 3.1) and the Deployment Report (JSON).

Time-named folders and files (the Acceptance Test's throwaway store under `acceptance/<release_id>/<time>/store`, and the
reports `failed/<time>.json` and `redeploy/<time>.json`) use the UTC second as `YYYYMMDDTHHMMSSZ`. If that name already exists
(a second run in the same second), the Installer uses `<time>-001`, then `-002` and so on, up to `-999`; past that it raises an error.
A name is claimed by creating it (`mkdir` without `exist_ok`, or exclusive file creation), not by checking first, so concurrent runs
cannot take the same name. Existing evidence and reports are never opened for writing, overwritten or removed, and each Acceptance
Test run gets its own new, empty folder. `deployment.json` keeps its fixed name and is still never overwritten.

## Lock

`manifests/platforms/linux-cpu.lock` is one universal lock (all Pythons >= 3.12, x86_64 and aarch64). It was generated on Darwin arm64
by `tools/generate_linux_cpu_lock.py` (record: `linux-cpu.lock.record.json`); `uv pip sync --dry-run --require-hashes` resolves it for
{x86_64, aarch64} x {3.12, 3.13, 3.14}. Changing the lock is a Platform Manifest change: update `linux-cpu.json` and `SHA256SUMS`.

## Not implemented / not verified

- Real runs: only the one host above (two runs). The automated tests use fake local git repositories and stubs, not real systems.
- The `unverified` list of a Deployment Report is built from the run's own host facts, so it states what was confirmed on that host
  and that other CPUs, Python versions and OS versions were not tried.
- Check 7 is a store round trip only. The artifact chain (Token Temporal -> window -> Frame -> Measurement) is not run, and no Gate verdict is put
  into a store. Observation is outside linux-cpu.
- Check 3 compares each vendored file to `LOCK.json`; only `gate-verdict.schema.json` is compared to its source (the other `source` fields are free text).
- hekb-vnext's HTTP service dependencies (fastapi, uvicorn, cryptography) are not in the lock.
- The Updater, Recovery, Operational Health Check (`health/<time>.json`), macos-mlx and the Observation Manifest do not exist yet.
- The CPU architecture of the Ubuntu VM (x86_64 or aarch64) is not stated in the design; both are accepted.

## Develop

```bash
python3 -m pytest        # offline
ruff check . && mypy
```
