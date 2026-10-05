# AGILAB native Windows core qualification — 2026-10-05

The candidate based on `dcaf0ad310b67bfddd7a10b51623f4a37c004e07` with the
prospective UNC formatting correction below passed the native Windows core
profile and package preinit first-proof. This checkpoint binds the executed
source hashes. Independent review and publication are separate checkpoints.

The regression history remains in [WINDOWS_TEST_FAILURES.md](WINDOWS_TEST_FAILURES.md).
The core command follows
[windows-core-tests.yml](.github/workflows/windows-core-tests.yml).

## Environment and scope

- Native Windows 11, build `10.0.26200`, x64.
- CPython `3.13.11`, uv `0.10.7`, pytest `9.1.1`, pytest-asyncio `1.4.0`,
  pytest-cov `7.1.0`.
- Editable `agi-env`, `agi-node`, `agi-cluster`, `agi-core` and `agi-web`
  from the isolated source snapshot; core distributions report `2026.10.4`
  or `2026.10.04`.
- Source, cache, final-lane temporary files and logs use the qualification
  workspace. `VIRTUAL_ENV` is cleared, background services are disabled and
  the API credential is the synthetic value used by the official profile.
- Scope: manager/scheduler core tests and one package preinit smoke step.
  Live remote workers, SSHFS and live LAN-cluster execution are outside this
  checkpoint. First-proof used `with_install=false` and `with_ui=false`.

## Failure, correction and regression

The initial core lane repeatedly waited in Windows `ntpath._readlink_deep`:
`BaseWorker.normalize_dataset_path` constructed a loopback UNC mapping and
passed it to `normalize_path`, whose `Path.resolve` probed SMB before
`_try_windows_net_use` checked whether mapping credentials existed. Native
stack captures reproduced this wait in two data-directory tests.

The two prospective mapping constructions in `normalize_dataset_path` and
`expand_and_join` now use `PureWindowsPath` formatting. Local dataset
resolution and the shared `normalize_path` helper keep their existing
filesystem behavior. The regression rejects filesystem resolution of the
constructed UNC while requiring local resolution and the expected mapping.

| Check | Native result |
| --- | --- |
| Regression against the preimage | 2 failed in 0.36 s, both at the UNC-resolution guard |
| Complete `test_base_worker.py` after correction | 69 passed in 0.64 s |
| Initial complete core lane | Interrupted after 915.066 s; retained as an incomplete, failed attempt |
| Corrected complete core lane | 4,000 passed, 26 skipped, 0 failures/errors; 4,026 JUnit cases |
| Corrected core duration | 212.490 s, measured with a monotonic clock |
| Strict warning audit | 0 warnings across the core log and source-package install stdout/stderr |
| First-proof | `success=true`, `within_target=true`, 1/1 step, 0.703 s against a 60 s target |
| User path marker | Initially absent and absent after the restoration check |

The official core profile installs the core distributions. Before first-proof,
the base `agilab` distribution and its declared base dependencies were installed
editable from the same source into the exact same Python interpreter. This
provided the package metadata required by the preinit smoke.

## Exclusion audit

All 26 exclusions were matched to their existing source guards:

| Existing guard category | Cases |
| --- | ---: |
| POSIX/platform contracts: SIGKILL, permissions/ownership, account database, process groups, mount parsing, named pipes and POSIX venv layout | 20 |
| Case-sensitive-volume assertions on the case-insensitive temporary volume | 2 |
| Live LAN-cluster opt-in | 2 |
| Remote-worker SSHFS/POSIX-shell mounting | 1 |
| `sshpass` availability | 1 |

The two new UNC regression cases executed and passed. The retained skip audit
includes every test identifier, reason and source-guard context.

## Source identity

The Windows snapshot retained the base HEAD above and exactly the two intended
tracked modifications. The final native hashes matched the reviewed candidate
files, and the original macOS checkout's corresponding source bytes matched
the preimages.

| File | Preimage SHA-256 | Qualified candidate SHA-256 |
| --- | --- | --- |
| `src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker.py` | `f748ca67965a462612d9f9a4eca070bb531a4ebd2de3bf574765cf22a68e322a` | `2652f239ede33e978bd171d63523510e9c0fca376dd6d6cbf041fc23f38e6390` |
| `src/agilab/core/test/test_base_worker.py` | `bb5b6645833b57f4b02e6bac49c2b07bfc2c63a3613d55f69703bbe716eaa230` | `36a432a511e18c7ed0abdf6e80b6dadf11cb4d68202a09b695e6e998ee4bf6e6` |

## Retained evidence

The operator-held archive
`agilab_windows_native_core_qualification_evidence_20261005.zip` contains 87
files: full stdout/stderr, JUnit, strict warning reports, first-proof JSON,
source/marker verification, native stack diagnostics, red/green regression
receipts, scripts and a per-file checksum inventory.

Archive SHA-256:
`3ea413125ac2cbd5f74aacd2e9b6b029e9206010d4290207485b891694c4393c`.

| Final-lane artifact | SHA-256 |
| --- | --- |
| `windows-core-tests.xml` | `8ccdd848fba24c63de3d9c46747b11bdaa8ba246f3b080fbf83edea509fa612a` |
| `windows-core-tests.txt` | `b1318d78360e7202326440d81376cbf8cee8f1ec3d8c03345237da5aeaad68af` |
| `windows-core-warning-report.json` | `93f83bda36a92587fbe192c0ea3899d71987c685c45b73877456d8e6e4ff155e` |
| `agilab_windows_first_proof_patched_20261005.stdout.log` | `ad6361d71005dd705ec9390e4b678b9957f14722a6e9c2b5ba8f252b96923d08` |

Every stage stream hash and every archived file hash was verified after
retrieval. Cross-host wall-clock stamps show clock skew; durations use the
recorded monotonic measurements.

## Reproduction profile

Set `AGILAB_DISABLE_BACKGROUND_SERVICES=1`, the official synthetic
`OPENAI_API_KEY`, and a qualification-local `AGILAB_LOG_ABS`, `UV_CACHE_DIR`,
`TEMP` and `TMP`. Clear `VIRTUAL_ENV`; select the installed Python 3.13.

```powershell
uv --preview-features extra-build-dependencies run --no-project --python 3.13 `
  --with-editable ./src/agilab/core/agi-env `
  --with-editable ./src/agilab/core/agi-node `
  --with-editable ./src/agilab/core/agi-cluster `
  --with-editable ./src/agilab/core/agi-core `
  --with sqlalchemy --with-editable ./src/agilab/lib/agi-web `
  --with fastparquet --with pytest --with pytest-asyncio --with pytest-cov `
  python -m pytest -q -o addopts= --import-mode=importlib `
  --junitxml test-results/windows-core-tests.xml `
  src/agilab/core/test src/agilab/core/agi-env/test src/agilab/core/agi-cluster/test
```

The archived orchestration preserves stdout/stderr separately, audits warnings,
installs the base source distribution into that same interpreter, and invokes
`python -m agilab.lab_run first-proof --json --no-manifest --max-seconds 60`.
It preserves the user's `.agilab-path` bytes or absence in `try/finally` because
successful first-proof also writes that marker with `--no-manifest`.
