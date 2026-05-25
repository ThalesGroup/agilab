# SQLite Connector Proof Example

## Purpose

Shows the smallest database-shaped AGILAB adoption bridge:

```text
SQLite database -> parameterized SQL query -> CSV result + JSON evidence
```

The preview is intentionally local and dependency-free. It creates a small
SQLite database, runs a read-only query, exports the result to CSV, and records
schema, query, and result hashes.

## What You Learn

- A database proof can be reproducible without a remote database server.
- AGILAB evidence should name the connector, driver, query mode, and artifact
  hashes instead of hiding database access inside app code.
- SQLite is the right public first step before Postgres, cloud warehouses, or
  private production data sources.
- Remote SQL connectors should remain explicit operator opt-ins because they
  need credentials, network reachability, and deployment threat modeling.

## Install

There is no separate project install for this preview. Install AGILAB first. The
script uses only the Python standard library.

## Run

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/sqlite_connector_proof/preview_sqlite_connector_proof.py
```

From an installed AGILAB package, locate the packaged script:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'sqlite_connector_proof' / 'preview_sqlite_connector_proof.py')"
```

Then run it:

```bash
python preview_sqlite_connector_proof.py
```

## Expected Input

The script creates deterministic local SQLite tables:

- `experiment_runs`
- `quality_gates`

It does not open a network connection, read a private database, or require
credentials.

## Expected Output

The script writes:

```text
~/log/execute/sqlite_connector_proof/sqlite_connector_proof.db
~/log/execute/sqlite_connector_proof/promotion_candidates.csv
~/log/execute/sqlite_connector_proof/database_evidence.json
```

Open `database_evidence.json` first. It records the connector ID, SQL driver,
read-only query mode, schema hash, query hash, row count, result hash, and
artifact hashes.

## Expected Preview

Read the output as a database proof contract:

| Artifact | Purpose |
|---|---|
| `sqlite_connector_proof.db` | Local database fixture with deterministic schema and rows. |
| `promotion_candidates.csv` | Result of the parameterized read-only SQL query. |
| `database_evidence.json` | Machine-readable connector, query, and artifact evidence. |

## Read The Script

Open `preview_sqlite_connector_proof.py` and look for these functions first:

- `_seed_database()` creates the deterministic SQLite database.
- `_query_database()` runs the parameterized SQL query.
- `build_preview()` writes the CSV and JSON evidence.

## Change One Thing

Run the preview with a stricter query threshold:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/sqlite_connector_proof/preview_sqlite_connector_proof.py --min-accuracy 0.94 --output-dir /tmp/agilab-sqlite-proof
```

Then compare `promotion_candidates.csv` and the `result.rows_sha256` value in
`database_evidence.json`.

## Troubleshooting

- If the output directory already contains an old database, the script replaces
  it to keep the proof deterministic.
- If you need Postgres or a cloud warehouse, keep this proof as the local
  contract first, then replace only the connector URI, driver, and operator
  credential boundary.
- If a live SQL connector contains credentials, never store them in the catalog
  or evidence. Reference them through an environment variable instead.
