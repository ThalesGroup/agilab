from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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
    artifact_dir = tmp_path_factory.mktemp("repository-knowledge")
    json_path = artifact_dir / "repository_knowledge_index.json"
    cache_path = artifact_dir / "repository_knowledge_records.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=json_path,
        record_cache_path=cache_path,
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
    assert report["summary"]["source_file_count"] > 20
    assert report["summary"]["code_file_count"] > 20
    assert report["summary"]["python_file_count"] > 20
    assert report["summary"]["tool_file_count"] > 10
    assert report["summary"]["test_file_count"] > 10
    assert report["summary"]["docs_file_count"] > 10
    assert report["summary"]["pyproject_count"] >= 8
    assert report["summary"]["runbook_count"] >= 3
    assert report["summary"]["total_line_count"] > 0
    assert report["summary"]["source_line_count"] > 0
    assert report["summary"]["code_line_count"] > 0
    assert report["summary"]["python_line_count"] > 0
    assert report["summary"]["tool_line_count"] > 0
    assert report["summary"]["test_line_count"] > 0
    assert report["summary"]["docs_line_count"] > 0
    assert report["summary"]["pyproject_line_count"] > 0
    assert report["summary"]["runbook_line_count"] > 0
    assert report["summary"]["total_size_bytes"] > 0
    assert report["summary"]["kind_counts"]["test"] == report["summary"]["test_file_count"]
    assert report["summary"]["kind_line_counts"]["test"] == report["summary"]["test_line_count"]
    assert report["summary"]["suffix_line_counts"][".py"] >= report["summary"]["python_line_count"]
    assert report["summary"]["suffix_counts"][".py"] >= report["summary"]["python_file_count"]
    assert report["summary"]["average_lines_per_indexed_file"] > 0
    assert report["summary"]["test_to_code_line_ratio"] > 0
    assert report["summary"]["docs_to_code_line_ratio"] > 0
    assert report["summary"]["manifest_to_code_line_ratio"] > 0
    assert report["summary"]["top_kinds_by_lines"][0]["line_count"] >= report["summary"]["top_kinds_by_lines"][-1]["line_count"]
    assert report["summary"]["top_suffixes_by_lines"][0]["line_count"] >= report["summary"]["top_suffixes_by_lines"][-1]["line_count"]
    assert report["summary"]["largest_files_by_lines"][0]["line_count"] >= report["summary"]["largest_files_by_lines"][-1]["line_count"]
    assert report["summary"]["knowledge_map_count"] == 5
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
        "repository_knowledge_statistics",
        "repository_knowledge_package_manifests",
        "repository_knowledge_exclusion_guardrails",
        "repository_knowledge_source_of_truth_boundary",
        "repository_knowledge_query_seeds",
        "repository_knowledge_no_network",
        "repository_knowledge_persistence",
        "repository_knowledge_docs_reference",
    }


def test_repository_knowledge_report_path_setup_handles_package_paths(tmp_path: Path, monkeypatch) -> None:
    module = _load_module(REPORT_PATH, "repository_knowledge_report_path_setup_test_module")
    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    package_root = src_root / "agilab"
    package_root.mkdir(parents=True)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry not in {str(repo_root), str(src_root)}])

    list_package = SimpleNamespace(__path__=[])
    monkeypatch.setitem(sys.modules, "agilab", list_package)
    module._ensure_repo_on_path(repo_root)

    assert sys.path[:2] == [str(repo_root), str(src_root)]
    assert list_package.__path__ == [str(package_root)]

    tuple_package = SimpleNamespace(__path__=())
    monkeypatch.setitem(sys.modules, "agilab", tuple_package)
    module._ensure_repo_on_path(repo_root)

    assert tuple_package.__path__ == [str(package_root)]


