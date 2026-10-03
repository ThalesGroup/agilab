# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

"""Recorded IO/replanning decisions and their paired pipeline evidence."""

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
    summaries = discover_files(root, "**/*_summary_metrics.json")
    if not summaries:
        return outputs + [
            Markdown("No decision summaries were found in the exported artifacts.")
        ]
    for path in summaries:
        label = relative_label(path, root)
        summary = load_json_object(path)
        if not summary:
            outputs.append(
                Markdown(f"Unable to read a decision summary from `{label}`.")
            )
            continue
        outputs.extend([Markdown(f"**{label}**"), pd.json_normalize(summary)])
        stem = path.name.removesuffix("_summary_metrics.json")
        for suffix, key in (
            ("generated_pipeline", "stages"),
            ("mission_decision", "applied_events"),
        ):
            peer = path.with_name(f"{stem}_{suffix}.json")
            payload = load_json_object(peer)
            if not payload:
                outputs.append(
                    Markdown(
                        f"Missing or invalid decision artifact: `{relative_label(peer, root)}`."
                    )
                )
                continue
            rows = payload.get(key)
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) for row in rows
            ):
                outputs.append(
                    Markdown(f"Unable to read `{key}` records from `{peer.name}`.")
                )
                continue
            outputs.extend(
                [
                    Markdown(f"**{key.replace('_', ' ').title()}**"),
                    pd.json_normalize(rows),
                ]
            )
        for suffix in ("candidate_routes", "decision_timeline"):
            peer = path.with_name(f"{stem}_{suffix}.csv")
            if not peer.is_file():
                outputs.append(
                    Markdown(
                        f"Missing decision artifact: `{relative_label(peer, root)}`."
                    )
                )
                continue
            try:
                frame = pd.read_csv(peer)
            except (OSError, ValueError, TypeError) as exc:
                outputs.append(Markdown(f"Unable to read `{peer.name}`: {exc}"))
                continue
            outputs.extend(
                [Markdown(f"**{suffix.replace('_', ' ').title()}**"), frame.head(1000)]
            )
            if len(frame) > 1000:
                outputs.append(
                    Markdown(f"Table shows the first 1000 of {len(frame)} rows.")
                )
    return outputs
