"""Durability and exact-byte identity of the local SQLite evidence store."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from agilab.evidence import evidence_contract as cli
from agilab.evidence import metadata_store as store
from agilab.evidence.run_manifest import MANIFEST_KIND, SCHEMA_VERSION


def _manifest(tmp_path, *, status="pass", run_id="same-run", revision=1):
    tmp_path.mkdir(parents=True, exist_ok=True)
    artifact = tmp_path / "result.txt"
    artifact.write_text("original")
    path = tmp_path / "run_manifest.json"
    payload = {
        "kind": MANIFEST_KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": status,
        "label": f"revision {revision}",
        "path_id": "test",
        "created_at": "2026-11-13T10:00:00Z",
        "command": {"argv": [sys.executable]},
        "artifacts": [
            {
                "name": "result",
                "path": "result.txt",
                "kind": "file",
                "exists": True,
                "sha256": hashlib.sha256(b"original").hexdigest(),
            }
        ],
        "validations": [
            {"label": "result", "status": status, "summary": "recorded result"}
        ],
    }
    path.write_text(json.dumps(payload))
    return path


def test_reopen_deduplicate_revisions_and_failed_run(tmp_path):
    path = _manifest(tmp_path, status="fail")
    database = tmp_path / "evidence.sqlite"
    first = store.ingest_metadata_store(path, database)
    assert first["status"] == "pass" and first["run_status"] == "fail"
    assert store.ingest_metadata_store(path, database)["inserted"] is False
    _manifest(tmp_path, status="pass", revision=2)
    second = store.ingest_metadata_store(path, database)
    assert first["manifest_sha256"] != second["manifest_sha256"]
    rows = store.query_metadata_store(database, run_id="same-run")["entries"]
    assert len(rows) == 2
    assert {r["entry"]["status"] for r in rows} == {"pass", "fail"}
    assert len(store.query_metadata_store(database, status="fail")["entries"]) == 1
    assert [r["manifest_sha256"] for r in rows] == sorted(
        r["manifest_sha256"] for r in rows
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM validations").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_manifest_read_once_validated_and_hashed_from_same_bytes(tmp_path, monkeypatch):
    path = _manifest(tmp_path)
    payload = json.loads(path.read_bytes())
    payload["artifacts"].append(
        {"name": "manifest", "path": path.name, "kind": "manifest", "exists": True}
    )
    path.write_text(json.dumps(payload))
    original = path.read_bytes()
    read_bytes = Path.read_bytes
    calls = []

    def racing_read(self):
        data = read_bytes(self)
        if self == path:
            calls.append(self)
            self.write_text('{"replaced": true}')
        return data

    monkeypatch.setattr(Path, "read_bytes", racing_read)
    result = store.ingest_metadata_store(path, tmp_path / "evidence.sqlite")
    assert calls == [path]
    assert result["manifest_sha256"] == hashlib.sha256(original).hexdigest()
    assert (
        result["entry"]["artifacts"][1]["observed_sha256"] == result["manifest_sha256"]
    )
    with sqlite3.connect(tmp_path / "evidence.sqlite") as connection:
        assert (
            connection.execute("SELECT manifest_bytes FROM runs").fetchone()[0]
            == original
        )


def test_observations_preserve_recorded_hash_and_first_ingest(tmp_path):
    path = _manifest(tmp_path)
    (tmp_path / "result.txt").write_text("tampered")
    database = tmp_path / "evidence.sqlite"
    result = store.ingest_metadata_store(path, database)
    item = result["entry"]["artifacts"][0]
    assert (
        result["run_status"] == "pass"
    )  # Recorded outcome is not rewritten by metadata.
    assert item["status"] == "fail" and item["hash_verification"] == "mismatch"
    assert item["observed_sha256"] != item["recorded_sha256"]
    (tmp_path / "result.txt").write_text("original")
    duplicate = store.ingest_metadata_store(path, database)
    assert duplicate["entry"]["artifacts"][0] == item
    assert (
        store.query_metadata_store(database)["entries"][0]["entry"]["artifacts"][0]
        == item
    )


def test_concurrent_ingest_and_readers_observe_complete_transactions(tmp_path):
    path = _manifest(tmp_path)
    database = tmp_path / "evidence.sqlite"
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(lambda _: store.ingest_metadata_store(path, database), range(12))
        )
    assert sum(r["inserted"] for r in results) == 1
    assert len(store.query_metadata_store(database)["entries"]) == 1


def test_failed_transaction_rolls_back_and_recovers(tmp_path):
    path = _manifest(tmp_path)
    database = tmp_path / "evidence.sqlite"
    store.ingest_metadata_store(path, database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_artifact BEFORE INSERT ON artifacts "
            "BEGIN SELECT RAISE(ABORT, 'test insert failure'); END"
        )
    _manifest(tmp_path, revision=2)
    with pytest.raises(sqlite3.IntegrityError, match="test insert failure"):
        store.ingest_metadata_store(path, database)
    assert len(store.query_metadata_store(database)["entries"]) == 1
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_artifact")
    assert store.ingest_metadata_store(path, database)["inserted"] is True
    assert len(store.query_metadata_store(database)["entries"]) == 2


def test_parameterized_queries_bounds_paging_and_no_query_creation(tmp_path):
    database = tmp_path / "evidence.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        store.query_metadata_store(database)
    assert not database.exists()
    for run_id in ["a", "b", "c"]:
        store.ingest_metadata_store(
            _manifest(tmp_path / run_id, run_id=run_id), database
        )
    assert store.query_metadata_store(database, run_id="' OR 1=1 --")["entries"] == []
    first = store.query_metadata_store(database, limit=2)
    assert first["has_more"] is True
    second = store.query_metadata_store(database, limit=2, offset=2)
    assert [r["entry"]["run_id"] for r in first["entries"] + second["entries"]] == [
        "a",
        "b",
        "c",
    ]
    assert second["has_more"] is False
    for value in [0, -1, 1001, True, "1"]:
        with pytest.raises(ValueError):
            store.query_metadata_store(database, limit=value)
    with pytest.raises(ValueError):
        store.query_metadata_store(database, offset=-1)


def test_existing_reader_gets_fresh_revisions(tmp_path):
    path = _manifest(tmp_path)
    database = tmp_path / "evidence.sqlite"
    store.ingest_metadata_store(path, database)
    assert len(store.query_metadata_store(database)["entries"]) == 1
    _manifest(tmp_path, revision=2)
    store.ingest_metadata_store(path, database)
    assert len(store.query_metadata_store(database)["entries"]) == 2


def test_invalid_manifest_and_unrelated_database_are_rejected(tmp_path):
    path = _manifest(tmp_path)
    database = tmp_path / "evidence.sqlite"
    path.write_text("{}")
    with pytest.raises(ValueError):
        store.ingest_metadata_store(path, database)
    assert not database.exists()
    path = _manifest(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated (id)")
    with pytest.raises(ValueError, match="Unsupported SQLite"):
        store.ingest_metadata_store(path, database)


def test_real_cli_ingest_reopen_query_and_legacy_json(tmp_path):
    path = _manifest(tmp_path, status="fail")
    database = tmp_path / "evidence.sqlite"

    def run(*args):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agilab.evidence.evidence_contract",
                "metadata-store",
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    first = run(str(path), "--store", str(database), "--sqlite", "--json")
    queried = run("--store", str(database), "--sqlite", "--mode", "query", "--json")
    assert (
        first["run_status"] == "fail"
        and queried["entries"][0]["entry"]["status"] == "fail"
    )
    legacy = run(str(path), "--store", str(tmp_path / "legacy.json"), "--json")
    assert legacy["schema"] == cli.METADATA_STORE_SCHEMA and legacy["entry_count"] == 1


def test_cli_help_and_invalid_modes(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["metadata-store", "--help"])
    assert exc.value.code == 0
    assert "--sqlite" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main(["metadata-store", "--store", str(tmp_path / "db"), "--mode", "query"])
    assert exc.value.code == 2


def test_reader_during_write_observes_committed_snapshot_then_refreshes(
    tmp_path, monkeypatch
):
    from threading import Event

    path = _manifest(tmp_path)
    database = tmp_path / "evidence.sqlite"
    store.ingest_metadata_store(path, database)
    _manifest(tmp_path, revision=2)
    entered, release = Event(), Event()
    original = store._check_database

    def pause(connection, *, initialize):
        original(connection, initialize=initialize)
        if initialize:
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(store, "_check_database", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(store.ingest_metadata_store, path, database)
        try:
            assert entered.wait(5)
            assert len(store.query_metadata_store(database)["entries"]) == 1
        finally:
            release.set()
        assert future.result(timeout=5)["inserted"] is True
    assert len(store.query_metadata_store(database)["entries"]) == 2


@pytest.mark.parametrize("module", ["agilab", "agilab.evidence.evidence_contract"])
def test_existing_root_cli_metadata_namespace_remains_compatible(tmp_path, module):
    path = _manifest(tmp_path, status="fail")
    command = [
        sys.executable,
        "-m",
        module,
        "metadata-store",
        str(path),
        "--sqlite",
        "--store",
        str(tmp_path / "metadata.sqlite"),
        "--json",
    ]
    result = subprocess.run(
        command, text=True, capture_output=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["run_status"] == "fail"
