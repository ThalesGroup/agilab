# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from pathlib import Path
import sqlite3
import subprocess
import sys


def get_mlflow_module():
    try:
        import mlflow  # type: ignore
    except ImportError:
        return None
    return mlflow


def resolve_mlflow_tracking_dir(env, *, home_factory=Path.home, path_cls=Path) -> Path:
    home_abs = path_cls(getattr(env, "home_abs", home_factory())).expanduser()
    tracking_value = getattr(env, "MLFLOW_TRACKING_DIR", None)
    if tracking_value:
        tracking_dir = path_cls(tracking_value).expanduser()
        if not tracking_dir.is_absolute():
            tracking_dir = home_abs / tracking_dir
    else:
        tracking_dir = home_abs / ".mlflow"
    return tracking_dir.resolve()


def resolve_mlflow_backend_db(tracking_dir: Path, *, default_db_name: str) -> Path:
    return tracking_dir / default_db_name


def resolve_mlflow_artifact_dir(tracking_dir: Path, *, default_artifact_dir: str) -> Path:
    artifact_dir = tracking_dir / default_artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir.resolve()


def sqlite_uri_for_path(db_path: Path, *, os_name: str, path_cls=Path) -> str:
    resolved = path_cls(db_path).expanduser().resolve()
    posix_path = resolved.as_posix()
    if os_name == "nt":
        return f"sqlite:///{posix_path}"
    return f"sqlite:////{posix_path.lstrip('/')}"


def legacy_mlflow_filestore_present(
    tracking_dir: Path,
    *,
    default_db_name: str,
    default_artifact_dir: str,
) -> bool:
    if not tracking_dir.exists():
        return False
    for child in tracking_dir.iterdir():
        if child.name in {default_db_name, default_artifact_dir}:
            continue
        if child.name == ".trash" or child.name == "meta.yaml":
            return True
        if child.is_dir() and child.name.isdigit():
            return True
    return False


