from __future__ import annotations

import importlib.util
import json

import pytest
import os
import sys
from pathlib import Path


MODULE_PATH = Path("tools/coverage_badge_guard.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("coverage_badge_guard_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_changed_coverage_components_maps_gui_and_root_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "src/agilab/orchestrate_execute.py",
            "test/test_orchestrate_execute.py",
            "tools/coverage_shard_plan.py",
        ]
    )

    assert changed == {
        "agi-gui": [
            "src/agilab/orchestrate_execute.py",
            "test/test_orchestrate_execute.py",
            "tools/coverage_shard_plan.py",
        ]
    }


def test_changed_coverage_components_maps_agi_web_without_gui_overlap() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "src/agilab/lib/agi-web/src/agi_web/component.py",
            "src/agilab/lib/agi-web/test/test_agi_web_component.py",
        ]
    )

    assert changed == {
        "agi-web": [
            "src/agilab/lib/agi-web/src/agi_web/component.py",
            "src/agilab/lib/agi-web/test/test_agi_web_component.py",
        ]
    }


def test_changed_coverage_components_ignores_coverage_tooling_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "test/test_coverage_badge_guard.py",
            "test/test_agilab_dev_shortcuts.py",
        ]
    )

    assert changed == {}


def test_changed_coverage_components_ignores_non_gui_policy_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "test/test_builtin_app_tests.py",
            "test/test_pyproject_dependency_hygiene.py",
        ]
    )

    assert changed == {}


def test_changed_coverage_components_ignores_release_and_public_docs_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "test/test_beta_readiness.py",
            "test/test_public_demo_links.py",
            "test/test_pypi_publish.py",
            "test/test_pypi_publish_workflow.py",
        ]
    )

    assert changed == {}


def test_changed_coverage_components_ignores_workflow_policy_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            ".github/workflows/coverage.yml",
            "test/conftest.py",
            "test/test_ci_workflow.py",
            "test/test_coverage_workflow.py",
            "test/test_impact_validate.py",
            "test/test_pypi_publish_workflow.py",
            "test/test_workflow_parity.py",
        ]
    )

    assert changed == {}


def test_changed_coverage_components_ignores_package_metadata() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "pyproject.toml",
            "src/agilab/core/agi-env/pyproject.toml",
            "src/agilab/core/agi-node/pyproject.toml",
            "src/agilab/core/agi-cluster/pyproject.toml",
            "src/agilab/core/agi-core/pyproject.toml",
            "src/agilab/lib/agi-gui/pyproject.toml",
            "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml",
        ]
    )

    assert changed == {}


def test_changed_coverage_components_maps_core_tests_to_node_and_cluster() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(["src/agilab/core/test/test_agi_distributor.py"])

    assert changed == {
        "agi-cluster": ["src/agilab/core/test/test_agi_distributor.py"],
        "agi-node": ["src/agilab/core/test/test_agi_distributor.py"],
    }


def test_expand_with_aggregates_adds_core_and_global_badges() -> None:
    module = _load_module()

    assert module.expand_with_aggregates(["agi-env"]) == ["agi-env", "agi-core", "agilab"]
    assert module.expand_with_aggregates(["agi-gui"]) == ["agi-gui", "agilab"]
    assert module.expand_with_aggregates(["agi-web"]) == ["agi-web"]


def test_expected_svg_uses_generator_aggregate_policy() -> None:
    module = _load_module()
    calls = []

    class FakeGenerator:
        COMPONENTS = {
            "agi-core": {
                "aggregate": ("agi-env", "agi-node", "agi-cluster"),
                "aggregate_policy": "minimum",
                "label": "agi-core coverage",
            }
        }

        @staticmethod
        def compute_aggregate_percent(components, combined_xml, *, policy="weighted"):
            calls.append((components, combined_xml.name, policy))
            return 97.0 if policy == "minimum" else 98.0

        @staticmethod
        def format_percent(percent):
            return f"{int(percent)}%"

        @staticmethod
        def badge_color(percent):
            return "green"

        @staticmethod
        def render_badge(label, value, color):
            return f"{label}: {value} ({color})"

    assert module._expected_svg(FakeGenerator, "agi-core") == "agi-core coverage: 97% (green)"
    assert calls == [
        (
            ("agi-env", "agi-node", "agi-cluster"),
            "coverage-agilab.combined.xml",
            "minimum",
        )
    ]


def test_guard_commands_use_combined_core_coverage_profile() -> None:
    module = _load_module()

    commands = module._guard_commands(["agi-node", "agi-cluster"])

    assert commands[0] == (
        "uv --preview-features extra-build-dependencies run python "
        "tools/workflow_parity.py --profile agi-core-combined"
    )
    assert "--profile agi-node --profile agi-cluster" not in "\n".join(commands)


