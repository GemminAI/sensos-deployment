# sensos-deployment

Installer, validator and updater for a pinned set of SensOS components. This README is the source for installing the current release; [docs/installer.md](docs/installer.md) describes what the Installer does in detail.

## Status

The `linux-cpu` Installer (Core only) has passed Acceptance checks 1-7 on Ubuntu 24.04 virtual machines (aarch64, Python 3.12), including a clean VM that started without git or the venv package.

Not run: a physical machine, x86_64, Python 3.13 and 3.14 (the Installer accepts 3.12-3.14, but only 3.12 was tried). Ubuntu 26.04 is outside the platform: the Installer stops at check 2 (Dependency Check). The records are in [docs/verification/](docs/verification/).

## What this installs

Core Release Manifest v1, release_id `core-2026.11.25-1` (`manifests/core/core-release.v1.json`).

- Four repositories, each pinned to a commit: `sensos`, `hekb-vnext`, `meaning-mapper`, `meaning-space-runtime`. The Installer requires the commit to be on `origin/main` and `HEAD` to equal it.
- Two packages from PyPI, pinned by version and wheel sha256: `nvs-runtime` 1.0.0 and `nvs-observation` 0.1.0.dev0.
- All other Python dependencies, pinned by sha256 in `manifests/platforms/linux-cpu.lock` and installed with `pip install --require-hashes`.

Not in this release: observation (Hidden State capture), the Validator and the Updater.

## Requirements

- Ubuntu 24.04, x86_64 or aarch64.
- Python 3.12-3.14 with the venv package (on Ubuntu 24.04: `python3.12-venv`), and git.
- Network access to github.com and pypi.org.
- No GPU. The Installer writes only under `SENSOS_HOME` (default `~/.sensos`).

## Install

1. Install the prerequisites:

   ```bash
   sudo apt-get update && sudo apt-get install -y git python3.12-venv
   ```

2. Get the Installer:

   ```bash
   git clone https://github.com/GemminAI/sensos-deployment.git
   cd sensos-deployment
   ```

3. Dry run. It prints the steps and the result of the dependency check on this host, and writes nothing:

   ```bash
   python3 -m installers.install --dry-run
   ```

4. Install:

   ```bash
   python3 -m installers.install
   ```

5. Check the result. A successful install ends with Acceptance checks 1-7 passing, exit status 0, and a line `report: <path>`. The Deployment Report is `<SENSOS_HOME>/reports/core-2026.11.25-1/deployment.json`.

Running the Installer again is safe: it reuses what is already there and writes its report under `redeploy/`. Nothing is deleted or overwritten. To use another location, set `SENSOS_HOME` before running.

## Where files go

```
<SENSOS_HOME>/releases/<release_id>/src/<repo>      checkouts (detached at the manifest commit)
<SENSOS_HOME>/releases/<release_id>/venv            dedicated environment
<SENSOS_HOME>/stores/gen-<catalogue sha256>/        Formal Store (+ declaration.json)
<SENSOS_HOME>/acceptance/<release_id>/<time>/store  throwaway store used by Acceptance check 7
<SENSOS_HOME>/reports/<release_id>/deployment.json  Deployment Report (written once; later runs -> redeploy/, failures -> failed/)
```

## Exit status and common stops

| Exit | Meaning |
|---|---|
| 0 | Installed, or `--dry-run` finished. |
| 1 | The installation stopped, or an Acceptance check failed. A report is written. |
| 2 | Refused before anything was written: a bad or tampered manifest, or the dependency check (check 2) failed on this host. |

`--dry-run` exits 0 even when the dependency check on this host fails. Read the line `dependency check on this host:` it prints; a real install on that host would stop with exit 2.

| Message | Cause and fix |
|---|---|
| `ensurepip is not available to this Python ... install the package python3.12-venv` | The venv package is missing. Install the package the message names (the Installer does not install it), then run again. |
| `OS is <id> '<version>', manifest wants ubuntu 24.04` | Wrong OS or version (Ubuntu 26.04 stops here too). Use Ubuntu 24.04. |
| `Python <version> is outside 3.12-3.14` | Use a Python in that range. |
| `git is not on PATH` | `sudo apt-get install -y git`. |
| apt: `Release file ... is not valid yet` (printed by apt, not by the Installer) | The system clock is behind. Run `sudo timedatectl set-ntp true`, wait for the clock to sync, then retry `apt-get update`. |

## Core Release Manifest

The official Core Release Manifest is v1: `manifests/core/core-release.v1.json`, release_id `core-2026.11.25-1`. The Installer uses it by default.
v0 (`core-release.v0.json`, release_id `core-2026.11.25-0`) is replaced by v1 and kept as history; it can still be read with `--core core/core-release.v0.json`.
Each manifest's sha256 is listed in `manifests/SHA256SUMS`, and the Installer verifies it before it does anything.

## Scope

- Install a release of the SensOS Core components from a Release Manifest that pins each component to a commit.
- Validate the installed result against that manifest.
- Update to a newer manifest.

First target platform: `linux-cpu` (Core components only). Only the Installer exists today.

## Sources

- [docs/installer.md](docs/installer.md): what the Installer does, step by step, and what is not implemented or not verified.
- [docs/verification/](docs/verification/): records of the runs on virtual machines.

## License

Apache-2.0. See [LICENSE](LICENSE).
