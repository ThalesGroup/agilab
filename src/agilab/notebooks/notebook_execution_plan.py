"""Compile reviewed notebook cells into one standard, state-preserving stage.

This is a source transformation, never an execution or a Python sandbox. Keeping
one execution unit preserves aliases, mutations and late-bound function globals
without guessing which cells can safely run in separate processes.
"""

from __future__ import annotations

import copy
import codeop
import hashlib
import json
from typing import Any, Mapping, Sequence

SCHEMA = "agilab.notebook_execution_plan.v1"


def compile_notebook_stage(
    entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve cell order and namespace after explicit runtime-role review.

    Explicit exported workflows are handled by the caller, retaining their
    existing stage graph. Mixed runtime choices cannot share Python state.
    """
    if not entries:
        return []
    roles = {entry.get("NB_RUNTIME_ROLE", "") for entry in entries}
    runtimes = {entry.get("R", "") for entry in entries}
    environments = {entry.get("E", "") for entry in entries}
    if len(roles) > 1 or len(runtimes) > 1 or len(environments) > 1:
        raise ValueError(
            "Notebook cells need one reviewed runtime and environment to preserve shared state. "
            "Choose the same runtime for these cells, or create explicit artifact boundaries "
            "before splitting them into separate workflow stages."
        )
    cells = []
    compiler = codeop.Compile()
    for entry in entries:
        source = str(entry.get("C", ""))
        cell_id = str(entry.get("NB_CELL_ID", ""))
        index = int(entry.get("NB_CELL_INDEX", 0))
        filename = f"notebook:cell-{index}"
        # Compilation catches magics and invalid Python without executing it.
        compiler(source, filename, "exec", incomplete_input=False)
        cells.append(
            {
                "id": cell_id,
                "index": index,
                "source": source,
                "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            }
        )
    stage = copy.deepcopy(dict(entries[0]))
    # Keep compiled cell inputs outside the execution namespace, so notebook
    # assignments to exec, compile, globals or helper names cannot break replay.
    cell_inputs = [(cell["source"], f"notebook:cell-{cell['index']}") for cell in cells]
    stage["C"] = (
        "# AGILAB notebook execution: original cell order, one Python namespace.\n"
        "(lambda _execute, _compile, _namespace, _cells: [\n"
        "    _execute(_compile(_source, _filename, 'exec', incomplete_input=False), _namespace)\n"
        "    for _source, _filename in _cells\n"
        "])(__import__('builtins').exec, __import__('codeop').Compile(), globals(),\n"
        f"   {cell_inputs!r})\n"
    )
    stage["NB_EXECUTION_PLAN_SCHEMA"] = SCHEMA
    stage["NB_COMPILED_SHA256"] = hashlib.sha256(stage["C"].encode("utf-8")).hexdigest()
    stage["NB_EXECUTION_STRATEGY"] = "shared_namespace"
    stage["NB_SOURCE_CELLS"] = cells
    stage["NB_SOURCE_SHA256"] = hashlib.sha256(
        json.dumps(cells, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    stage["NB_CELL_ID"] = "notebook-" + stage["NB_SOURCE_SHA256"][:16]
    for key in ("NB_CONTEXT_IDS", "NB_ENV_HINTS", "NB_ARTIFACT_REFERENCES"):
        stage[key] = list(
            dict.fromkeys(value for entry in entries for value in entry.get(key, []))
        )
    descriptions = list(
        dict.fromkeys(str(entry.get("D", "")) for entry in entries if entry.get("D"))
    )
    stage["D"] = " / ".join(descriptions) or "Imported notebook"
    stage["Q"] = (
        "Run the reviewed notebook cells in order, preserving their shared Python state."
    )
    stage.pop("NB_EXECUTION_COUNT", None)
    return [stage]
