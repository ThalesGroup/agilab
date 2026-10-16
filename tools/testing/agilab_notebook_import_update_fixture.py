"""Deterministic native import surface for the reviewed-update browser robot.

This fixture uses the production uploader callback and complete import renderer.
It never runs notebook code or calls a provider. The robot owns the temporary
project named by AGILAB_NOTEBOOK_UPDATE_ROBOT_PROJECT.
"""

from __future__ import annotations

import os
from pathlib import Path

from agi_web import python_ui as st

from agilab.pipeline import pipeline_editor as editor


INDEX_PAGE = "notebook_reviewed_update_robot"
UPLOAD_KEY = "notebook_reviewed_update_robot_upload"


def main() -> None:
    project_value = os.environ.get("AGILAB_NOTEBOOK_UPDATE_ROBOT_PROJECT")
    if not project_value:
        raise RuntimeError("This fixture requires an explicitly owned robot project.")
    project = Path(project_value).resolve(strict=True)
    stages_file = project / "lab_stages.toml"
    if not stages_file.is_file():
        raise RuntimeError("The robot project must already contain its stage contract.")

    st.set_page_config(page_title="Notebook update review", layout="wide")
    st.title("Review changes to a notebook import")
    st.caption(
        "Deterministic browser fixture using AGILAB's native import controls. "
        "Notebook code is not executed and no provider is called."
    )

    def preview_upload() -> None:
        editor.on_preview_notebook_import(
            UPLOAD_KEY,
            project,
            INDEX_PAGE,
            stages_file=stages_file,
            module_name=project.name,
        )

    st.file_uploader(
        "Source notebook",
        type=["ipynb"],
        key=UPLOAD_KEY,
        on_change=preview_upload,
    )
    editor.render_notebook_import_preview(
        project,
        stages_file,
        INDEX_PAGE,
        container=st,
        on_cancel=lambda: st.caption("Notebook preview cancelled."),
    )


main()
