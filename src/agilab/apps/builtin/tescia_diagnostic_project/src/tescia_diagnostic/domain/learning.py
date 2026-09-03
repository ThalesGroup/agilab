"""Stable learner-path metadata for the TeSciA teaching workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final


DEFAULT_LEARNING_TRACK: Final = "general_diagnostic"

LEARNING_TRACKS: Final[dict[str, dict[str, Any]]] = {
    "agilab_diagnostics": {
        "label": "AGILAB diagnostics",
        "audience": "AGILAB learners and operators",
        "outcomes": [
            "Separate symptoms from root causes.",
            "Choose evidence-backed fixes.",
            "Design discriminating regression checks.",
        ],
    },
    "mathematics_2026": {
        "label": "Mathematics 2026",
        "audience": "Secondary-school learners and teachers",
        "outcomes": [
            "Audit exercise coverage against explicit curriculum ids.",
            "Identify missing evidence in a proposed correction.",
            "Turn feedback into a targeted second practice round.",
        ],
    },
    "data_science_2026": {
        "label": "Data science 2026",
        "audience": "Data-science candidates and practitioners",
        "outcomes": [
            "Diagnose modern ML and AI-engineering failure modes.",
            "Calibrate confidence against deployment evidence.",
            "Select a reversible fix and a measurable regression plan.",
        ],
    },
    DEFAULT_LEARNING_TRACK: {
        "label": "General diagnostics",
        "audience": "Learners adapting their own diagnostic cases",
        "outcomes": [
            "Structure a diagnosis as reviewable evidence.",
            "Compare candidate fixes with explicit trade-offs.",
            "Export a deterministic correction and regression plan.",
        ],
    },
}


def normalize_learning_track(value: Any) -> str:
    """Return a stable learning-track id and reject unknown explicit values."""

    track_id = str(value or "").strip() or DEFAULT_LEARNING_TRACK
    if track_id not in LEARNING_TRACKS:
        available = ", ".join(LEARNING_TRACKS)
        raise ValueError(
            f"Unknown learning track {track_id!r}; expected one of: {available}."
        )
    return track_id


def learning_track_metadata(case: Mapping[str, Any]) -> dict[str, Any]:
    """Return copy-safe public metadata for one case's learner path."""

    track_id = normalize_learning_track(case.get("learning_track"))
    track = LEARNING_TRACKS[track_id]
    return {
        "id": track_id,
        "label": str(track["label"]),
        "audience": str(track["audience"]),
        "outcomes": [str(item) for item in track["outcomes"]],
    }


def available_learning_tracks(
    cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return learner paths represented by cases in stable product order."""

    represented = {
        normalize_learning_track(case.get("learning_track")) for case in cases
    }
    return [
        {
            "id": track_id,
            "label": str(track["label"]),
            "audience": str(track["audience"]),
            "outcomes": [str(item) for item in track["outcomes"]],
        }
        for track_id, track in LEARNING_TRACKS.items()
        if track_id in represented
    ]


__all__ = [
    "DEFAULT_LEARNING_TRACK",
    "LEARNING_TRACKS",
    "available_learning_tracks",
    "learning_track_metadata",
    "normalize_learning_track",
]
