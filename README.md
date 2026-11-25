# sensos-deployment

Installer, validator and updater for a pinned set of SensOS components.

**Status: the linux-cpu Installer (Core only) has passed Acceptance checks 1-7 on Ubuntu 24.04 virtual machines (Parallels, aarch64, Python 3.12), including a clean VM. It has not been run on a physical machine, on x86_64 or on Python 3.13/3.14. Ubuntu 26.04 is outside the platform: the Installer stops at check 2. See [docs/installer.md](docs/installer.md) and the records in [docs/verification/](docs/verification/).**

## Scope

- Install a release of the SensOS Core components from a Release Manifest that pins each component to a commit.
- Validate the installed result against that manifest.
- Update to a newer manifest.

First target platform: `linux-cpu` (Core components only).

## Core Release Manifest

The official Core Release Manifest is v1: `manifests/core/core-release.v1.json`, release_id `core-2026.11.25-1`. The Installer uses it by default.
v0 (`core-release.v0.json`, release_id `core-2026.11.25-0`) is replaced by v1 and kept as history; it can still be read with `--core core/core-release.v0.json`.

## License

Apache-2.0. See [LICENSE](LICENSE).
