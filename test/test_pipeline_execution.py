from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from agilab.pipeline.pipeline_execution import execute_pipeline_lifecycle
from agilab.pipeline.pipeline_run_state import PipelineRunState


@pytest.mark.parametrize(
    "cause", [None, RuntimeError("stage failed"), KeyboardInterrupt("cancelled")]
)
@pytest.mark.parametrize("broken_cleanup", [None, "publish", "restore", "release"])
def test_lifecycle_attempts_all_cleanup_and_preserves_original_error(
    cause, broken_cleanup
):
    state = PipelineRunState("run", "start", 0)
    calls = []
    secondary = OSError("cleanup failed")

    def execute(current):
        calls.append("execute")
        current.stage_records.append({"status": "running"})
        if cause is not None:
            raise cause
        current.record_executed()
        current.complete()

    def cleanup(name):
        def call(current):
            calls.append(name)
            if name == broken_cleanup:
                raise secondary
            return Path("manifest.json") if name == "publish" else None

        return call

    effects = SimpleNamespace(
        execute=execute,
        record_failure=cleanup("record_failure"),
        publish=cleanup("publish"),
        restore=cleanup("restore"),
        release=cleanup("release"),
    )
    if cause is not None or broken_cleanup:
        with pytest.raises(BaseException) as found:
            execute_pipeline_lifecycle(
                state, effects, describe_error=str, timestamp=lambda: "end"
            )
        assert found.value is (cause or secondary)
        if cause is not None and broken_cleanup:
            assert "cleanup failed" in "\n".join(found.value.__notes__)
    else:
        result = execute_pipeline_lifecycle(
            state, effects, describe_error=str, timestamp=lambda: "end"
        )
        assert result.manifest_path == Path("manifest.json")
        assert result.executed == 1
    assert calls[-3:] == ["publish", "restore", "release"]
    if cause is not None:
        assert state.status == "failed"
        assert state.stage_records[0]["finished_at"] == "end"


def test_workflow_function_boundaries_ratchet_down():
    root = Path(__file__).resolve().parents[1] / "src/agilab/pipeline"
    limits = {
        "pipeline_run_controls.py": {
            "run_all_stages": 170,
            "execute": 105,
            "_execute_wave": 85,
            "_execute_stage": 290,
        },
        "pipeline_lab.py": {"display_lab_tab": 2082},
        "pipeline_execution.py": {"execute_pipeline_lifecycle": 85},
        "pipeline_page_state.py": {
            "prepare_pipeline_editor_updates": 30,
            "hydrate_pipeline_editor_values": 70,
        },
    }
    for filename, functions in limits.items():
        tree = ast.parse((root / filename).read_text())
        for name, limit in functions.items():
            nodes = [
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name
            ]
            assert len(nodes) == 1, (filename, name)
            assert nodes[0].end_lineno - nodes[0].lineno + 1 <= limit, (filename, name)
    pure = ast.parse((root / "pipeline_execution.py").read_text())
    imports = [
        ast.unparse(n)
        for n in ast.walk(pure)
        if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    assert not any(
        "streamlit" in line or "pipeline_run_controls" in line for line in imports
    )
