# Verification record: clean install on Ubuntu 24.04.5, 2026-11-25

Status of this record: it states what was run on one newly created VM, the Installer defects found, the change made for them, and the run of
that change on the same VM from the `clean-base` snapshot (section 6), and the public nvs-runtime tests and the repository's own tests run on that VM (section 7).
The unit tests of the change also ran on the development machine.

## 1. What was run

| Item | Value |
|---|---|
| Date | 2026-11-25 (JST) |
| Host | newly created Parallels VM, Ubuntu 24.04.5 LTS (`ubuntu-24.04.5-desktop-arm64.iso`, sha256 `2be09ca883921bff6d8e6b0bfbafd13e32436553b7086f33bce3a4c5bad8bd14`, equal to Canonical's SHA256SUMS), aarch64, Python 3.12.3 |
| Starting state | Parallels deb packages not installed (absent from `dpkg`); shared folders (Home, an external-drive shared folder and others) visible. After the OS update, snapshot `clean-base` was taken and the run started from it |
| Manifest | `core-release.v1.json` (release_id `core-2026.11.25-1`), branch `manifest/core-v1-msr-eadae4e` |
| Delivery | bundle `sd-clean.bundle`, sha256 `701fc3480eeec4295c55213815cb895c11815e850548667bcf96a7f89a1d20bf`; HEAD `efd6061f1bc1e13809d2bb6b1177c4b98db53461` |

Acquisition worked without authentication: the `main` of the four repositories was reachable, and the HEADs equal the pins of Manifest v1
(sensos `f700a3d3`, hekb-vnext `5943a8d4`, meaning-mapper `f76dc2f7`, meaning-space-runtime `eadae4e8`).

## 2. Prerequisites missing on the clean image

- `git` was absent. It was installed with apt: git 2.43.0 (with `liberror-perl` and `git-man`).
- `python3.12-venv` (3.12.3-1ubuntu0.17) was absent. This led to the two defects below.

## 3. Failed run (python3.12-venv not installed)

- `--dry-run`: exit 0.
- Real run: `STOP at venv: venv creation failed: ` with nothing after the colon, exit 1 (defect 1).
- Run again with the same `SENSOS_HOME`: stopped with `No module named pip`, exit 1 (defect 2).
- Failed reports: `failed/...Z.json` and `failed/...Z-001.json` (the collision-free naming worked).

### 3.1 The defects

1. `venv.create()` put only `stderr` into the error. The venv failure produced an empty message. Which stream the Ubuntu explanation uses was not checked.
2. After the failed creation a `bin/python` stayed in the venv directory. On the rerun, `create()` took the existing `bin/python` as a usable venv and
   went on, and stopped later at `No module named pip`.
3. The dependency check (step 2) passed although `ensurepip` was not available. `python3 -m venv --help` works without `ensurepip`, so the check was not made that way.

## 4. Run after installing python3.12-venv (new `SENSOS_HOME`)

- Real run: exit 0, Acceptance checks 1 to 7 passed, result `installed`; `declaration_match` was `not-compared (store created by this run)`.
- Second run: exit 0, checks 1 to 7 passed, report in `redeploy/...Z.json`, `declaration_match` was `match`.
- Declaration sha256 in both runs: `f12dbda73e8f4797fd50e5ceeaa545583df7f2ba7e3cdb1278e6edeb2268da72`.
- One Formal Store: `gen-568e4f0a6ecb924afb4f6a510cc2dcfc84f9a99a2f3a164bb2fb7a5732e6f2b4`.
- `acceptance/` holds two folders (a time name and its `-001`).
- The public nvs-runtime tests were not run in this run (see section 7).

## 5. Change made for the defects (commit `65e81bf`, branch `feature/installer-linux-cpu`)

- `venv.create()`: the error text contains both stdout and stderr (`stdout: ... | stderr: ...`, or `no output`), and the exit status.
- `venv.create()`: an existing venv is reused only if its python exists **and** `python -m pip --version` succeeds in it. A python without a working pip
  stops the installation with a `VenvError` that names the directory, says the environment is incomplete, and quotes the `pip --version` output. The directory is neither reused nor deleted.
- Check 2 (Dependency Check) requires `import ensurepip` to work in the Python that runs the Installer. It fails with a message naming the missing
  piece and, for Debian/Ubuntu, the package `python3.12-venv`. The Installer does not install it. The check runs before any repository is fetched, and
  an install that fails it exits 2 with nothing written.
- Later change (commit `4c02725`, found in section 8): the package name in the check 2 message is `python<major>.<minor>-venv` of the Python that runs the
  Installer (from `sys.version_info`), no longer fixed to `python3.12-venv`. The rest of the message is unchanged.
- Not changed: Manifest v0 and v1, the Platform Manifest, the lock, `SHA256SUMS`.

Tests added (`tests/test_venv.py`, `tests/test_install_flow.py`):
`test_creation_failure_carries_stdout_and_stderr`, `test_creation_failure_with_no_output_says_so`,
`test_python_without_pip_stops_and_is_not_removed`, `test_venv_with_working_pip_is_reused`,
`test_missing_ensurepip_stops_before_any_acquisition`.
Result on the development machine: 55 passed, 0 skipped, 0 failed; `ruff check` and `mypy` (strict, as configured in `pyproject.toml`) report no issues.

## 6. Verification of the change on the VM

Same VM (Ubuntu 24.04.5, aarch64, Python 3.12.3), restored to the snapshot `clean-base`.

**Run not counted.** The first attempt was made without restoring `clean-base`: git and `python3.12-venv` were already installed and an old `~/sd` (at `efd6061`)
was still there. The Installer ran from that old checkout, so the change was not under test, and the attempt is not counted.

After restoring `clean-base`:

- `which git` showed git missing. `python3 -c "import ensurepip"` raised `ModuleNotFoundError: No module named 'ensurepip'`. So on Ubuntu without
  `python3.12-venv`, `import ensurepip` fails, which is what check 2 relies on.
- git was installed with apt (git 2.43.0, with `liberror-perl` and `git-man`).
- Bundle `sd-clean2.bundle` (sha256 `fe00d18e3c670089781d018f7b0aed81ef11750ab2da9960379802738d4e40a0`); branch `manifest/core-v1-msr-eadae4e` was cloned from it.
  HEAD `e43a67bc7922d515efd45e1b17d2c95f19985664`, a merge commit that contains `65e81bf` and `4aafe47` of `feature/installer-linux-cpu`.

### 6.1 Without python3.12-venv, new `SENSOS_HOME`, Manifest v1

- Output: `STOP dependency check: ensurepip is not available to this Python, so a virtual environment cannot be created; on Debian/Ubuntu install the package python3.12-venv (the Installer does not install it)`; exit 2.
- The `SENSOS_HOME` directory was empty afterwards: no `releases`, and no repository was acquired.

### 6.2 After installing python3.12-venv (3.12.3-1ubuntu0.17), same `SENSOS_HOME`

- Real run: the four repositories were acquired (sensos `f700a3d3ba4e`, hekb-vnext `5943a8d43ef1`, meaning-mapper `f76dc2f7692f`,
  meaning-space-runtime `eadae4e86658`); checks 1 to 7 all passed; exit 0; result `installed`; `declaration_match` was `not-compared (store created by this run)`.
- Second run: the four repositories were reused; checks 1 to 7 all passed; exit 0; report `redeploy/20261125T105101Z.json`; `declaration_match` was `match`.
  The throwaway stores of check 7 were `20261125T105101Z` and `20261125T105101Z-001`.

## 7. Public nvs-runtime tests and the repository's own tests

Same VM (from `clean-base`: Ubuntu 24.04.5, aarch64, Python 3.12.3), after `python3.12-venv` was installed, on the installed `SENSOS_HOME`
(Manifest v1, meaning-space-runtime `eadae4e86658`).

### 7.1 Public nvs-runtime tests

- `GemminAI/nvs-runtime` could be cloned without authentication; checkout `4e5cc638e7f0f756b921bfad596d09c29360a3a4`. Its `tests/` was copied out of
  the repository to `~/vt/tests`.
- The capture copy `s1-copy-window` (12 files) was copied from a capture folder on the Mac through the shared folder.
- A throwaway `HOME` held a symlink `GemminAI/meaning-space-runtime-wt-contract-ver` to the installed meaning-space-runtime checkout.
- Environment: `GATE_PY` (the installed venv's python), `SENSOS_TOOLS` (the `tools` directory of the acquired sensos), and `SENSOS_WINDOW_E2E_DIR`,
  `SENSOS_TOKEN_TEMPORAL_E2E_DIR`, `SENSOS_MM_E2E_DIR` (each `s1-copy-window`).
- `pytest` was installed into the installed venv. Running the Installer again in this `SENSOS_HOME` would fail check 1 (see section 7.2 of `2026-11-25-linux-cpu.md`).

First run: **38 passed, 2 failed**: `test_the_gate_passes_the_window_and_fails_a_different_producer` and
`test_geometry_is_measured_only_when_msr_imports`. Cause: the test helper `_producer_build()` runs `git -C <parent of the tests folder> rev-parse HEAD`, and the
parent was not a git repository (`not a git repository`). The previous record (`2026-11-25-linux-cpu.md`) does not state this prerequisite.

The `.git` of the cloned public repository (HEAD `4e5cc638...`, no `src`) was copied into the parent folder `~/vt`. Second run: **40 passed, 0 skipped, 0 failed**.
`test_geometry_is_measured_only_when_msr_imports` passed (1 passed; with MSR `ee26c7c` it failed with `TypeError`). `msr` resolved to the meaning-space-runtime
checkout under `$SENSOS_HOME`, and `nvs_runtime` to the venv's `site-packages`.

### 7.2 The repository's own tests

In a separate venv holding only `pytest`, the v1 branch (checkout of `e43a67b`) gave **57 passed, 0 skipped, 0 failed**: the 55 tests of the `feature/installer-linux-cpu`
branch plus the 2 tests of `test_core_v1_manifest.py` of the v1 branch.

## 8. Ubuntu 26.04 (an OS outside the declaration)

- Host: a different, newly created Parallels VM (not the `clean-base` VM): Ubuntu 26.04 LTS, aarch64, Python 3.14.4. `git` was absent and was installed with apt
  (git 2.53.0). `python3.14-venv` was not installed (`python3 -c "import ensurepip"` raised `ModuleNotFoundError`). Shared folders were visible.
- Delivery: bundle `sd-clean3.bundle` (sha256 `0e88ce03b3eaf0142826de59e36d443d875d4cb86231996db924863c2836bf27`), branch `manifest/core-v1-msr-eadae4e`,
  HEAD `135232cc912422d9338ef5451ce4dac0d6626fa8`.
- `--dry-run`: the plan of 12 steps, then `dependency check on this host: fail -- OS is ubuntu '26.04', manifest wants ubuntu 24.04; ensurepip is not available to this Python, ...;
  on Debian/Ubuntu install the package python3.12-venv ...`. Exit status 0.
- Real run: `STOP dependency check: OS is ubuntu '26.04', manifest wants ubuntu 24.04; ensurepip is not available ...`, exit 2. `SENSOS_HOME` was empty afterwards
  (no repository acquired, no venv).
- Observation 1: the message advised `python3.12-venv`, while this VM's Python is 3.14.4, so the package needed is `python3.14-venv`. This was changed
  (commit `4c02725`, see section 5).
- Observation 2: `--dry-run` ends with exit status 0 even when its dependency check reports `fail`. The behaviour was not changed; whether it should be is a design decision outside this record.
- Whether an installation succeeds on 26.04 was not tried, because check 2 stops on the OS. Installing there needs a Platform Manifest for 26.04 and a lock for Python 3.14;
  neither was made in this record.

## 9. Not verified

- Whether the Ubuntu explanation of a failed `venv` creation goes to stdout or stderr (defect 1). It does not reproduce once `python3.12-venv` is installed;
  on `clean-base` check 2 stops first, so the run never reaches the venv creation.
- The stop for a venv whose python has no pip (defect 2) was checked only by `tests/test_venv.py`, not on the VM: check 2 stops before that state can arise.
- A round trip in which the Gate child saves a 1.1.0 calibration together with its parent and reads it back.
- Whether the installed nvs-runtime wheel and the public `4e5cc638` are the same apart from documents and CI.
- Ubuntu 26.04 (Python 3.14.4): only the stop of check 2 was seen (section 8). An installation there was not tried.
- An installation on x86_64, and on Python 3.13 and 3.14.
- This verification used the v1 branch at `e43a67b`, which contains the branch of PR #1. PR #1 was merged into `main` as the merge commit `d0d75ad` (tree identical to `10f2ab8`); the commits recorded here are ancestors of `main`, so the SHAs are unchanged.
- This record does not declare v1 the official release.
