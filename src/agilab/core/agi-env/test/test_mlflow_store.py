from __future__ import annotations

import builtins
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_env import mlflow_store


def _patch_mlflow_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mlflow_store, "mlflow_cli_argv", lambda args, **_kwargs: ["mlflow", *args])


def test_get_mlflow_module_handles_missing_and_present_module(monkeypatch: pytest.MonkeyPatch):
    original_import = builtins.__import__

    def _missing_mlflow(name, *args, **kwargs):
        if name == "mlflow":
            raise ImportError("missing mlflow")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_mlflow)
    assert mlflow_store.get_mlflow_module() is None

    fake_mlflow = object()

    def _present_mlflow(name, *args, **kwargs):
        if name == "mlflow":
            return fake_mlflow
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _present_mlflow)
    assert mlflow_store.get_mlflow_module() is fake_mlflow


def test_mlflow_optional_import_handles_broken_transitive_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def _broken_mlflow(name, *args, **kwargs):
        if name == "mlflow":
            raise TypeError("Descriptors cannot be created directly.")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_mlflow)
    assert mlflow_store.get_mlflow_module() is None


def test_mlflow_exception_type_loader_handles_import_crash() -> None:
    def _broken_import(_name: str):
        raise TypeError("Descriptors cannot be created directly.")

    assert mlflow_store._load_mlflow_exception_type(_broken_import) is None


def test_mlflow_path_helpers_and_legacy_detection(tmp_path: Path):
    home_abs = tmp_path / "home"
    env = SimpleNamespace(home_abs=home_abs, MLFLOW_TRACKING_DIR="runs")
    tracking_dir = mlflow_store.resolve_mlflow_tracking_dir(env)
    assert tracking_dir == (home_abs / "runs").resolve()

    absolute_tracking = tmp_path / "absolute-tracking"
    env = SimpleNamespace(home_abs=home_abs, MLFLOW_TRACKING_DIR=str(absolute_tracking))
    assert mlflow_store.resolve_mlflow_tracking_dir(env) == absolute_tracking.resolve()

    default_env = SimpleNamespace(home_abs=home_abs, MLFLOW_TRACKING_DIR=None)
    assert mlflow_store.resolve_mlflow_tracking_dir(default_env) == (home_abs / ".mlflow").resolve()

    db_path = mlflow_store.resolve_mlflow_backend_db(tracking_dir, default_db_name="mlflow.db")
    assert db_path == tracking_dir / "mlflow.db"

    artifact_dir = mlflow_store.resolve_mlflow_artifact_dir(tracking_dir, default_artifact_dir="artifacts")
    assert artifact_dir == (tracking_dir / "artifacts").resolve()
    assert artifact_dir.is_dir()

    posix_uri = mlflow_store.sqlite_uri_for_path(db_path, os_name="posix")
    nt_uri = mlflow_store.sqlite_uri_for_path(db_path, os_name="nt")
    assert posix_uri.startswith("sqlite:////")
    assert nt_uri.startswith("sqlite:///")

    tracking_dir.mkdir(parents=True, exist_ok=True)
    assert mlflow_store.legacy_mlflow_filestore_present(
        tracking_dir,
        default_db_name="mlflow.db",
        default_artifact_dir="artifacts",
    ) is False

    (tracking_dir / "123").mkdir()
    assert mlflow_store.legacy_mlflow_filestore_present(
        tracking_dir,
        default_db_name="mlflow.db",
        default_artifact_dir="artifacts",
    ) is True

    (tracking_dir / "123").rename(tracking_dir / "meta.yaml")
    assert mlflow_store.legacy_mlflow_filestore_present(
        tracking_dir,
        default_db_name="mlflow.db",
        default_artifact_dir="artifacts",
    ) is True

    assert mlflow_store.legacy_mlflow_filestore_present(
        tmp_path / "missing-tracking",
        default_db_name="mlflow.db",
        default_artifact_dir="artifacts",
    ) is False

    assert mlflow_store.sqlite_identifier('bad"name') == '"bad""name"'


def test_repair_mlflow_default_experiment_db_updates_default_experiment_and_artifacts(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY, name TEXT, workspace TEXT, artifact_location TEXT)"
        )
        conn.execute("CREATE TABLE metrics (experiment_id INTEGER, value REAL)")
        conn.execute(
            "INSERT INTO experiments (experiment_id, name, workspace, artifact_location) VALUES (5, ?, ?, ?)",
            ("Default", "default", "old://artifact"),
        )
        conn.execute("INSERT INTO metrics (experiment_id, value) VALUES (5, 1.0)")
        conn.commit()
    finally:
        conn.close()

    repaired = mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name="Default",
        sqlite_identifier_fn=mlflow_store.sqlite_identifier,
        artifact_uri="file:///new-artifacts",
    )

    assert repaired is True
    conn = sqlite3.connect(db_path)
    try:
        experiment = conn.execute(
            "SELECT experiment_id, artifact_location FROM experiments WHERE name = ?",
            ("Default",),
        ).fetchone()
        metric = conn.execute("SELECT experiment_id FROM metrics").fetchone()
    finally:
        conn.close()

    assert experiment == (0, "file:///new-artifacts")
    assert metric == (0,)


def test_repair_mlflow_default_experiment_db_returns_false_for_missing_tables_or_rows(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    assert mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name="Default",
        sqlite_identifier_fn=mlflow_store.sqlite_identifier,
    ) is False

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE experiments (name TEXT)")
        conn.commit()
    finally:
        conn.close()

    assert mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name="Default",
        sqlite_identifier_fn=mlflow_store.sqlite_identifier,
    ) is False

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE experiments")
        conn.execute("CREATE TABLE experiments (experiment_id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
    finally:
        conn.close()

    assert mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name="Missing",
        sqlite_identifier_fn=mlflow_store.sqlite_identifier,
    ) is False


def test_repair_mlflow_default_experiment_db_returns_false_on_sqlite_error(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    db_path.write_text("placeholder", encoding="utf-8")

    def _broken_connect(_path):
        raise sqlite3.Error("broken sqlite")

    assert mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name="Default",
        sqlite_identifier_fn=mlflow_store.sqlite_identifier,
        connect_fn=_broken_connect,
    ) is False


