"""Root-confined repository exploration, persistence, and recovery regressions."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from agilab.reports import repository_knowledge as knowledge


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def public_repo(tmp_path: Path) -> Path:
    root = tmp_path / "public-repo"
    files = {
        "src/agilab/calcul_été.py": (
            '"""See docs/source/guide.rst for the compute_total contract."""\n'
            "def compute_total(values):\n"
            "    return sum(values)\n"
            "# a.*b is a literal marker\n"
            "# alpha beta and alpha alone\n"
        ),
        "docs/source/guide.rst": "Public guide\n============\ncompute_total sums values.\n",
        "test/test_calcul.py": "from agilab.calcul_été import compute_total\n",
        "pyproject.toml": "[project]\nname = 'public-fixture'\n",
        "README.md": "# Public fixture\n",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _build(root: Path):
    return knowledge.build_repository_knowledge_index(repo_root=root)


def _search(state, root, query="compute_total", **kwargs):
    return knowledge.search_repository_knowledge_index(
        state, repo_root=root, query=query, **kwargs
    )


def test_persist_reload_source_links_and_literal_crosslinks(
    public_repo: Path, tmp_path: Path
):
    path = tmp_path / "public-repository-index.json"
    proof = knowledge.persist_repository_knowledge_index(
        repo_root=public_repo,
        output_path=path,
        record_cache_path=tmp_path / "cache.json",
    )
    assert proof["ok"]
    state = knowledge.load_repository_knowledge_index(path, repo_root=public_repo)
    assert state == proof["state"]
    result = _search(state, public_repo, "def compute_total")
    assert result["status"] == "pass"
    assert result["source_fingerprint"] == state["source_fingerprint"]
    assert result["match_count"] == 1
    hit = result["results"][0]
    source = public_repo / hit["path"]
    assert hit["path"] == "src/agilab/calcul_été.py"
    assert hit["line"] == 2
    assert hit["source_ref"].endswith("#L2")
    assert hit["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert "def compute_total" in hit["excerpt"]
    assert hit["line_start"] <= 2 <= hit["line_end"]
    assert hit["crosslinks"][0]["path"] == "docs/source/guide.rst"
    assert hit["crosslinks"][0]["relationship"] == "literal_path_reference"
    assert result["official_documentation"][0]["path"] == "docs/source/guide.rst"
    assert all("sha256" in item for item in result["official_documentation"])


def test_search_literal_metacharacters_tokens_and_determinism(public_repo: Path):
    state = _build(public_repo)
    assert _search(state, public_repo, "a.*b")["match_count"] == 1
    assert _search(state, public_repo, "a.+b")["match_count"] == 0
    result = _search(state, public_repo, "alpha beta", mode="tokens")
    assert result["match_count"] == 1
    assert result == _search(state, public_repo, "alpha beta", mode="tokens")
    rows = _search(state, public_repo)["results"]
    assert [(r["path"], r["line"]) for r in rows] == sorted(
        (r["path"], r["line"]) for r in rows
    )


@pytest.mark.parametrize("change", ["edit", "delete", "add", "replace_identity"])
def test_changed_sources_refuse_until_explicit_rebuild(
    public_repo: Path, tmp_path: Path, change
):
    path = tmp_path / "public-repository-index.json"
    knowledge.persist_repository_knowledge_index(
        repo_root=public_repo, output_path=path
    )
    state = knowledge.load_repository_knowledge_index(path, repo_root=public_repo)
    source = public_repo / "src/agilab/calcul_été.py"
    if change == "edit":
        before = source.stat()
        source.write_bytes(source.read_bytes().replace(b"sum(values)", b"max(values)"))
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == "delete":
        source.unlink()
    elif change == "add":
        (public_repo / "tools").mkdir()
        (public_repo / "tools/new.py").write_text("# compute_total\n")
    else:
        replacement = source.with_suffix(".replacement")
        replacement.write_bytes(source.read_bytes())
        replacement.replace(source)
    with pytest.raises(ValueError, match="(?i)rebuild"):
        _search(state, public_repo)
    with pytest.raises(ValueError, match="(?i)rebuild"):
        knowledge.load_repository_knowledge_index(path, repo_root=public_repo)
    proof = knowledge.persist_repository_knowledge_index(
        repo_root=public_repo, output_path=path
    )
    assert proof["ok"]
    recovered = knowledge.load_repository_knowledge_index(path, repo_root=public_repo)
    assert _search(recovered, public_repo)["status"] == "pass"
    assert recovered["source_fingerprint"] != state["source_fingerprint"]


def test_explicit_root_and_corrupt_index_refusal(public_repo: Path, tmp_path: Path):
    path = tmp_path / "public-repository-index.json"
    state = _build(public_repo)
    knowledge.write_repository_knowledge_index(path, state)
    other = tmp_path / "separate-public-root"
    other.mkdir()
    with pytest.raises(ValueError, match="(?i)root"):
        knowledge.load_repository_knowledge_index(path, repo_root=other)
    with pytest.raises(ValueError, match="(?i)root"):
        knowledge.load_repository_knowledge_index(path)
    for content in ("{broken", "[]", '{"schema":"unknown"}'):
        path.write_text(content)
        with pytest.raises(ValueError, match="(?i)(index|rebuild)"):
            knowledge.load_repository_knowledge_index(path, repo_root=public_repo)
    altered = copy.deepcopy(state)
    altered["records"][0]["sha256"] = "0" * 64
    knowledge.write_repository_knowledge_index(path, altered)
    with pytest.raises(ValueError, match="(?i)(fingerprint|rebuild)"):
        knowledge.load_repository_knowledge_index(path, repo_root=public_repo)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.py",
        "/tmp/outside.py",
        "src/../outside.py",
        r"src\outside.py",
        "src//agilab/calcul_été.py",
        ".tokki/source.py",
        "src/agilab/.venv-secret/evil.py",
    ],
)
def test_index_rejects_unsafe_paths_before_source_reads(
    public_repo: Path, unsafe_path, monkeypatch
):
    state = _build(public_repo)
    state["records"][0]["path"] = unsafe_path
    monkeypatch.setattr(
        knowledge, "_read_source", lambda *_a: pytest.fail("unsafe source read")
    )
    with pytest.raises(ValueError, match="(?i)(path|index|rebuild)"):
        _search(state, public_repo)


def test_duplicate_records_refuse(public_repo: Path):
    state = _build(public_repo)
    state["records"].append(copy.deepcopy(state["records"][0]))
    with pytest.raises(ValueError, match="(?i)(duplicate|index|rebuild)"):
        _search(state, public_repo)


def test_outside_symlinks_never_indexed_and_replacements_refuse(
    public_repo: Path, tmp_path: Path
):
    outside = tmp_path / "public-outside-fixture"
    outside.mkdir()
    (outside / "outside.py").write_text("OUTSIDE_PUBLIC_SENTINEL = 1\n")
    (outside / "pyproject.toml").write_text("[project]\nname='outside'\n")
    linked = public_repo / "src/agilab/escape.py"
    linked.symlink_to(outside / "outside.py")
    (public_repo / "src/agilab/escape_dir").symlink_to(
        outside, target_is_directory=True
    )
    state = _build(public_repo)
    assert not any("escape" in row["path"] for row in state["records"])
    assert _search(state, public_repo, "OUTSIDE_PUBLIC_SENTINEL")["match_count"] == 0
    source = public_repo / "src/agilab/calcul_été.py"
    original = source.read_bytes()
    source.unlink()
    source.symlink_to(outside / "outside.py")
    with pytest.raises(ValueError, match="(?i)(rebuild|symlink|source)"):
        _search(state, public_repo)
    source.unlink()
    source.write_bytes(original)
    assert _search(_build(public_repo), public_repo)["match_count"] > 0


def test_generated_environment_and_report_paths_are_pruned(public_repo: Path):
    for part in (
        ".git",
        ".tokki",
        "reports",
        ".venv-private",
        "node_modules",
        "__pycache__",
        "build",
        "dist",
        "artifacts",
        ".env",
    ):
        path = public_repo / part / "pyproject.toml"
        path.parent.mkdir(parents=True)
        path.write_text("[project]\nname='excluded-marker'\n")
        nested = (
            public_repo
            / "src/agilab"
            / ("generated" if part == "reports" else "")
            / part
            / "excluded.py"
        )
        nested.parent.mkdir(parents=True)
        nested.write_text("EXCLUDED_MARKER = 1\n")
    state = _build(public_repo)
    assert all("excluded" not in row["path"] for row in state["records"])
    assert _search(state, public_repo, "EXCLUDED_MARKER")["match_count"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"query": "é" * 1025},
        {"query": "a\nb"},
        {"mode": "regex"},
        {"query": " ".join(str(i) for i in range(40)), "mode": "tokens"},
        {"limit": 0},
        {"limit": 1000},
        {"limit": True},
        {"context_lines": 100},
        {"context_bytes": 1000000},
        {"output_bytes": 1000000},
    ],
)
def test_search_limits_fail_before_reading_sources(
    public_repo: Path, kwargs, monkeypatch
):
    state = _build(public_repo)
    monkeypatch.setattr(
        knowledge, "_read_source", lambda *_a: pytest.fail("invalid query read source")
    )
    query = kwargs.pop("query", "compute_total")
    with pytest.raises(ValueError):
        _search(state, public_repo, query, **kwargs)


def test_utf8_context_result_and_response_limits(public_repo: Path):
    source = public_repo / "src/agilab/calcul_été.py"
    source.write_text("# " + "é" * 800 + "needle" + "界" * 800 + "\n# needle\n" * 20)
    state = _build(public_repo)
    result = _search(
        state, public_repo, "needle", limit=2, context_bytes=512, output_bytes=4096
    )
    assert result["match_count"] == 21
    assert 0 < len(result["results"]) <= 2
    assert result["results_truncated"]
    for row in result["results"]:
        assert len(row["excerpt"].encode("utf-8")) <= 512
        assert "needle" in row["excerpt"]
        assert "\ufffd" not in row["excerpt"]
    assert (
        len(
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
        )
        <= 4096
    )


def test_finite_source_file_and_scan_budgets(public_repo: Path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "MAX_SOURCE_FILE_BYTES", 32)
        with pytest.raises(ValueError, match="(?i)(limit|budget|large)"):
            _build(public_repo)
    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "MAX_SOURCE_BYTES", 32)
        with pytest.raises(ValueError, match="(?i)(limit|budget)"):
            _build(public_repo)
    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "MAX_SCAN_ENTRIES", 2)
        with pytest.raises(ValueError, match="(?i)(limit|budget)"):
            _build(public_repo)


def test_selected_source_rechecked_before_return(public_repo: Path, monkeypatch):
    state = _build(public_repo)
    source = public_repo / "src/agilab/calcul_été.py"
    original_read = knowledge._read_source
    seen = 0

    def changing_read(root, path):
        nonlocal seen
        if path.name == source.name:
            seen += 1
            if seen == 2:
                source.write_text("# changed during query\n")
        return original_read(root, path)

    monkeypatch.setattr(knowledge, "_read_source", changing_read)
    with pytest.raises(ValueError, match="(?i)rebuild"):
        _search(state, public_repo, "def compute_total")


def test_cli_build_load_query_and_explicit_recovery(
    public_repo: Path, tmp_path: Path, capsys
):
    spec = importlib.util.spec_from_file_location(
        "public_knowledge_explorer_cli", ROOT / "tools/repository_knowledge_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    index = tmp_path / "public-repository-index.json"
    root_args = ["--repo-root", str(public_repo), "--compact"]
    assert module.main([*root_args, "--build-index", str(index), "--no-cache"]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["status"] == "pass"
    assert index.is_file()
    assert (
        module.main([*root_args, "--index", str(index), "--query", "def compute_total"])
        == 0
    )
    queried = json.loads(capsys.readouterr().out)
    assert queried["results"][0]["line"] == 2
    assert queried["official_documentation"][0]["path"] == "docs/source/guide.rst"
    (public_repo / "docs/source/guide.rst").write_text(
        "Updated official public guide\n"
    )
    assert (
        module.main([*root_args, "--index", str(index), "--query", "compute_total"])
        == 2
    )
    refused = json.loads(capsys.readouterr().out)
    assert refused["status"] == "fail"
    assert "rebuild" in refused["error"].lower()
    assert "results" not in refused
    assert (
        module.main(
            [
                *root_args,
                "--build-index",
                str(index),
                "--query",
                "compute_total",
                "--no-cache",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["match_count"] > 0


def test_index_duplicate_json_keys_and_special_files_refuse(
    public_repo: Path, tmp_path: Path
):
    path = tmp_path / "public-repository-index.json"
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError, match="(?i)(corrupt|rebuild)"):
        knowledge.load_repository_knowledge_index(path, repo_root=public_repo)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ValueError, match="(?i)(corrupt|rebuild)"):
        knowledge.load_repository_knowledge_index(path, repo_root=public_repo)


def test_source_and_directory_swap_cannot_follow_an_external_symlink(
    public_repo: Path, tmp_path: Path, monkeypatch
):
    outside = tmp_path / "another-public-fixture"
    outside.mkdir()
    (outside / "payload.py").write_text("OUTSIDE_PUBLIC_SENTINEL = 1\n")
    target = public_repo / "src/agilab/calcul_été.py"
    target.unlink()
    target.symlink_to(outside / "payload.py")
    with pytest.raises(ValueError, match="(?i)(source|symlink|rebuild)"):
        knowledge._read_source(public_repo, target)

    # A race replaces the already selected root with a symlink. The file reader
    # must retain that root identity rather than resolve the replacement target.
    moved = public_repo.with_name("moved-public-fixture")
    public_repo.rename(moved)
    public_repo.symlink_to(outside, target_is_directory=True)
    (outside / "src/agilab").mkdir(parents=True)
    (outside / "src/agilab/calcul_été.py").write_text("OUTSIDE_PUBLIC_SENTINEL = 1\n")
    with pytest.raises(ValueError, match="(?i)(source|symlink|rebuild)"):
        knowledge._read_source(public_repo, public_repo / "src/agilab/calcul_été.py")


def test_artifact_paths_cannot_overwrite_indexed_source(public_repo: Path):
    source = public_repo / "docs/source/guide.rst"
    before = source.read_bytes()
    with pytest.raises(ValueError, match="(?i)(source|outside)"):
        knowledge.persist_repository_knowledge_index(
            repo_root=public_repo, output_path=source
        )
    with pytest.raises(ValueError, match="(?i)(source|outside)"):
        knowledge.build_repository_knowledge_index(
            repo_root=public_repo, record_cache_path=source
        )
    assert source.read_bytes() == before


def test_environment_repository_hints_do_not_expand_the_index(
    public_repo: Path, tmp_path: Path, monkeypatch
):
    outside = tmp_path / "explicitly-unselected-public-fixture"
    outside.mkdir()
    (outside / "pyproject.toml").write_text("[project]\nname='unselected-fixture'\n")
    monkeypatch.setenv("APPS_REPOSITORY", str(outside))
    monkeypatch.setenv("AGILAB_DOCS_SOURCE", str(outside))
    state = _build(public_repo)
    assert _search(state, public_repo, "unselected-fixture")["match_count"] == 0


def test_cache_does_not_preserve_corrupt_line_statistics(
    public_repo: Path, tmp_path: Path
):
    cache = tmp_path / "public-record-cache.json"
    first = knowledge.build_repository_knowledge_index(
        repo_root=public_repo, record_cache_path=cache
    )
    payload = json.loads(cache.read_text())
    for entry in payload["entries"].values():
        entry["record"]["line_count"] = 987654321
    cache.write_text(json.dumps(payload))
    current = knowledge.build_repository_knowledge_index(
        repo_root=public_repo, record_cache_path=cache
    )
    assert current["summary"] == first["summary"]
    assert current["source_fingerprint"] == first["source_fingerprint"]


def test_source_reports_package_remains_indexed_while_generated_reports_are_pruned(
    public_repo: Path,
):
    maintained = public_repo / "src/agilab/reports/maintained.py"
    maintained.parent.mkdir()
    maintained.write_text("def maintained_public_report(): pass\\n")
    generated = public_repo / "reports/generated/pyproject.toml"
    generated.parent.mkdir(parents=True)
    generated.write_text("[project]\\nname='generated-report-output'\\n")
    state = _build(public_repo)
    assert state["summary"]["excluded_path_hit_count"] == 0
    assert any(
        row["path"] == "src/agilab/reports/maintained.py" for row in state["records"]
    )
    hit = _search(state, public_repo, "maintained_public_report")["results"][0]
    assert hit["path"] == "src/agilab/reports/maintained.py"
    assert _search(state, public_repo, "generated-report-output")["match_count"] == 0


@pytest.mark.parametrize("cache_mode", ["default", "explicit"])
@pytest.mark.parametrize(
    "content,field,poison",
    [
        ("x\n", "line_count", True),
        ("", "line_count", False),
        ("x\n", "line_count", 1.0),
        ("x\n", "line_count", "1"),
        ("x\n", "size_bytes", 2.0),
        ("x", "size_bytes", True),
        ("", "size_bytes", False),
        ("x\n", "size_bytes", "2"),
    ],
)
def test_cached_numeric_types_rebuild_cli(
    public_repo: Path, tmp_path: Path, monkeypatch, cache_mode, content, field, poison
):
    (public_repo / "README.md").write_text(content, encoding="utf-8")
    cache_home = tmp_path / "cache-root"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    cache = (
        tmp_path / "explicit-record-cache.json"
        if cache_mode == "explicit"
        else knowledge.default_record_cache_path(public_repo)
    )
    expected_index = tmp_path / "cache-disabled-index.json"
    index = tmp_path / "cached-index.json"
    options = ["--cache-path", str(cache)] if cache_mode == "explicit" else []
    disabled = _kex_cli(
        public_repo,
        "--build-index",
        str(expected_index),
        "--no-cache",
        cache_home=cache_home,
    )
    assert disabled.returncode == 0, (disabled.stdout, disabled.stderr)
    expected = json.loads(expected_index.read_text())
    initial = _kex_cli(
        public_repo, "--build-index", str(index), *options, cache_home=cache_home
    )
    assert initial.returncode == 0, (initial.stdout, initial.stderr)
    assert json.loads(index.read_text()) == expected
    valid_cache = json.loads(cache.read_text())
    poisoned = copy.deepcopy(valid_cache)
    poisoned["entries"]["README.md"]["record"][field] = poison
    cache.write_text(json.dumps(poisoned), encoding="utf-8")
    # Run twice before asserting: a failed build must not preserve a cache poison.
    rebuilt = [
        _kex_cli(
            public_repo, "--build-index", str(index), *options, cache_home=cache_home
        )
        for _ in range(2)
    ]
    reloaded = _kex_cli(public_repo, "--index", str(index), cache_home=cache_home)
    outcomes = [*rebuilt, reloaded]
    assert [result.returncode for result in outcomes] == [0, 0, 0], [
        (result.returncode, result.stdout, result.stderr) for result in outcomes
    ]
    assert all("Traceback" not in result.stderr for result in outcomes)
    assert all(len(result.stdout.encode("utf-8")) < 65536 for result in outcomes)
    assert json.loads(index.read_text()) == expected
    repaired = json.loads(cache.read_text())
    assert repaired == valid_cache
    record = repaired["entries"]["README.md"]["record"]
    assert type(record[field]) is int
    assert (
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
        == expected
    )


@pytest.mark.parametrize(
    "field_path",
    [
        ("signature", "size"),
        ("signature", "mtime_ns"),
        ("signature", "source_identity", "device"),
        ("signature", "source_identity", "inode"),
        ("record", "line_count"),
        ("record", "size_bytes"),
        ("record", "source_identity", "device"),
        ("record", "source_identity", "inode"),
    ],
)
def test_numeric_cache_metadata_misses_repair_and_preserve_valid_hits(
    public_repo: Path, tmp_path: Path, monkeypatch, field_path
):
    source = public_repo / "src/agilab/calcul_été.py"
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    cache = tmp_path / "record-cache.json"
    expected = _build(public_repo)
    assert (
        knowledge.build_repository_knowledge_index(
            repo_root=public_repo, record_cache_path=cache
        )
        == expected
    )
    valid = json.loads(cache.read_text())
    key = source.relative_to(public_repo).as_posix()
    signature = copy.deepcopy(valid["entries"][key]["signature"])
    assert knowledge._cached_record(valid, signature) == valid["entries"][key]["record"]
    poisoned = copy.deepcopy(valid)
    target = poisoned["entries"][key]
    for part in field_path[:-1]:
        target = target[part]
    original = target[field_path[-1]]
    assert type(original) is int
    target[field_path[-1]] = float(original)
    assert target[field_path[-1]] == original
    assert knowledge._cached_record(poisoned, signature) is None
    cache.write_text(json.dumps(poisoned), encoding="utf-8")
    regenerated = []
    file_record = knowledge._file_record

    def regenerate(root, path, *args, **kwargs):
        regenerated.append(path.relative_to(root).as_posix())
        return file_record(root, path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "_file_record", regenerate)
        assert (
            knowledge.build_repository_knowledge_index(
                repo_root=public_repo, record_cache_path=cache
            )
            == expected
        )
    assert regenerated == [key]
    assert json.loads(cache.read_text()) == valid
    monkeypatch.setattr(
        knowledge, "_file_record", lambda *_a, **_kw: pytest.fail("valid cache miss")
    )
    assert (
        knowledge.build_repository_knowledge_index(
            repo_root=public_repo, record_cache_path=cache
        )
        == expected
    )


def _kex_cli(root: Path, *args: str, cache_home: Path | None = None):
    import subprocess
    import sys

    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    if cache_home is not None:
        environment["XDG_CACHE_HOME"] = str(cache_home)
    # subprocess.run kills and reaps its child before raising TimeoutExpired.
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/repository_knowledge_report.py"),
            "--repo-root",
            str(root),
            "--compact",
            *args,
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=4,
    )


@pytest.mark.parametrize("entrypoint", ["report", "explorer"])
@pytest.mark.parametrize("cache_mode", ["explicit", "default"])
def test_kex_cache_fifo_cli_is_bounded_and_reaped(
    public_repo: Path, tmp_path: Path, monkeypatch, entrypoint, cache_mode
):
    cache_home = tmp_path / "cache-root"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    cache = (
        tmp_path / "record-cache.json"
        if cache_mode == "explicit"
        else knowledge.default_record_cache_path(public_repo)
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(cache)
    index = tmp_path / "public-repository-index.json"
    flag = "--output" if entrypoint == "report" else "--build-index"
    options = ["--cache-path", str(cache)] if cache_mode == "explicit" else []
    completed = _kex_cli(public_repo, flag, str(index), *options, cache_home=cache_home)
    assert completed.returncode == (1 if entrypoint == "report" else 0)
    assert "Traceback" not in completed.stderr
    assert json.loads(completed.stdout)["status"] in {"pass", "fail"}
    assert (
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)[
            "run_status"
        ]
        == "indexed"
    )
    import stat

    assert stat.S_ISFIFO(cache.lstat().st_mode)


@pytest.mark.parametrize(
    "case", ["file_symlink", "parent_symlink", "oversized", "invalid_utf8"]
)
def test_kex_cache_unsafe_reads_are_disposable_misses(
    tmp_path: Path, monkeypatch, case
):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "record-cache.json"
    payload = {
        "schema": knowledge.RECORD_CACHE_SCHEMA,
        "entries": {"marker": "x" * 256},
    }
    sentinel.write_text(json.dumps(payload))
    before = sentinel.read_bytes()
    path = tmp_path / "record-cache.json"
    if case == "file_symlink":
        path.symlink_to(sentinel)
    elif case == "parent_symlink":
        parent = tmp_path / "linked-parent"
        parent.symlink_to(outside, target_is_directory=True)
        path = parent / sentinel.name
    elif case == "oversized":
        monkeypatch.setattr(knowledge, "MAX_INDEX_BYTES", 128)
        path.write_bytes(before)
    else:
        path.write_bytes(b"\xff")
    assert knowledge._load_record_cache(path) == knowledge._empty_record_cache()
    assert sentinel.read_bytes() == before


def test_kex_cache_read_is_bounded_before_parsing(tmp_path: Path, monkeypatch):
    path = tmp_path / "record-cache.json"
    state = {"schema": knowledge.RECORD_CACHE_SCHEMA, "entries": {"marker": {}}}
    path.write_text(json.dumps(state))
    original = knowledge.os.fdopen
    sizes = []

    class BoundedReader:
        def __init__(self, *args, **kwargs):
            self.stream = original(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            assert 0 < size <= knowledge.MAX_INDEX_BYTES + 1
            sizes.append(size)
            return self.stream.read(size)

    monkeypatch.setattr(knowledge.os, "fdopen", BoundedReader)
    assert knowledge._load_record_cache(path) == state
    assert sizes


def test_kex_cache_predictable_temporary_symlink_does_not_touch_sentinel(
    public_repo: Path, tmp_path: Path
):
    cache = tmp_path / "record-cache.json"
    sentinel = tmp_path / "outside-sentinel.txt"
    sentinel.write_text("outside sentinel must remain untouched")
    before = sentinel.read_bytes()
    planted = cache.with_name(cache.name + ".tmp")
    planted.symlink_to(sentinel)
    expected = _build(public_repo)
    actual = knowledge.build_repository_knowledge_index(
        repo_root=public_repo, record_cache_path=cache
    )
    assert sentinel.read_bytes() == before
    assert planted.is_symlink()
    assert not cache.is_symlink()
    assert actual == expected
    assert (
        knowledge.build_repository_knowledge_index(
            repo_root=public_repo, record_cache_path=cache
        )
        == expected
    )


@pytest.mark.parametrize("case", ["file_symlink", "parent_symlink", "fifo"])
def test_kex_cache_unsafe_write_targets_are_skipped(tmp_path: Path, case):
    import stat

    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "record-cache.json"
    sentinel.write_text("outside sentinel")
    before = sentinel.read_bytes()
    cache = tmp_path / "record-cache.json"
    if case == "file_symlink":
        cache.symlink_to(sentinel)
    elif case == "parent_symlink":
        parent = tmp_path / "linked-parent"
        parent.symlink_to(outside, target_is_directory=True)
        cache = parent / sentinel.name
    else:
        os.mkfifo(cache)
    knowledge._write_record_cache(
        cache, {"schema": knowledge.RECORD_CACHE_SCHEMA, "entries": {"new": {}}}
    )
    assert sentinel.read_bytes() == before
    if case == "file_symlink":
        assert cache.is_symlink()
    if case == "fifo":
        assert stat.S_ISFIFO(cache.lstat().st_mode)
    assert sorted(p.name for p in outside.iterdir()) == [sentinel.name]


def test_kex_cache_interrupted_replace_preserves_previous_cache_and_recovers(
    tmp_path: Path, monkeypatch
):
    cache = tmp_path / "record-cache.json"
    old = {"schema": knowledge.RECORD_CACHE_SCHEMA, "entries": {"old": {}}}
    new = {"schema": knowledge.RECORD_CACHE_SCHEMA, "entries": {"new": {}}}
    knowledge._write_record_cache(cache, old)
    before = cache.read_bytes()
    calls = []

    def interrupted_replace(source, target, **kwargs):
        calls.append(kwargs)
        raise OSError("simulated interrupted cache replacement")

    with monkeypatch.context() as patch:
        patch.setattr(knowledge.os, "replace", interrupted_replace)
        knowledge._write_record_cache(cache, new)
    assert calls
    assert calls[0].get("src_dir_fd") is not None
    assert calls[0].get("dst_dir_fd") is not None
    assert cache.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [cache.name]
    knowledge._write_record_cache(cache, new)
    assert knowledge._load_record_cache(cache) == new


def test_kex_docs_pyprojects_full_persist_reload_and_search_roundtrip(
    public_repo: Path, tmp_path: Path
):
    names = ["docs/source/pyproject.toml", "docs/source/examples/nested/pyproject.toml"]
    for name in names:
        path = public_repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[project]\nname = 'documentation-compute_total-example'\n")
    proof = knowledge.persist_repository_knowledge_index(
        repo_root=public_repo,
        output_path=tmp_path / "public-repository-index.json",
        record_cache_path=tmp_path / "record-cache.json",
    )
    assert proof["ok"] and proof["round_trip_ok"]
    state = proof["reloaded_state"]
    records = {record["path"]: record for record in state["records"]}
    for name in names:
        assert records[name]["kind"] == "package_manifest"
        assert records[name]["line_count"] == 2
    assert state["summary"]["indexed_file_count"] == 7
    assert state["summary"]["pyproject_count"] == 3
    assert state["summary"]["pyproject_line_count"] == 6
    assert state["summary"]["total_line_count"] == sum(
        record["line_count"] for record in records.values()
    )
    result = _search(state, public_repo, "documentation-compute_total-example")
    assert {hit["path"] for hit in result["results"]} == set(names)


@pytest.mark.parametrize("value", [None, [], {}, True, 3, "invented"])
def test_kex_loader_rejects_wrong_or_invalid_run_status(
    public_repo: Path, tmp_path: Path, value
):
    state = _build(public_repo)
    state["run_status"] = value
    path = tmp_path / "public-repository-index.json"
    path.write_text(json.dumps(state))
    with pytest.raises(
        knowledge.RepositoryKnowledgeError, match="(?i)(status|rebuild)"
    ):
        knowledge.load_repository_knowledge_index(path, repo_root=public_repo)


@pytest.mark.parametrize(
    "field",
    [
        "schema",
        "run_status",
        "run_id",
        "created_at",
        "updated_at",
        "execution_mode",
        "summary",
        "repo_root",
        "root_identity",
        "source_policy",
        "source_fingerprint",
        "records",
        "issues",
        "provenance",
        "knowledge_maps",
        "query_seeds",
        "excluded_roots",
        "excluded_existing_roots",
    ],
)
def test_kex_loader_rejects_missing_required_fields(
    public_repo: Path, tmp_path: Path, field
):
    state = _build(public_repo)
    del state[field]
    path = tmp_path / "public-repository-index.json"
    path.write_text(json.dumps(state))
    with pytest.raises(knowledge.RepositoryKnowledgeError, match="(?i)rebuild"):
        knowledge.load_repository_knowledge_index(path, repo_root=public_repo)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", []),
        ("created_at", None),
        ("updated_at", False),
        ("execution_mode", "invented"),
        ("summary", []),
        ("summary", {}),
        ("issues", "none"),
        ("provenance", []),
        ("knowledge_maps", {}),
        ("query_seeds", {}),
        ("excluded_roots", None),
        ("excluded_existing_roots", {}),
    ],
)
def test_kex_loader_rejects_malformed_required_metadata(
    public_repo: Path, tmp_path: Path, field, value
):
    state = _build(public_repo)
    state[field] = value
    path = tmp_path / "public-repository-index.json"
    path.write_text(json.dumps(state))
    with pytest.raises(knowledge.RepositoryKnowledgeError, match="(?i)rebuild"):
        knowledge.load_repository_knowledge_index(path, repo_root=public_repo)


@pytest.mark.parametrize("case", ["missing", "wrong_type", "invalid"])
def test_kex_actual_cli_corrupt_status_json_exit2_and_rebuild_recovery(
    public_repo: Path, tmp_path: Path, case
):
    index = tmp_path / "public-repository-index.json"
    state = _build(public_repo)
    if case == "missing":
        del state["run_status"]
    else:
        state["run_status"] = [] if case == "wrong_type" else "invented"
    index.write_text(json.dumps(state))
    failed = _kex_cli(public_repo, "--index", str(index), "--query", "compute_total")
    assert failed.returncode == 2, (failed.stdout, failed.stderr)
    assert "Traceback" not in failed.stderr
    assert len(failed.stdout.encode("utf-8")) <= 1024
    payload = json.loads(failed.stdout)
    assert payload["status"] == "fail" and "results" not in payload
    assert "--build-index" in payload["error"]
    rebuilt = _kex_cli(
        public_repo,
        "--build-index",
        str(index),
        "--query",
        "def compute_total",
        "--no-cache",
    )
    assert rebuilt.returncode == 0, (rebuilt.stdout, rebuilt.stderr)
    assert json.loads(rebuilt.stdout)["match_count"] == 1


def test_kex_cli_defensively_rejects_missing_status(
    public_repo: Path, monkeypatch, capsys
):
    spec = importlib.util.spec_from_file_location(
        "kex_defensive_cli", ROOT / "tools/repository_knowledge_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_repository_knowledge_index", lambda *a, **k: {})
    assert module.main(["--repo-root", str(public_repo), "--index", "unused.json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert "--build-index" in payload["error"]


def test_kex_cache_exclusive_temporary_collision_preserves_preplanted_file(
    tmp_path: Path, monkeypatch
):
    cache = tmp_path / "record-cache.json"
    planted = tmp_path / (".record-cache.json." + "0" * 32 + ".tmp")
    planted.write_text("preplanted file must remain untouched")
    before = planted.read_bytes()
    monkeypatch.setattr(knowledge.secrets, "token_hex", lambda size: "0" * 32)
    knowledge._write_record_cache(cache, knowledge._empty_record_cache())
    assert planted.read_bytes() == before
    assert not cache.exists()


def test_kex_cli_rejects_non_utf8_required_source_path_and_recovers(
    public_repo: Path, tmp_path: Path
):
    index = tmp_path / "public-repository-index.json"
    state = _build(public_repo)
    state["records"][0]["path"] = "docs/source/\ud800.rst"
    index.write_text(json.dumps(state))
    failed = _kex_cli(public_repo, "--index", str(index), "--query", "compute_total")
    assert failed.returncode == 2, (failed.stdout, failed.stderr)
    assert "Traceback" not in failed.stderr
    payload = json.loads(failed.stdout)
    assert payload["status"] == "fail" and "results" not in payload
    assert "--build-index" in payload["error"]
    with pytest.raises(knowledge.RepositoryKnowledgeError, match="(?i)(utf|rebuild)"):
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
    rebuilt = _kex_cli(
        public_repo,
        "--build-index",
        str(index),
        "--query",
        "def compute_total",
        "--no-cache",
    )
    assert rebuilt.returncode == 0
    assert json.loads(rebuilt.stdout)["match_count"] == 1


@pytest.mark.parametrize("flag", ["--build-index", "--output"])
@pytest.mark.parametrize(
    "case", ["parent_symlink", "file_symlink", "fifo", "directory"]
)
def test_kex_remaining_index_cli_refuses_unsafe_output_and_recovers(
    public_repo: Path, tmp_path: Path, flag, case
):
    import stat

    outside = tmp_path / "outside-public-output"
    outside.mkdir()
    sentinel = outside / "index.json"
    sentinel.write_bytes(b"OUTSIDE PUBLIC SENTINEL\n")
    before = sentinel.read_bytes()
    parent = tmp_path / "output-parent"
    parent.mkdir()
    index = parent / "index.json"
    if case == "parent_symlink":
        parent.rmdir()
        parent.symlink_to(outside, target_is_directory=True)
    elif case == "file_symlink":
        index.symlink_to(sentinel)
    elif case == "fifo":
        os.mkfifo(index)
    else:
        index.mkdir()
    failed = _kex_cli(public_repo, flag, str(index), "--no-cache")
    assert failed.returncode == 2, (failed.stdout, failed.stderr)
    assert "Traceback" not in failed.stderr
    assert len(failed.stdout.encode("utf-8")) <= 1024
    assert json.loads(failed.stdout)["status"] == "fail"
    assert sentinel.read_bytes() == before
    assert sorted(p.name for p in outside.iterdir()) == ["index.json"]
    if case == "parent_symlink":
        assert parent.is_symlink()
        parent.unlink()
        parent.mkdir()
    elif case == "file_symlink":
        assert index.is_symlink()
        index.unlink()
    elif case == "fifo":
        assert stat.S_ISFIFO(index.lstat().st_mode)
        index.unlink()
    else:
        assert index.is_dir()
        index.rmdir()
    # A pre-existing regular index remains a supported replacement target.
    index.write_bytes(b"previous regular index\n")
    recovered = _kex_cli(public_repo, flag, str(index), "--no-cache")
    assert recovered.returncode == (0 if flag == "--build-index" else 1)
    assert "Traceback" not in recovered.stderr
    assert knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
    assert sentinel.read_bytes() == before


@pytest.mark.parametrize("stage", ["file_sync", "replace"])
@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_kex_remaining_index_interruption_preserves_prior_index_and_owned_cleanup(
    public_repo: Path, tmp_path: Path, monkeypatch, stage, failure
):
    index = tmp_path / "public-index.json"
    state = _build(public_repo)
    knowledge.write_repository_knowledge_index(index, state)
    before = index.read_bytes()
    planted = tmp_path / ".public-index.json.unowned.tmp"
    planted.write_bytes(b"UNOWNED TEMPORARY\n")
    before_names = sorted(p.name for p in tmp_path.iterdir())
    replacement = {**state, "run_id": "corrective-publication-recovery"}
    calls = []

    def interrupted(*args, **kwargs):
        calls.append(kwargs)
        raise failure("controlled interrupted publication")

    with monkeypatch.context() as patch:
        patch.setattr(
            knowledge.os, "fsync" if stage == "file_sync" else "replace", interrupted
        )
        with pytest.raises(failure):
            knowledge.write_repository_knowledge_index(index, replacement)
    assert calls
    if stage == "replace":
        assert calls[0]["src_dir_fd"] == calls[0]["dst_dir_fd"]
    assert index.read_bytes() == before
    assert planted.read_bytes() == b"UNOWNED TEMPORARY\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == before_names
    knowledge.write_repository_knowledge_index(index, replacement)
    assert (
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
        == replacement
    )


def test_kex_remaining_index_parent_replacement_keeps_publication_on_pinned_directory(
    public_repo: Path, tmp_path: Path, monkeypatch
):
    parent = tmp_path / "output-parent"
    parent.mkdir()
    moved = tmp_path / "pinned-original-parent"
    outside = tmp_path / "outside-public-output"
    outside.mkdir()
    sentinel = outside / "public-index.json"
    sentinel.write_bytes(b"OUTSIDE PUBLIC SENTINEL\n")
    index = parent / sentinel.name
    state = _build(public_repo)
    knowledge.write_repository_knowledge_index(index, state)
    real_replace = knowledge.os.replace
    calls = []

    def swap_parent(source, target, **kwargs):
        calls.append(kwargs)
        parent.rename(moved)
        parent.symlink_to(outside, target_is_directory=True)
        return real_replace(source, target, **kwargs)

    replacement = {**state, "run_id": "pinned-directory-publication"}
    with monkeypatch.context() as patch:
        patch.setattr(knowledge.os, "replace", swap_parent)
        knowledge.write_repository_knowledge_index(index, replacement)
    assert len(calls) == 1
    assert calls[0].get("src_dir_fd") is not None
    assert calls[0]["src_dir_fd"] == calls[0]["dst_dir_fd"]
    assert sentinel.read_bytes() == b"OUTSIDE PUBLIC SENTINEL\n"
    assert sorted(p.name for p in outside.iterdir()) == [sentinel.name]
    assert (
        knowledge.load_repository_knowledge_index(
            moved / index.name, repo_root=public_repo
        )
        == replacement
    )
    parent.unlink()
    moved.rename(parent)
    assert (
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
        == replacement
    )


@pytest.mark.parametrize("case", ["regular", "symlink"])
def test_kex_remaining_index_exclusive_temporary_collision_preserves_unowned_files(
    public_repo: Path, tmp_path: Path, monkeypatch, case
):
    index = tmp_path / "public-index.json"
    state = _build(public_repo)
    knowledge.write_repository_knowledge_index(index, state)
    before = index.read_bytes()
    sentinel = tmp_path / "public-sentinel.txt"
    sentinel.write_bytes(b"OUTSIDE PUBLIC SENTINEL\n")
    planted = tmp_path / (".public-index.json." + "0" * 32 + ".tmp")
    if case == "regular":
        planted.write_bytes(b"UNOWNED TEMPORARY\n")
    else:
        planted.symlink_to(sentinel)
    with monkeypatch.context() as patch:
        patch.setattr(knowledge.secrets, "token_hex", lambda size: "0" * 32)
        with pytest.raises(OSError):
            knowledge.write_repository_knowledge_index(index, state)
    assert index.read_bytes() == before
    assert sentinel.read_bytes() == b"OUTSIDE PUBLIC SENTINEL\n"
    assert (
        planted.is_symlink()
        if case == "symlink"
        else planted.read_bytes() == b"UNOWNED TEMPORARY\n"
    )
    knowledge.write_repository_knowledge_index(index, state)
    assert (
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo) == state
    )


@pytest.mark.parametrize("operation", ["open", "mkdir", "stat", "unlink", "rename"])
def test_kex_remaining_index_unsupported_platform_refuses_before_creating_output(
    public_repo: Path, tmp_path: Path, monkeypatch, operation
):
    state = _build(public_repo)
    parent = tmp_path / "not-created" / "nested"
    with monkeypatch.context() as patch:
        patch.setattr(
            knowledge.os,
            "supports_dir_fd",
            knowledge.os.supports_dir_fd - {getattr(knowledge.os, operation)},
        )
        with pytest.raises(
            knowledge.RepositoryKnowledgeError, match="(?i)(platform|descriptor)"
        ):
            knowledge.write_repository_knowledge_index(
                parent / "public-index.json", state
            )
    assert not parent.parent.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("heading", "\ud800"),
        ("docstring", "\udfff"),
        ("extra", {"nested": ["\ud800"]}),
        ("extra", {"\ud800": "invalid key"}),
        ("extra", float("nan")),
    ],
)
def test_kex_remaining_cli_rejects_corrupt_record_metadata_and_recovers(
    public_repo: Path, tmp_path: Path, field, value
):
    index = tmp_path / "public-index.json"
    state = _build(public_repo)
    state["records"][0][field] = value
    index.write_text(json.dumps(state), encoding="utf-8")
    failed = _kex_cli(public_repo, "--index", str(index), "--query", "compute_total")
    assert failed.returncode == 2, (failed.stdout, failed.stderr)
    assert "Traceback" not in failed.stderr
    assert len(failed.stdout.encode("utf-8")) <= 1024
    payload = json.loads(failed.stdout)
    assert payload["status"] == "fail" and "results" not in payload
    assert "--build-index" in payload["error"]
    with pytest.raises(
        knowledge.RepositoryKnowledgeError, match="(?i)(metadata|utf|rebuild)"
    ):
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
    rebuilt = _kex_cli(
        public_repo,
        "--build-index",
        str(index),
        "--query",
        "def compute_total",
        "--no-cache",
    )
    assert rebuilt.returncode == 0, (rebuilt.stdout, rebuilt.stderr)
    assert json.loads(rebuilt.stdout)["match_count"] == 1


@pytest.mark.parametrize("field", ["run_id", "extra"])
def test_kex_remaining_loader_rejects_nonrecord_non_utf8_metadata(
    public_repo: Path, tmp_path: Path, field
):
    index = tmp_path / "public-index.json"
    state = _build(public_repo)
    state[field] = "\ud800"
    index.write_text(json.dumps(state), encoding="utf-8")
    failed = _kex_cli(public_repo, "--index", str(index), "--query", "compute_total")
    assert failed.returncode == 2, (failed.stdout, failed.stderr)
    assert "Traceback" not in failed.stderr
    payload = json.loads(failed.stdout)
    assert payload["status"] == "fail" and "results" not in payload
    assert "--build-index" in payload["error"]


@pytest.mark.parametrize("flag", ["--build-index", "--output"])
@pytest.mark.parametrize("field", ["heading", "docstring", "extra"])
def test_kex_remaining_default_cache_discards_poisoned_metadata_and_rebuilds(
    public_repo: Path, tmp_path: Path, monkeypatch, flag, field
):
    cache_home = tmp_path / "public-default-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    cache = knowledge.default_record_cache_path(public_repo)
    expected = _build(public_repo)
    index = tmp_path / "public-index.json"
    initial = _kex_cli(public_repo, flag, str(index), cache_home=cache_home)
    assert initial.returncode == (0 if flag == "--build-index" else 1)
    assert cache.is_file()
    payload = json.loads(cache.read_text())
    key = sorted(payload["entries"])[0]
    payload["entries"][key]["record"][field] = (
        {"nested": "\ud800"} if field == "extra" else "\ud800"
    )
    poisoned = json.dumps(payload)
    cache.write_text(poisoned, encoding="utf-8")
    # Ordinary cached builds repair, rather than perpetuate, the bad record.
    actual = knowledge.build_repository_knowledge_index(
        repo_root=public_repo, record_cache_path=cache
    )
    assert actual == expected
    repaired_record = json.loads(cache.read_text())["entries"][key]["record"]
    assert repaired_record == next(
        record for record in expected["records"] if record["path"] == key
    )
    # Explicit CLI rebuilds using the poisoned default cache repair it too.
    cache.write_text(poisoned, encoding="utf-8")
    recovered = _kex_cli(public_repo, flag, str(index), cache_home=cache_home)
    assert recovered.returncode == (0 if flag == "--build-index" else 1), (
        recovered.stdout,
        recovered.stderr,
    )
    assert "Traceback" not in recovered.stderr
    assert (
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
        == expected
    )
    assert json.loads(cache.read_text())["entries"][key]["record"] == repaired_record
    queried = _kex_cli(
        public_repo, "--index", str(index), "--query", "def compute_total"
    )
    assert queried.returncode == 0
    assert json.loads(queried.stdout)["match_count"] == 1


@pytest.mark.parametrize(
    "case", ["fifo", "file_symlink", "parent_symlink", "missing", "oversized"]
)
def test_kex_remaining_legacy_docs_cli_is_confined_bounded_and_recovers(
    public_repo: Path, tmp_path: Path, case
):
    required = (
        "repository knowledge index report\n"
        "tools/repository_knowledge_report.py --compact\n"
        "agilab.repository_knowledge_index.v1\n"
        "repository_knowledge_static_index\nroot tests\n"
        "deterministic file, line, size, kind, and suffix statistics\n"
        "generated wiki as an exploration aid\n"
    )
    features = public_repo / "docs/source/features.rst"
    outside = tmp_path / "outside-public-docs"
    outside.mkdir()
    sentinel = outside / "features.rst"
    sentinel.write_text(required, encoding="utf-8")
    before = sentinel.read_bytes()
    moved = public_repo / "original-docs"
    if case == "fifo":
        os.mkfifo(features)
    elif case == "file_symlink":
        features.symlink_to(sentinel)
    elif case == "parent_symlink":
        features.parent.rename(moved)
        features.parent.symlink_to(outside, target_is_directory=True)
    elif case == "oversized":
        features.write_bytes(b"x" * (knowledge.MAX_SOURCE_FILE_BYTES + 1))
    # The pre-existing guide.rst is another ordinary documentation input.
    index = tmp_path / "public-index.json"
    completed = _kex_cli(public_repo, "--output", str(index), "--no-cache")
    assert completed.returncode == (2 if case == "oversized" else 1), (
        completed.stdout,
        completed.stderr,
    )
    assert "Traceback" not in completed.stderr
    assert len(completed.stdout.encode("utf-8")) < 65536
    payload = json.loads(completed.stdout)
    assert payload["status"] == "fail"
    if case == "oversized":
        assert "byte limit" in payload["error"]
    else:
        docs = next(
            row
            for row in payload["checks"]
            if row["id"] == "repository_knowledge_docs_reference"
        )
        assert docs["status"] == "fail" and docs["details"].get("error")
        assert len(docs["details"]["error"]) <= 512
    assert sentinel.read_bytes() == before
    if case == "parent_symlink":
        features.parent.unlink()
        moved.rename(features.parent)
    elif case != "missing":
        features.unlink()
    features.write_text(required, encoding="utf-8")
    recovered = _kex_cli(public_repo, "--output", str(index), "--no-cache")
    assert recovered.returncode == 1
    docs = next(
        row
        for row in json.loads(recovered.stdout)["checks"]
        if row["id"] == "repository_knowledge_docs_reference"
    )
    assert docs["status"] == "pass"
    assert sentinel.read_bytes() == before
    assert knowledge.load_repository_knowledge_index(index, repo_root=public_repo)


@pytest.mark.parametrize("case", ["file_symlink", "parent_symlink"])
def test_kex_remaining_docs_check_never_uses_path_text_reads(
    public_repo: Path, tmp_path: Path, monkeypatch, case
):
    outside = tmp_path / "outside-public-docs"
    outside.mkdir()
    (outside / "features.rst").write_bytes(b"OUTSIDE PUBLIC SENTINEL\n")
    features = public_repo / "docs/source/features.rst"
    if case == "file_symlink":
        features.symlink_to(outside / features.name)
    else:
        features.parent.rename(public_repo / "original-docs")
        features.parent.symlink_to(outside, target_is_directory=True)
    spec = importlib.util.spec_from_file_location(
        "kex_remaining_docs_cli", ROOT / "tools/repository_knowledge_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reads = []

    def path_read(*args, **kwargs):
        reads.append(str(args[0]))
        raise AssertionError("documentation bypassed the bounded descriptor reader")

    outside_identities = {
        (p.stat().st_dev, p.stat().st_ino) for p in (outside, outside / "features.rst")
    }
    outside_opens = []
    real_open = knowledge.os.open

    def observed_open(path, flags, *args, **kwargs):
        descriptor = real_open(path, flags, *args, **kwargs)
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) in outside_identities:
            outside_opens.append(str(path))
        return descriptor

    monkeypatch.setattr(Path, "read_text", path_read)
    monkeypatch.setattr(knowledge.os, "open", observed_open)
    monkeypatch.setattr(
        knowledge.os, "supports_dir_fd", knowledge.os.supports_dir_fd | {observed_open}
    )
    result = module._docs_check(public_repo)
    assert result["status"] == "fail"
    assert reads == [] and outside_opens == []


@pytest.mark.parametrize("case", ["file_symlink", "fifo"])
def test_kex_remaining_index_refuses_changed_target_before_commit_and_recovers(
    public_repo: Path, tmp_path: Path, monkeypatch, case
):
    import stat

    index = tmp_path / "public-index.json"
    state = _build(public_repo)
    knowledge.write_repository_knowledge_index(index, state)
    sentinel = tmp_path / "outside-public-sentinel.json"
    sentinel.write_bytes(b"OUTSIDE PUBLIC SENTINEL\n")
    real_sync = knowledge.os.fsync
    changed = []

    def swap_target(descriptor):
        if not changed:
            changed.append(True)
            index.unlink()
            if case == "file_symlink":
                index.symlink_to(sentinel)
            else:
                os.mkfifo(index)
        return real_sync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(knowledge.os, "fsync", swap_target)
        with pytest.raises(knowledge.RepositoryKnowledgeError, match="regular"):
            knowledge.write_repository_knowledge_index(index, state)
    assert changed and sentinel.read_bytes() == b"OUTSIDE PUBLIC SENTINEL\n"
    assert not list(tmp_path.glob(".public-index.json.*.tmp"))
    assert (
        index.is_symlink()
        if case == "file_symlink"
        else stat.S_ISFIFO(index.lstat().st_mode)
    )
    index.unlink()
    knowledge.write_repository_knowledge_index(index, state)
    assert (
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo) == state
    )


@pytest.mark.parametrize("flag", ["--build-index", "--output"])
def test_final_three_parent_traversal_output_refuses_without_mkdir(
    public_repo: Path, tmp_path: Path, flag
):
    parent = tmp_path / "physical-output-parent"
    parent.mkdir()
    outside = tmp_path / "outside-public-output"
    outside.mkdir()
    sentinel = outside / "index.json"
    sentinel.write_bytes(b"UNCHANGED PUBLIC SENTINEL\n")
    (parent / "alias").symlink_to(outside, target_is_directory=True)
    unsafe = parent / "new" / ".." / "alias" / "index.json"
    failed = _kex_cli(public_repo, flag, str(unsafe), "--no-cache")
    # Check the actual owned filesystem, even though the CLI already refused.
    assert not (parent / "new").exists()
    assert sentinel.read_bytes() == b"UNCHANGED PUBLIC SENTINEL\n"
    assert sorted(path.name for path in outside.iterdir()) == ["index.json"]
    assert sorted(path.name for path in parent.iterdir()) == ["alias"]
    assert failed.returncode == 2, (failed.stdout, failed.stderr)
    assert "Traceback" not in failed.stderr
    payload = json.loads(failed.stdout)
    assert payload["status"] == "fail" and "results" not in payload
    assert "parent traversal" in payload["error"].lower()
    assert len(failed.stdout.encode("utf-8")) <= 1024
    safe = parent / "safe" / "nested" / "index.json"
    recovered = _kex_cli(public_repo, flag, str(safe), "--no-cache")
    assert recovered.returncode == (0 if flag == "--build-index" else 1)
    assert knowledge.load_repository_knowledge_index(safe, repo_root=public_repo)
    assert sentinel.read_bytes() == b"UNCHANGED PUBLIC SENTINEL\n"


def test_final_three_parent_traversal_cache_skips_without_mkdir(
    public_repo: Path, tmp_path: Path
):
    parent = tmp_path / "physical-cache-parent"
    parent.mkdir()
    outside = tmp_path / "outside-public-cache"
    outside.mkdir()
    sentinel = outside / "cache.json"
    sentinel.write_bytes(b"UNCHANGED PUBLIC CACHE SENTINEL\n")
    (parent / "alias").symlink_to(outside, target_is_directory=True)
    unsafe = parent / "new" / ".." / "alias" / "cache.json"
    expected = _build(public_repo)
    actual = knowledge.build_repository_knowledge_index(
        repo_root=public_repo, record_cache_path=unsafe
    )
    assert not (parent / "new").exists()
    assert actual == expected
    assert sentinel.read_bytes() == b"UNCHANGED PUBLIC CACHE SENTINEL\n"
    assert sorted(path.name for path in outside.iterdir()) == ["cache.json"]
    assert sorted(path.name for path in parent.iterdir()) == ["alias"]
    safe = parent / "safe" / "nested" / "cache.json"
    assert (
        knowledge.build_repository_knowledge_index(
            repo_root=public_repo, record_cache_path=safe
        )
        == expected
    )
    assert json.loads(safe.read_text())["entries"]
    assert sentinel.read_bytes() == b"UNCHANGED PUBLIC CACHE SENTINEL\n"


@pytest.mark.parametrize("cache_mode", ["default", "explicit"])
@pytest.mark.parametrize("field", ["function_count", "class_count", "import_count"])
@pytest.mark.parametrize(
    "poison", [True, "1", -1, None], ids=["bool", "string", "negative", "missing"]
)
def test_final_three_outline_cache_repairs_builder_cli_and_reload(
    public_repo: Path, tmp_path: Path, monkeypatch, cache_mode, field, poison
):
    cache_home = tmp_path / "public-cache-home"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    cache = (
        knowledge.default_record_cache_path(public_repo)
        if cache_mode == "default"
        else tmp_path / "explicit-public-cache.json"
    )
    expected = _build(public_repo)
    assert (
        knowledge.build_repository_knowledge_index(
            repo_root=public_repo, record_cache_path=cache
        )
        == expected
    )
    valid = json.loads(cache.read_text())
    key = "src/agilab/calcul_été.py"
    poisoned = copy.deepcopy(valid)
    record = poisoned["entries"][key]["record"]
    if poison is None:
        del record[field]
    else:
        record[field] = poison
    damaged = json.dumps(poisoned)
    cache.write_text(damaged)
    rebuilt_paths = []
    file_record = knowledge._file_record

    def regenerate(root, path, *args, **kwargs):
        rebuilt_paths.append(path.relative_to(root).as_posix())
        return file_record(root, path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "_file_record", regenerate)
        builds = [
            knowledge.build_repository_knowledge_index(
                repo_root=public_repo, record_cache_path=cache
            )
            for _ in range(2)
        ]
    assert builds == [expected, expected]
    assert rebuilt_paths == [key]
    assert json.loads(cache.read_text()) == valid
    index = tmp_path / "public-outline-index.json"
    options = ["--cache-path", str(cache)] if cache_mode == "explicit" else []
    cache.write_text(damaged)
    for _ in range(2):
        rebuilt = _kex_cli(
            public_repo, "--build-index", str(index), *options, cache_home=cache_home
        )
        assert rebuilt.returncode == 0, (rebuilt.stdout, rebuilt.stderr)
        assert "Traceback" not in rebuilt.stderr
        assert (
            knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
            == expected
        )
        assert json.loads(cache.read_text()) == valid
    reloaded = _kex_cli(public_repo, "--index", str(index), cache_home=cache_home)
    assert reloaded.returncode == 0, (reloaded.stdout, reloaded.stderr)
    assert (
        json.loads(reloaded.stdout)["source_fingerprint"]
        == expected["source_fingerprint"]
    )


@pytest.mark.parametrize(
    "field,poison",
    [
        (field, poison)
        for field in ("function_count", "class_count", "import_count")
        for poison in (True, "1", -1, None)
    ]
    + [
        ("parse_status", None),
        ("parse_status", True),
        ("parse_status", "unavailable"),
        ("docstring", None),
        ("docstring", 1),
        ("heading", None),
        ("heading", 1),
    ],
)
def test_final_three_record_shape_is_shared_by_cache_and_loader(
    public_repo: Path, tmp_path: Path, field, poison
):
    state = _build(public_repo)
    record = next(
        row
        for row in state["records"]
        if row["path"]
        == ("README.md" if field == "heading" else "src/agilab/calcul_été.py")
    )
    signature = knowledge._record_signature(
        public_repo, public_repo / record["path"], record["kind"]
    )
    if poison is None:
        del record[field]
    else:
        record[field] = poison
    cache_state = {
        "entries": {record["path"]: {"signature": signature, "record": record}}
    }
    assert knowledge._cached_record(cache_state, signature) is None
    # Bind the malformed metadata into a matching fingerprint: shape must still fail.
    state["source_fingerprint"] = knowledge._source_fingerprint(
        state["records"], state["repo_root"], state["root_identity"]
    )
    index = tmp_path / "malformed-public-outline-index.json"
    index.write_text(json.dumps(state))
    with pytest.raises(knowledge.RepositoryKnowledgeError, match="(?i)record metadata"):
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)


@pytest.mark.parametrize(
    "text,status",
    [("def broken(:\n", "syntax_error"), ("def valid(): pass\n", "parsed")],
)
def test_final_three_actual_python_parse_status_and_valid_cache_hits(
    public_repo: Path, tmp_path: Path, monkeypatch, text, status
):
    source = public_repo / "src/agilab/calcul_été.py"
    source.write_text(text)
    expected = _build(public_repo)
    record = next(
        row
        for row in expected["records"]
        if row["path"] == source.relative_to(public_repo).as_posix()
    )
    assert record["parse_status"] == status
    assert all(
        type(record[field]) is int and record[field] >= 0
        for field in ("function_count", "class_count", "import_count")
    )
    cache = tmp_path / "parse-status-cache.json"
    assert (
        knowledge.build_repository_knowledge_index(
            repo_root=public_repo, record_cache_path=cache
        )
        == expected
    )
    monkeypatch.setattr(
        knowledge, "_file_record", lambda *_a, **_kw: pytest.fail("valid cache miss")
    )
    assert (
        knowledge.build_repository_knowledge_index(
            repo_root=public_repo, record_cache_path=cache
        )
        == expected
    )
    index = tmp_path / "parse-status-index.json"
    knowledge.write_repository_knowledge_index(index, expected)
    assert (
        knowledge.load_repository_knowledge_index(index, repo_root=public_repo)
        == expected
    )


def test_final_three_surrogate_query_rejected_before_source_access(
    public_repo: Path, monkeypatch
):
    state = _build(public_repo)
    expected = _search(state, public_repo)
    with monkeypatch.context() as patch:
        patch.setattr(
            knowledge,
            "_validated_sources",
            lambda *_a, **_kw: pytest.fail("invalid query accessed source"),
        )
        with pytest.raises(knowledge.RepositoryKnowledgeError, match="UTF-8"):
            _search(state, public_repo, os.fsdecode(bytes([255])))
    assert _search(state, public_repo) == expected


def test_final_three_actual_cli_surrogate_query_is_bounded_and_recovers(
    public_repo: Path, tmp_path: Path
):
    index = tmp_path / "public-query-index.json"
    state = _build(public_repo)
    knowledge.write_repository_knowledge_index(index, state)
    paths = [index, *(public_repo / row["path"] for row in state["records"])]
    before = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }
    good = _kex_cli(public_repo, "--index", str(index), "--query", "compute_total")
    failed = _kex_cli(
        public_repo, "--index", str(index), "--query", os.fsdecode(bytes([255]))
    )
    recovered = _kex_cli(public_repo, "--index", str(index), "--query", "compute_total")
    assert good.returncode == recovered.returncode == 0
    assert recovered.stdout == good.stdout
    assert failed.returncode == 2, (failed.stdout, failed.stderr)
    assert "Traceback" not in failed.stderr
    assert len(failed.stdout.encode("utf-8")) <= 1024
    payload = json.loads(failed.stdout)
    assert payload["status"] == "fail" and "UTF-8" in payload["error"]
    assert set(payload) == {"status", "error"}
    assert (
        "compute_total" not in failed.stdout and str(public_repo) not in failed.stdout
    )
    assert "\\udcff" not in failed.stdout
    assert before == {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }
