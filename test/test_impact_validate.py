from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/impact_validate.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("impact_validate_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_analyze_paths_flags_shared_core_and_gui_actions() -> None:
    module = _load_module()

    report = module.analyze_paths(
        [
            "src/agilab/core/agi-env/src/agi_env/bootstrap_support.py",
            "src/agilab/orchestrate_execute.py",
        ]
    )

    assert report.overall_risk == "high"
    assert any(zone.key == "shared-core" for zone in report.risk_zones)
    assert any(gate.key == "shared-core-approval" for gate in report.push_gates)
    assert any(action.key == "agi-env-tests" for action in report.required_validations)
    targeted = next(action for action in report.required_validations if action.key == "targeted-pytest")
    assert "test/test_orchestrate_execute.py" in targeted.commands[0]
    gui_parity = next(
        action for action in report.required_validations if action.key == "workflow-parity-agi-gui"
    )
    assert "tools/workflow_parity.py --profile agi-gui" in gui_parity.commands[0]


def test_analyze_paths_adds_skill_sync_and_index_refresh() -> None:
    module = _load_module()

    report = module.analyze_paths(
        [".claude/skills/codex-session-learning/SKILL.md", ".codex/skills/README.md"]
    )

    assert report.overall_risk == "medium"
    artifact = next(action for action in report.artifact_actions if action.key == "skill-sync")
    assert artifact.commands[0] == "python3 tools/sync_agent_skills.py --skills codex-session-learning"
    assert "python3 tools/codex_skills.py --root .codex/skills validate --strict" in artifact.commands
    assert "python3 tools/codex_skills.py --root .codex/skills generate" in artifact.commands
    assert "python3 tools/agent_skill_catalog.py --apply" in artifact.commands
    assert "python3 tools/generate_skill_badges.py" in artifact.commands
    assert (
        "python3 tools/agent_skill_quality_guard.py --roots .claude/skills .codex/skills --fail-on high"
        in artifact.commands
    )
    assert (
        "python3 tools/skill_security_scan.py --roots .claude/skills .codex/skills --fail-on critical"
        in artifact.commands
    )
    parity = next(action for action in report.artifact_actions if action.key == "workflow-parity-skills")
    assert "tools/workflow_parity.py --profile skills" in parity.commands[0]


def test_analyze_paths_keeps_skill_badges_out_of_coverage_badge_refresh() -> None:
    module = _load_module()

    report = module.analyze_paths(
        [
            ".claude/skills/agilab-ui-robot-validation/SKILL.md",
            ".codex/skills/agilab-ui-robot-validation/SKILL.md",
            "badges/skills.svg",
        ]
    )

    assert any(zone.key == "skills" for zone in report.risk_zones)
    assert all(zone.key != "badges" for zone in report.risk_zones)
    assert any(action.key == "workflow-parity-skills" for action in report.artifact_actions)
    assert all(action.key != "badge-refresh" for action in report.artifact_actions)
    assert all(action.key != "workflow-parity-badges" for action in report.artifact_actions)


def test_analyze_paths_adds_badge_refresh_with_component_hint() -> None:
    module = _load_module()

    report = module.analyze_paths(
        [
            "tools/generate_component_coverage_badges.py",
            "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py",
        ]
    )

    artifact = next(action for action in report.artifact_actions if action.key == "badge-refresh")
    assert any("test/test_generate_component_coverage_badges.py" in command for command in artifact.commands)
    assert any("--components agi-gui" in command for command in artifact.commands)
    assert any("tools/coverage_badge_guard.py" in command for command in artifact.commands)
    assert all(action.key != "coverage-badge-guard" for action in report.artifact_actions)
    assert all("--require-fresh-xml" not in command for command in artifact.commands)
    parity = next(action for action in report.artifact_actions if action.key == "workflow-parity-badges")
    assert "tools/workflow_parity.py --profile badges" in parity.commands[0]


def test_analyze_paths_keeps_workflow_policy_tests_out_of_gui_parity() -> None:
    module = _load_module()

    report = module.analyze_paths(
        [
            ".github/workflows/coverage.yml",
            ".github/workflows/ensure-roadmap-label.yaml",
            "test/conftest.py",
            "test/test_ci_workflow.py",
            "test/test_impact_validate.py",
            "test/test_workflow_parity.py",
        ]
    )

    assert all(action.key != "workflow-parity-agi-gui" for action in report.required_validations)
    assert all(action.key != "coverage-badge-guard" for action in report.artifact_actions)
    targeted = next(action for action in report.required_validations if action.key == "targeted-pytest")
    assert targeted.commands == [
        "uv --preview-features extra-build-dependencies run pytest -q -o addopts='' "
        "test/test_coverage_workflow.py test/test_ci_workflow.py "
        "test/test_view_maps_3d.py::test_view_maps_3d_warns_when_no_dataset_exists "
        "test/test_impact_validate.py test/test_workflow_parity.py"
    ]


def test_main_json_output_for_explicit_files(capsys, tmp_path: Path) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--files",
            ".idea/runConfigurations/agilab_run_dev.xml",
            "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py",
            "--cache-path",
            str(tmp_path / "impact-cache.json"),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_risk"] == "medium"
    assert any(zone["key"] == "runconfig" for zone in payload["risk_zones"])
    assert any(action["key"] == "runconfig-regenerate" for action in payload["artifact_actions"])
    assert "test/test_view_maps_network.py" in payload["guessed_tests"]


def test_analyze_paths_adds_install_contract_check_for_install_entrypoint() -> None:
    module = _load_module()

    report = module.analyze_paths(["src/agilab/apps/install.py"])

    assert report.overall_risk == "high"
    assert any(gate.key == "install-contract" for gate in report.push_gates)
    contract_check = next(
        action for action in report.required_validations if action.key == "install-contract-check"
    )
    assert "tools/install_contract_check.py" in contract_check.commands[0]
    parity = next(
        action for action in report.required_validations if action.key == "workflow-parity-installer"
    )
    assert "tools/workflow_parity.py --profile installer" in parity.commands[0]


def test_analyze_paths_treats_core_installer_as_shared_installer() -> None:
    module = _load_module()

    report = module.analyze_paths(["src/agilab/core/install.sh"])

    assert report.overall_risk == "high"
    assert any(zone.key == "shared-core" for zone in report.risk_zones)
    assert any(zone.key == "installer" for zone in report.risk_zones)
    shell_syntax = next(action for action in report.required_validations if action.key == "shell-syntax")
    assert shell_syntax.commands == ["bash -n install.sh src/agilab/install_apps.sh src/agilab/core/install.sh"]


def test_analyze_paths_adds_docs_workflow_parity_for_docs_source() -> None:
    module = _load_module()

    report = module.analyze_paths(["docs/source/faq.rst"])

    artifact = next(action for action in report.artifact_actions if action.key == "workflow-parity-docs")
    assert "tools/workflow_parity.py --profile docs" in artifact.commands[0]


def test_build_test_index_matches_exact_and_prefix_tests(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_demo.py").write_text("def test_demo():\n    pass\n")
    (tmp_path / "test" / "test_demo_extra.py").write_text(
        "def test_demo_extra():\n    pass\n",
        encoding="utf-8",
    )
    core_test_root = tmp_path / "src" / "agilab" / "core" / "test"
    core_test_root.mkdir(parents=True)
    (core_test_root / "test_demo_core.py").write_text(
        "def test_demo_core():\n    pass\n",
        encoding="utf-8",
    )

    index = module._build_test_index(repo=tmp_path)

    assert index.tests_for_stem("demo") == [
        "test/test_demo.py",
        "test/test_demo_extra.py",
        "src/agilab/core/test/test_demo_core.py",
    ]
    assert index.tests_for_stem("demo", roots=("test",)) == [
        "test/test_demo.py",
        "test/test_demo_extra.py",
    ]


def test_test_index_signature_ignores_test_content_changes(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "test").mkdir()
    test_path = tmp_path / "test" / "test_demo.py"
    test_path.write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    first = module._test_index_signature(repo=tmp_path)

    test_path.write_text("def test_demo():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    second = module._test_index_signature(repo=tmp_path)

    assert second == first


def test_cached_test_index_reuses_signature_paths_without_rescan(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    cache_path = tmp_path / "impact-cache.json"
    signature = [
        {"path": "test", "state": "root", "exists": True},
        {"path": "test/test_demo.py", "state": "test-file"},
        {"path": "test/test_demo_extra.py", "state": "test-file"},
    ]

    monkeypatch.setattr(
        module,
        "_discover_test_index_paths",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("signature paths should avoid rediscovery")
        ),
    )
    index = module._build_cached_test_index(cache_path=cache_path, signature=signature)

    assert index.tests_for_stem("demo") == [
        "test/test_demo.py",
        "test/test_demo_extra.py",
    ]


def test_cached_test_index_reuses_unchanged_signature(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_demo.py").write_text(
        "def test_demo():\n    pass\n",
        encoding="utf-8",
    )
    cache_path = tmp_path / "impact-cache.json"

    first = module._build_cached_test_index(cache_path=cache_path)

    monkeypatch.setattr(
        module,
        "_build_test_index",
        lambda: (_ for _ in ()).throw(
            AssertionError("unchanged cached test index should avoid rebuild")
        ),
    )
    second = module._build_cached_test_index(cache_path=cache_path)

    assert second.paths == first.paths
    assert second.tests_for_stem("demo") == ["test/test_demo.py"]


def test_cached_test_index_accepts_empty_signature(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    for root in module.TEST_GUESS_ROOTS:
        (tmp_path / root).mkdir(parents=True)
    cache_path = tmp_path / "impact-cache.json"

    first = module._build_cached_test_index(cache_path=cache_path, signature=[])

    monkeypatch.setattr(
        module,
        "_test_index_signature",
        lambda: (_ for _ in ()).throw(
            AssertionError("explicit empty signature should be reused")
        ),
    )
    monkeypatch.setattr(
        module,
        "_build_test_index",
        lambda: (_ for _ in ()).throw(
            AssertionError("matching empty signature should avoid rebuild")
        ),
    )
    second = module._build_cached_test_index(cache_path=cache_path, signature=[])

    assert second.paths == first.paths == frozenset()


def test_analyze_paths_reuses_cached_report(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_demo.py").write_text(
        "def test_demo():\n    pass\n",
        encoding="utf-8",
    )
    cache_path = tmp_path / "impact-cache.json"

    first = module.analyze_paths(
        ["src/agilab/demo.py"],
        cache_path=cache_path,
    )

    monkeypatch.setattr(
        module,
        "_analyze_paths_uncached",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cached report should avoid impact recomputation")
        ),
    )
    second = module.analyze_paths(
        ["src/agilab/demo.py"],
        cache_path=cache_path,
    )

    assert second.to_dict() == first.to_dict()


def test_analyze_paths_invalidates_report_when_test_index_changes(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_demo.py").write_text(
        "def test_demo():\n    pass\n",
        encoding="utf-8",
    )
    cache_path = tmp_path / "impact-cache.json"

    first = module.analyze_paths(["src/agilab/demo.py"], cache_path=cache_path)
    assert first.guessed_tests == ["test/test_demo.py"]

    (tmp_path / "test" / "test_demo_extra.py").write_text(
        "def test_demo_extra():\n    pass\n",
        encoding="utf-8",
    )
    second = module.analyze_paths(["src/agilab/demo.py"], cache_path=cache_path)

    assert second.guessed_tests == ["test/test_demo.py", "test/test_demo_extra.py"]


def test_invalid_impact_cache_falls_back_to_rebuild(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_demo.py").write_text(
        "def test_demo():\n    pass\n",
        encoding="utf-8",
    )
    cache_path = tmp_path / "impact-cache.json"
    cache_path.write_text("[]", encoding="utf-8")

    report = module.analyze_paths(["src/agilab/demo.py"], cache_path=cache_path)

    assert report.guessed_tests == ["test/test_demo.py"]
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["schema"] == module.IMPACT_CACHE_SCHEMA


def test_analyze_paths_builds_test_index_once(monkeypatch) -> None:
    module = _load_module()
    real_build_test_index = module._build_test_index
    calls = []

    def _wrapped_build_test_index(*args, **kwargs):
        calls.append((args, kwargs))
        return real_build_test_index(*args, **kwargs)

    monkeypatch.setattr(module, "_build_test_index", _wrapped_build_test_index)

    report = module.analyze_paths(
        [
            "src/agilab/pipeline_ai.py",
            "src/agilab/pipeline_openai.py",
            "src/agilab/orchestrate_execute.py",
        ],
        use_cache=False,
    )

    assert len(calls) == 1
    assert "test/test_pipeline_ai.py" in report.guessed_tests
    assert "test/test_pipeline_openai.py" in report.guessed_tests
    assert "test/test_orchestrate_execute.py" in report.guessed_tests