def test_repository_knowledge_report_docs_failure_and_temporary_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module(REPORT_PATH, "repository_knowledge_report_docs_failure_test_module")
    docs_check = module._docs_check(tmp_path / "missing-repo")

    assert docs_check["status"] == "fail"
    assert "error" in docs_check["details"]

    def _fake_persist_repository_knowledge_index(*, repo_root, output_path, record_cache_path):
        del repo_root, record_cache_path
        state = {
            "schema": module.SCHEMA,
            "run_status": "indexed",
            "execution_mode": "repository_knowledge_static_index",
            "excluded_roots": ["artifacts", ".venv", "build", "dist"],
            "excluded_existing_roots": [],
            "issues": [],
            "summary": {
                "indexed_file_count": 90,
                "source_file_count": 40,
                "code_file_count": 70,
                "python_file_count": 45,
                "tool_file_count": 12,
                "test_file_count": 20,
                "docs_file_count": 15,
                "pyproject_count": 8,
                "runbook_count": 3,
                "total_line_count": 1000,
                "source_line_count": 500,
                "code_line_count": 800,
                "python_line_count": 600,
                "tool_line_count": 120,
                "test_line_count": 200,
                "docs_line_count": 100,
                "pyproject_line_count": 80,
                "runbook_line_count": 60,
                "total_size_bytes": 12345,
                "kind_counts": {"test": 20},
                "kind_line_counts": {"test": 200},
                "suffix_counts": {".py": 45},
                "suffix_line_counts": {".py": 600},
                "average_lines_per_indexed_file": 11.1111,
                "test_to_code_line_ratio": 0.25,
                "docs_to_code_line_ratio": 0.125,
                "manifest_to_code_line_ratio": 0.1,
                "top_kinds_by_lines": [
                    {
                        "id": "test",
                        "file_count": 20,
                        "line_count": 200,
                        "average_lines_per_file": 10.0,
                    }
                ],
                "top_suffixes_by_lines": [
                    {
                        "id": ".py",
                        "file_count": 45,
                        "line_count": 600,
                        "average_lines_per_file": 13.3333,
                    }
                ],
                "largest_files_by_lines": [
                    {
                        "path": "test/test_example.py",
                        "kind": "test",
                        "suffix": ".py",
                        "line_count": 120,
                        "size_bytes": 4096,
                    }
                ],
                "knowledge_map_count": 5,
                "query_seed_count": 4,
                "excluded_root_count": 4,
                "excluded_existing_count": 0,
                "excluded_path_hit_count": 0,
                "generated_wiki_source_of_truth": False,
                "official_docs_source_of_truth": True,
                "private_repository_indexed": False,
                "network_probe_count": 0,
                "command_execution_count": 0,
            },
            "knowledge_maps": [{"id": "official_docs", "source_of_truth": True}],
            "query_seeds": [
                {"id": "evidence_flow"},
                {"id": "connector_flow"},
                {"id": "dag_flow"},
                {"id": "docs_source"},
            ],
            "provenance": {"executes_commands": False, "queries_network": False},
        }
        output_path.write_text(module.json.dumps(state, sort_keys=True), encoding="utf-8")
        return {
            "ok": True,
            "round_trip_ok": True,
            "path": str(output_path),
            "state": state,
        }

    monkeypatch.setattr(
        module,
        "persist_repository_knowledge_index",
        _fake_persist_repository_knowledge_index,
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        record_cache_path=tmp_path / "repository-knowledge-cache.json",
    )

    assert report["status"] == "pass"
    assert report["summary"]["round_trip_ok"] is True


