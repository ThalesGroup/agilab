from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Sequence


DEFAULT_OUTPUT_DIR = Path.home() / "log" / "execute" / "sqlite_connector_proof"
SCHEMA = "agilab.example.sqlite_connector_proof.evidence.v1"
CREATED_AT = "2026-01-01T00:00:00Z"

SCHEMA_SQL = (
    """
    CREATE TABLE experiment_runs (
        run_id TEXT PRIMARY KEY,
        app TEXT NOT NULL,
        dataset TEXT NOT NULL,
        accuracy REAL NOT NULL,
        latency_ms REAL NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE quality_gates (
        run_id TEXT NOT NULL REFERENCES experiment_runs(run_id),
        gate TEXT NOT NULL,
        threshold REAL NOT NULL,
        passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
        PRIMARY KEY (run_id, gate)
    )
    """,
)

EXPERIMENT_RUNS = (
    ("run-001", "flight_telemetry_project", "flight-demo", 0.918, 42.4, "2026-01-01T00:00:00Z"),
    ("run-002", "weather_forecast_project", "weather-demo", 0.934, 58.1, "2026-01-01T00:01:00Z"),
    ("run-003", "mission_decision_project", "mission-demo", 0.901, 35.7, "2026-01-01T00:02:00Z"),
    ("run-004", "pytorch_playground_project", "circles", 0.947, 64.8, "2026-01-01T00:03:00Z"),
)

QUALITY_GATES = (
    ("run-001", "promotion_gate", 0.91, 1),
    ("run-002", "promotion_gate", 0.91, 1),
    ("run-003", "promotion_gate", 0.91, 0),
    ("run-004", "promotion_gate", 0.91, 1),
)

QUERY = """
SELECT
    r.run_id,
    r.app,
    r.dataset,
    ROUND(r.accuracy, 4) AS accuracy,
    ROUND(r.latency_ms, 1) AS latency_ms,
    q.gate
FROM experiment_runs AS r
JOIN quality_gates AS q ON q.run_id = r.run_id
WHERE r.accuracy >= :min_accuracy
  AND q.passed = 1
ORDER BY r.accuracy DESC, r.run_id ASC
"""


def _hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_sql(sql: str) -> str:
    return " ".join(sql.split())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "sha256": _hash_file(path),
    }


def _seed_database(path: Path) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    with sqlite3.connect(path) as connection:
        for statement in SCHEMA_SQL:
            connection.execute(statement)
        connection.executemany(
            """
            INSERT INTO experiment_runs
                (run_id, app, dataset, accuracy, latency_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            EXPERIMENT_RUNS,
        )
        connection.executemany(
            """
            INSERT INTO quality_gates
                (run_id, gate, threshold, passed)
            VALUES (?, ?, ?, ?)
            """,
            QUALITY_GATES,
        )
        connection.commit()

    return {
        "experiment_run_count": len(EXPERIMENT_RUNS),
        "quality_gate_count": len(QUALITY_GATES),
    }


def _schema_sql(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """
            SELECT name, sql
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    return "\n".join(f"{name}: {_normalise_sql(sql)}" for name, sql in rows)


def _query_database(path: Path, *, min_accuracy: float) -> tuple[list[str], list[dict[str, Any]]]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(QUERY, {"min_accuracy": float(min_accuracy)})
        columns = [description[0] for description in cursor.description]
        rows = [dict(row) for row in cursor.fetchall()]
    return columns, rows


def _write_csv(path: Path, *, columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)


def build_preview(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_accuracy: float = 0.91,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = output_dir / "sqlite_connector_proof.db"
    csv_path = output_dir / "promotion_candidates.csv"
    evidence_path = output_dir / "database_evidence.json"

    source_counts = _seed_database(db_path)
    columns, rows = _query_database(db_path, min_accuracy=min_accuracy)
    _write_csv(csv_path, columns=columns, rows=rows)

    schema_sql = _schema_sql(db_path)
    query_sql = _normalise_sql(QUERY)
    result_payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))

    evidence = {
        "schema": SCHEMA,
        "created_at": CREATED_AT,
        "example": "sqlite_connector_proof",
        "goal": "Show a local SQL database connector proof with reproducible query evidence.",
        "connector": {
            "id": "local_sqlite_proof",
            "kind": "sql",
            "driver": "sqlite",
            "uri": f"sqlite:///{db_path}",
            "query_mode": "read_only",
            "network_required": False,
            "secrets_required": False,
        },
        "database": {
            "path": str(db_path),
            "schema_sha256": _hash_text(schema_sql),
            "seed_counts": source_counts,
        },
        "query": {
            "sql_sha256": _hash_text(query_sql),
            "parameters": {"min_accuracy": float(min_accuracy)},
            "parameterized": True,
        },
        "result": {
            "columns": list(columns),
            "row_count": len(rows),
            "rows_sha256": _hash_text(result_payload),
        },
        "artifacts": {
            "database": _artifact(db_path),
            "csv": _artifact(csv_path),
            "evidence_json": {"path": str(evidence_path)},
        },
        "notes": [
            "The preview uses Python's sqlite3 standard-library driver.",
            "No external database server, network access, Docker image, or secret is required.",
            "Use the same evidence shape with a remote SQL connector only after an operator opts in.",
        ],
    }
    _write_json(evidence_path, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return evidence


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a deterministic AGILAB SQLite connector proof."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-accuracy", type=float, default=0.91)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    build_preview(output_dir=args.output_dir, min_accuracy=args.min_accuracy)


if __name__ == "__main__":
    main()