def sqlite_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def repair_mlflow_default_experiment_db(
    db_path: Path,
    *,
    default_experiment_name: str,
    sqlite_identifier_fn,
    artifact_uri: str | None = None,
    connect_fn=sqlite3.connect,
) -> bool:
    if not db_path.exists():
        return False

    try:
        conn = connect_fn(str(db_path))
        try:
            table_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "experiments" not in table_names:
                return False

            experiment_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()
            }
            if {"experiment_id", "name"} - experiment_cols:
                return False

            where_clause = "name = ?"
            params = [default_experiment_name]
            if "workspace" in experiment_cols:
                where_clause += " AND workspace = ?"
                params.append("default")

            default_row = conn.execute(
                f"SELECT experiment_id FROM experiments WHERE {where_clause} ORDER BY experiment_id LIMIT 1",
                params,
            ).fetchone()
            if default_row is None:
                return False

            current_id = int(default_row[0])
            zero_row = conn.execute(
                "SELECT experiment_id, name FROM experiments WHERE experiment_id = 0"
            ).fetchone()

            repaired = False
            if current_id != 0 and zero_row is None:
                conn.execute("PRAGMA foreign_keys=OFF")
                for table_name in table_names:
                    if table_name.startswith("sqlite_"):
                        continue
                    cols = {
                        row[1]
                        for row in conn.execute(
                            f"PRAGMA table_info({sqlite_identifier_fn(table_name)})"
                        ).fetchall()
                    }
                    if "experiment_id" not in cols:
                        continue
                    conn.execute(
                        f"UPDATE {sqlite_identifier_fn(table_name)} SET experiment_id = 0 WHERE experiment_id = ?",
                        (current_id,),
                    )
                repaired = True

            if artifact_uri and "artifact_location" in experiment_cols:
                conn.execute(
                    "UPDATE experiments SET artifact_location = ? WHERE experiment_id = 0",
                    (artifact_uri,),
                )
                repaired = True

            if repaired:
                conn.commit()
            return repaired
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def ensure_mlflow_sqlite_schema_current(
    db_path: Path,
    *,
    checked_uris: set[str],
    sqlite_uri_for_path_fn,
    schema_reset_markers: tuple[str, ...],
    reset_backend_fn,
    connect_fn=sqlite3.connect,
    run_cmd=subprocess.run,
    sys_executable: str = sys.executable,
) -> None:
    if not db_path.exists():
        return

    db_uri = sqlite_uri_for_path_fn(db_path)
    if db_uri in checked_uris:
        return

    try:
        conn = connect_fn(db_path)
        try:
            has_alembic_version = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        has_alembic_version = None
    if not has_alembic_version:
        return

    result = run_cmd(
        [sys_executable, "-m", "mlflow", "db", "upgrade", db_uri],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if any(marker in details for marker in schema_reset_markers):
            reset_backend_fn(db_path)
            return
        raise RuntimeError(
            "Failed to upgrade the local MLflow SQLite schema. "
            f"Database: {db_path}. {details}"
        )
    checked_uris.add(db_uri)


def _migrate_legacy_mlflow_filestore_if_needed(
    tracking_dir: Path,
    *,
    db_path: Path,
    legacy_mlflow_filestore_present_fn,
    sqlite_uri_for_path_fn,
    run_cmd=subprocess.run,
    sys_executable: str = sys.executable,
) -> None:
    if db_path.exists() or not legacy_mlflow_filestore_present_fn(tracking_dir):
        return

    target_uri = sqlite_uri_for_path_fn(db_path)
    result = run_cmd(
        [
            sys_executable,
            "-m",
            "mlflow",
            "migrate-filestore",
            "--source",
            str(tracking_dir),
            "--target",
            target_uri,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "Failed to migrate the legacy MLflow file store to SQLite. "
            f"Source: {tracking_dir}. {details}"
        )


def reset_mlflow_sqlite_backend(
    db_path: Path,
    *,
    checked_uris: set[str],
    sqlite_uri_for_path_fn,
    timestamp_fn,
) -> Path | None:
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        return None

    db_uri = sqlite_uri_for_path_fn(db_path)
    checked_uris.discard(db_uri)
    timestamp = timestamp_fn()
    backup_path = db_path.with_name(f"{db_path.stem}.schema-reset-{timestamp}{db_path.suffix}")
    for sidecar in ("", "-shm", "-wal", "-journal"):
        candidate = Path(f"{db_path}{sidecar}")
        if candidate.exists():
            candidate.replace(Path(f"{backup_path}{sidecar}"))
    return backup_path


def ensure_mlflow_backend_ready(
    tracking_dir: Path,
    *,
    resolve_mlflow_backend_db_fn,
    legacy_mlflow_filestore_present_fn,
    sqlite_uri_for_path_fn,
    ensure_mlflow_sqlite_schema_current_fn,
    resolve_mlflow_artifact_dir_fn,
    repair_mlflow_default_experiment_db_fn,
    run_cmd=subprocess.run,
    sys_executable: str = sys.executable,
) -> str:
    db_path = resolve_mlflow_backend_db_fn(tracking_dir)
    _migrate_legacy_mlflow_filestore_if_needed(
        tracking_dir,
        db_path=db_path,
        legacy_mlflow_filestore_present_fn=legacy_mlflow_filestore_present_fn,
        sqlite_uri_for_path_fn=sqlite_uri_for_path_fn,
        run_cmd=run_cmd,
        sys_executable=sys_executable,
    )
    ensure_mlflow_sqlite_schema_current_fn(db_path)
    artifact_uri = resolve_mlflow_artifact_dir_fn(tracking_dir).as_uri()
    repair_mlflow_default_experiment_db_fn(db_path, artifact_uri=artifact_uri)
    return sqlite_uri_for_path_fn(db_path)


def _is_existing_experiment_conflict(
    exc: Exception,
    *,
    get_experiment_fn,
    default_experiment_name: str,
) -> bool:
    refreshed = (
        get_experiment_fn(default_experiment_name)
        if callable(get_experiment_fn)
        else None
    )
    if refreshed is not None:
        return True
    return "already exists" in str(exc).lower()


def _is_schema_reset_error(
    exc: Exception,
    *,
    schema_reset_markers: tuple[str, ...],
) -> bool:
    details = str(exc)
    return (
        "Detected out-of-date database schema" in details
        or any(marker in details for marker in schema_reset_markers)
    )


def _create_default_experiment_if_missing(
    mlflow,
    *,
    default_experiment_name: str,
    artifact_uri: str,
) -> None:
    experiment = None
    get_experiment = getattr(mlflow, "get_experiment_by_name", None)
    if callable(get_experiment):
        experiment = get_experiment(default_experiment_name)
    if experiment is not None:
        return

    create_experiment = getattr(mlflow, "create_experiment", None)
    if callable(create_experiment):
        try:
            create_experiment(default_experiment_name, artifact_location=artifact_uri)
        except Exception as exc:
            if not _is_existing_experiment_conflict(
                exc,
                get_experiment_fn=get_experiment,
                default_experiment_name=default_experiment_name,
            ):
                raise


def _activate_default_mlflow_experiment(
    mlflow,
    *,
    backend_uri: str,
    default_experiment_name: str,
    artifact_uri: str,
) -> None:
    mlflow.set_tracking_uri(backend_uri)
    _create_default_experiment_if_missing(
        mlflow,
        default_experiment_name=default_experiment_name,
        artifact_uri=artifact_uri,
    )
    mlflow.set_experiment(default_experiment_name)


def _activate_default_mlflow_experiment_with_schema_retry(
    mlflow,
    *,
    tracking_dir: Path,
    artifact_uri: str,
    db_path: Path,
    ensure_mlflow_backend_ready_fn,
    reset_mlflow_sqlite_backend_fn,
    default_experiment_name: str,
    schema_reset_markers: tuple[str, ...],
) -> str:
    for attempt in range(2):
        backend_uri = ensure_mlflow_backend_ready_fn(tracking_dir)
        try:
            _activate_default_mlflow_experiment(
                mlflow,
                backend_uri=backend_uri,
                default_experiment_name=default_experiment_name,
                artifact_uri=artifact_uri,
            )
            return backend_uri
        except Exception as exc:
            if attempt == 0 and _is_schema_reset_error(
                exc,
                schema_reset_markers=schema_reset_markers,
            ):
                reset_mlflow_sqlite_backend_fn(db_path)
                continue
            raise
    return backend_uri


def ensure_default_mlflow_experiment(
    tracking_dir: Path,
    *,
    get_mlflow_module_fn,
    resolve_mlflow_artifact_dir_fn,
    resolve_mlflow_backend_db_fn,
    ensure_mlflow_backend_ready_fn,
    reset_mlflow_sqlite_backend_fn,
    default_experiment_name: str,
    schema_reset_markers: tuple[str, ...],
) -> str | None:
    mlflow = get_mlflow_module_fn()
    if mlflow is None:
        return None
    artifact_uri = resolve_mlflow_artifact_dir_fn(tracking_dir).as_uri()
    db_path = resolve_mlflow_backend_db_fn(tracking_dir)
    return _activate_default_mlflow_experiment_with_schema_retry(
        mlflow,
        tracking_dir=tracking_dir,
        artifact_uri=artifact_uri,
        db_path=db_path,
        ensure_mlflow_backend_ready_fn=ensure_mlflow_backend_ready_fn,
        reset_mlflow_sqlite_backend_fn=reset_mlflow_sqlite_backend_fn,
        default_experiment_name=default_experiment_name,
        schema_reset_markers=schema_reset_markers,
    )
