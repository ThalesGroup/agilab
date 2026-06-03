from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path.home() / "log" / "execute" / "voila_notebook_proof"
SCHEMA = "agilab.example.voila_notebook_proof.evidence.v1"
CREATED_AT = "2026-01-01T00:00:00Z"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, *, output_dir: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(output_dir)),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def sample_notebook() -> dict[str, Any]:
    """Return a small Voila-shaped notebook without importing runtime deps."""
    return {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Sales risk dashboard\n",
                    "\n",
                    "This notebook keeps the interactive dashboard surface familiar while the "
                    "AGILAB bridge extracts app arguments, code boundaries, and evidence.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"agilab": {"role": "app_ui", "hide_input": True}},
                "outputs": [],
                "source": [
                    "import ipywidgets as widgets\n",
                    "region = widgets.Dropdown(options=['EU', 'NA', 'APAC'], value='EU', description='Region')\n",
                    "min_margin = widgets.FloatSlider(value=0.18, min=0.0, max=0.5, step=0.01, description='Margin')\n",
                    "include_forecast = widgets.Checkbox(value=True, description='Forecast')\n",
                    "widgets.VBox([region, min_margin, include_forecast])\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"agilab": {"role": "worker_logic"}},
                "outputs": [],
                "source": [
                    "def score_region(rows, *, region, min_margin, include_forecast):\n",
                    "    selected = [row for row in rows if row['region'] == region]\n",
                    "    risky = [row for row in selected if row['margin'] < min_margin]\n",
                    "    return {\n",
                    "        'region': region,\n",
                    "        'rows': len(selected),\n",
                    "        'risky_rows': len(risky),\n",
                    "        'forecast_enabled': include_forecast,\n",
                    "    }\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"agilab": {"role": "analysis_output", "hide_input": True}},
                "outputs": [],
                "source": [
                    "rows = [\n",
                    "    {'region': 'EU', 'margin': 0.14},\n",
                    "    {'region': 'EU', 'margin': 0.22},\n",
                    "    {'region': 'NA', 'margin': 0.19},\n",
                    "]\n",
                    "score_region(rows, region=region.value, min_margin=min_margin.value, include_forecast=include_forecast.value)\n",
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {"agilab": {"role": "evidence_note"}},
                "source": [
                    "AGILAB can keep this notebook as the stakeholder-facing dashboard while "
                    "promoting stable widgets into app arguments and recording hashes for "
                    "the notebook, generated view plan, and evidence sidecars.\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
            "agilab": {
                "preview": "voila_notebook_proof",
                "optional_runtime": "voila",
                "runtime_required_for_preview": False,
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def widget_to_args_contract() -> dict[str, Any]:
    return {
        "schema": "agilab.example.voila_notebook_proof.widget_to_args.v1",
        "source": "dashboard.ipynb",
        "app_args": {
            "region": {
                "widget": "Dropdown",
                "type": "str",
                "default": "EU",
                "choices": ["EU", "NA", "APAC"],
            },
            "min_margin": {
                "widget": "FloatSlider",
                "type": "float",
                "default": 0.18,
                "minimum": 0.0,
                "maximum": 0.5,
            },
            "include_forecast": {
                "widget": "Checkbox",
                "type": "bool",
                "default": True,
            },
        },
        "migration_hint": (
            "Promote stable ipywidgets to app_args_form.py fields; keep "
            "notebook-only presentation cells inside the app project."
        ),
    }


def hidden_code_manifest() -> dict[str, Any]:
    return {
        "schema": "agilab.example.voila_notebook_proof.hidden_code.v1",
        "source": "dashboard.ipynb",
        "cells": [
            {"index": 1, "role": "app_ui", "hide_input": True},
            {"index": 2, "role": "worker_logic", "hide_input": False},
            {"index": 3, "role": "analysis_output", "hide_input": True},
            {"index": 4, "role": "evidence_note", "hide_input": False},
        ],
        "note": (
            "The preview records the hide-code contract as data. A future "
            "Voila runtime can apply the same contract when serving the notebook."
        ),
    }


def app_view_plan() -> dict[str, Any]:
    return {
        "schema": "agilab.example.voila_notebook_proof.app_view_plan.v1",
        "current_preview": True,
        "target_app": "sales_dashboard_project",
        "app_owned_files": [
            "notebooks/dashboard.ipynb",
            "src/app_args_form.py",
            "src/sales_dashboard/worker_logic.py",
            "src/sales_dashboard/app_surface.py",
        ],
        "shared_pages_boundary": [
            {
                "component": "view_app_ui",
                "responsibility": (
                    "Generic AGILAB surface that opens an app-declared UI entrypoint; "
                    "it must not know sales-dashboard semantics."
                ),
            }
        ],
        "notebook_user_path": [
            "Keep the existing notebook dashboard visible.",
            "Extract stable widgets into AGILAB app arguments.",
            "Move reusable compute cells into worker code.",
            "Write evidence and artifact hashes on every run.",
        ],
        "future_command": "agilab notebook-proof dashboard.ipynb --app-name sales_dashboard",
    }


def _html_preview(*, contract: dict[str, Any], plan: dict[str, Any]) -> str:
    fields = "\n".join(
        f"<li><code>{name}</code>: {spec['widget']} -> {spec['type']}</li>"
        for name, spec in contract["app_args"].items()
    )
    steps = "\n".join(f"<li>{step}</li>" for step in plan["notebook_user_path"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>AGILAB Voila notebook proof preview</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; color: #172033; }}
    main {{ max-width: 860px; }}
    code {{ background: #eef2f7; padding: 0.1rem 0.25rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <main>
    <h1>Voila notebook proof preview</h1>
    <p>This static preview shows the migration contract before any Voila server integration.</p>
    <h2>Widget to app arguments</h2>
    <ul>{fields}</ul>
    <h2>Adoption path</h2>
    <ol>{steps}</ol>
  </main>
</body>
</html>
"""


def build_preview(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    notebook = sample_notebook()
    contract = widget_to_args_contract()
    hidden_manifest = hidden_code_manifest()
    plan = app_view_plan()

    paths = {
        "dashboard_notebook": output_dir / "dashboard.ipynb",
        "widget_to_args": output_dir / "widget_to_args.json",
        "hidden_code_manifest": output_dir / "hidden_code_manifest.json",
        "app_view_plan": output_dir / "agilab_app_view_plan.json",
        "static_preview": output_dir / "dashboard_app_preview.html",
    }

    _write_json(paths["dashboard_notebook"], notebook)
    _write_json(paths["widget_to_args"], contract)
    _write_json(paths["hidden_code_manifest"], hidden_manifest)
    _write_json(paths["app_view_plan"], plan)
    paths["static_preview"].write_text(
        _html_preview(contract=contract, plan=plan),
        encoding="utf-8",
    )

    evidence = {
        "schema": SCHEMA,
        "created_at": CREATED_AT,
        "source_runtime": "voila",
        "voila_dependency_required_for_preview": False,
        "optional_runtime": "voila",
        "future_extra": "agilab[voila]",
        "future_command": plan["future_command"],
        "artifacts": {
            name: _artifact(path, output_dir=output_dir)
            for name, path in paths.items()
        },
        "current_limits": [
            "This preview does not launch a Voila server.",
            "It does not execute ipywidgets or notebook kernels.",
            "It records the migration and evidence contracts as deterministic files.",
        ],
    }
    evidence_path = output_dir / "voila_notebook_evidence.json"
    _write_json(evidence_path, evidence)

    summary = dict(evidence)
    summary["artifacts"] = dict(evidence["artifacts"])
    summary["artifacts"]["evidence"] = _artifact(evidence_path, output_dir=output_dir)
    summary["output_dir"] = str(output_dir)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a deterministic AGILAB preview for Voila notebook users."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for generated preview artifacts. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the summary as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = build_preview(output_dir=args.output_dir)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Wrote Voila notebook proof preview to {summary['output_dir']}")
        print(f"Evidence: {summary['artifacts']['evidence']['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
