"""Source-bound experiments exercise real execution and independent acceptance."""

import json
from pathlib import Path
import shutil

import pytest

from agilab.agent_runtime import experiment


def prepare(tmp_path, *, answer=6, grader=None):
    source = tmp_path / "source"
    source.mkdir()
    (source / "candidate.py").write_text(
        f"from pathlib import Path\nPath('result.json').write_text('{json.dumps({'value': answer})}')\n"
    )
    (source / "inputs.json").write_text('{"value": 3}')
    (source / "grader.py").write_text(
        grader
        or """import json, sys
from pathlib import Path
workspace = Path(sys.argv[1])
actual = json.loads((workspace / 'result.json').read_text())['value']
expected = json.loads(Path('inputs.json').read_text())['value'] * 2
print(json.dumps({'schema': 'agilab.agent_experiment_acceptance.v1', 'checks': {'doubled': actual == expected}}))
"""
    )
    root = tmp_path / "evidence"
    plan = experiment.prepare_experiment(
        source_root=source,
        output_dir=root,
        files=["candidate.py", "inputs.json", "grader.py"],
        entrypoint="candidate.py",
        grader="grader.py",
        outputs=["result.json"],
        checks=["doubled"],
    )
    return source, root, plan


@pytest.mark.parametrize("answer, expected", [(6, "passed"), (3, "failed")])
def test_acceptance_is_independent_of_zero_exit_code(tmp_path, answer, expected):
    _, root, _ = prepare(tmp_path, answer=answer)
    receipt = experiment.execute_experiment(root, attempt_id="first")
    assert receipt["runs"]["entrypoint"]["returncode"] == 0
    assert receipt["status"] == expected
    assert receipt["usage"]["status"] == "not_observed"
    assert receipt["usage"]["input_tokens"] is None
    verification = experiment.verify_experiment(root, "attempts/first/receipt.json")
    assert verification["verification"] == "passed"
    assert verification["experiment_status"] == expected


def test_stale_source_cannot_reuse_prepared_success(tmp_path):
    source, root, _ = prepare(tmp_path)
    (source / "candidate.py").write_text("raise RuntimeError('new unexecuted source')")
    with pytest.raises(ValueError, match="Source changed"):
        experiment.execute_experiment(root)
    assert not (root / "attempts").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("entrypoint", "/tmp/undeclared.py"),
        ("grader", "undeclared.py"),
        ("checks", []),
        ("outputs", []),
        ("timeout_seconds", True),
        ("arguments", "invalid"),
    ],
)
def test_resealed_malformed_plan_cannot_execute(tmp_path, field, value):
    _, root, plan = prepare(tmp_path)
    plan.pop("sha256")
    plan[field] = value
    (root / "plan.json").write_text(json.dumps(experiment.seal(plan)))
    with pytest.raises(ValueError):
        experiment.execute_experiment(root)
    assert not (root / "attempts").exists()


def test_receipt_publication_interruption_cannot_reuse_stale_grading(
    tmp_path, monkeypatch
):
    _, root, _ = prepare(tmp_path)
    publish = experiment.persist_evaluation

    def fail_receipt(root, output, payload):
        if Path(output).name == "receipt.json":
            raise OSError("interrupted receipt publication")
        return publish(root, output, payload)

    monkeypatch.setattr(experiment, "persist_evaluation", fail_receipt)
    with pytest.raises(OSError):
        experiment.execute_experiment(root, attempt_id="first")
    monkeypatch.setattr(experiment, "persist_evaluation", publish)
    (root / "attempts/first/workspace/result.json").write_text('{"value":123}')
    with pytest.raises(ValueError, match="output checkpoint"):
        experiment.execute_experiment(root, attempt_id="first", resume=True)


def test_experiment_overrides_disabled_home_trace_policy(tmp_path, monkeypatch):
    home = tmp_path / "agent-home"
    home.mkdir()
    (home / "agents.json").write_text('{"trace":{"enabled":false}}')
    monkeypatch.setenv("AGILAB_AGENT_HOME", str(home))
    _, root, _ = prepare(tmp_path)
    receipt = experiment.execute_experiment(root)
    assert receipt["status"] == "passed"


def test_resume_after_grader_checkpoint_before_claim_is_safe(tmp_path, monkeypatch):
    _, root, _ = prepare(tmp_path)
    run = experiment.run_agent_command

    def stop_before_claim(config, **kwargs):
        if config.metadata["experiment_role"] == "grader":
            raise OSError("interrupted before grader claim")
        return run(config, **kwargs)

    monkeypatch.setattr(experiment, "run_agent_command", stop_before_claim)
    with pytest.raises(OSError):
        experiment.execute_experiment(root, attempt_id="first")
    monkeypatch.setattr(experiment, "run_agent_command", run)
    assert (
        experiment.execute_experiment(root, attempt_id="first", resume=True)["status"]
        == "passed"
    )


def test_frozen_input_tamper_is_rejected(tmp_path):
    _, root, _ = prepare(tmp_path)
    (root / "snapshot" / "inputs.json").write_text('{"value": 4}')
    with pytest.raises(ValueError, match="Frozen input changed"):
        experiment.execute_experiment(root)


def test_artifact_tamper_fails_verification_and_receipt_is_relocatable(tmp_path):
    _, root, _ = prepare(tmp_path)
    experiment.execute_experiment(root, attempt_id="first")
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    assert (
        experiment.verify_experiment(moved, "attempts/first/receipt.json")[
            "verification"
        ]
        == "passed"
    )
    (moved / "attempts" / "first" / "workspace" / "result.json").write_text(
        '{"value": 7}'
    )
    with pytest.raises(ValueError, match="outputs changed"):
        experiment.verify_experiment(moved, "attempts/first/receipt.json")


def test_missing_acceptance_is_not_success(tmp_path):
    _, root, _ = prepare(
        tmp_path, grader="print('grader did not produce observations')"
    )
    receipt = experiment.execute_experiment(root)
    assert receipt["runs"]["grader"]["returncode"] == 0
    assert receipt["acceptance"]["status"] == "insufficient_evidence"
    assert receipt["status"] == "failed"


def test_resume_reuses_completed_evidence_and_rejects_an_ambiguous_claim(tmp_path):
    _, root, _ = prepare(tmp_path)
    first = experiment.execute_experiment(root, attempt_id="first")
    assert experiment.execute_experiment(root, attempt_id="first", resume=True) == first
    ambiguous = root / "attempts" / "ambiguous" / "entrypoint"
    ambiguous.mkdir(parents=True)
    (ambiguous / ".agent_run.claim.json").write_text("{}")
    with pytest.raises(RuntimeError, match="Interrupted command"):
        experiment.execute_experiment(root, attempt_id="ambiguous", resume=True)


def test_grader_cannot_change_the_candidate_artifacts(tmp_path):
    _, root, _ = prepare(
        tmp_path,
        grader="""import sys
from pathlib import Path
(Path(sys.argv[1]) / 'result.json').write_text('{"value": 9}')
print('{"schema": "agilab.agent_experiment_acceptance.v1", "checks": {"doubled": true}}')
""",
    )
    with pytest.raises(ValueError, match="grader changed"):
        experiment.execute_experiment(root)


def test_symlinked_source_input_is_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')")
    (source / "candidate.py").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes|symlink"):
        experiment.prepare_experiment(
            source_root=source,
            output_dir=tmp_path / "proof",
            files=["candidate.py", "grader.py"],
            entrypoint="candidate.py",
            grader="grader.py",
            outputs=["result.json"],
            checks=["doubled"],
        )
