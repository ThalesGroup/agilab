from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.agent_context import benchmark


def _cohort(monkeypatch, tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "policy.md").write_text("Always preserve the required policy.\n")
    (root / "owner.py").write_text(
        'PAD = "' + "x" * 5000 + '"\n\ndef target():\n    return 42\n'
    )
    monkeypatch.setattr(
        benchmark, "TASKS", [("fixed-task", "inspect target", ("owner.py::target",))]
    )
    monkeypatch.setattr(benchmark, "load_skill_index", lambda path: {})
    monkeypatch.setattr(
        benchmark,
        "recommend_context",
        lambda **kwargs: {
            "context_profile": {
                "max_total_tokens": 10000,
                "baseline_files": ["policy.md"],
                "matched_packs": [],
            },
            "recommended_skills": [],
        },
    )
    original_run = benchmark.subprocess.run

    def git_only(args, **kwargs):
        if args[0] == "git":
            return SimpleNamespace(stdout="a" * 40 if "rev-parse" in args else "")
        return original_run(args, **kwargs)

    monkeypatch.setattr(benchmark.subprocess, "run", git_only)
    return root


def test_fixed_packets_preserve_policy_and_bound_the_source_read(monkeypatch, tmp_path):
    pytest.importorskip("tiktoken")
    root = _cohort(monkeypatch, tmp_path)
    corpus = benchmark.collect_contexts(root, context_budget=250)
    case = corpus["cases"][0]
    assert case["baseline"]["actual_tokens"] > 250
    assert case["candidate"]["actual_tokens"] < 250
    assert "return 42" in case["candidate"]["context_text"]
    assert len(case["required_policy"]) == 1
    assert (
        case["candidate"]["selected"][0]["sha256"]
        == case["baseline"]["selected"][0]["sha256"]
    )
    (root / "policy.md").unlink()
    with pytest.raises(ValueError, match="mandatory context incomplete"):
        benchmark.collect_contexts(root)


def test_repeated_benchmark_keeps_usage_missing_and_verifies_acceptance(
    monkeypatch, tmp_path
):
    pytest.importorskip("tiktoken")
    root = _cohort(monkeypatch, tmp_path)
    output = tmp_path / "result"
    result = benchmark.run_benchmark(root, output, repeats=2, context_budget=250)
    assert result["billed_token_savings"] is None
    assert result["model_task_completion"] == "not evaluated"
    assert len(result["comparisons"]) == 2
    for comparison in result["comparisons"]:
        assert comparison["baseline"]["status"] == "failed"
        assert comparison["candidate"]["status"] == "passed"
        assert comparison["candidate"]["tokens_per_accepted_run"] is None
        assert comparison["candidate"]["usage"]["status"] == "not_observed"
    with pytest.raises(FileExistsError):
        benchmark.run_benchmark(root, output, repeats=1)


def test_pair_rejects_source_drift_between_reads(monkeypatch, tmp_path):
    pytest.importorskip("tiktoken")
    root = _cohort(monkeypatch, tmp_path)
    real_materialize = benchmark.materialize_context
    calls = []

    def materialize(*args, **kwargs):
        result = real_materialize(*args, **kwargs)
        calls.append(result)
        if len(calls) == 1:
            (root / "owner.py").write_text("def target():\n    return 99\n")
        return result

    monkeypatch.setattr(benchmark, "materialize_context", materialize)
    with pytest.raises(ValueError, match="source changed between paired reads"):
        benchmark.collect_contexts(root)


def test_grader_rejects_forged_zero_token_measurement(monkeypatch, tmp_path):
    pytest.importorskip("tiktoken")
    import hashlib
    import json
    import subprocess
    import sys

    root = _cohort(monkeypatch, tmp_path)
    corpus = benchmark.collect_contexts(root, context_budget=10)
    text = corpus["cases"][0]["baseline"]["context_text"]
    (tmp_path / "contexts.json").write_text(json.dumps(corpus))
    (tmp_path / "measurements.json").write_text(
        json.dumps(
            {
                "variant": "baseline",
                "rows": [
                    {
                        "task": "fixed-task",
                        "reference_tokens": 0,
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    }
                ],
            }
        )
    )
    checked = subprocess.run(
        [sys.executable, str(benchmark.FIXTURE / "grader.py"), str(tmp_path)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    checks = json.loads(checked.stdout)["checks"]
    assert not checks["context_intact"]
    assert not checks["within_context_budget"]
