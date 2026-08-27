from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import benchmark_tokki_agent_efficiency as benchmark


def _result(
    *,
    task_id: str,
    condition: str,
    attempt: int,
    accepted: bool = True,
    usage: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "condition": condition,
        "attempt": attempt,
        "accepted": accepted,
        "agent": {
            "duration_seconds": 10.0,
            "usage": {
                "status": "available" if usage is not None else "missing",
                "usage": usage,
            },
        },
    }


def _usage(total: int) -> dict[str, int]:
    return {
        "input_tokens": total - 20,
        "cached_input_tokens": 10,
        "uncached_input_tokens": total - 30,
        "output_tokens": 20,
        "total_tokens": total,
    }


def test_public_task_contract_is_sha_pinned_and_direct() -> None:
    tasks = benchmark.load_tasks(benchmark.DEFAULT_TASKS_PATH)

    assert [task.task_id for task in tasks] == [
        "dispatcher-work-size-gate",
        "ui-robot-scenario-watchdog",
        "windows-owner-rights-acl",
    ]
    for task in tasks:
        proof = benchmark.validate_task_provenance(benchmark.REPO_ROOT, task)
        assert proof["base_commit"] == task.base_commit
        assert proof["reference_fix_commit"] == task.reference_fix_commit
        assert proof["hidden_test_patch_bytes"] > 0
        assert proof["reference_product_paths"]


def test_task_loader_rejects_path_traversal(tmp_path: Path) -> None:
    payload = json.loads(benchmark.DEFAULT_TASKS_PATH.read_text(encoding="utf-8"))
    payload["tasks"][0]["hidden_test_paths"] = ["../answer.py"]
    task_path = tmp_path / "tasks.json"
    task_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(benchmark.BenchmarkError, match="traversal"):
        benchmark.load_tasks(task_path)


def test_task_loader_rejects_arbitrary_verification_commands(tmp_path: Path) -> None:
    payload = json.loads(benchmark.DEFAULT_TASKS_PATH.read_text(encoding="utf-8"))
    payload["tasks"][0]["verification_commands"] = [["sh", "-c", "echo pass"]]
    task_path = tmp_path / "tasks.json"
    task_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(benchmark.BenchmarkError, match="focused pytest"):
        benchmark.load_tasks(task_path)


def test_codex_jsonl_parser_uses_terminal_structured_usage() -> None:
    events = "\n".join(
        (
            json.dumps({"type": "thread.started", "model": "gpt-test"}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 120,
                        "input_tokens_details": {"cached_tokens": 80},
                        "output_tokens": 30,
                        "total_tokens": 150,
                    },
                }
            ),
        )
    )

    parsed = benchmark.parse_codex_jsonl(events)

    assert parsed["status"] == "available"
    assert parsed["reported_models"] == ["gpt-test"]
    assert parsed["usage"] == {
        "input_tokens": 120,
        "cached_input_tokens": 80,
        "uncached_input_tokens": 40,
        "output_tokens": 30,
        "total_tokens": 150,
    }


def test_codex_jsonl_parser_fails_closed_when_usage_is_missing() -> None:
    parsed = benchmark.parse_codex_jsonl('{"type":"turn.completed"}\nnot-json\n')

    assert parsed["status"] == "missing"
    assert parsed["usage"] is None
    assert parsed["invalid_line_count"] == 1


def test_driver_refuses_an_active_tokki_provider() -> None:
    with pytest.raises(benchmark.BenchmarkError, match="unrelated human shell"):
        benchmark.validate_driver_environment({"TOKKI_SESSION_ID": "active"})


def test_driver_refuses_a_disabled_outer_shell() -> None:
    with pytest.raises(benchmark.BenchmarkError, match="unset TOKKI_AUTO_RUN"):
        benchmark.validate_driver_environment({"TOKKI_AUTO_RUN": "off"})


def test_condition_environment_preserves_ambient_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGILAB_BENCHMARK_AMBIENT", "present")

    environment = benchmark._merged_environment({"TOKKI_AUTO_RUN": "off"})

    assert environment["AGILAB_BENCHMARK_AMBIENT"] == "present"
    assert environment["TOKKI_AUTO_RUN"] == "off"


