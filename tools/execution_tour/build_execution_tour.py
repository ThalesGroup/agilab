# BSD 3-Clause License
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Build a source-bound, offline tour of the source-checkout first-proof path."""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "agilab.execution-tour.v1"
PROOF = "tools/newcomer_first_proof.py"
PROOF_TEST = "test/test_newcomer_first_proof.py"
MANIFEST = "src/agilab/evidence/run_manifest.py"
EVIDENCE = "src/agilab/evidence/evidence_contract.py"
FLIGHT = "src/agilab/apps/builtin/flight_telemetry_project/src"
PRODUCER = "tools/execution_tour/build_execution_tour.py"
TEMPLATE = "tools/execution_tour/template.html"
MAPS = "tools/render_package_maps.py"

# Editorial sequence, not an inferred call graph. Selectors resolve against ASTs.
STEPS = (
    {
        "id": "project",
        "title": "Choose the project",
        "purpose": "Start with the built-in flight telemetry project. The proof tool checks "
        "that the selected app directory has a pyproject.toml; FlightArgs defines its typed inputs.",
        "inputs": "A source checkout and an active app directory.",
        "outputs": "A resolved app path; project-owned argument definitions.",
        "sources": (
            (PROOF, "resolve_active_app"),
            (f"{FLIGHT}/flight_telemetry/flight_args.py", "FlightArgs"),
        ),
        "tests": ((PROOF_TEST, "test_resolve_active_app_rejects_missing_pyproject"),),
    },
    {
        "id": "prepare",
        "title": "Prepare execution",
        "purpose": "The source-checkout --with-run option implies installation. The plan checks "
        "pre-initialization and the UI, installs the app, checks generated helpers and readiness, "
        "then appends the execution probe. --print-only previews this plan.",
        "inputs": "The active app and the --with-run option.",
        "outputs": "An ordered list of commands, including installation and execution checks.",
        "sources": ((PROOF, "build_proof_commands"), (PROOF, "_install_command")),
        "tests": ((PROOF_TEST, "test_main_print_only_with_run_implies_install"),),
    },
    {
        "id": "execute",
        "title": "Run the worker",
        "purpose": "The proof runner stops at the first failing command. Its execution probe "
        "launches the generated AGI_run_flight_telemetry.py helper; the telemetry worker's "
        "work_pool method handles a data item. The worker reference explains the implementation, "
        "rather than asserting a dynamically observed call edge.",
        "inputs": "Generated execution helper, installed worker, and configured telemetry data.",
        "outputs": "Command exit codes, captured output, elapsed time, and app-produced results.",
        "sources": (
            (PROOF, "run_proof"),
            (PROOF, "_execute_script_code"),
            (
                f"{FLIGHT}/flight_telemetry_worker/flight_telemetry_worker.py",
                "FlightTelemetryWorker.work_pool",
            ),
        ),
        "tests": (
            (PROOF_TEST, "test_build_proof_commands_with_run_adds_execute_probe"),
            (PROOF_TEST, "test_run_proof_stops_on_first_failure"),
        ),
    },
    {
        "id": "record",
        "title": "Record the result",
        "purpose": "The proof tool records command outcomes, timing, validation status, and "
        "existing artifacts in run_manifest.json, including failure results. Its default output "
        "directory is the configured log root followed by execute/flight_telemetry. "
        "--no-manifest disables this record.",
        "inputs": "Executed command results and the proof summary.",
        "outputs": "run_manifest.json; proof_steps and target_seconds validation results.",
        "sources": (
            (PROOF, "build_run_manifest"),
            (PROOF, "default_output_dir"),
            (MANIFEST, "write_run_manifest"),
        ),
        "tests": (
            (PROOF_TEST, "test_build_run_manifest_records_first_proof_contract"),
        ),
    },
    {
        "id": "verify",
        "title": "Inspect the evidence",
        "purpose": "The evidence verifier checks manifest structure, recorded status, declared "
        "artifact presence, and other evidence checks. Artifact presence alone does not prove "
        "content integrity or reproduce the run. Generating this tour neither runs the proof "
        "nor establishes that its tests pass.",
        "inputs": "The generated run manifest and its declared artifacts.",
        "outputs": "A verification report with individual check results.",
        "sources": ((EVIDENCE, "verify_manifest"), (MANIFEST, "manifest_passed")),
        "tests": (
            (
                "test/test_evidence_contract.py",
                "test_verify_manifest_and_standard_exports",
            ),
            (
                "test/test_evidence_contract.py",
                "test_verify_manifest_detects_missing_relative_artifact_and_unavailable_replay",
            ),
        ),
    },
)


class TourError(ValueError):
    """A missing, ambiguous, or stale tour input."""


def read_source(root: Path, relative: str) -> bytes:
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise TourError(f"Source must be repository-relative: {relative}")
    if any(
        part.is_symlink()
        for part in (path, *path.parents)
        if part != root and root in part.parents
    ):
        raise TourError(f"Symlink source is not supported: {relative}")
    try:
        path.resolve().relative_to(root.resolve())
        return path.read_bytes()
    except (OSError, ValueError) as exc:
        raise TourError(f"Cannot read source {relative}: {exc}") from exc


def locate_symbol(source: bytes, path: str, symbol: str) -> tuple[int, int, str]:
    """Resolve qualified definition names without importing application code."""
    text = source.decode("utf-8")
    matches = []

    def visit(node: ast.AST, scope: tuple[str, ...] = ()) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = (*scope, node.name)
            if ".".join(scope) == symbol:
                matches.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    try:
        visit(ast.parse(text, filename=path))
    except SyntaxError as exc:
        raise TourError(f"Cannot parse {path}: {exc.msg}") from exc
    if len(matches) != 1:
        raise TourError(
            f"Expected one definition of {path}:{symbol}; found {len(matches)}"
        )
    node = matches[0]
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    end = node.end_lineno
    return start, end, "\n".join(text.splitlines()[start - 1 : end])


def load_package_maps():
    # Reuse the existing responsibility declarations; never import app code.
    name = "agilab_execution_tour_package_maps"
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / MAPS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def package_context(path: str, maps) -> list[dict[str, str]]:
    result = []
    for package in maps.PACKAGE_MAPS:
        prefix = package.source_root.relative_to(maps.REPO_ROOT)
        try:
            relative = Path(path).relative_to(prefix)
        except ValueError:
            continue
        for group in package.groups:
            if any(relative.match(pattern) for pattern in group.patterns):
                result.append(
                    {
                        "package": package.title,
                        "group": group.title,
                        "note": group.note,
                        "basis": "curated-package-map",
                        "source": MAPS,
                    }
                )
    return result


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def build_tour(root: Path = REPO_ROOT) -> dict:
    root = root.resolve()
    inputs = {path: read_source(root, path) for path in (PRODUCER, TEMPLATE, MAPS)}
    if inputs[MAPS] != read_source(REPO_ROOT, MAPS):
        raise TourError(
            "Package-map implementation differs; run the generator from the target checkout"
        )
    maps = load_package_maps()
    steps = []
    references = {}
    for declared in STEPS:
        step = {
            key: value
            for key, value in declared.items()
            if key not in ("sources", "tests")
        }
        step["basis"] = "curated-interpretation"
        for role in ("sources", "tests"):
            step[role] = []
            for path, symbol in declared[role]:
                if path not in inputs:
                    inputs[path] = read_source(root, path)
                start, end, excerpt = locate_symbol(inputs[path], path, symbol)
                ref_id = (
                    "source-"
                    + hashlib.sha256(f"{path}:{symbol}".encode()).hexdigest()[:16]
                )
                references[ref_id] = {
                    "id": ref_id,
                    "path": path,
                    "symbol": symbol,
                    "start_line": start,
                    "end_line": end,
                    "excerpt": excerpt,
                    "basis": "parsed-source",
                    "package_context": package_context(path, maps),
                }
                step[role].append(ref_id)
        steps.append(step)
    files = [
        {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for path, data in sorted(inputs.items())
    ]
    return {
        "schema": SCHEMA,
        "producer": {
            "path": PRODUCER,
            "version": 1,
            "command": "uv run --no-project python tools/execution_tour/build_execution_tour.py",
        },
        "snapshot": {
            "id": hashlib.sha256(json_bytes(files)).hexdigest(),
            "files": files,
        },
        "title": "From project to evidence",
        "description": "A guided tour of AGILAB's source-checkout first-proof workflow.",
        "scope": "Source-checkout tools/newcomer_first_proof.py --with-run. "
        "The packaged first-proof CLI is a separate entry point.",
        "limitations": "Source locations are parsed facts. Explanations, package responsibilities, "
        "and step order are curated interpretations, not a complete call graph or an execution trace. "
        "Linked tests are source references, not passing-test evidence. Freshness checks bind this "
        "artifact to the listed source bytes; they do not certify a run or authenticate the author.",
        "steps": steps,
        "references": list(references.values()),
    }


def render_html(tour: dict, template: str) -> str:
    escape = html.escape
    references = {ref["id"]: ref for ref in tour["references"]}
    nav, cards, sources = [], [], []
    for number, step in enumerate(tour["steps"], 1):
        nav.append(
            f'<li><a href="#{escape(step["id"])}">{number:02d} {escape(step["title"])}</a></li>'
        )
        sections = []
        for role, title in (("sources", "Implementation"), ("tests", "Related tests")):
            links = "".join(
                f'<li><a href="#{ref_id}">{escape(references[ref_id]["symbol"])}</a>'
                f"<small>{escape(references[ref_id]['path'])}</small></li>"
                for ref_id in step[role]
            )
            sections.append(f"<div><h3>{title}</h3><ul>{links}</ul></div>")
        next_link = (
            f'<a href="#{tour["steps"][number]["id"]}">Next step →</a>'
            if number < len(tour["steps"])
            else '<a href="#snapshot">Inspect the source snapshot →</a>'
        )
        cards.append(
            f'<section class="step" id="{escape(step["id"])}">'
            f'<p class="eyebrow">STEP {number:02d} · GUIDED INTERPRETATION</p>'
            f"<h2>{escape(step['title'])}</h2><p>{escape(step['purpose'])}</p>"
            f"<dl><dt>Inputs</dt><dd>{escape(step['inputs'])}</dd>"
            f"<dt>Outputs</dt><dd>{escape(step['outputs'])}</dd></dl>"
            f'<div class="references">{"".join(sections)}</div>{next_link}</section>'
        )
    for ref in tour["references"]:
        contexts = "".join(
            f'<p class="context">{escape(c["package"])} / {escape(c["group"])}: '
            f"{escape(c['note'])} (curated package map)</p>"
            for c in ref["package_context"]
        )
        lines = "\n".join(
            f"{number:4d}  {escape(line)}"
            for number, line in enumerate(
                ref["excerpt"].splitlines(), ref["start_line"]
            )
        )
        sources.append(
            f'<article class="source" id="{ref["id"]}"><h3>{escape(ref["symbol"])}</h3>'
            f"<p><code>{escape(ref['path'])}:{ref['start_line']}–{ref['end_line']}</code></p>"
            f"{contexts}<details><summary>View captured source · parsed definition</summary>"
            f'<pre><code>{lines}</code></pre></details><a href="#top">Back to tour</a></article>'
        )
    values = {
        "title": escape(tour["title"]),
        "description": escape(tour["description"]),
        "scope": escape(tour["scope"]),
        "limitations": escape(tour["limitations"]),
        "snapshot_id": escape(tour["snapshot"]["id"]),
        "nav": "".join(nav),
        "steps": "".join(cards),
        "sources": "".join(sources),
    }
    # Substitute once: source text that resembles a template marker remains literal.
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda match: values[match[1]], template)


def expected_artifacts(root: Path = REPO_ROOT) -> dict[str, bytes]:
    tour = build_tour(root)
    template = read_source(root, TEMPLATE).decode("utf-8")
    artifacts = {
        "tour.json": json_bytes(tour),
        "index.html": render_html(tour, template).encode("utf-8"),
    }
    for entry in tour["snapshot"]["files"]:
        if (
            hashlib.sha256(read_source(root, entry["path"])).hexdigest()
            != entry["sha256"]
        ):
            raise TourError(f"Source changed during generation: {entry['path']}; retry")
    return artifacts


def write_or_check(
    output: Path, *, check: bool = False, root: Path = REPO_ROOT
) -> None:
    artifacts = expected_artifacts(root)
    if check:
        stale = [
            name
            for name, data in artifacts.items()
            if not (output / name).is_file() or (output / name).read_bytes() != data
        ]
        if stale:
            raise TourError(
                "Missing or stale tour artifacts: "
                + ", ".join(stale)
                + "; regenerate the tour"
            )
        return
    output.mkdir(parents=True, exist_ok=True)
    for name in artifacts:
        path = output / name
        if path.is_symlink():
            raise TourError(f"Refusing to overwrite an output symlink: {path}")
    for name, data in artifacts.items():
        (output / name).write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=REPO_ROOT / "reports" / "execution-tour"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only freshness and generated-content check.",
    )
    args = parser.parse_args(argv)
    try:
        write_or_check(args.output_dir, check=args.check)
    except (TourError, OSError, UnicodeError) as exc:
        print(f"Execution tour: {exc}", file=sys.stderr)
        return 1
    print(
        f"Execution tour {'is current' if args.check else 'written'}: {args.output_dir / 'index.html'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
