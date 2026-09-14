"""The packaged agent pilot must compare acceptance and preserve missing usage."""

import json

import pytest

from agilab.agent_runtime.experiment import read_json, verify_experiment
from agilab.agent_runtime.experiment_comparison import compare_experiments
from agilab.agent_runtime.experiment_demo import demo_source, run_demo
from agilab.agent_runtime.usage import parse_codex_jsonl


def test_packaged_pilot_retains_the_failed_baseline(tmp_path):
    root = tmp_path / "pilot"
    result = run_demo(root)
    assert result["baseline"]["status"] == "failed"
    assert result["baseline"]["process_status"] == "pass"
    assert result["candidate"]["status"] == "passed"
    assert result["accepted_runs"] == 1
    assert result["attempts"] == 2
    assert result["improved_acceptance"]
    assert result["candidate"]["usage"]["usage"] is None
    assert result["candidate"]["tokens_per_accepted_run"] is None
    assert read_json(root / "comparison.json") == result
    assert (
        verify_experiment(root / "baseline", "attempts/pilot/receipt.json")[
            "verification"
        ]
        == "passed"
    )
    import shutil

    shutil.copytree(root / "candidate", root / "copied")
    with pytest.raises(ValueError, match="distinct observations"):
        compare_experiments(
            baseline_root=root / "candidate",
            baseline_receipt="attempts/pilot/receipt.json",
            candidate_root=root / "copied",
            candidate_receipt="attempts/pilot/receipt.json",
        )
    with pytest.raises(ValueError, match="registered"):
        compare_experiments(
            baseline_root=root / "baseline",
            baseline_receipt="attempts/pilot/receipt.json",
            candidate_root=root / "candidate",
            candidate_receipt="attempts/pilot/receipt.json",
            candidate_usage_output="unregistered.jsonl",
        )


@pytest.mark.parametrize(
    "raw",
    [
        {"output_tokens": 1},
        {"input_tokens": True, "output_tokens": 1},
        {"input_tokens": 4, "output_tokens": 1, "total_tokens": 999},
    ],
)
def test_usage_never_invents_missing_or_invalid_counts(raw):
    parsed = parse_codex_jsonl(json.dumps({"type": "turn.completed", "usage": raw}))
    assert parsed["status"] == "missing"
    assert parsed["usage"] is None


def test_usage_requires_one_uncorrupted_terminal_report():
    report = json.dumps(
        {"type": "turn.completed", "usage": {"input_tokens": 4, "output_tokens": 1}}
    )
    assert parse_codex_jsonl(report)["usage"]["total_tokens"] == 5
    assert parse_codex_jsonl(report)["usage"]["cached_input_tokens"] is None
    assert parse_codex_jsonl(report)["usage"]["uncached_input_tokens"] is None
    assert parse_codex_jsonl(report + "\n" + report)["status"] == "ambiguous"
    assert parse_codex_jsonl(report + "\n{partial")["usage"] is None
    assert (
        parse_codex_jsonl(
            json.dumps({"type": "tool.output", "data": json.loads(report)})
        )["usage"]
        is None
    )
    for suffix in ('{"type":"turn.started"}', '{"type":"turn.failed"}'):
        assert parse_codex_jsonl(report + "\n" + suffix)["usage"] is None


@pytest.mark.parametrize(
    "usage",
    [
        '{"input_tokens":100,"input_tokens":1,"output_tokens":2}',
        '{"input_tokens":1,"output_tokens":2,"x":NaN}',
    ],
)
def test_usage_rejects_duplicate_and_nonfinite_json(usage):
    parsed = parse_codex_jsonl('{"type":"turn.completed","usage":' + usage + "}")
    assert parsed["usage"] is None
    assert parsed["invalid_line_count"] == 1


def test_verified_usage_counts_exact_parsed_artifact(tmp_path, monkeypatch):
    import shutil
    from agilab.agent_runtime import experiment, experiment_comparison

    source = tmp_path / "source"
    shutil.copytree(demo_source(), source)
    usage = json.dumps(
        {"type": "turn.completed", "usage": {"input_tokens": 4, "output_tokens": 1}}
    )
    for variant in ("baseline", "candidate"):
        path = source / f"{variant}.py"
        path.write_text(
            path.read_text() + f"\nPath('usage.jsonl').write_text({usage!r})\n"
        )
        experiment.prepare_experiment(
            source_root=source,
            output_dir=tmp_path / variant,
            files=[f"{variant}.py", "grader.py", "inputs.json"],
            entrypoint=f"{variant}.py",
            grader="grader.py",
            outputs=["result.json", "usage.jsonl"],
            checks=["finite_mean", "missing_values_excluded"],
        )
        experiment.execute_experiment(tmp_path / variant, attempt_id="observed")
    options = dict(
        baseline_root=tmp_path / "baseline",
        candidate_root=tmp_path / "candidate",
        baseline_receipt="attempts/observed/receipt.json",
        candidate_receipt="attempts/observed/receipt.json",
        baseline_usage_output="usage.jsonl",
        candidate_usage_output="usage.jsonl",
    )
    result = compare_experiments(**options)
    assert result["candidate"]["tokens_per_accepted_run"] == 5
    assert result["baseline"]["tokens_per_accepted_run"] is None
    verify = experiment_comparison.verify_experiment

    def change_after_verification(root, receipt):
        result = verify(root, receipt)
        (root / "attempts/observed/workspace/usage.jsonl").write_text(usage + "\n")
        return result

    monkeypatch.setattr(
        experiment_comparison, "verify_experiment", change_after_verification
    )
    with pytest.raises(ValueError, match="Usage bytes changed"):
        compare_experiments(**options)


def test_pilot_resources_follow_runtime_when_parent_package_spec_is_polluted(
    tmp_path, monkeypatch
):
    import importlib.util
    import agilab

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("")
    monkeypatch.setattr(
        agilab,
        "__spec__",
        importlib.util.spec_from_file_location("agilab", shadow / "__init__.py"),
    )
    # Root pytest collection can bind agilab's spec to the empty repo package
    # while its runtime modules still resolve under src/agilab.
    result = run_demo(tmp_path / "proof")
    assert result["baseline"]["status"] == "failed"
    assert result["candidate"]["status"] == "passed"