def test_prompts_change_only_the_recorded_treatment() -> None:
    task = benchmark.load_tasks(benchmark.DEFAULT_TASKS_PATH)[0]

    tokki_prompt = benchmark.build_agent_prompt(task, "tokki")
    control_prompt = benchmark.build_agent_prompt(task, "control")

    assert task.prompt in tokki_prompt
    assert task.prompt in control_prompt
    assert "Use the repository's Tokki-aware workflow" in tokki_prompt
    assert "Do not invoke Tokki" in control_prompt
    assert "Do not modify tests" in tokki_prompt


@pytest.mark.parametrize(
    "path",
    (
        "test/test_widget.py",
        "src/agilab/core/tests/test_runtime.py",
        "src/agilab/core/conftest.py",
        "pyproject.toml",
        ".tokki/profile",
        "AGENTS.md",
    ),
)
def test_test_and_benchmark_control_paths_are_forbidden(path: str) -> None:
    assert benchmark._is_test_or_benchmark_control_path(path)


def test_product_source_path_is_not_forbidden() -> None:
    assert not benchmark._is_test_or_benchmark_control_path(
        "src/agilab/core/src/agi_node/agi_dispatcher/agi_dispatcher.py"
    )


def test_complete_single_attempt_is_pilot_only() -> None:
    results = [
        _result(task_id="task-a", condition="tokki", attempt=1, usage=_usage(100)),
        _result(task_id="task-a", condition="control", attempt=1, usage=_usage(140)),
    ]

    summary = benchmark.summarize_results(results, expected_tasks=1, attempts=1)

    assert summary["claim_status"] == "pilot_only"
    assert summary["complete_pairs"] == 1
    assert summary["conditions"]["tokki"]["total_tokens_per_accepted_task"] == 100
    assert summary["comparison"]["observed_signal"] == "efficiency_improvement"
    assert summary["comparison"]["total_token_reduction_fraction"] == pytest.approx(
        2 / 7
    )


def test_three_complete_attempts_are_claim_eligible() -> None:
    results = [
        _result(
            task_id="task-a", condition=condition, attempt=attempt, usage=_usage(100)
        )
        for attempt in (1, 2, 3)
        for condition in benchmark.CONDITIONS
    ]

    summary = benchmark.summarize_results(results, expected_tasks=1, attempts=3)

    assert summary["claim_status"] == "eligible"
    assert summary["expected_pairs"] == 3
    assert summary["complete_pairs"] == 3
    assert summary["comparison"]["observed_signal"] == "no_measured_efficiency_gain"


def test_missing_usage_makes_the_comparison_incomplete() -> None:
    results = [
        _result(task_id="task-a", condition="tokki", attempt=1, usage=_usage(100)),
        _result(task_id="task-a", condition="control", attempt=1, usage=None),
    ]

    summary = benchmark.summarize_results(results, expected_tasks=1, attempts=1)

    assert summary["claim_status"] == "incomplete"
    assert summary["usage_complete"] is False
    assert summary["comparison"]["observed_signal"] == "evidence_incomplete"


def test_lower_tokens_cannot_hide_a_quality_regression() -> None:
    results = [
        _result(
            task_id="task-a",
            condition="tokki",
            attempt=1,
            accepted=False,
            usage=_usage(80),
        ),
        _result(task_id="task-a", condition="control", attempt=1, usage=_usage(140)),
    ]

    summary = benchmark.summarize_results(results, expected_tasks=1, attempts=1)

    assert summary["comparison"]["observed_signal"] == "quality_regression"


def test_report_leads_with_quality_and_discloses_limitations() -> None:
    results = [
        _result(task_id="task-a", condition="tokki", attempt=1, usage=_usage(100)),
        _result(task_id="task-a", condition="control", attempt=1, usage=_usage(140)),
    ]
    manifest = {
        "run_id": "example",
        "source_commit": "a" * 40,
        "model": "gpt-test",
        "reasoning_effort": "high",
        "summary": benchmark.summarize_results(results, expected_tasks=1, attempts=1),
    }

    report = benchmark.render_report(manifest)

    assert "Accepted / attempted" in report
    assert "Comparative signal" in report
    assert "Claim status: **pilot_only**" in report
    assert "Lower tokens are not a win" in report
    assert "first-party evidence" in report


