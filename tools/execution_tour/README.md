# AGILAB execution tour

Build a five-step walkthrough from project selection through preparation, worker
execution, manifest recording, and evidence verification:

```sh
uv run --no-project python tools/execution_tour/build_execution_tour.py
uv run --no-project python tools/execution_tour/build_execution_tour.py --check
```

Open `reports/execution-tour/index.html` in a browser. The page works offline:
its implementation and test links jump to captured, numbered source definitions.
Native disclosure controls reveal the code without JavaScript, a server, or a CDN.
`tour.json` contains the same tour as `agilab.execution-tour.v1` data. Keep the two
files together when sharing. Generated files stay under ignored `reports/`.
Use `--output-dir PATH` for another destination, including with `--check`.

The tour covers **`tools/newcomer_first_proof.py --with-run` in a source checkout**.
The packaged first-proof CLI is a separate entry point. Preview the underlying
source-checkout commands without running installation or workers:

```sh
uv run --no-project python tools/newcomer_first_proof.py --with-run --print-only
```

Generating the tour does not execute these commands. Running the actual proof
requires AGILAB's installation, data, and runtime prerequisites. The default
manifest path is `~/log/execute/flight_telemetry/run_manifest.json`; `AGILAB_LOG_ABS`
changes the log root, and the proof command supports `--manifest-out`.

## Source and freshness contract

- Definition names and line ranges are resolved with Python's AST, including
  qualified class methods. A missing or ambiguous symbol stops generation.
- Purpose, order, and source/test relationships are curated interpretations.
  Package responsibilities reuse `tools/render_package_maps.py` declarations.
  Neither relationship is presented as a dynamically observed call edge.
- The snapshot lists repository-relative paths, byte sizes, and SHA-256 hashes
  for referenced files, the generator, the HTML template, and the package maps.
  Its ID hashes that sorted inventory. No timestamps or absolute checkout paths
  enter the artifact, so identical inputs produce identical files across clones.
- `--check` is read-only. It regenerates expected content in memory and fails on
  source drift, missing symbols, missing outputs, or edited JSON/HTML. Unrelated
  files and Git-only changes do not make the tour stale.
- Source hashes establish correspondence to local bytes. They do not establish
  author authenticity, test success, runtime success, or scientific validity.
  The first-proof manifest verifier's artifact-presence checks are distinct from
  this tour's source-byte checks.

The snapshot is scoped to the explicitly linked files; it is not a complete
repository dependency graph. Extend `STEPS` with source and test selectors when
the maintained first-proof path changes, then regenerate and validate:

```sh
uv run pytest -q -o addopts='' test/test_execution_tour.py test/test_tools_surface_contract.py test/test_agilab_capabilities_manifest.py test/test_agenticweb_manifest.py
```

When changing the tour's schema or schema-bearing file paths, regenerate the
discovery inventory and its derived front door in dependency order:

```sh
uv run --no-project python tools/agilab_capabilities_manifest.py --apply
uv run --no-project python tools/agenticweb_manifest.py --apply
```
