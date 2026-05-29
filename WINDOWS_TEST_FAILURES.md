# Windows Core Test Failures — Fix Guide (updated)

**Last Windows validation:** 2026-05-22 — **2nd pass after developer fixes**  
**Machine:** TOUR-JULIEN (Windows 11, Python 3.13.13, PowerShell 5.1)  
**Last verified count:** 97 previous · 43 fixed · 54 remaining · 1 new regression
**Current repo note (2026-05-29):** Category 1 environment isolation has since
landed in the root, core, and agi-env test fixtures. The total remaining count
below still reflects the last Windows run until the command below is rerun on
Windows.

Reproduce remaining failures:
```powershell
cd C:\Users\julie\agilab
uv --preview-features extra-build-dependencies run -p 3.13.13 --no-sync -m pytest `
  src/agilab/core/test src/agilab/core/agi-env/test -q 2>&1 | Tee-Object test_results.txt
```

---

## ✅ Fixed since last pass (68 tests)

The following test categories were resolved by the dev team:

| Category | Count |
|---|---|
| Path separator `\` vs `/` in assertions | 16 |
| `signal.SIGKILL` not on Windows | 2 |
| PATH export Linux format (`.local/bin:/usr/bin`) | 3 |
| `sshpass` not on Windows (one of two) | 1 |
| uv TOML paths with `\` (partial) | 4 |
| `deploy_local_worker` path issues (partial) | 7 |
| Virtualenv Windows layout (`.venv/Scripts`) | 7 |
| uv TOML paths with `\` (remaining) | 8 |
| Python subprocess exit-code fixtures | 4 |
| Linux-only feature guards | 6 |
| Miscellaneous | 10 |

---

## ❌ Remaining failures from last Windows run (54 tests)

---

### Category 1 — Env isolation: real `~/.agilab/.env` leaks (15 tests)

**Current repo status:** fixed in code, pending a fresh Windows rerun to remove
these failures from the verified count.

`AgiEnv` reads the real `C:\Users\julie\.agilab\.env`, real `.agilab-path`, and real `Path.home()` instead of the monkeypatched test values.

**Implemented fix:** autouse isolation fixtures now seed fake `HOME`,
`USERPROFILE`, `%LOCALAPPDATA%\agilab\.agilab-path`, posix `.agilab-path`, and
blank AGILAB env values in:

- `test/conftest.py`
- `src/agilab/core/test/conftest.py`
- `src/agilab/core/agi-env/test/conftest.py`

The root regression coverage is `test/test_root_test_environment_isolation.py`.

Original fix sketch:
```python
# src/agilab/core/agi-env/test/conftest.py
# src/agilab/core/test/conftest.py
import pytest, os
from pathlib import Path