def test_repair_mlflow_default_experiment_db_closes_connection_on_early_return(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    db_path.write_text("placeholder", encoding="utf-8")
    closed = {"value": False}

    class _Rows:
        def __init__(self, *, fetchall_rows=None, fetchone_row=None):
            self._fetchall_rows = fetchall_rows or []
            self._fetchone_row = fetchone_row

        def fetchall(self):
            return self._fetchall_rows

        def fetchone(self):
            return self._fetchone_row

    class _Connection:
        def execute(self, sql, *_args):
            if "sqlite_master" in sql:
                return _Rows(fetchall_rows=[])
            raise AssertionError(f"Unexpected SQL: {sql}")

        def close(self):
            closed["value"] = True

    assert mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name="Default",
        sqlite_identifier_fn=mlflow_store.sqlite_identifier,
        connect_fn=lambda _path: _Connection(),
    ) is False
    assert closed["value"] is True


def test_ensure_mlflow_sqlite_schema_current_adds_checked_uri_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = tmp_path / "mlflow.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
        conn.commit()
    finally:
        conn.close()

    checked_uris: set[str] = set()
    run_calls: list[list[str]] = []

    def _run_cmd(cmd, **_kwargs):
        run_calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    _patch_mlflow_cli(monkeypatch)
    mlflow_store.ensure_mlflow_sqlite_schema_current(
        db_path,
        checked_uris=checked_uris,
        sqlite_uri_for_path_fn=lambda path: f"sqlite:///{Path(path).name}",
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda _path: None,
        run_cmd=_run_cmd,
        sys_executable="python-test",
    )

    assert run_calls == [["mlflow", "db", "upgrade", "sqlite:///mlflow.db"]]
    assert checked_uris == {"sqlite:///mlflow.db"}


def test_resolve_mlflow_schema_upgrade_uri_covers_skip_and_success_cases(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    db_path.write_text("db", encoding="utf-8")
    has_table_calls: list[Path] = []

    assert mlflow_store._resolve_mlflow_schema_upgrade_uri(
        tmp_path / "missing.db",
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda path: f"sqlite:///{Path(path).name}",
        has_alembic_version_table_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("alembic probe should not run for a missing database")
        ),
    ) is None

    assert mlflow_store._resolve_mlflow_schema_upgrade_uri(
        db_path,
        checked_uris={"sqlite:///mlflow.db"},
        sqlite_uri_for_path_fn=lambda path: f"sqlite:///{Path(path).name}",
        has_alembic_version_table_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("alembic probe should not run for an already checked database")
        ),
    ) is None

    assert mlflow_store._resolve_mlflow_schema_upgrade_uri(
        db_path,
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda path: f"sqlite:///{Path(path).name}",
        has_alembic_version_table_fn=lambda path, **_kwargs: has_table_calls.append(Path(path)) or False,
    ) is None

    assert mlflow_store._resolve_mlflow_schema_upgrade_uri(
        db_path,
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda path: f"sqlite:///{Path(path).name}",
        has_alembic_version_table_fn=lambda path, **_kwargs: has_table_calls.append(Path(path)) or True,
    ) == "sqlite:///mlflow.db"

    assert has_table_calls == [db_path, db_path]


def test_handle_mlflow_schema_upgrade_result_covers_success_reset_and_failure(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    reset_calls: list[Path] = []

    assert mlflow_store._handle_mlflow_schema_upgrade_result(
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        db_path=db_path,
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda path: reset_calls.append(Path(path)),
    ) is True
    assert reset_calls == []

    assert mlflow_store._handle_mlflow_schema_upgrade_result(
        SimpleNamespace(returncode=1, stdout="schema-reset needed", stderr=""),
        db_path=db_path,
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda path: reset_calls.append(Path(path)),
    ) is False
    assert reset_calls == [db_path]

    with pytest.raises(RuntimeError, match="Failed to upgrade the local MLflow SQLite schema"):
        mlflow_store._handle_mlflow_schema_upgrade_result(
            SimpleNamespace(returncode=1, stdout="", stderr="upgrade failed badly"),
            db_path=db_path,
            schema_reset_markers=("schema-reset",),
            reset_backend_fn=lambda _path: None,
        )


def test_ensure_mlflow_sqlite_schema_current_resets_or_raises_on_upgrade_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = tmp_path / "mlflow.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
        conn.commit()
    finally:
        conn.close()

    reset_calls: list[Path] = []

    def _schema_reset_run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="schema-reset needed")

    _patch_mlflow_cli(monkeypatch)
    mlflow_store.ensure_mlflow_sqlite_schema_current(
        db_path,
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///db",
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda path: reset_calls.append(Path(path)),
        run_cmd=_schema_reset_run,
    )
    assert reset_calls == [db_path]

    def _failing_run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="upgrade failed badly")

    with pytest.raises(RuntimeError, match="Failed to upgrade the local MLflow SQLite schema"):
        mlflow_store.ensure_mlflow_sqlite_schema_current(
            db_path,
            checked_uris=set(),
            sqlite_uri_for_path_fn=lambda _path: "sqlite:///db",
            schema_reset_markers=("schema-reset",),
            reset_backend_fn=lambda _path: None,
            run_cmd=_failing_run,
        )


