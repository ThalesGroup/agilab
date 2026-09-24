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


@pytest.mark.parametrize("path,value,reason", [
    (("plan_sha256",), "0" * 64, "not bound"),
    (("input_binding",), {}, "not bound"),
    (("checkpoints", "launch"), {}, "launch checkpoint changed"),
    (("runs",), {}, "independent grading"),
    (("outputs",), [], "outputs changed"),
    (("missing_outputs",), ["unreported"], "outputs changed"),
    (("checkpoints", "candidate-output"), {}, "checkpoint changed"),
    (("checkpoints", "grader-input"), {}, "checkpoint changed"),
    (("acceptance",), {}, "contradicts independent acceptance"),
    (("status",), "failed", "contradicts independent acceptance"),
])
def test_resealing_receipt_does_not_authorize_changed_evidence(tmp_path, path, value, reason):
    _, root, _ = prepare(tmp_path)
    receipt = experiment.execute_experiment(root, attempt_id="first")
    target = receipt
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    receipt.pop("sha256")
    receipt_path = root / "attempts/first/receipt.json"
    receipt_path.write_text(json.dumps(experiment.seal(receipt)))
    with pytest.raises(ValueError, match=reason):
        experiment.verify_experiment(root, "attempts/first/receipt.json")


@pytest.mark.parametrize("checkpoint", ["candidate-output", "grader-input"])
def test_rehashed_checkpoint_must_bind_actual_outputs_to_grading(tmp_path, checkpoint):
    _, root, _ = prepare(tmp_path)
    receipt = experiment.execute_experiment(root, attempt_id="first")
    relative = f"attempts/first/{checkpoint}.json"
    (root / relative).write_text("{}")
    receipt["checkpoints"][checkpoint] = experiment.file_record(root, relative)
    receipt.pop("sha256")
    (root / "attempts/first/receipt.json").write_text(json.dumps(experiment.seal(receipt)))
    with pytest.raises(ValueError, match="do not bind"):
        experiment.verify_experiment(root, "attempts/first/receipt.json")


