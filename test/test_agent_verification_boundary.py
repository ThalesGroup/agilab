"""The read-only verification owner stays independent of execution and CLI code."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from agilab.agent_runtime import verification
from agilab import agent_run


def test_read_only_import_does_not_load_execution_owner():
    source = Path(__file__).resolve().parents[1] / "src"
    code = """import json, sys
sys.path.insert(0, sys.argv[1])
from agilab.agent_runtime.verification import validate_agent_run
print(json.dumps({"execution_loaded": "agilab.agent_runtime.agent_run" in sys.modules,
                  "capture_loaded": "agilab.agent_runtime.process_capture" in sys.modules}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(source)],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert json.loads(result.stdout) == {
        "execution_loaded": False,
        "capture_loaded": False,
    }


def test_public_facade_and_read_only_verifier_preserve_outcomes(tmp_path):
    manifest = {
        "kind": verification.TRACE_KIND,
        "status": "planned",
        "run_id": "planned",
        "command": {"argv_sha256": "hash"},
        "artifacts": {},
    }
    assert agent_run.validate_agent_run(manifest) == verification.validate_agent_run(
        manifest
    )
    assert agent_run.AgentRunSummary is verification.AgentRunSummary
    assert agent_run.summarize_agent_run(manifest) == verification.summarize_agent_run(
        manifest
    )


def test_verification_source_remains_small_and_execution_free():
    path = Path(verification.__file__)
    assert len(path.read_text().splitlines()) <= 550
    assert "from agilab.agent_runtime.agent_run import" not in path.read_text()