def test_ensure_mlflow_sqlite_schema_current_skips_missing_checked_or_non_alembic_db(tmp_path: Path):
    missing_db = tmp_path / "missing.db"
    mlflow_store.ensure_mlflow_sqlite_schema_current(
        missing_db,
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///missing.db",
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda _path: None,
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("run_cmd should not be called")),
    )

    checked_db = tmp_path / "checked.db"
    checked_db.write_text("placeholder", encoding="utf-8")
    mlflow_store.ensure_mlflow_sqlite_schema_current(
        checked_db,
        checked_uris={"sqlite:///checked.db"},
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///checked.db",
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda _path: None,
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("run_cmd should not be called")),
    )

    no_alembic_db = tmp_path / "no_alembic.db"
    conn = sqlite3.connect(no_alembic_db)
    try:
        conn.execute("CREATE TABLE metrics (value REAL)")
        conn.commit()
    finally:
        conn.close()

    mlflow_store.ensure_mlflow_sqlite_schema_current(
        no_alembic_db,
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///no_alembic.db",
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda _path: None,
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("run_cmd should not be called")),
    )

    sqlite_error_db = tmp_path / "sqlite_error.db"
    sqlite_error_db.write_text("placeholder", encoding="utf-8")

    def _broken_connect(_path):
        raise sqlite3.Error("broken sqlite")

    mlflow_store.ensure_mlflow_sqlite_schema_current(
        sqlite_error_db,
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///sqlite_error.db",
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda _path: None,
        connect_fn=_broken_connect,
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("run_cmd should not be called")),
    )


def test_ensure_mlflow_sqlite_schema_current_closes_connection_after_probe(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    db_path.write_text("placeholder", encoding="utf-8")
    closed = {"value": False}

    class _Rows:
        def fetchone(self):
            return None

    class _Connection:
        def execute(self, sql):
            assert "sqlite_master" in sql
            return _Rows()

        def close(self):
            closed["value"] = True

    mlflow_store.ensure_mlflow_sqlite_schema_current(
        db_path,
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///mlflow.db",
        schema_reset_markers=("schema-reset",),
        reset_backend_fn=lambda _path: None,
        connect_fn=lambda _path: _Connection(),
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("run_cmd should not be called")),
    )

    assert closed["value"] is True


