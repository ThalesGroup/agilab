from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPORT_PATH = Path("tools/repository_knowledge_report.py").resolve()
CORE_PATH = Path("src/agilab/repository_knowledge.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def repository_knowledge_artifacts(tmp_path_factory):
    module = _load_module(REPORT_PATH, "repository_knowledge_report_test_module")
    json_path = tmp_path_factory.mktemp("repository-knowledge") / "repository_knowledge_index.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=json_path,
    )
    payload = module.json.loads(json_path.read_text(encoding="utf-8"))
    return report, payload


def test_repository_knowledge_report_passes(repository_knowledge_artifacts) -> None:
    report, _payload = repository_knowledge_artifacts
    assert report["report"] == "Repository knowledge index report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.repository_knowledge_index.v1"
    assert report["summary"]["run_status"] == "indexed"
    assert report["summary"]["execution_mode"] == "repository_knowledge_static_index"
    assert report["summary"]["indexed_file_count"] > 50
    assert report["summary"]["python_file_count"] > 20
    assert report["summary"]["tool_file_count"] > 10
    assert report["summary"]["docs_file_count"] > 10
    assert report["summary"]["pyproject_count"] >= 8
    assert report["summary"]["runbook_count"] >= 3
    assert report["summary"]["knowledge_map_count"] == 4
    assert report["summary"]["query_seed_count"] >= 4
    assert report["summary"]["excluded_path_hit_count"] == 0
    assert report["summary"]["generated_wiki_source_of_truth"] is False
    assert report["summary"]["official_docs_source_of_truth"] is True
    assert report["summary"]["private_repository_indexed"] is False
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["command_execution_count"] == 0
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "repository_knowledge_schema",
        "repository_knowledge_code_docs_runbooks",
        "repository_knowledge_package_manifests",
        "repository_knowledge_exclusion_guardrails",
        "repository_knowledge_source_of_truth_boundary",
        "repository_knowledge_query_seeds",
        "repository_knowledge_no_network",
        "repository_knowledge_persistence",
        "repository_knowledge_docs_reference",
    }


def test_repository_knowledge_index_excludes_generated_paths(repository_knowledge_artifacts) -> None:
    report, payload = repository_knowledge_artifacts
    assert report["status"] == "pass"
    indexed_paths = [record["path"] for record in payload["records"]]
    assert "artifacts" in payload["excluded_roots"]
    assert ".venv" in payload["excluded_roots"]
    assert "build" in payload["excluded_roots"]
    assert "dist" in payload["excluded_roots"]
    assert not any(path.startswith("artifacts/") for path in indexed_paths)
    assert not any(path.startswith(".venv/") for path in indexed_paths)
    assert payload["provenance"]["generated_content_source_of_truth"] is False
    assert payload["provenance"]["official_docs_remain_source_of_truth"] is True


def test_repository_knowledge_core_handles_small_and_malformed_repositories(tmp_path: Path) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_core_test_module")
    missing = tmp_path / "missing"
    excluded = tmp_path / ".venv" / "file.py"
    excluded.parent.mkdir()
    excluded.write_text("print('skip')\n", encoding="utf-8")
    syntax_error = tmp_path / "bad.py"
    syntax_error.write_text("def broken(:\n", encoding="utf-8")
    doc = tmp_path / "doc.rst"
    doc.write_text(".. comment\n:field: value\n| table\nVisible heading\n", encoding="utf-8")

    assert module._iter_files(missing) == []
    assert module._iter_files(excluded) == []
    assert module._iter_files(syntax_error) == [syntax_error]
    assert module._iter_named_files(missing, "pyproject.toml") == []
    assert module._python_outline(syntax_error)["parse_status"] == "syntax_error"
    assert module._first_heading(doc.read_text(encoding="utf-8")) == "Visible heading"
    assert module._first_heading(".. comment\n:field: value\n| table\n") == ""

    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True)
    (repo_root / "tools").mkdir()
    (repo_root / ".venv").mkdir()
    (repo_root / "src" / "agilab" / "module.py").write_text('"""Doc."""\nimport os\nclass A: pass\ndef f(): pass\n', encoding="utf-8")
    (repo_root / "tools" / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    state = module.build_repository_knowledge_index(repo_root=repo_root)

    assert state["run_status"] == "invalid"
    assert state["summary"]["docs_file_count"] == 0
    assert state["issues"] == [
        {
            "level": "error",
            "location": "official_docs",
            "message": "official documentation was not indexed",
        }
    ]
    assert ".venv" in state["excluded_existing_roots"]


def test_repository_knowledge_core_reports_excluded_index_hits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_exclusion_test_module")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    duplicate = repo_root / "src" / "agilab" / "same.py"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text("VALUE = 1\n", encoding="utf-8")
    pyproject = repo_root / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\n", encoding="utf-8")

    assert module._records(repo_root)

    monkeypatch.setattr(
        module,
        "_records",
        lambda _repo_root: [{"path": ".venv/generated.py", "kind": "package_source"}],
    )

    state = module.build_repository_knowledge_index(repo_root=repo_root)

    assert state["run_status"] == "invalid"
    assert any(issue["location"] == "exclusion_guardrail" for issue in state["issues"])
