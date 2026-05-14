from __future__ import annotations

from pathlib import Path


def _compact(text: str) -> str:
    return " ".join(text.split())


def test_pipeline_docs_sell_runnable_supervisor_notebook_export() -> None:
    experiment_help = Path("docs/source/experiment-help.rst").read_text(encoding="utf-8")

    assert "runnable supervisor notebook" in experiment_help
    assert "outside the AGILAB UI" in experiment_help
    assert "avoid lock-in" in experiment_help
    assert "you do not lose the work" in experiment_help
    assert "Use notebook export when you want a durable exit path" in experiment_help
    assert "<app-project>/notebooks/lab_stages.ipynb" in experiment_help
    assert "uv --project \"$APP_PROJECT\" run --with jupyterlab jupyter lab" in experiment_help
    assert (
        "uv --project \"$APP_PROJECT\" run --with nbconvert python -m jupyter nbconvert"
        in experiment_help
    )


def test_readme_leads_with_anti_lock_in_notebook_export_value() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    headline_window = readme[readme.index("# AGILAB") : readme.index("## Core Flow")]

    assert "anti-lock-in reproducibility workbench" in headline_window
    assert "exported back to a runnable notebook" in headline_window
    assert "you do not lose your work" in headline_window
    assert "runnable outside AGILAB as exported notebooks" in headline_window


def test_docs_overview_leads_with_no_lock_in_notebook_export_value() -> None:
    index = Path("docs/source/index.rst").read_text(encoding="utf-8")
    architecture = Path("docs/source/architecture-five-minutes.rst").read_text(
        encoding="utf-8"
    )
    compact_index = _compact(index)
    compact_architecture = _compact(architecture)

    assert "controlled AI/ML experimentation without lock-in" in compact_index
    assert "export the work back to runnable notebooks" in compact_index
    assert "anti-lock-in reproducibility workbench" in compact_architecture
    assert "workflows can be exported back to runnable notebooks" in compact_architecture


def test_agilab_help_mentions_pipeline_notebook_export() -> None:
    agilab_help = Path("docs/source/agilab-help.rst").read_text(encoding="utf-8")

    assert "export a runnable supervisor notebook" in agilab_help
    assert "work remains reusable outside the AGILAB UI" in agilab_help
    assert "no-lock-in copy of the pipeline" in agilab_help
