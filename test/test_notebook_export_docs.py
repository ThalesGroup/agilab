from __future__ import annotations

from pathlib import Path


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


def test_agilab_help_mentions_pipeline_notebook_export() -> None:
    agilab_help = Path("docs/source/agilab-help.rst").read_text(encoding="utf-8")

    assert "export a runnable supervisor notebook" in agilab_help
    assert "work remains reusable outside the AGILAB UI" in agilab_help
    assert "no-lock-in copy of the pipeline" in agilab_help
