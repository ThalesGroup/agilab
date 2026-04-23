from __future__ import annotations

from pathlib import Path


def test_pipeline_docs_sell_runnable_supervisor_notebook_export() -> None:
    experiment_help = Path("docs/source/experiment-help.rst").read_text(encoding="utf-8")

    assert "runnable supervisor notebook" in experiment_help
    assert "outside the AGILAB UI" in experiment_help
    assert "exported_notebooks/<module>/lab_steps.ipynb" in experiment_help


def test_agilab_help_mentions_pipeline_notebook_export() -> None:
    agilab_help = Path("docs/source/agilab-help.rst").read_text(encoding="utf-8")

    assert "export a runnable supervisor notebook" in agilab_help
    assert "outside the AGILAB UI" in agilab_help