def test_mlflow_sqlite_has_alembic_version_table_handles_true_false_and_sqlite_error(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
        conn.commit()
    finally:
        conn.close()

    assert mlflow_store._mlflow_sqlite_has_alembic_version_table(db_path) is True

    no_alembic_db = tmp_path / "no_alembic.db"
    conn = sqlite3.connect(no_alembic_db)
    try:
        conn.execute("CREATE TABLE metrics (value REAL)")
        conn.commit()
    finally:
        conn.close()

    assert mlflow_store._mlflow_sqlite_has_alembic_version_table(no_alembic_db) is False
    assert mlflow_store._mlflow_sqlite_has_alembic_version_table(
        tmp_path / "broken.db",
        connect_fn=lambda _path: (_ for _ in ()).throw(sqlite3.Error("broken sqlite")),
    ) is False


def test_reset_mlflow_sqlite_backend_moves_database_and_sidecars(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    for suffix in ("", "-shm", "-wal", "-journal"):
        Path(f"{db_path}{suffix}").write_text("x", encoding="utf-8")

    checked_uris = {"sqlite:///mlflow.db"}
    backup_path = mlflow_store.reset_mlflow_sqlite_backend(
        db_path,
        checked_uris=checked_uris,
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///mlflow.db",
        timestamp_fn=lambda: "20260415T120000",
    )

    assert backup_path == tmp_path / "mlflow.schema-reset-20260415T120000.db"
    assert "sqlite:///mlflow.db" not in checked_uris
    for suffix in ("", "-shm", "-wal", "-journal"):
        assert not Path(f"{db_path}{suffix}").exists()
        assert Path(f"{backup_path}{suffix}").exists()


def test_reset_mlflow_sqlite_backend_returns_none_when_db_is_missing(tmp_path: Path):
    assert mlflow_store.reset_mlflow_sqlite_backend(
        tmp_path / "missing.db",
        checked_uris=set(),
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///missing.db",
        timestamp_fn=lambda: "20260415T120000",
    ) is None


def test_move_mlflow_sqlite_backend_files_moves_present_files_only(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    backup_path = tmp_path / "mlflow.schema-reset-20260415T120000.db"
    for suffix in ("", "-wal"):
        Path(f"{db_path}{suffix}").write_text("x", encoding="utf-8")

    mlflow_store._move_mlflow_sqlite_backend_files(
        db_path,
        backup_path=backup_path,
    )

    assert not db_path.exists()
    assert not Path(f"{db_path}-wal").exists()
    assert Path(backup_path).exists()
    assert Path(f"{backup_path}-wal").exists()
    assert not Path(f"{backup_path}-shm").exists()
    assert not Path(f"{backup_path}-journal").exists()


def test_resolve_mlflow_artifact_uri_delegates_to_artifact_dir_resolver(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    calls: list[Path] = []

    artifact_uri = mlflow_store._resolve_mlflow_artifact_uri(
        tracking_dir,
        resolve_mlflow_artifact_dir_fn=lambda path: calls.append(Path(path)) or (tracking_dir / "artifacts"),
    )

    assert artifact_uri == (tracking_dir / "artifacts").as_uri()
    assert calls == [tracking_dir]


def test_migrate_legacy_mlflow_filestore_if_needed_skips_when_backend_exists_or_no_legacy(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()
    db_path = tracking_dir / "mlflow.db"
    db_path.write_text("db", encoding="utf-8")

    mlflow_store._migrate_legacy_mlflow_filestore_if_needed(
        tracking_dir,
        db_path=db_path,
        legacy_mlflow_filestore_present_fn=lambda _tracking_dir: (_ for _ in ()).throw(
            AssertionError("legacy detection should not run when the backend already exists")
        ),
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///mlflow.db",
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("migration should not run when the backend already exists")
        ),
    )

    db_path.unlink()
    legacy_checks: list[Path] = []
    mlflow_store._migrate_legacy_mlflow_filestore_if_needed(
        tracking_dir,
        db_path=db_path,
        legacy_mlflow_filestore_present_fn=lambda candidate: legacy_checks.append(Path(candidate)) or False,
        sqlite_uri_for_path_fn=lambda _path: "sqlite:///mlflow.db",
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("migration should not run when no legacy store is present")
        ),
    )

    assert legacy_checks == [tracking_dir]


def test_migrate_legacy_mlflow_filestore_if_needed_runs_migration_and_raises_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()
    db_path = tracking_dir / "mlflow.db"
    run_calls: list[list[str]] = []

    def _run_cmd(cmd, **_kwargs):
        run_calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    _patch_mlflow_cli(monkeypatch)
    mlflow_store._migrate_legacy_mlflow_filestore_if_needed(
        tracking_dir,
        db_path=db_path,
        legacy_mlflow_filestore_present_fn=lambda _tracking_dir: True,
        sqlite_uri_for_path_fn=lambda path: f"sqlite:///{Path(path).name}",
        run_cmd=_run_cmd,
        sys_executable="python-test",
    )

    assert run_calls == [[
        "mlflow",
        "migrate-filestore",
        "--source",
        str(tracking_dir),
        "--target",
        "sqlite:///mlflow.db",
    ]]

    def _failing_run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="migration failed")

    with pytest.raises(RuntimeError, match="Failed to migrate the legacy MLflow file store"):
        mlflow_store._migrate_legacy_mlflow_filestore_if_needed(
            tracking_dir,
            db_path=db_path,
            legacy_mlflow_filestore_present_fn=lambda _tracking_dir: True,
            sqlite_uri_for_path_fn=lambda _path: "sqlite:///mlflow.db",
            run_cmd=_failing_run,
        )


def test_handle_mlflow_filestore_migration_result_covers_success_and_failure(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"

    mlflow_store._handle_mlflow_filestore_migration_result(
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        tracking_dir=tracking_dir,
    )

    with pytest.raises(RuntimeError, match="Failed to migrate the legacy MLflow file store"):
        mlflow_store._handle_mlflow_filestore_migration_result(
            SimpleNamespace(returncode=1, stdout="", stderr="migration failed"),
            tracking_dir=tracking_dir,
        )


def test_finalize_mlflow_backend_runs_schema_then_repairs_default_experiment(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()
    db_path = tracking_dir / "mlflow.db"
    events: list[tuple[str, object, object | None]] = []

    mlflow_store._finalize_mlflow_backend(
        tracking_dir,
        db_path=db_path,
        ensure_mlflow_sqlite_schema_current_fn=lambda path: events.append(("schema", Path(path), None)),
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
        repair_mlflow_default_experiment_db_fn=lambda path, artifact_uri=None: events.append(
            ("repair", Path(path), artifact_uri)
        ),
    )

    assert events == [
        ("schema", db_path, None),
        ("repair", db_path, (tracking_dir / "artifacts").as_uri()),
    ]


def test_prepare_mlflow_backend_migrates_then_finalizes(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()
    db_path = tracking_dir / "mlflow.db"
    events: list[tuple[str, object]] = []

    mlflow_store._prepare_mlflow_backend(
        tracking_dir,
        db_path=db_path,
        legacy_mlflow_filestore_present_fn=lambda _tracking_dir: events.append(("legacy", _tracking_dir)) or False,
        sqlite_uri_for_path_fn=lambda path: events.append(("sqlite_uri", Path(path))) or "sqlite:///mlflow.db",
        ensure_mlflow_sqlite_schema_current_fn=lambda path: events.append(("schema", Path(path))),
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
        repair_mlflow_default_experiment_db_fn=lambda path, artifact_uri=None: events.append(
            ("repair", (Path(path), artifact_uri))
        ),
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("migration should not run")),
        sys_executable="python-test",
    )

    assert events == [
        ("legacy", tracking_dir),
        ("schema", db_path),
        ("repair", (db_path, (tracking_dir / "artifacts").as_uri())),
    ]


def test_ensure_mlflow_backend_ready_migrates_legacy_store_and_repairs_default_experiment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()
    db_path = tracking_dir / "mlflow.db"
    schema_calls: list[Path] = []
    repair_calls: list[tuple[Path, str | None]] = []
    run_calls: list[list[str]] = []

    def _run_cmd(cmd, **_kwargs):
        run_calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    _patch_mlflow_cli(monkeypatch)
    backend_uri = mlflow_store.ensure_mlflow_backend_ready(
        tracking_dir,
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: db_path,
        legacy_mlflow_filestore_present_fn=lambda _tracking_dir: True,
        sqlite_uri_for_path_fn=lambda path: f"sqlite:///{Path(path).name}",
        ensure_mlflow_sqlite_schema_current_fn=lambda path: schema_calls.append(Path(path)),
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
        repair_mlflow_default_experiment_db_fn=lambda path, artifact_uri=None: repair_calls.append((Path(path), artifact_uri)),
        run_cmd=_run_cmd,
        sys_executable="python-test",
    )

    assert backend_uri == "sqlite:///mlflow.db"
    assert run_calls == [[
        "mlflow",
        "migrate-filestore",
        "--source",
        str(tracking_dir),
        "--target",
        "sqlite:///mlflow.db",
    ]]
    assert schema_calls == [db_path]
    assert repair_calls == [(db_path, (tracking_dir / "artifacts").as_uri())]


def test_ensure_mlflow_backend_ready_raises_when_filestore_migration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()

    def _run_cmd(_cmd, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="migration failed")

    _patch_mlflow_cli(monkeypatch)
    with pytest.raises(RuntimeError, match="Failed to migrate the legacy MLflow file store"):
        mlflow_store.ensure_mlflow_backend_ready(
            tracking_dir,
            resolve_mlflow_backend_db_fn=lambda _tracking_dir: tracking_dir / "mlflow.db",
            legacy_mlflow_filestore_present_fn=lambda _tracking_dir: True,
            sqlite_uri_for_path_fn=lambda _path: "sqlite:///mlflow.db",
            ensure_mlflow_sqlite_schema_current_fn=lambda _path: None,
            resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
            repair_mlflow_default_experiment_db_fn=lambda _path, artifact_uri=None: None,
            run_cmd=_run_cmd,
        )


def test_ensure_mlflow_backend_ready_skips_migration_when_backend_already_exists(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()
    db_path = tracking_dir / "mlflow.db"
    db_path.write_text("db", encoding="utf-8")
    schema_calls: list[Path] = []
    repair_calls: list[tuple[Path, str | None]] = []

    backend_uri = mlflow_store.ensure_mlflow_backend_ready(
        tracking_dir,
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: db_path,
        legacy_mlflow_filestore_present_fn=lambda _tracking_dir: (_ for _ in ()).throw(
            AssertionError("legacy filestore detection should not run when the DB already exists")
        ),
        sqlite_uri_for_path_fn=lambda path: f"sqlite:///{Path(path).name}",
        ensure_mlflow_sqlite_schema_current_fn=lambda path: schema_calls.append(Path(path)),
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
        repair_mlflow_default_experiment_db_fn=lambda path, artifact_uri=None: repair_calls.append((Path(path), artifact_uri)),
        run_cmd=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("migration should not run")),
    )

    assert backend_uri == "sqlite:///mlflow.db"
    assert schema_calls == [db_path]
    assert repair_calls == [(db_path, (tracking_dir / "artifacts").as_uri())]


def test_resolve_default_mlflow_activation_context_handles_missing_module_and_resolves_paths(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"

    assert mlflow_store._resolve_default_mlflow_activation_context(
        tracking_dir,
        get_mlflow_module_fn=lambda: None,
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: (_ for _ in ()).throw(
            AssertionError("artifact dir should not be resolved without mlflow")
        ),
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: (_ for _ in ()).throw(
            AssertionError("backend db should not be resolved without mlflow")
        ),
    ) is None

    fake_mlflow = object()
    activation_context = mlflow_store._resolve_default_mlflow_activation_context(
        tracking_dir,
        get_mlflow_module_fn=lambda: fake_mlflow,
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: tracking_dir / "mlflow.db",
    )

    assert activation_context == (
        fake_mlflow,
        (tracking_dir / "artifacts").as_uri(),
        tracking_dir / "mlflow.db",
    )


def test_activate_default_mlflow_experiment_from_context_delegates_retry_helper(monkeypatch, tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    activation_context = (object(), "file:///artifacts", tracking_dir / "mlflow.db")
    calls: list[tuple[str, object]] = []

    def _fake_retry(
        mlflow,
        *,
        tracking_dir,
        artifact_uri,
        db_path,
        ensure_mlflow_backend_ready_fn,
        reset_mlflow_sqlite_backend_fn,
        default_experiment_name,
        schema_reset_markers,
    ):
        calls.append(
            (
                "retry",
                (
                    mlflow,
                    Path(tracking_dir),
                    artifact_uri,
                    Path(db_path),
                    ensure_mlflow_backend_ready_fn,
                    reset_mlflow_sqlite_backend_fn,
                    default_experiment_name,
                    schema_reset_markers,
                ),
            )
        )
        return "sqlite:///mlflow.db"

    monkeypatch.setattr(
        mlflow_store,
        "_activate_default_mlflow_experiment_with_schema_retry",
        _fake_retry,
    )

    ensure_fn = object()
    reset_fn = object()
    backend_uri = mlflow_store._activate_default_mlflow_experiment_from_context(
        activation_context,
        tracking_dir=tracking_dir,
        ensure_mlflow_backend_ready_fn=ensure_fn,
        reset_mlflow_sqlite_backend_fn=reset_fn,
        default_experiment_name="Default",
        schema_reset_markers=("schema-reset",),
    )

    assert backend_uri == "sqlite:///mlflow.db"
    assert calls == [
        (
            "retry",
            (
                activation_context[0],
                tracking_dir,
                "file:///artifacts",
                tracking_dir / "mlflow.db",
                ensure_fn,
                reset_fn,
                "Default",
                ("schema-reset",),
            ),
        )
    ]


def test_ensure_default_mlflow_experiment_handles_missing_mlflow_module(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    assert mlflow_store.ensure_default_mlflow_experiment(
        tracking_dir,
        get_mlflow_module_fn=lambda: None,
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: tracking_dir / "mlflow.db",
        ensure_mlflow_backend_ready_fn=lambda _tracking_dir: "sqlite:///mlflow.db",
        reset_mlflow_sqlite_backend_fn=lambda _db_path: None,
        default_experiment_name="Default",
        schema_reset_markers=("schema-reset",),
    ) is None


def test_mlflow_existing_experiment_conflict_helper_prefers_refreshed_lookup():
    calls = []

    def _get_experiment(name):
        calls.append(name)
        return object()

    assert mlflow_store._is_existing_experiment_conflict(
        RuntimeError("irrelevant"),
        get_experiment_fn=_get_experiment,
        default_experiment_name="Default",
    ) is True
    assert calls == ["Default"]


def test_mlflow_existing_experiment_conflict_helper_matches_message_or_propagates_lookup_bug():
    assert mlflow_store._is_existing_experiment_conflict(
        RuntimeError("Experiment already exists"),
        get_experiment_fn=None,
        default_experiment_name="Default",
    ) is True

    assert mlflow_store._is_existing_experiment_conflict(
        RuntimeError("unexpected create bug"),
        get_experiment_fn=None,
        default_experiment_name="Default",
    ) is False

    with pytest.raises(RuntimeError, match="lookup bug"):
        mlflow_store._is_existing_experiment_conflict(
            RuntimeError("Experiment already exists"),
            get_experiment_fn=lambda _name: (_ for _ in ()).throw(RuntimeError("lookup bug")),
            default_experiment_name="Default",
        )


def test_lookup_experiment_by_name_handles_missing_callable_and_propagates_lookup_bug():
    assert mlflow_store._lookup_experiment_by_name(
        "Default",
        get_experiment_fn=None,
    ) is None

    calls = []

    def _get_experiment(name):
        calls.append(name)
        return object()

    assert mlflow_store._lookup_experiment_by_name(
        "Default",
        get_experiment_fn=_get_experiment,
    ) is not None
    assert calls == ["Default"]

    with pytest.raises(RuntimeError, match="lookup bug"):
        mlflow_store._lookup_experiment_by_name(
            "Default",
            get_experiment_fn=lambda _name: (_ for _ in ()).throw(RuntimeError("lookup bug")),
        )


def test_mlflow_schema_reset_error_helper_matches_default_phrase_and_markers():
    assert mlflow_store._is_schema_reset_error(
        RuntimeError("Detected out-of-date database schema"),
        schema_reset_markers=("schema-reset",),
    ) is True
    assert mlflow_store._is_schema_reset_error(
        RuntimeError("schema-reset needed"),
        schema_reset_markers=("schema-reset",),
    ) is True
    assert mlflow_store._is_schema_reset_error(
        RuntimeError("other failure"),
        schema_reset_markers=("schema-reset",),
    ) is False


def test_create_default_experiment_helper_skips_missing_creator_and_ignores_existing_race():
    mlflow_store._create_default_experiment(
        None,
        get_experiment_fn=lambda _name: (_ for _ in ()).throw(
            AssertionError("lookup should not run when there is no create function")
        ),
        default_experiment_name="Default",
        artifact_uri="file:///artifacts",
    )

    calls: list[tuple[str, object]] = []
    created = {"value": False}

    def _get_experiment(name):
        calls.append(("get_experiment", name))
        if created["value"]:
            return object()
        return None

    def _create_experiment(name, artifact_location=None):
        calls.append(("create_experiment", (name, artifact_location)))
        created["value"] = True
        raise RuntimeError("already exists")

    mlflow_store._create_default_experiment(
        _create_experiment,
        get_experiment_fn=_get_experiment,
        default_experiment_name="Default",
        artifact_uri="file:///artifacts",
    )

    assert calls == [
        ("create_experiment", ("Default", "file:///artifacts")),
        ("get_experiment", "Default"),
    ]


def test_create_default_experiment_helper_propagates_unexpected_create_bug():
    with pytest.raises(RuntimeError, match="unexpected create bug"):
        mlflow_store._create_default_experiment(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected create bug")),
            get_experiment_fn=lambda _name: None,
            default_experiment_name="Default",
            artifact_uri="file:///artifacts",
        )


def test_create_default_experiment_helper_propagates_non_runtime_programmer_bug():
    with pytest.raises(AssertionError, match="programmer bug"):
        mlflow_store._create_default_experiment(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("programmer bug")),
            get_experiment_fn=lambda _name: pytest.fail("unexpected lookup"),
            default_experiment_name="Default",
            artifact_uri="file:///artifacts",
        )


def test_retry_default_mlflow_activation_after_schema_reset_resets_once():
    reset_calls: list[Path] = []
    db_path = Path("/tmp/mlflow.db")

    assert mlflow_store._retry_default_mlflow_activation_after_schema_reset(
        RuntimeError("schema-reset needed"),
        attempt=0,
        db_path=db_path,
        reset_mlflow_sqlite_backend_fn=lambda path: reset_calls.append(Path(path)),
        schema_reset_markers=("schema-reset",),
    ) is True
    assert reset_calls == [db_path]


def test_retry_default_mlflow_activation_after_schema_reset_skips_non_schema_or_late_errors():
    reset_calls: list[Path] = []
    db_path = Path("/tmp/mlflow.db")

    assert mlflow_store._retry_default_mlflow_activation_after_schema_reset(
        RuntimeError("other failure"),
        attempt=0,
        db_path=db_path,
        reset_mlflow_sqlite_backend_fn=lambda path: reset_calls.append(Path(path)),
        schema_reset_markers=("schema-reset",),
    ) is False
    assert mlflow_store._retry_default_mlflow_activation_after_schema_reset(
        RuntimeError("schema-reset needed"),
        attempt=1,
        db_path=db_path,
        reset_mlflow_sqlite_backend_fn=lambda path: reset_calls.append(Path(path)),
        schema_reset_markers=("schema-reset",),
    ) is False
    assert reset_calls == []


def test_create_default_experiment_if_missing_skips_create_when_lookup_finds_experiment():
    calls: list[tuple[str, object]] = []

    class _FakeMlflow:
        def get_experiment_by_name(self, name):
            calls.append(("get_experiment_by_name", name))
            return object()

        def create_experiment(self, name, artifact_location=None):
            calls.append(("create_experiment", (name, artifact_location)))

    mlflow_store._create_default_experiment_if_missing(
        _FakeMlflow(),
        default_experiment_name="Default",
        artifact_uri="file:///artifacts",
    )

    assert calls == [("get_experiment_by_name", "Default")]


def test_lookup_default_mlflow_experiment_uses_object_lookup_contract():
    calls: list[str] = []

    class _FakeMlflow:
        def get_experiment_by_name(self, name):
            calls.append(name)
            return object()

    assert mlflow_store._lookup_default_mlflow_experiment(
        _FakeMlflow(),
        default_experiment_name="Default",
    ) is not None
    assert calls == ["Default"]


def test_create_default_mlflow_experiment_from_object_uses_object_create_contract():
    calls: list[tuple[str, object]] = []

    class _FakeMlflow:
        def create_experiment(self, name, artifact_location=None):
            calls.append(("create_experiment", (name, artifact_location)))

    mlflow_store._create_default_mlflow_experiment_from_object(
        _FakeMlflow(),
        get_experiment_fn=lambda _name: None,
        default_experiment_name="Default",
        artifact_uri="file:///artifacts",
    )

    assert calls == [("create_experiment", ("Default", "file:///artifacts"))]


def test_create_default_experiment_if_missing_propagates_unexpected_create_bug():
    class _FakeMlflow:
        def get_experiment_by_name(self, _name):
            return None

        def create_experiment(self, _name, artifact_location=None):
            raise RuntimeError("unexpected create bug")

    with pytest.raises(RuntimeError, match="unexpected create bug"):
        mlflow_store._create_default_experiment_if_missing(
            _FakeMlflow(),
            default_experiment_name="Default",
            artifact_uri="file:///artifacts",
        )


def test_prepare_default_mlflow_experiment_selection_sets_tracking_then_ensures_experiment():
    calls: list[tuple[str, object]] = []

    class _FakeMlflow:
        def set_tracking_uri(self, uri):
            calls.append(("set_tracking_uri", uri))

        def get_experiment_by_name(self, name):
            calls.append(("get_experiment_by_name", name))
            return None

        def create_experiment(self, name, artifact_location=None):
            calls.append(("create_experiment", (name, artifact_location)))

    mlflow_store._prepare_default_mlflow_experiment_selection(
        _FakeMlflow(),
        backend_uri="sqlite:///mlflow.db",
        default_experiment_name="Default",
        artifact_uri="file:///artifacts",
    )

    assert calls == [
        ("set_tracking_uri", "sqlite:///mlflow.db"),
        ("get_experiment_by_name", "Default"),
        ("create_experiment", ("Default", "file:///artifacts")),
    ]


def test_activate_default_mlflow_experiment_orders_tracking_create_and_select():
    calls: list[tuple[str, object]] = []

    class _FakeMlflow:
        def set_tracking_uri(self, uri):
            calls.append(("set_tracking_uri", uri))

        def get_experiment_by_name(self, name):
            calls.append(("get_experiment_by_name", name))
            return None

        def create_experiment(self, name, artifact_location=None):
            calls.append(("create_experiment", (name, artifact_location)))

        def set_experiment(self, name):
            calls.append(("set_experiment", name))

    mlflow_store._activate_default_mlflow_experiment(
        _FakeMlflow(),
        backend_uri="sqlite:///mlflow.db",
        default_experiment_name="Default",
        artifact_uri="file:///artifacts",
    )

    assert calls == [
        ("set_tracking_uri", "sqlite:///mlflow.db"),
        ("get_experiment_by_name", "Default"),
        ("create_experiment", ("Default", "file:///artifacts")),
        ("set_experiment", "Default"),
    ]


def test_activate_default_mlflow_experiment_once_resolves_backend_then_activates(monkeypatch, tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    calls: list[tuple[str, object]] = []

    def _fake_activate(_mlflow, *, backend_uri, default_experiment_name, artifact_uri):
        calls.append(
            (
                "activate",
                (backend_uri, default_experiment_name, artifact_uri),
            )
        )

    monkeypatch.setattr(mlflow_store, "_activate_default_mlflow_experiment", _fake_activate)

    backend_uri = mlflow_store._activate_default_mlflow_experiment_once(
        object(),
        tracking_dir=tracking_dir,
        artifact_uri="file:///artifacts",
        ensure_mlflow_backend_ready_fn=lambda path: calls.append(("backend", Path(path))) or "sqlite:///mlflow.db",
        default_experiment_name="Default",
    )

    assert backend_uri == "sqlite:///mlflow.db"
    assert calls == [
        ("backend", tracking_dir),
        ("activate", ("sqlite:///mlflow.db", "Default", "file:///artifacts")),
    ]


def test_activate_default_mlflow_experiment_with_schema_retry_resets_once(monkeypatch, tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    db_path = tracking_dir / "mlflow.db"
    backend_calls: list[Path] = []
    reset_calls: list[Path] = []
    activate_calls: list[str] = []

    def _fake_activate(_mlflow, *, backend_uri, default_experiment_name, artifact_uri):
        activate_calls.append(backend_uri)
        if len(activate_calls) == 1:
            raise RuntimeError("schema-reset needed")

    monkeypatch.setattr(mlflow_store, "_activate_default_mlflow_experiment", _fake_activate)

    backend_uri = mlflow_store._activate_default_mlflow_experiment_with_schema_retry(
        object(),
        tracking_dir=tracking_dir,
        artifact_uri="file:///artifacts",
        db_path=db_path,
        ensure_mlflow_backend_ready_fn=lambda path: backend_calls.append(Path(path)) or "sqlite:///mlflow.db",
        reset_mlflow_sqlite_backend_fn=lambda path: reset_calls.append(Path(path)),
        default_experiment_name="Default",
        schema_reset_markers=("schema-reset",),
    )

    assert backend_uri == "sqlite:///mlflow.db"
    assert activate_calls == ["sqlite:///mlflow.db", "sqlite:///mlflow.db"]
    assert backend_calls == [tracking_dir, tracking_dir]
    assert reset_calls == [db_path]


def test_activate_default_mlflow_experiment_with_schema_retry_propagates_non_schema_error(monkeypatch, tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    db_path = tracking_dir / "mlflow.db"
    reset_calls: list[Path] = []

    def _fake_activate(_mlflow, *, backend_uri, default_experiment_name, artifact_uri):
        raise RuntimeError("unexpected activation bug")

    monkeypatch.setattr(mlflow_store, "_activate_default_mlflow_experiment", _fake_activate)

    with pytest.raises(RuntimeError, match="unexpected activation bug"):
        mlflow_store._activate_default_mlflow_experiment_with_schema_retry(
            object(),
            tracking_dir=tracking_dir,
            artifact_uri="file:///artifacts",
            db_path=db_path,
            ensure_mlflow_backend_ready_fn=lambda _path: "sqlite:///mlflow.db",
            reset_mlflow_sqlite_backend_fn=lambda path: reset_calls.append(Path(path)),
            default_experiment_name="Default",
            schema_reset_markers=("schema-reset",),
        )

    assert reset_calls == []


def test_activate_default_mlflow_experiment_with_schema_retry_propagates_non_runtime_bug(monkeypatch, tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    db_path = tracking_dir / "mlflow.db"
    reset_calls: list[Path] = []

    def _fake_activate(_mlflow, *, backend_uri, default_experiment_name, artifact_uri):
        raise AssertionError("unexpected activation bug")

    monkeypatch.setattr(mlflow_store, "_activate_default_mlflow_experiment", _fake_activate)

    with pytest.raises(AssertionError, match="unexpected activation bug"):
        mlflow_store._activate_default_mlflow_experiment_with_schema_retry(
            object(),
            tracking_dir=tracking_dir,
            artifact_uri="file:///artifacts",
            db_path=db_path,
            ensure_mlflow_backend_ready_fn=lambda _path: "sqlite:///mlflow.db",
            reset_mlflow_sqlite_backend_fn=lambda path: reset_calls.append(Path(path)),
            default_experiment_name="Default",
            schema_reset_markers=("schema-reset",),
        )

    assert reset_calls == []


def test_ensure_default_mlflow_experiment_creates_or_reuses_default_experiment(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()
    calls: list[tuple[str, object]] = []

    class _FakeMlflow:
        def __init__(self):
            self.experiment = None

        def set_tracking_uri(self, uri):
            calls.append(("set_tracking_uri", uri))

        def get_experiment_by_name(self, name):
            calls.append(("get_experiment_by_name", name))
            return self.experiment

        def create_experiment(self, name, artifact_location=None):
            calls.append(("create_experiment", (name, artifact_location)))
            raise RuntimeError("Experiment already exists")

        def set_experiment(self, name):
            calls.append(("set_experiment", name))

    backend_uri = mlflow_store.ensure_default_mlflow_experiment(
        tracking_dir,
        get_mlflow_module_fn=_FakeMlflow,
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: tracking_dir / "mlflow.db",
        ensure_mlflow_backend_ready_fn=lambda _tracking_dir: "sqlite:///mlflow.db",
        reset_mlflow_sqlite_backend_fn=lambda _db_path: None,
        default_experiment_name="Default",
        schema_reset_markers=("schema-reset",),
    )

    assert backend_uri == "sqlite:///mlflow.db"
    assert ("set_tracking_uri", "sqlite:///mlflow.db") in calls
    assert ("get_experiment_by_name", "Default") in calls
    assert ("set_experiment", "Default") in calls


def test_ensure_default_mlflow_experiment_resets_backend_once_for_schema_drift(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()
    reset_calls: list[Path] = []
    backend_calls: list[Path] = []

    class _FakeMlflow:
        def __init__(self):
            self.set_experiment_calls = 0

        def set_tracking_uri(self, _uri):
            return None

        def get_experiment_by_name(self, _name):
            return SimpleNamespace(name="Default")

        def set_experiment(self, _name):
            self.set_experiment_calls += 1
            if self.set_experiment_calls == 1:
                raise RuntimeError("Detected out-of-date database schema")

    fake_mlflow = _FakeMlflow()

    backend_uri = mlflow_store.ensure_default_mlflow_experiment(
        tracking_dir,
        get_mlflow_module_fn=lambda: fake_mlflow,
        resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
        resolve_mlflow_backend_db_fn=lambda _tracking_dir: tracking_dir / "mlflow.db",
        ensure_mlflow_backend_ready_fn=lambda _tracking_dir: backend_calls.append(Path(_tracking_dir)) or "sqlite:///mlflow.db",
        reset_mlflow_sqlite_backend_fn=lambda db_path: reset_calls.append(Path(db_path)),
        default_experiment_name="Default",
        schema_reset_markers=("schema",),
    )

    assert backend_uri == "sqlite:///mlflow.db"
    assert backend_calls == [tracking_dir, tracking_dir]
    assert reset_calls == [tracking_dir / "mlflow.db"]


def test_ensure_default_mlflow_experiment_propagates_non_schema_errors(tmp_path: Path):
    tracking_dir = tmp_path / "tracking"
    tracking_dir.mkdir()

    class _FakeMlflow:
        def set_tracking_uri(self, _uri):
            return None

        def get_experiment_by_name(self, _name):
            return None

        def create_experiment(self, _name, artifact_location=None):
            raise RuntimeError("unexpected create bug")

        def set_experiment(self, _name):
            return None

    with pytest.raises(RuntimeError, match="unexpected create bug"):
        mlflow_store.ensure_default_mlflow_experiment(
            tracking_dir,
            get_mlflow_module_fn=lambda: _FakeMlflow(),
            resolve_mlflow_artifact_dir_fn=lambda _tracking_dir: tracking_dir / "artifacts",
            resolve_mlflow_backend_db_fn=lambda _tracking_dir: tracking_dir / "mlflow.db",
            ensure_mlflow_backend_ready_fn=lambda _tracking_dir: "sqlite:///mlflow.db",
            reset_mlflow_sqlite_backend_fn=lambda _db_path: None,
            default_experiment_name="Default",
            schema_reset_markers=("schema-reset",),
        )


def test_repair_mlflow_default_experiment_db_skips_internal_and_non_experiment_tables(tmp_path: Path):
    db_path = tmp_path / "mlflow.db"
    db_path.write_text("", encoding="utf-8")
    updates: list[tuple[str, tuple | None]] = []
    committed: list[bool] = []

    class _Result:
        def __init__(self, fetchall_rows=None, fetchone_row=None):
            self._fetchall_rows = fetchall_rows or []
            self._fetchone_row = fetchone_row

        def fetchall(self):
            return self._fetchall_rows

        def fetchone(self):
            return self._fetchone_row

    class _Conn:
        def execute(self, query, params=None):
            query = str(query)
            if query == "SELECT name FROM sqlite_master WHERE type='table'":
                return _Result(
                    fetchall_rows=[("experiments",), ("sqlite_shadow",), ("tags",)]
                )
            if query in {"PRAGMA table_info(experiments)", 'PRAGMA table_info("experiments")'}:
                return _Result(
                    fetchall_rows=[
                        (0, "experiment_id"),
                        (1, "name"),
                        (2, "artifact_location"),
                    ]
                )
            if query.startswith("SELECT experiment_id FROM experiments WHERE"):
                return _Result(fetchone_row=(5,))
            if query == "SELECT experiment_id, name FROM experiments WHERE experiment_id = 0":
                return _Result(fetchone_row=None)
            if query == 'PRAGMA table_info("tags")':
                return _Result(fetchall_rows=[(0, "key")])
            if query == "PRAGMA foreign_keys=OFF":
                updates.append((query, params))
                return _Result()
            if query.startswith("UPDATE"):
                updates.append((query, params))
                return _Result()
            raise AssertionError(f"Unexpected query: {query}")

        def commit(self):
            committed.append(True)

        def close(self):
            return None

    repaired = mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        artifact_uri="file:///artifacts",
        default_experiment_name="Default",
        sqlite_identifier_fn=mlflow_store.sqlite_identifier,
        connect_fn=lambda _path: _Conn(),
    )

    assert repaired is True
    assert committed == [True]
    assert all("sqlite_shadow" not in query for query, _params in updates)
    assert all('UPDATE "tags"' not in query for query, _params in updates)
    assert any(
        query == "UPDATE experiments SET artifact_location = ? WHERE experiment_id = 0"
        and params == ("file:///artifacts",)
        for query, params in updates
    )
