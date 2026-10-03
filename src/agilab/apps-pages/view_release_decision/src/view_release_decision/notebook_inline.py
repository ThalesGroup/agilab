# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

"""Display recorded release evidence without recomputing the release gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from IPython.display import Markdown

from agi_pages.runtime import discover_files, load_json_object, relative_label


def render_inline(
    *, page: str, record: dict[str, Any], export_payload: dict[str, Any]
) -> list[Any]:
    outputs: list[Any] = [Markdown(f"### {record.get('label') or page}")]
    value = export_payload.get("artifact_dir")
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return outputs + [
            Markdown("No export artifact directory is recorded in this notebook.")
        ]
    root = Path(value)
    if not root.is_dir():
        return outputs + [Markdown(f"Missing artifact directory: `{root}`.")]
    manifests = discover_files(root, "**/run_manifest.json")
    metrics = discover_files(root, "**/*metrics*.json")
    if not manifests:
        outputs.append(
            Markdown(
                "Missing run_manifest.json; release verification status is unavailable."
            )
        )
    if not metrics:
        outputs.append(Markdown("No metric artifacts were found."))
    for title, paths in (
        ("Recorded run manifests", manifests),
        ("Recorded metrics", metrics),
    ):
        if paths:
            outputs.append(Markdown(f"**{title}**"))
        for path in paths:
            label = relative_label(path, root)
            payload = load_json_object(path)
            if not payload:
                outputs.append(
                    Markdown(f"Unable to read a JSON object from `{label}`.")
                )
                continue
            outputs.extend([Markdown(f"`{label}`"), pd.json_normalize(payload)])
    return outputs
