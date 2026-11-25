# Verification record: Core Release Manifest v1 (MSR eadae4e), 2026-11-25

Status of this record: it states what was run on one host and what it returned. By the maintainer's decision of 2026-11-25 v1 is the
official Core Release Manifest and the Installer's default is v1; the declaration is in that decision, not in this record.

## 1. What was run

| Item | Value |
|---|---|
| Date | 2026-11-25 (JST) |
| Host | Parallels VM, Ubuntu 24.04.3, aarch64, Python 3.12.3 |
| Manifest | `manifests/core/core-release.v1.json`, release_id `core-2026.11.25-1` |
| Installer branch | `manifest/core-v1-msr-eadae4e` at `7003a4b428c8ec27197292dc9845fe38bc4b3cc3` (on top of `feature/installer-linux-cpu`, PR #1, merged into `main` as `d0d75ad`) |
| Delivery to the VM | git bundle `sd-v1.bundle`, sha256 `b95e15c94908a047c787e96e6189fc8b0585b431c7414f1716369b975e6bb7b1`, cloned on the VM; HEAD `7003a4b4...` |

Difference from Core Release Manifest v0: `release_id`, `note` and the meaning-space-runtime commit, and nothing else
(`tests/test_core_v1_manifest.py` fixes this). The sensos, hekb-vnext and meaning-mapper commits and the two wheel hashes are the same as in v0.

### 1.1 meaning-space-runtime

- Pinned commit: `eadae4e866584aba6fc33ef1ee1f8985abcedca5`, GitHub `main` of GemminAI/meaning-space-runtime; the merge commit of PR #4
  (parents `ee26c7c...` and `709d395...`).
- Its tree (`<commit>^{tree}`) is `937a1e49cf745fc3d1d704d0f150bd36c37ed7eb`. This is the same tree as the rehearsal's test-merge ref
  (`rehearsal/msr-pr4-pin`, `refs/pull/4/merge` = `ad55ad34...`).
- The rehearsal's local bare repository and URL redirection were **not** used. The four repositories were fetched from GitHub.

## 2. Installer

- New `SENSOS_HOME`. Result: `installed`.
- Acceptance checks 1 to 7 all passed: 1 Version Lock, 2 Dependency Check, 3 Contract Check, 4 Store Setup, 5 Gate Setup,
  6 Runtime Setup, 7 E2E (store round trip, no observation).
- The HEAD of each of the four repositories equals the Manifest: sensos `f700a3d3ba4e`, hekb-vnext `5943a8d43ef1`,
  meaning-mapper `f76dc2f7692f`, meaning-space-runtime `eadae4e86658`.

## 3. Public nvs-runtime tests

The same three files as in the chain test of `2026-11-25-linux-cpu.md` section 3, run against the installed packages.

| Result | Value |
|---|---|
| Passed | 40 |
| Failed | 0 |
| Skipped | 0 |
| `test_geometry_is_measured_only_when_msr_imports` | 1 passed (with MSR `ee26c7c` it failed with `TypeError`; that run was 39 passed, 1 failed) |
| Import paths | `msr` resolves to the checkout under `$SENSOS_HOME`; `nvs_runtime` to the venv's `site-packages` |

Environment the tests need: `GATE_PY` (the venv's python), `SENSOS_TOOLS` (the `tools` directory of the acquired sensos), and
`SENSOS_WINDOW_E2E_DIR`, `SENSOS_TOKEN_TEMPORAL_E2E_DIR`, `SENSOS_MM_E2E_DIR` (each a copy of the earlier capture). Without them the tests skip.

### 3.1 Procedure error

The first procedure did not contain the variables above. The first two runs skipped. Skips were not counted as passes; the variables were
added and the tests were run again, which gave the result in the table.

## 4. Not verified

- The exit status of the Installer's `--dry-run` was not recorded in this run (the real run ended `installed`).
- The value of `declaration_match` was not recorded (the Formal Store was newly created, so there was presumably nothing to compare).
- A round trip in which the Gate child saves a 1.1.0 calibration and reads it back with its parent was not run. The rehearsal's step (c)
  went as far as `check_envelope_versioned`; it was not repeated because the MSR tree is identical.
- x86_64, Python 3.13 and 3.14 were not run.
- A clean install on a newly created VM: see `docs/verification/2026-11-25-clean-install-ubuntu-24.04.md`.
- This verification ran on the branch of PR #1. PR #1 was merged into `main` as the merge commit `d0d75ad` (tree identical to `10f2ab8`); the commits recorded here are ancestors of `main`, so the SHAs are unchanged.
- Declaring v1 the official release is not done by this record; it is stated in the maintainer's decision of 2026-11-25 by which v1 is official and the Installer's default is v1.