def test_repository_knowledge_report_cli_modes(tmp_path: Path, capsys) -> None:
    module = _load_module(REPORT_PATH, "repository_knowledge_report_cli_test_module")
    compact_output = tmp_path / "repository_knowledge_compact.json"
    cache_path = tmp_path / "repository-knowledge-cache.json"
    calls: list[dict[str, object]] = []

    def _fake_build_report(*, output_path=None, record_cache_path=None, use_record_cache=True):
        calls.append(
            {
                "output_path": output_path,
                "record_cache_path": record_cache_path,
                "use_record_cache": use_record_cache,
            }
        )
        report = {"report": "Repository knowledge index report", "status": "pass", "summary": {}}
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(module.json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if record_cache_path is not None and use_record_cache:
            record_cache_path.write_text("{}", encoding="utf-8")
        return report

    module.build_report = _fake_build_report

    assert module.main(["--output", str(compact_output), "--cache-path", str(cache_path), "--compact"]) == 0
    compact = capsys.readouterr().out
    assert "\n" not in compact.strip()
    assert module.json.loads(compact)["status"] == "pass"
    assert compact_output.is_file()
    assert cache_path.is_file()

    pretty_output = tmp_path / "repository_knowledge_pretty.json"
    assert module.main(["--output", str(pretty_output), "--no-cache"]) == 0
    pretty = capsys.readouterr().out
    assert "\n  " in pretty
    assert module.json.loads(pretty)["status"] == "pass"
    assert pretty_output.is_file()
    assert calls == [
        {
            "output_path": compact_output,
            "record_cache_path": cache_path,
            "use_record_cache": True,
        },
        {
            "output_path": pretty_output,
            "record_cache_path": None,
            "use_record_cache": False,
        },
    ]


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
    assert module._text_line_count("one\ntwo\n") == 2
    assert module._text_line_count("") == 0
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
    assert state["summary"]["test_file_count"] == 0
    assert state["summary"]["total_line_count"] > 0
    assert state["summary"]["kind_counts"]["package_source"] == 1
    assert state["summary"]["kind_line_counts"]["package_source"] == 4
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
        lambda _repo_root, **_kwargs: [{"path": ".venv/generated.py", "kind": "package_source"}],
    )

    state = module.build_repository_knowledge_index(repo_root=repo_root)

    assert state["run_status"] == "invalid"
    assert any(issue["location"] == "exclusion_guardrail" for issue in state["issues"])


def test_repository_knowledge_records_skip_duplicate_scan_hits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_duplicate_scan_module")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    shared = repo_root / "shared.py"
    shared.write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(module, "_iter_files", lambda _root: [shared])
    monkeypatch.setattr(module, "_iter_named_files", lambda _root, _filename: [shared])

    records = module._records(repo_root)

    assert len(records) == 1
    assert records[0]["path"] == "shared.py"
    assert records[0]["kind"] == "package_source"


def test_repository_knowledge_records_skip_disappearing_scan_hits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_disappearing_scan_module")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    disappearing = repo_root / "src" / "agilab" / "gone.py"

    monkeypatch.setattr(module, "_iter_files", lambda _root: [disappearing])
    monkeypatch.setattr(module, "_iter_named_files", lambda _root, _filename: [])

    assert module._records(repo_root) == []