def test_stale_xml_messages_flags_xml_older_than_changed_input(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "src" / "agilab" / "orchestrate_execute.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('changed')\n", encoding="utf-8")
    xml = tmp_path / "coverage-agi-gui.xml"
    xml.write_text('<coverage lines-covered="1" lines-valid="1" />\n', encoding="utf-8")

    old = 1_700_000_000
    new = old + 60
    os.utime(xml, (old, old))
    os.utime(source, (new, new))

    messages = module.stale_xml_messages(
        {"agi-gui": ["src/agilab/orchestrate_execute.py"]},
        repo_root=tmp_path,
    )

    assert messages == [
        "agi-gui: coverage-agi-gui.xml is older than changed input src/agilab/orchestrate_execute.py"
    ]


def test_stale_xml_messages_ignores_regenerated_badge_outputs(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "src" / "agilab" / "orchestrate_execute.py"
    badge = tmp_path / "badges" / "coverage-agi-gui.svg"
    source.parent.mkdir(parents=True)
    badge.parent.mkdir(parents=True)
    source.write_text("print('changed')\n", encoding="utf-8")
    badge.write_text("<svg />\n", encoding="utf-8")
    xml = tmp_path / "coverage-agi-gui.xml"
    xml.write_text('<coverage lines-covered="1" lines-valid="1" />\n', encoding="utf-8")

    old = 1_700_000_000
    os.utime(source, (old + 10, old + 10))
    os.utime(xml, (old + 20, old + 20))
    os.utime(badge, (old + 30, old + 30))

    messages = module.stale_xml_messages(
        {"agi-gui": ["badges/coverage-agi-gui.svg", "src/agilab/orchestrate_execute.py"]},
        repo_root=tmp_path,
    )

    assert messages == []


def test_badge_only_update_messages_blocks_badge_only_changes() -> None:
    module = _load_module()

    messages = module.badge_only_update_messages(
        {"agi-node": ["badges/coverage-agi-node.svg"]},
    )

    assert len(messages) == 1
    assert "badge-only coverage update blocked" in messages[0]
    assert "AGILAB_ALLOW_BADGE_ONLY_UPDATE=1" in messages[0]


def test_badge_only_update_messages_allows_paired_coverage_inputs() -> None:
    module = _load_module()

    messages = module.badge_only_update_messages(
        {
            "agi-node": [
                "badges/coverage-agi-node.svg",
                "src/agilab/core/agi-node/src/agi_node/example.py",
            ],
        },
    )

    assert messages == []


def test_badge_only_update_messages_allows_explicit_override() -> None:
    module = _load_module()

    messages = module.badge_only_update_messages(
        {"agi-node": ["badges/coverage-agi-node.svg"]},
        allow=True,
    )

    assert messages == []


# README status configuration is an offline contract; public verification uses
# controlled HTTP/Actions responses so cache races do not make these tests flaky.

def _readme_badge_html(source=None, destination=None, label="Coverage workflow (main push)"):
    source = source or "https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml/badge.svg?branch=main&amp;event=push"
    destination = destination or "https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml?query=branch%3Amain+event%3Apush"
    return f'<a href="{destination}"><img src="{source}" alt="{label}" /></a>'


def test_readme_workflow_badge_decodes_html_and_query_scope(tmp_path):
    guard = _load_module()
    readme = tmp_path / "README.md"
    readme.write_text(_readme_badge_html())
    assert guard.readme_workflow_badge(readme).endswith("?branch=main&event=push")


@pytest.mark.parametrize("mutation", [
    "missing", "duplicate", "branch", "event", "static", "token",
    "destination", "label", "foreign_host", "fragment",
])
def test_readme_workflow_badge_rejects_scope_or_evidence_regression(tmp_path, mutation):
    guard = _load_module()
    text = _readme_badge_html()
    if mutation == "missing":
        text = "# No status badge"
    elif mutation == "duplicate":
        text *= 2
    elif mutation == "branch":
        text = text.replace("branch=main", "branch=feature")
    elif mutation == "event":
        text = text.replace("&amp;event=push", "")
    elif mutation == "static":
        text = text.replace("https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml/badge.svg?branch=main&amp;event=push",
                            "https://img.shields.io/badge/coverage-passing-green")
    elif mutation == "token":
        text = text.replace("&amp;event=push", "&amp;event=push&amp;cache=123")
    elif mutation == "destination":
        text = text.replace("?query=branch%3Amain+event%3Apush", "")
    elif mutation == "label":
        text = text.replace("Coverage workflow (main push)", "Coverage workflow")
    elif mutation == "foreign_host":
        text = text.replace("github.com", "example.com", 1)
    elif mutation == "fragment":
        text = text.replace("&amp;event=push", "&amp;event=push#fragment")
    readme = tmp_path / "README.md"
    readme.write_text(text)
    with pytest.raises(guard.GuardError):
        guard.readme_workflow_badge(readme)


def _badge_responses(guard, monkeypatch, runs, titles):
    calls, sleeps = [], []
    run_values, title_values = iter(runs), iter(titles)
    def command(args):
        calls.append(args)
        if args[0] == "gh":
            return json.dumps({"workflow_runs": [next(run_values)]})
        assert args[0] == "curl"
        title = next(title_values)
        return f'<svg xmlns="http://www.w3.org/2000/svg"><title>{title}</title></svg>'
    monkeypatch.setattr(guard, "_public_command", command)
    monkeypatch.setattr(guard.time, "sleep", sleeps.append)
    return calls, sleeps


def _coverage_run(number=123, conclusion="success", status="completed"):
    return {"id": number, "conclusion": conclusion, "status": status}


def test_public_badge_retries_stale_image_until_it_matches_actions(monkeypatch):
    guard = _load_module()
    calls, sleeps = _badge_responses(guard, monkeypatch, [_coverage_run()] * 2,
                                    ["coverage - failing", "coverage - passing"])
    result = guard.public_workflow_badge("https://github.com/badge", run_id=123, attempts=2, delay=1)
    assert "matches coverage run 123: success" in result
    assert sleeps == [1]
    assert [call[0] for call in calls] == ["gh", "curl", "gh", "curl"]


def test_persistent_stale_badge_is_not_reported_as_test_failure(monkeypatch):
    guard = _load_module()
    calls, sleeps = _badge_responses(guard, monkeypatch, [_coverage_run()] * 2,
                                    ["coverage - failing"] * 2)
    with pytest.raises(guard.GuardError, match="not evidence of a new test failure") as error:
        guard.public_workflow_badge("https://github.com/badge", run_id=123, attempts=2, delay=1)
    assert "https://github.com/ThalesGroup/agilab/actions/runs/123" in str(error.value)
    assert sleeps == [1]
    assert len(calls) == 4


def test_real_failed_workflow_with_failing_badge_is_faithful(monkeypatch):
    guard = _load_module()
    _, sleeps = _badge_responses(guard, monkeypatch, [_coverage_run(conclusion="failure")],
                                ["coverage - failing"])
    assert "failure" in guard.public_workflow_badge("https://github.com/badge", attempts=1)
    assert sleeps == []


def test_newer_run_supersedes_old_badge_postflight_without_false_failure(monkeypatch):
    guard = _load_module()
    calls, sleeps = _badge_responses(guard, monkeypatch,
                                    [_coverage_run(), _coverage_run(124, None, "in_progress")],
                                    ["coverage - failing"])
    result = guard.public_workflow_badge("https://github.com/badge", run_id=123, attempts=2, delay=1)
    assert "superseded by run 124" in result
    assert [call[0] for call in calls] == ["gh", "curl", "gh"]
    assert sleeps == [1]


def test_pending_run_without_event_identity_cannot_claim_badge_verified(monkeypatch):
    guard = _load_module()
    calls, _ = _badge_responses(guard, monkeypatch, [_coverage_run(status="in_progress")], [])
    with pytest.raises(guard.GuardError, match="verification is pending"):
        guard.public_workflow_badge("https://github.com/badge", attempts=1)
    assert len(calls) == 1


@pytest.mark.parametrize("response", ["not json", "{}", '{"workflow_runs": []}'])
def test_public_badge_fails_closed_without_actions_evidence(monkeypatch, response):
    guard = _load_module()
    monkeypatch.setattr(guard, "_public_command", lambda args: response)
    with pytest.raises(guard.GuardError, match="no valid main push"):
        guard.public_workflow_badge("https://github.com/badge", attempts=1)


def test_readme_only_cli_does_not_require_xml_or_network(tmp_path, monkeypatch, capsys):
    guard = _load_module()
    (tmp_path / "README.md").write_text(_readme_badge_html())
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(guard, "run_guard", lambda args: pytest.fail("XML guard called"))
    monkeypatch.setattr(guard, "_public_command", lambda args: pytest.fail("network called"))
    assert guard.main(["--readme-only", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["success"] is True


def test_badge_guard_is_wired_before_ci_dependencies_and_after_coverage_completion():
    import yaml
    root = MODULE_PATH.parents[1]
    ci = yaml.load((root / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    steps = ci["jobs"]["local-only-policy"]["steps"]
    index = next(i for i, step in enumerate(steps)
                 if step.get("run") == "python tools/coverage_badge_guard.py --readme-only")
    assert index < next(i for i, step in enumerate(steps) if "Playwright" in step.get("name", ""))
    postflight = yaml.load((root / ".github/workflows/coverage-badge-public-status.yml").read_text(),
                          Loader=yaml.BaseLoader)
    assert postflight["on"]["workflow_run"] == {
        "workflows": ["coverage"], "types": ["completed"], "branches": ["main"]}
    assert postflight["permissions"] == {"contents": "read", "actions": "read"}
    job = postflight["jobs"]["verify-public-badge"]
    assert "head_repository.full_name == github.repository" in job["if"]
    assert ".event == 'push'" in job["if"]
    assert job["steps"][0]["with"] == {"ref": "main", "persist-credentials": "false"}
    assert "--workflow-run-id" in job["steps"][-1]["run"]


@pytest.mark.parametrize("document", ["<broken", "<html><title>coverage - passing</title></html>"])
def test_public_badge_rejects_invalid_svg(monkeypatch, document):
    guard = _load_module()
    def command(args):
        if args[0] == "gh":
            return json.dumps({"workflow_runs": [_coverage_run()]})
        return document

    monkeypatch.setattr(guard, "_public_command", command)
    with pytest.raises(guard.GuardError, match="SVG"):
        guard.public_workflow_badge("https://github.com/badge", attempts=1)
