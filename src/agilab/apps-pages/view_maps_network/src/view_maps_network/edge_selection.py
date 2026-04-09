from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

NONE_OPTION = "(none)"
CUSTOM_OPTION = "(custom path…)"


@dataclass(frozen=True)
class EdgesPickerState:
    picker_options: list[str]
    choice: str
    custom_value: str
    edges_clean: str
    recovered_from_missing: bool = False


def _path_exists(value: str) -> bool:
    if not value.strip():
        return False
    try:
        return Path(value).expanduser().exists()
    except Exception:
        return False


def _preferred_recovery_candidate(edges_prev: str, edges_candidates: Sequence[str]) -> str | None:
    if not edges_candidates:
        return None
    prev_name = Path(edges_prev).name.lower()
    tokens: list[str] = []
    if "topology" in prev_name:
        tokens.extend(["topology", "ilp_topology"])
    if "routing_edges" in prev_name:
        tokens.append("routing_edges")
    elif "edges" in prev_name:
        tokens.append("edges")
    for token in tokens:
        for candidate in edges_candidates:
            if token in Path(candidate).name.lower():
                return candidate
    return edges_candidates[0]


def resolve_edges_picker_state(
    edges_prev: str,
    edges_candidates: Sequence[str],
    *,
    current_choice: str | None = None,
    current_custom: str | None = None,
) -> EdgesPickerState:
    picker_options = [NONE_OPTION, *edges_candidates, CUSTOM_OPTION]
    choice = current_choice or ""
    custom_value = current_custom or ""
    recovered_from_missing = False

    if (
        choice == CUSTOM_OPTION
        and custom_value.strip()
        and not _path_exists(custom_value)
        and edges_candidates
    ):
        choice = _preferred_recovery_candidate(custom_value, edges_candidates) or NONE_OPTION
        custom_value = ""
        recovered_from_missing = bool(choice and choice != NONE_OPTION)

    if choice not in picker_options:
        if edges_prev and edges_prev in edges_candidates:
            choice = edges_prev
        elif edges_prev and _path_exists(edges_prev):
            choice = CUSTOM_OPTION
            if not custom_value:
                custom_value = edges_prev
        elif edges_prev and edges_candidates:
            choice = _preferred_recovery_candidate(edges_prev, edges_candidates) or NONE_OPTION
            recovered_from_missing = bool(choice and choice != NONE_OPTION)
        elif edges_prev:
            choice = CUSTOM_OPTION
            if not custom_value:
                custom_value = edges_prev
        else:
            choice = edges_candidates[0] if edges_candidates else NONE_OPTION

    if choice == CUSTOM_OPTION:
        edges_clean = custom_value.strip()
    elif choice == NONE_OPTION:
        edges_clean = ""
    else:
        edges_clean = choice.strip()

    return EdgesPickerState(
        picker_options=picker_options,
        choice=choice,
        custom_value=custom_value,
        edges_clean=edges_clean,
        recovered_from_missing=recovered_from_missing,
    )