def test_cli_help_exposes_the_claim_and_session_boundaries() -> None:
    help_text = benchmark._build_parser().format_help()

    assert "unrelated human shell" in help_text
    assert "claim-eligible" in help_text
    assert "workspace sandbox is not a VM" in help_text


def test_resolve_executable_preserves_virtualenv_launcher_symlink(
    tmp_path: Path,
) -> None:
    interpreter = tmp_path / "python-base"
    interpreter.write_text("#!/bin/sh\n", encoding="utf-8")
    interpreter.chmod(0o755)
    launcher = tmp_path / "python"
    try:
        launcher.symlink_to(interpreter)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    resolved = benchmark._resolve_executable(str(launcher), label="Python")

    assert resolved == launcher


def test_workspace_uses_current_reviewed_tokki_profile(tmp_path: Path) -> None:
    repo_root = tmp_path / "source"
    workspace = tmp_path / "workspace"
    source_profile = repo_root / ".tokki" / "profile"
    archived_profile = workspace / ".tokki" / "profile"
    source_profile.parent.mkdir(parents=True)
    archived_profile.parent.mkdir(parents=True)
    source_profile.write_text("context-provenance-require-pass\n", encoding="utf-8")
    archived_profile.write_text("stale-capability\n", encoding="utf-8")

    benchmark._overlay_current_tokki_profile(repo_root, workspace)

    assert archived_profile.read_bytes() == source_profile.read_bytes()


@pytest.mark.parametrize(
    ("changed_path", "expected_accepted"),
    (
        ("src/agilab/core/src/agi_node/agi_dispatcher/agi_dispatcher.py", True),
        ("test/conftest.py", False),
    ),
)
def test_condition_runner_grades_product_changes_and_control_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed_path: str,
    expected_accepted: bool,
) -> None:
    task = benchmark.load_tasks(benchmark.DEFAULT_TASKS_PATH)[0]
    observed: dict[str, object] = {}

    def fake_prepare_workspace(repo_root: Path, commit: str, destination: Path) -> str:
        del repo_root, commit
        destination.mkdir()
        return "b" * 40

    def fake_trace_agent_run(command: tuple[str, ...], **kwargs: object) -> object:
        del command
        trace_dir = Path(str(kwargs["output_dir"]))
        trace_dir.mkdir()
        (trace_dir / "stdout.txt").write_text(
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                    },
                }
            ),
            encoding="utf-8",
        )
        (trace_dir / "stderr.txt").write_text("", encoding="utf-8")
        (trace_dir / "agent_run_manifest.json").write_text(
            json.dumps({"kind": "agilab.agent_run.v1"}), encoding="utf-8"
        )
        observed["env_overrides"] = kwargs["env_overrides"]
        return SimpleNamespace(
            returncode=0,
            manifest={"timing": {"duration_seconds": 1.0}},
        )

    monkeypatch.setattr(benchmark, "prepare_workspace", fake_prepare_workspace)
    monkeypatch.setattr(benchmark, "trace_agent_run", fake_trace_agent_run)
    monkeypatch.setattr(
        benchmark,
        "_capture_solution",
        lambda *args, **kwargs: {
            "changed_paths": [changed_path],
            "agent_created_commit": False,
        },
    )
    monkeypatch.setattr(benchmark, "_hidden_test_patch", lambda *args: b"patch")
    monkeypatch.setattr(
        benchmark,
        "_apply_hidden_tests",
        lambda *args: benchmark.CommandCapture(0, "", "", 0.1),
    )
    monkeypatch.setattr(
        benchmark,
        "_run_verification",
        lambda *args, **kwargs: {"passed": True, "commands": []},
    )

    result = benchmark._run_condition(
        task,
        condition="control",
        attempt=1,
        order_index=1,
        repo_root=tmp_path,
        output_root=tmp_path / "output",
        codex_bin=Path("/usr/bin/codex"),
        model="gpt-test",
        reasoning_effort="high",
        python_executable=Path("/usr/bin/python3"),
    )

    assert result["accepted"] is expected_accepted
    assert observed["env_overrides"] == {"TOKKI_AUTO_RUN": "off"}
    assert result["agent"]["usage"]["status"] == "available"
