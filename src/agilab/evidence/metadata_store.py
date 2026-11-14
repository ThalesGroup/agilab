"""Transactional local metadata revisions; ingestion never promotes run results."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote

from agilab.evidence.evidence_contract import build_metadata_store_entry
from agilab.evidence.run_manifest import RunManifest

STORE_SCHEMA = "agilab.sqlite_metadata_store.v1"
_APPLICATION_ID = 0x4147494D
_VERSION = 1
_TABLES = (
    """CREATE TABLE IF NOT EXISTS runs (
        manifest_sha256 TEXT PRIMARY KEY CHECK(length(manifest_sha256)=64),
        run_id TEXT NOT NULL, run_status TEXT NOT NULL, created_at TEXT NOT NULL,
        ingested_at TEXT NOT NULL, manifest_bytes BLOB NOT NULL, entry_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS artifacts (
        manifest_sha256 TEXT NOT NULL REFERENCES runs(manifest_sha256),
        ordinal INTEGER NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
        recorded_sha256 TEXT NOT NULL, observed_sha256 TEXT NOT NULL,
        observation_json TEXT NOT NULL, PRIMARY KEY(manifest_sha256, ordinal))""",
    """CREATE TABLE IF NOT EXISTS validations (
        manifest_sha256 TEXT NOT NULL REFERENCES runs(manifest_sha256),
        ordinal INTEGER NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL,
        validation_json TEXT NOT NULL, PRIMARY KEY(manifest_sha256, ordinal))""",
    "CREATE INDEX IF NOT EXISTS runs_identity ON runs(run_id, created_at, manifest_sha256)",
)


def _check_database(connection: sqlite3.Connection, *, initialize: bool) -> None:
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if application_id == _APPLICATION_ID and version == _VERSION:
        return
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if not initialize or application_id or version or tables:
        raise ValueError(
            "Unsupported SQLite metadata store; use an AGILAB metadata database."
        )
    for statement in _TABLES:
        connection.execute(statement)
    connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version={_VERSION}")


def ingest_metadata_store(manifest_path: Path, store_path: Path) -> dict[str, Any]:
    """Read the manifest once, validate and hash those bytes, then atomically ingest.

    A repeated manifest retains its first observations. Artifact observations are
    snapshots at ingestion, not live assertions about the current filesystem.
    """
    manifest_path = manifest_path.expanduser().resolve()
    raw = manifest_path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Run manifest must contain a JSON object.")
    manifest = RunManifest.from_dict(payload)
    if not manifest.run_id:
        raise ValueError("Run manifest must have a nonempty run_id.")
    digest = hashlib.sha256(raw).hexdigest()
    entry = build_metadata_store_entry(manifest, manifest_path, manifest_bytes=raw)
    entry_json = json.dumps(entry, sort_keys=True, allow_nan=False)
    observed_at = datetime.now(timezone.utc).isoformat()
    store_path = store_path.expanduser()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(
        sqlite3.connect(store_path, timeout=5, isolation_level=None)
    ) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            _check_database(connection, initialize=True)
            prior = connection.execute(
                "SELECT entry_json FROM runs WHERE manifest_sha256=?", (digest,)
            ).fetchone()
            if prior is None:
                connection.execute(
                    "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                    (
                        digest,
                        manifest.run_id,
                        manifest.status,
                        manifest.created_at,
                        observed_at,
                        raw,
                        entry_json,
                    ),
                )
                connection.executemany(
                    "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?)",
                    [
                        (
                            digest,
                            i,
                            item["id"],
                            item["path"],
                            item["recorded_sha256"],
                            item["observed_sha256"],
                            json.dumps(item, sort_keys=True),
                        )
                        for i, item in enumerate(entry["artifacts"])
                    ],
                )
                connection.executemany(
                    "INSERT INTO validations VALUES (?,?,?,?,?)",
                    [
                        (
                            digest,
                            i,
                            item["label"],
                            item["status"],
                            json.dumps(item, sort_keys=True),
                        )
                        for i, item in enumerate(entry["validations"])
                    ],
                )
            else:
                entry = json.loads(prior[0])
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    return {
        "schema": STORE_SCHEMA,
        "status": "pass",
        "operation": "ingest",
        "inserted": prior is None,
        "manifest_sha256": digest,
        "run_id": manifest.run_id,
        "run_status": manifest.status,
        "entry": entry,
        "observation_scope": "first ingestion of these manifest bytes; not current filesystem verification",
    }


def query_metadata_store(
    store_path: Path,
    *,
    run_id: str | None = None,
    status: str | None = None,
    manifest_sha256: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a bounded, deterministic page from a newly opened read-only connection."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Query limit must be an integer from 1 to 1000.")
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or not 0 <= offset <= 1_000_000
    ):
        raise ValueError("Query offset must be an integer from 0 to 1000000.")
    clauses, values = [], []
    for column, value in (
        ("run_id", run_id),
        ("run_status", status),
        ("manifest_sha256", manifest_sha256),
    ):
        if value is not None:
            clauses.append(f"{column}=?")
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    uri = (
        "file:" + quote(str(store_path.expanduser().resolve()), safe="/:") + "?mode=ro"
    )
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA query_only=ON")
        _check_database(connection, initialize=False)
        rows = connection.execute(
            "SELECT manifest_sha256, ingested_at, entry_json FROM runs"
            + where
            + " ORDER BY created_at, run_id, manifest_sha256 LIMIT ? OFFSET ?",
            [*values, limit + 1, offset],
        ).fetchall()
    return {
        "schema": STORE_SCHEMA,
        "status": "pass",
        "operation": "query",
        "entries": [
            {
                "manifest_sha256": row[0],
                "ingested_at": row[1],
                "entry": json.loads(row[2]),
            }
            for row in rows[:limit]
        ],
        "limit": limit,
        "offset": offset,
        "has_more": len(rows) > limit,
        "observation_scope": "stored ingestion snapshots; not current filesystem verification",
    }