@pytest.fixture(autouse=True)
def isolate_agilab_env(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake_home"
    (fake_home / ".agilab").mkdir(parents=True)
    (fake_home / ".agilab" / ".env").write_text(
        "AGI_CLUSTER_SHARE=\nAGI_LOCAL_SHARE=\nOPENAI_API_KEY=\n"
    )
    agilab_path_dir = Path(os.environ.get("LOCALAPPDATA", fake_home)) / "agilab"
    agilab_path_dir.mkdir(parents=True, exist_ok=True)
    (agilab_path_dir / ".agilab-path").write_text("")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("AGI_CLUSTER_SHARE", "")
    monkeypatch.setenv("AGI_LOCAL_SHARE", "")
    monkeypatch.setenv("APPS_REPOSITORY", "")
    monkeypatch.delenv("AGILAB_LOG_ABS", raising=False)
    yield
```

#### `test_blank_env_assignments_are_treated_as_unset_globally`
```
AssertionError: assert WindowsPath('C:/Users/julie/log')
                    == (fake_home / 'log')
 + where WindowsPath('C:/Users/julie/log') = AgiEnv.AGILAB_LOG_ABS
```

#### `test_app_settings_file_points_to_user_workspace_and_is_seeded`
```
AssertionError: assert WindowsPath('C:/Users/julie/.agilab/apps/mycode_project/app_settings.toml')
                    == fake_home / '.agilab/apps/mycode_project/app_settings.toml'
 + where ... = AgiEnv.app_settings_file
```

#### `test_read_agilab_path_active_and_home_helpers`
```
AssertionError: assert WindowsPath('C:/Users/julie/agilab/src/agilab')
                    == fake_install_path
 + where WindowsPath('C:/Users/julie/agilab/src/agilab') = AgiEnv.read_agilab_path()
```
Reads real `C:\Users\julie\AppData\Local\agilab\.agilab-path`.

#### `test_cluster_enabled_raises_when_app_src_invalid`
```
Failed: DID NOT RAISE <class 'RuntimeError'>
```
Expected RuntimeError because cluster share is invalid — but the real `AGI_CLUSTER_SHARE=C:\Users\julie\clustershare` from `~/.agilab/.env` satisfies the check unexpectedly.

#### `test_cluster_share_same_as_local_share_raises`
#### `test_cluster_enabled_from_process_env_when_app_src_invalid` *(fixed in run 4, regressed)*
#### `test_cluster_enabled_from_apps_repository_when_app_src_invalid` *(fixed in run 4, regressed)*
```
RuntimeError: Cluster mode requires AGI_CLUSTER_SHARE to be mounted and writable.
Configured AGI_CLUSTER_SHARE='C:\\Users\\julie\\clustershare' is not usable;
env=C:\Users\julie\.agilab\.env
  at: runtime_bootstrap_support.py:135 in resolve_share_runtime_config
```

#### `test_init_worker_env_flag_requires_app_and_sets_skip_repo_links`
```
Failed: DID NOT RAISE <class 'ValueError'>
```

#### `test_init_worker_install_type_detects_wenv_apps_path`
```
RuntimeError: Cluster mode requires AGI_CLUSTER_SHARE to be mounted and writable.
  at: runtime_bootstrap_support.py:135
```

#### `test_init_prefers_worker_sources_already_staged_in_wenv`
```
AssertionError: assert WindowsPath('C:/.../test_tmp/repo-apps/demo_project/src')
                    == WindowsPath('C:/Users/julie/wenv/demo_worker') / 'src'
```
`wenv_abs` resolves to the real machine path `C:\Users\julie\wenv\`.

#### `test_share_root_resolution_worker_uses_runtime_home_and_init_honours_share_override`
Fails because real home paths leak into share resolution logic.

#### `test_load_last_active_app_prefers_global_state_file`
```
AssertionError: assert None == WindowsPath('C:/.../test_tmp/demo_app')
 + where None = ui_support.load_last_active_app()
```
Reads the real global state file instead of the test's isolated one.

#### `test_ui_support_global_state_and_last_active_app_round_trip`
```
AssertionError: assert {} == {'last_active_app': 'C:\\...\\test_tmp\\demo_project'}
```

#### `test_init_dataset_stamp_probe_failure_appends_sys_path_and_sets_windows_export_bin`
#### `test_init_missing_worker_and_empty_projects_log_before_invalid_scheduler`
#### `test_init_preserves_existing_dataset_without_stamp_and_uses_windows_export_bin`
```
# All three: AgiEnv reads real ~/.agilab/.env before monkeypatch applies
```

---

### Category 2 — `.venv/bin` vs `.venv/Scripts` — fixed in current repo (7 tests)

Status: fixed in current repository; pending live Windows rerun.

The project-venv install path now uses the platform-aware virtualenv helpers
instead of hard-coding the POSIX `.venv/bin/python` layout. The regression slice
also includes a simulated Windows assertion that resolves
`.venv/Scripts/python.exe`.

Validation evidence from macOS with Windows-path simulation:

```bash
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_install_into_project_venv_skips_cached_editable_metadata \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_install_into_project_venv_invalidates_editable_metadata_cache \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_install_many_into_project_venv_skips_cached_editables \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_install_many_into_project_venv_reinstalls_only_missing_editable_proofs \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_project_venv_python_uses_windows_layout \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_deploy_local_worker_install_type_zero_non_source_covers_dependency_flow \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_deploy_local_worker_install_type_zero_uses_resource_fallbacks_and_free_threaded_python \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_deploy_local_worker_rapids_reuses_cli_and_falls_back_from_localhost_ssh
```

Result: `8 passed`.

---

### Category 3 — uv TOML source paths written with `\` — fixed in current repo (8 tests)

Status: fixed in current repository; pending live Windows rerun.

The worker pyproject rewrite and manager sync overlay paths now keep `uv` source
paths TOML-safe by normalizing local relative source paths to POSIX separators.

Validation evidence from macOS with Windows-path simulation:

```bash
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' \
  src/agilab/core/test/test_agi_distributor_uv_source_support.py::test_rewrite_uv_sources_paths_rewrites_invalid_entries_and_logs \
  src/agilab/core/test/test_agi_distributor_uv_source_support.py::test_rewrite_uv_sources_paths_for_copied_pyproject_rewrites_invalid_paths_and_keeps_valid_ones \
  src/agilab/core/test/test_agi_distributor_uv_source_support.py::test_rewrite_uv_sources_paths_for_copied_pyproject_handles_missing_files_and_relpath_failures \
  src/agilab/core/test/test_agi_distributor_uv_source_support.py::test_rewrite_uv_sources_paths_handles_non_table_sources_and_noop_rewrites \
  src/agilab/core/test/test_agi_distributor_uv_source_support.py::test_iter_local_uv_source_paths_handles_missing_invalid_and_absolute_entries \
  src/agilab/core/test/test_agi_distributor_uv_source_support.py::test_missing_uv_source_paths_skips_blank_non_dict_and_absolute_existing_entries \
  src/agilab/core/test/test_agi_distributor_uv_source_support.py::test_stage_uv_sources_for_copied_pyproject_falls_back_when_relpath_fails \
  src/agilab/core/test/test_agi_distributor_deployment_local_support.py::test_write_manager_sync_overlay_normalizes_paths_and_skips_invalid_entries
```

Result: `8 passed`.

---

### Category 4 — `cmd /c exit N` unreliable exit code — fixed in current repo (4 tests)

Status: fixed in current repository; pending live Windows rerun.

The affected `agi-env` execution-support tests now use deterministic Python
one-liners for nonzero subprocess exits instead of relying on `cmd /c exit N`.

Validation evidence from macOS:

```bash
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' \
  src/agilab/core/agi-env/test/test_agi_env.py::test_run_nonzero_command_does_not_log_traceback_for_runtime_error \
  src/agilab/core/agi-env/test/test_agi_env.py::test_run_nonzero_command_prefers_last_subprocess_line_in_runtime_error \
  src/agilab/core/agi-env/test/test_agi_env.py::test_run_async_and_run_bg_cover_success_and_nonzero_paths \
  src/agilab/core/agi-env/test/test_agi_env.py::test_run_async_nonzero_command_prefers_last_subprocess_line_in_runtime_error
```

Result: `4 passed, 1 warning`.

---

### Category 5 — Linux-only features not guarded — fixed in current repo (6 tests)

Status: fixed in current repository; pending live Windows rerun.

The procfs/fstab, POSIX mount-helper, SQLite URI, Windows link-helper, and
remote `sshfs` cases now have current regression coverage. The remote `sshfs`
test is guarded for Windows because the mount path depends on POSIX shell tools.

Validation evidence from macOS:

```bash
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' \
  src/agilab/core/agi-env/test/test_share_mount_support.py::test_fstab_bind_source_for_target_handles_oserror_and_parses_bind \
  src/agilab/core/agi-env/test/test_share_mount_support.py::test_share_mount_support_path_and_mount_helpers \
  src/agilab/core/agi-env/test/test_pagelib.py::test_mount_helpers_cover_proc_fstab_and_shell_fallbacks \
  src/agilab/core/agi-env/test/test_pagelib.py::test_sqlite_uri_for_path_covers_posix_and_windows_formats \
  src/agilab/core/agi-env/test/test_agi_env.py::test_create_symlink_and_windows_link_helpers_log_expected_paths \
  src/agilab/core/test/test_agi_distributor_deployment_remote_support.py::test_deploy_remote_worker_mounts_scheduler_cluster_share_with_sshfs
```

Result: `6 passed`.

---

### Category 6 — mlflow file locking on Windows (1 test)

Windows does not allow renaming a file held open by another process.

**Fix in `mlflow_store.py` `_move_mlflow_sqlite_backend_files`:**
```python
import shutil, sys, os
if sys.platform == "win32":
    shutil.copy2(src, dst)
    os.unlink(src)
else:
    os.rename(src, dst)
```

#### `test_ensure_mlflow_backend_ready_resets_unknown_alembic_revision`
```
PermissionError: [WinError 32] Le processus ne peut pas accéder au fichier
car ce fichier est utilisé par un autre processus:
'C:\...\mlflow.db' -> 'C:\...\mlflow.schema-reset-20260522_113825.db'
  at: mlflow_store.py:435 in _move_mlflow_sqlite_backend_files
```

---

### Category 7 — Polars CSV read fails: non-UTF-8 encoding (2 tests)

**Current repo status:** fixed in code, pending a fresh Windows rerun to remove
these failures from the verified count. `capacity_support.update_capacity` now
opens the capacity CSV with `encoding="utf-8"` and `newline=""`, with regression
coverage in `test_update_capacity_writes_utf8_capacity_csv_for_polars`.

On Windows, the system default encoding for file writes can be CP1252 (French locale). When capacity data is written as CSV and read back by polars, the non-UTF-8 content triggers an error.

**Fix in the CSV write path in `capacity_support.py`:** always write UTF-8:
```python
with open(path, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    ...
```
And in the polars read: `pl.read_csv(path, encoding="utf8")` (already the default, but verify no `open()` wrapper uses system encoding).

#### `test_update_capacity_success_and_guard_paths`
```
polars.exceptions.InvalidOperationError: file encoding is not UTF-8
  at: polars/lazyframe/frame.py:3910
```

#### `test_update_capacity_adjusts_against_other_workers`
```
polars.exceptions.InvalidOperationError: file encoding is not UTF-8
  at: polars/lazyframe/frame.py:3910
```

---

### Category 8 — `prepare_local_env` / self-update path (3 tests + 1 regression)

**Current repo status:** fixed in code, pending a fresh Windows rerun to remove
these failures from the verified count. The focused local validation passes for:

- `test_prepare_local_env_online_ignores_uv_self_update_failure`
- `test_prepare_local_env_windows_skips_self_update_when_standalone_uv_missing`
- `test_prepare_local_env_windows_handles_empty_uv_and_self_update_failure`

#### ⚠️ NEW REGRESSION: `test_prepare_local_env_online_ignores_uv_self_update_failure`
```
AssertionError  (no E-line captured — run pytest -vv to see full diff)
  at: test_agi_distributor_deployment_prepare_support.py:234
```
Was passing in the previous run. This is a regression introduced by the recent fixes. The test checks that `prepare_local_env` continues normally when `uv self update` raises a `RuntimeError("Self-update is only available for standalone installs")`. The assertion failure suggests the error is no longer being swallowed — either the exception handling was tightened, or the detection condition changed.

**Immediate action:** run `pytest -vv test_agi_distributor_deployment_prepare_support.py::test_prepare_local_env_online_ignores_uv_self_update_failure` and compare with the previous version of `prepare_local_env`.

#### `test_prepare_local_env_windows_skips_self_update_when_standalone_uv_missing`
#### `test_prepare_local_env_windows_handles_empty_uv_and_self_update_failure`
```
# No assertion captured — run with pytest -vv
# Both test the Windows-specific code path where uv self-update is attempted
# via the standalone binary at ~/.local/bin/uv.exe
```

---

### Category 9 — `sshpass` not on Windows (1 test)

**Current repo status:** fixed in code, pending a fresh Windows rerun to remove
this failure from the verified count. The transport test now has a Windows
skip marker and accepts the production `scp` fallback on Windows. Focused local
validation passes for `test_send_file_remote_success_and_command_construction`.

#### `test_send_file_remote_success_and_command_construction`
```
AssertionError: assert 'scp' == 'sshpass'
  - sshpass
  + scp
```
On Windows, `sshpass` is unavailable; production code correctly falls back to `scp`, but the test expects `sshpass` unconditionally.

**Fix:** `@pytest.mark.skipif(sys.platform == "win32", reason="sshpass not available on Windows")`

---

### Tests needing `pytest -vv` (no assertion captured, 7 remaining)

| Test | File | Probable category |
|---|---|---|
| `test_baseworker_setup_data_directories_falls_back_when_output_unavailable` | `test_base_worker.py` | Cat 1 (path sep) |
| `test_baseworker_setup_data_directories_without_env_falls_back_to_home` | same | Cat 1 |
| `test_execute_initialized_worker_plan_expands_payloads_runs_worker_and_logs_completion` | `test_base_worker_execution_support.py` | Cat 1 |
| `test_log_worker_plan_progress_reports_counts_and_returns_plan_batch_count` | same | Cat 1 |
| `test_measure_worker_write_speed_writes_probe_file_and_removes_it` | same | Cat 1 |
| `test_run_local_covers_debug_and_script_execution_paths` | `test_agi_distributor_runtime_distribution_support.py` | Unknown |
| `test_post_try_link_dir_returns_false_on_setup_and_symlink_failures` | `test_agi_dispatcher_scripts.py` | Symlink |

---

## Summary

| # | Category | Count | Status | Primary fix location |
|---|---|---|---|---|
| 1 | Env isolation (`~/.agilab/.env` leaks) | 15 | ✅ Fixed in current repo; rerun Windows to verify count | `test/conftest.py`, `src/agilab/core/test/conftest.py`, `src/agilab/core/agi-env/test/conftest.py` |
| 2 | `.venv/bin` vs `.venv/Scripts` | 7 | ✅ Fixed in current repo; rerun Windows to verify count | `deployment_local_support.py`, `process_support.py` |
| 3 | uv TOML paths with `\` | 8 | ✅ Fixed in current repo; rerun Windows to verify count | `uv_source_support.py` |
| 4 | `cmd /c exit N` unreliable exit code | 4 | ✅ Fixed in current repo; rerun Windows to verify count | `src/agilab/core/agi-env/test/test_agi_env.py` |
| 5 | Linux-only (fstab, PosixPath, sshfs) | 6 | ✅ Fixed in current repo; rerun Windows to verify count | `share_mount_support.py`, `test_pagelib.py`, `test_agi_env.py`, `test_agi_distributor_deployment_remote_support.py` |
| 6 | mlflow file locking | 1 | ❌ Open | `mlflow_store.py` copy+delete on Windows |
| 7 | Polars CSV non-UTF-8 encoding | 2 | ✅ Fixed in current repo; rerun Windows to verify count | `capacity_support.py`, `test_agi_distributor_capacity_support.py` |
| 8 | `prepare_local_env` self-update | 3 | ✅ Fixed in current repo; rerun Windows to verify count | `deployment_prepare_support.py`, `test_agi_distributor_deployment_prepare_support.py` |
| 9 | `sshpass` not on Windows | 1 | ✅ Fixed in current repo; rerun Windows to verify count | `test_agi_distributor_transport_support.py` |
| — | Needs `pytest -vv` | 7 | ❓ Unknown | Run targeted to diagnose |

**Recommended priority:** rerun the Windows command above to refresh the verified
remaining count after the environment-isolation, virtualenv layout, uv TOML path,
Python subprocess exit fixture, Linux-only guard, capacity CSV encoding,
prepare_local_env self-update, and sshpass test fixes. Then prioritize any
still-failing Windows categories from the refreshed run.