def test_repository_knowledge_record_cache_reuses_unchanged_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_record_cache_module")
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True)
    (repo_root / "tools").mkdir()
    (repo_root / "docs" / "source").mkdir(parents=True)
    (repo_root / "src" / "agilab" / "module.py").write_text('"""Cached."""\nVALUE = 1\n', encoding="utf-8")
    (repo_root / "tools" / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo_root / "docs" / "source" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (repo_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    cache_path = tmp_path / "record-cache.json"

    first_records = module._records(repo_root, record_cache_path=cache_path)

    assert cache_path.is_file()

    def _fail_file_record(*_args, **_kwargs):
        raise AssertionError("unchanged records should be loaded from cache")

    monkeypatch.setattr(module, "_file_record", _fail_file_record)

    assert module._records(repo_root, record_cache_path=cache_path) == first_records


def test_repository_knowledge_record_cache_preserves_index_output(tmp_path: Path) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_record_cache_output_module")
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True)
    (repo_root / "tools").mkdir()
    (repo_root / "docs" / "source").mkdir(parents=True)
    (repo_root / "src" / "agilab" / "module.py").write_text('"""Cached."""\nVALUE = 1\n', encoding="utf-8")
    (repo_root / "tools" / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo_root / "docs" / "source" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (repo_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    cache_path = tmp_path / "record-cache.json"

    uncached = module.build_repository_knowledge_index(repo_root=repo_root)
    cached = module.build_repository_knowledge_index(repo_root=repo_root, record_cache_path=cache_path)
    cached_again = module.build_repository_knowledge_index(repo_root=repo_root, record_cache_path=cache_path)

    assert cached == uncached
    assert cached_again == uncached


def test_repository_knowledge_record_cache_invalidates_changed_files(tmp_path: Path) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_record_cache_invalidation_module")
    repo_root = tmp_path / "repo"
    module_path = repo_root / "src" / "agilab" / "module.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text('"""One."""\nVALUE = 1\n', encoding="utf-8")
    cache_path = tmp_path / "record-cache.json"

    first_records = module._records(repo_root, record_cache_path=cache_path)
    first_record = next(record for record in first_records if record["path"] == "src/agilab/module.py")
    original_stat = module_path.stat()

    module_path.write_text('"""Two."""\nVALUE = 1\n', encoding="utf-8")
    os.utime(module_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    second_records = module._records(repo_root, record_cache_path=cache_path)
    second_record = next(record for record in second_records if record["path"] == "src/agilab/module.py")

    assert first_record["docstring"] == "One."
    assert second_record["docstring"] == "Two."
    assert second_record["sha256"] != first_record["sha256"]


def test_repository_knowledge_relative_paths_accept_symlinked_repo_root(tmp_path: Path) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_symlink_root_module")
    repo_root = tmp_path / "repo"
    module_path = repo_root / "src" / "agilab" / "module.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text('"""Linked."""\nVALUE = 1\n', encoding="utf-8")
    link_root = tmp_path / "repo-link"
    try:
        link_root.symlink_to(repo_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are not available: {exc}")

    records = module._records(link_root, record_cache_path=tmp_path / "record-cache.json")

    assert any(record["path"] == "src/agilab/module.py" for record in records)


def test_repository_knowledge_record_cache_helpers_reject_bad_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_record_cache_helpers_module")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    default_cache_path = module.default_record_cache_path(repo_root)

    assert str(default_cache_path).startswith(str(tmp_path / "xdg-cache"))
    assert not str(default_cache_path).startswith(str(repo_root))

    cache_path = tmp_path / "bad-cache.json"
    assert module._load_record_cache(cache_path) == module._empty_record_cache()
    cache_path.write_text("{bad json", encoding="utf-8")
    assert module._load_record_cache(cache_path) == module._empty_record_cache()
    cache_path.write_text(module.json.dumps({"schema": "wrong", "entries": {}}), encoding="utf-8")
    assert module._load_record_cache(cache_path) == module._empty_record_cache()

    signature = {
        "repo_root": str(repo_root),
        "path": "src/agilab/module.py",
        "kind": "package_source",
        "suffix": ".py",
        "size": 10,
        "mtime_ns": 1,
    }
    assert module._cached_record({"entries": {"src/agilab/module.py": {"signature": signature, "record": []}}}, signature) is None
    assert module._cached_record(
        {
            "entries": {
                "src/agilab/module.py": {
                    "signature": {**signature, "mtime_ns": 2},
                    "record": {"path": "src/agilab/module.py"},
                }
            }
        },
        signature,
    ) is None


def test_repository_knowledge_record_cache_round_trips_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_record_cache_module")
    repo_root = tmp_path / "repo"
    source = repo_root / "src" / "agilab" / "module.py"
    docs = repo_root / "docs" / "source" / "index.rst"
    source.parent.mkdir(parents=True)
    docs.parent.mkdir(parents=True)
    source.write_text('"""Module."""\nVALUE = 1\n', encoding="utf-8")
    docs.write_text("Docs\n====\n", encoding="utf-8")
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (repo_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    cache_path = tmp_path / "records-cache.json"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))

    state = module.build_repository_knowledge_index(repo_root=repo_root, record_cache_path=cache_path)

    assert state["summary"]["indexed_file_count"] == 4
    assert state["summary"]["total_line_count"] == 7
    assert state["summary"]["test_file_count"] == 0
    assert module.default_record_cache_path(repo_root).parent == tmp_path / "xdg-cache" / "agilab" / "repository_knowledge"
    cache = module._load_record_cache(cache_path)
    assert cache["schema"] == module.RECORD_CACHE_SCHEMA
    assert sorted(cache["entries"]) == ["README.md", "docs/source/index.rst", "pyproject.toml", "src/agilab/module.py"]

    monkeypatch.setattr(
        module,
        "_file_record",
        lambda *_args, **_kwargs: pytest.fail("cached records should avoid rebuilding file records"),
    )
    cached_state = module.build_repository_knowledge_index(repo_root=repo_root, record_cache_path=cache_path)

    assert cached_state["summary"] == state["summary"]


def test_repository_knowledge_record_cache_rejects_invalid_entries(tmp_path: Path) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_record_cache_invalid_module")
    cache_path = tmp_path / "records-cache.json"

    assert module._load_record_cache(None) == module._empty_record_cache()
    assert module._load_record_cache(cache_path) == module._empty_record_cache()
    cache_path.write_text("{bad json", encoding="utf-8")
    assert module._load_record_cache(cache_path) == module._empty_record_cache()
    cache_path.write_text(module.json.dumps({"schema": "wrong", "entries": {}}), encoding="utf-8")
    assert module._load_record_cache(cache_path) == module._empty_record_cache()
    cache_path.write_text(module.json.dumps({"schema": module.RECORD_CACHE_SCHEMA, "entries": []}), encoding="utf-8")
    assert module._load_record_cache(cache_path) == module._empty_record_cache()

    module._write_record_cache(None, {"entries": {}})
    module._write_record_cache(tmp_path / "bad-state.json", {"entries": []})
    assert not (tmp_path / "bad-state.json").exists()
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    module._write_record_cache(blocker / "records-cache.json", {"entries": {}})
    assert blocker.read_text(encoding="utf-8") == "not a directory"

    signature = {
        "schema": module.RECORD_SCHEMA,
        "path": "src/agilab/module.py",
        "kind": "package_source",
        "suffix": ".py",
        "size": 12,
        "sha256": "abc",
    }
    valid_record = {
        "schema": module.RECORD_SCHEMA,
        "path": "src/agilab/module.py",
        "kind": "package_source",
        "suffix": ".py",
        "size_bytes": 12,
        "line_count": 1,
        "sha256": "abc",
    }
    assert module._cached_record({"entries": []}, signature) is None
    assert module._cached_record({"entries": {}}, signature) is None
    assert module._cached_record({"entries": {"src/agilab/module.py": {"signature": {}, "record": valid_record}}}, signature) is None
    assert module._cached_record({"entries": {"src/agilab/module.py": {"signature": signature, "record": []}}}, signature) is None
    assert (
        module._cached_record(
            {"entries": {"src/agilab/module.py": {"signature": signature, "record": {**valid_record, "sha256": 3}}}},
            signature,
        )
        is None
    )
    assert (
        module._cached_record(
            {"entries": {"src/agilab/module.py": {"signature": signature, "record": {**valid_record, "sha256": "def"}}}},
            signature,
        )
        is None
    )
    cached = module._cached_record(
        {"entries": {"src/agilab/module.py": {"signature": signature, "record": valid_record}}},
        signature,
    )

    assert cached == valid_record
    assert cached is not valid_record


def test_repository_knowledge_excluded_existing_handles_unreadable_root(tmp_path: Path) -> None:
    module = _load_module(CORE_PATH, "repository_knowledge_unreadable_root_module")

    class _UnreadableRoot:
        def iterdir(self):
            raise OSError("denied")

        def __truediv__(self, child: str) -> Path:
            return tmp_path / child

    assert module._excluded_existing(_UnreadableRoot()) == []