def test_experiment_cli_prepares_executes_and_verifies_real_artifacts(tmp_path, capsys):
    source, _, _ = prepare(tmp_path)
    root = tmp_path / "cli-evidence"
    assert experiment.main([
        "prepare", "--source", str(source), "--output", str(root),
        "--file", "candidate.py", "--file", "inputs.json", "--file", "grader.py",
        "--entrypoint", "candidate.py", "--grader", "grader.py",
        "--artifact", "result.json", "--check", "doubled",
    ]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["sha256"] == experiment.load_plan(root)["sha256"]
    assert experiment.main(["run", str(root), "--attempt-id", "cli"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "passed"
    assert json.loads((root / "attempts/cli/workspace/result.json").read_text()) == {"value": 6}
    assert experiment.main(["verify", str(root), "attempts/cli/receipt.json"]) == 0
    assert json.loads(capsys.readouterr().out)["verification"] == "passed"


def test_experiment_cli_returns_failure_for_rejected_candidate(tmp_path, capsys):
    _, root, _ = prepare(tmp_path, answer=3)
    assert experiment.main(["run", str(root), "--attempt-id", "rejected"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


@pytest.mark.parametrize("path,value", [
    (("files",), []), (("files",), "invalid"),
    (("files", 0), {}), (("files", 0, "size_bytes"), True),
    (("files", 0, "size_bytes"), -1), (("files", 0, "size_bytes"), experiment.MAX_INPUT_BYTES + 1),
    (("files", 0, "sha256"), "invalid"),
    (("outputs",), ["result.json", "result.json"]),
    (("outputs",), ["candidate.py"]),
    (("checks",), ["duplicate", "duplicate"]), (("checks",), ["invalid check"]),
    (("arguments",), [1]), (("arguments",), ["x" * 4097]),
    (("arguments",), ["x"] * 65),
    (("timeout_seconds",), 0), (("timeout_seconds",), 3601),
    (("source_root",), "relative"), (("source_root",), None),
])
def test_resealed_plan_bounds_are_enforced_before_execution(tmp_path, path, value):
    _, root, plan = prepare(tmp_path)
    target = plan
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    plan.pop("sha256")
    (root / "plan.json").write_text(json.dumps(experiment.seal(plan)))
    with pytest.raises(ValueError):
        experiment.execute_experiment(root)
    assert not (root / "attempts").exists()


@pytest.mark.parametrize("content,reason", [
    ('{"same": 1, "same": 2}', "Duplicate"),
    ('{"value": NaN}', "Nonfinite"),
    ('{"value": Infinity}', "Nonfinite"),
    ("[]", "must be an object"),
    (" " * (1024 * 1024 + 1), "exceeds 1 MiB"),
])
def test_experiment_json_rejects_ambiguous_or_unbounded_input(tmp_path, content, reason):
    path = tmp_path / "experiment-input.json"
    path.write_text(content)
    with pytest.raises(ValueError, match=reason):
        experiment.read_json(path)


@pytest.mark.parametrize("path", [
    "", None, "x" * 513, "/absolute", "../escape", "folder/../escape",
    "folder//file", "./file", ".secret", "folder/.secret", "folder\\file",
])
def test_experiment_paths_are_normalized_visible_relative_paths(path):
    with pytest.raises(ValueError):
        experiment.relative_path(path)


def test_experiment_rejects_symlinked_root_and_output_parent(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="directories cannot use symlinks"):
        experiment.confined(alias, "output.json")
    (root / "outside").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        experiment.confined(root, "outside/output.json")
    (root / "inside").symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="files cannot use symlinks"):
        experiment.confined(root, "inside/output.json")


@pytest.mark.parametrize("changed,value,message", [
    ("files", [], "Select 1-256"),
    ("entrypoint", "missing.py", "Select 1-256"),
    ("grader", "candidate.py", "independent grader"),
    ("outputs", [], "1-64 outputs"),
    ("outputs", ["candidate.py"], "distinct"),
    ("checks", [], "1-100 unique"),
    ("checks", ["doubled", "doubled"], "unique"),
    ("checks", ["invalid check"], "identifiers"),
    ("checks", [1], "identifiers"),
    ("timeout_seconds", True, "between 1 and 3600"),
    ("timeout_seconds", 0, "between 1 and 3600"),
    ("timeout_seconds", 3601, "between 1 and 3600"),
    ("arguments", ["x"] * 65, "arguments exceed"),
    ("arguments", [42], "arguments exceed"),
    ("arguments", ["x" * 4097], "arguments exceed"),
])
def test_prepare_rejects_invalid_contract_before_creating_evidence(tmp_path, changed, value, message):
    source = tmp_path / "source"
    source.mkdir()
    (source / "candidate.py").write_text("pass")
    (source / "grader.py").write_text("pass")
    root = tmp_path / "evidence"
    kwargs = dict(source_root=source, output_dir=root, files=["candidate.py", "grader.py"],
                  entrypoint="candidate.py", grader="grader.py", outputs=["result.json"], checks=["doubled"])
    kwargs[changed] = value
    with pytest.raises(ValueError, match=message):
        experiment.prepare_experiment(**kwargs)
    assert not root.exists()


def test_prepare_detects_source_mutation_during_snapshot_copy(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "candidate.py").write_text("pass")
    (source / "grader.py").write_text("pass")
    root = tmp_path / "evidence"
    original_copy = experiment.shutil.copyfile
    def corrupted_copy(src, dest):
        result = original_copy(src, dest)
        Path(dest).write_text("changed during snapshot")
        return result
    monkeypatch.setattr(experiment.shutil, "copyfile", corrupted_copy)
    with pytest.raises(ValueError, match="Source changed while freezing"):
        experiment.prepare_experiment(source_root=source, output_dir=root,
            files=["candidate.py", "grader.py"], entrypoint="candidate.py", grader="grader.py",
            outputs=["result.json"], checks=["doubled"])
    assert not (root / "plan.json").exists()


def test_prepare_input_budget_applies_before_publication(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "candidate.py").write_text("pass")
    (source / "grader.py").write_text("pass")
    root = tmp_path / "evidence"
    monkeypatch.setattr(experiment, "MAX_INPUT_BYTES", 1)
    with pytest.raises(ValueError, match="exceed 50 MiB"):
        experiment.prepare_experiment(source_root=source, output_dir=root,
            files=["candidate.py", "grader.py"], entrypoint="candidate.py", grader="grader.py",
            outputs=["result.json"], checks=["doubled"])
    assert not root.exists()


@pytest.mark.parametrize("payload", [
    {}, {"schema": "unsupported", "checks": {"doubled": True}},
    {"schema": experiment.ACCEPTANCE_SCHEMA, "checks": []},
    {"schema": experiment.ACCEPTANCE_SCHEMA, "checks": {"other": True}},
    {"schema": experiment.ACCEPTANCE_SCHEMA, "checks": {"doubled": 1}},
    {"schema": experiment.ACCEPTANCE_SCHEMA, "checks": {"doubled": "true"}},
])
def test_acceptance_requires_exact_boolean_check_contract(tmp_path, payload):
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(payload))
    assert experiment._acceptance({"checks": ["doubled"]}, path, 0) == {
        "status": "insufficient_evidence", "checks": {"doubled": None}}


@pytest.mark.parametrize("check_value,returncode,status", [(True, 0, "passed"), (False, 0, "failed"), (True, 1, "failed")])
def test_acceptance_success_requires_both_grader_exit_and_check(tmp_path, check_value, returncode, status):
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps({"schema": experiment.ACCEPTANCE_SCHEMA, "checks": {"doubled": check_value}}))
    assert experiment._acceptance({"checks": ["doubled"]}, path, returncode)["status"] == status


def test_missing_or_symlinked_output_is_reported_missing(tmp_path):
    workspace = tmp_path / "attempts" / "first" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "valid.json").write_text("{}")
    external = tmp_path / "external.json"
    external.write_text("{}")
    (workspace / "escaped.json").symlink_to(external)
    records, missing = experiment._output_records(tmp_path, {
        "outputs": ["valid.json", "absent.json", "escaped.json"]}, "first")
    assert [record["path"] for record in records] == ["attempts/first/workspace/valid.json"]
    assert missing == ["absent.json", "escaped.json"]
