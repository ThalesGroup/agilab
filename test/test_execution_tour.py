from __future__ import annotations

import importlib.util
import json
from html.parser import HTMLParser
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "execution_tour_test_module", ROOT / "tools/build_execution_tour.py"
)
tour = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tour
SPEC.loader.exec_module(tour)


@pytest.fixture
def source_copy(tmp_path):
    root = tmp_path / "checkout"
    for entry in tour.build_tour()["snapshot"]["files"]:
        target = root / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / entry["path"]).read_bytes())
    return root


def test_real_tour_links_resolve_and_reuse_package_responsibilities():
    document = tour.build_tour()
    assert document["schema"] == "agilab.execution-tour.v1"
    assert [step["id"] for step in document["steps"]] == [
        "project",
        "prepare",
        "execute",
        "record",
        "verify",
    ]
    refs = {ref["id"]: ref for ref in document["references"]}
    assert all(step["sources"] and step["tests"] for step in document["steps"])
    assert all(
        ref_id in refs
        for step in document["steps"]
        for role in ("sources", "tests")
        for ref_id in step[role]
    )
    worker = next(
        ref
        for ref in refs.values()
        if ref["symbol"] == "FlightTelemetryWorker.work_pool"
    )
    assert worker["package_context"][0]["group"] == "Worker runtime"
    assert worker["basis"] == "parsed-source"
    assert all(step["basis"] == "curated-interpretation" for step in document["steps"])
    for ref in refs.values():
        lines = (ROOT / ref["path"]).read_text().splitlines()
        assert ref["excerpt"] == "\n".join(
            lines[ref["start_line"] - 1 : ref["end_line"]]
        )


def test_build_is_portable_and_ignores_unrelated_changes(source_copy, tmp_path):
    expected = tour.expected_artifacts()
    assert tour.expected_artifacts(source_copy) == expected
    (source_copy / "unrelated.txt").write_text("A separate change")
    assert tour.expected_artifacts(source_copy) == expected
    output = tmp_path / "tour"
    tour.write_or_check(output, root=source_copy)
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in output.iterdir()
    }
    tour.write_or_check(output, root=source_copy, check=True)
    assert {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in output.iterdir()
    } == before
    assert str(source_copy).encode() not in expected["tour.json"]


@pytest.mark.parametrize(
    "path", [tour.PROOF, tour.PROOF_TEST, tour.PRODUCER, tour.TEMPLATE]
)
def test_check_detects_changed_inputs_without_rewriting_outputs(
    source_copy, tmp_path, path
):
    output = tmp_path / "tour"
    tour.write_or_check(output, root=source_copy)
    before = (output / "tour.json").read_bytes()
    source = source_copy / path
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(tour.TourError, match="stale tour artifacts"):
        tour.write_or_check(output, root=source_copy, check=True)
    assert (output / "tour.json").read_bytes() == before


@pytest.mark.parametrize("name", ["tour.json", "index.html"])
@pytest.mark.parametrize("missing", [False, True])
def test_check_rejects_modified_or_missing_outputs(
    source_copy, tmp_path, name, missing
):
    output = tmp_path / "tour"
    tour.write_or_check(output, root=source_copy)
    path = output / name
    if missing:
        path.unlink()
    else:
        path.write_text("tampered")
    with pytest.raises(tour.TourError, match="Missing or stale"):
        tour.write_or_check(output, root=source_copy, check=True)


def test_missing_symbol_stops_generation(source_copy, tmp_path):
    source = source_copy / tour.PROOF
    source.write_text(
        source.read_text().replace("def run_proof(", "def renamed_run_proof(")
    )
    output = tmp_path / "tour"
    with pytest.raises(tour.TourError, match="run_proof; found 0"):
        tour.write_or_check(output, root=source_copy)
    assert not output.exists()


def test_qualified_decorated_async_and_duplicate_definitions():
    source = b"class Worker:\n    @decorator\n    async def run(self):\n        pass\n"
    start, end, excerpt = tour.locate_symbol(source, "worker.py", "Worker.run")
    assert (start, end) == (2, 4)
    assert excerpt.startswith("    @decorator")
    with pytest.raises(tour.TourError, match="found 2"):
        tour.locate_symbol(b"def run(): pass\ndef run(): pass\n", "worker.py", "run")
    with pytest.raises(tour.TourError, match="Cannot parse"):
        tour.locate_symbol(b"def (", "worker.py", "run")


def test_source_path_containment_and_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("private data")
    for path in (str(outside), "../outside.py"):
        with pytest.raises(tour.TourError, match="repository-relative"):
            tour.read_source(root, path)
    link = root / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this platform")
    with pytest.raises(tour.TourError, match="Symlink"):
        tour.read_source(root, "linked.py")


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.hrefs = []
        self.resources = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if "href" in attrs:
            self.hrefs.append(attrs["href"])
        if tag in ("script", "img", "iframe", "link"):
            self.resources.append(tag)


def test_offline_navigation_and_escaped_source_content():
    artifacts = tour.expected_artifacts()
    page = PageLinks()
    page.feed(artifacts["index.html"].decode())
    assert len(page.ids) == len(set(page.ids))
    assert all(
        href[1:] in page.ids if href.startswith("#") else href == "tour.json"
        for href in page.hrefs
    )
    assert not page.resources
    document = json.loads(artifacts["tour.json"])
    document["references"][0]["excerpt"] = '<script>alert("bad")</script> {{title}}'
    rendered = tour.render_html(document, (ROOT / tour.TEMPLATE).read_text())
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "{{title}}" in rendered


def test_cli_failure_and_success(tmp_path, capsys):
    output = tmp_path / "tour"
    assert tour.main(["--output-dir", str(output), "--check"]) == 1
    assert "regenerate" in capsys.readouterr().err
    assert tour.main(["--output-dir", str(output)]) == 0
    assert tour.main(["--output-dir", str(output), "--check"]) == 0


def test_changing_source_during_generation_is_rejected(monkeypatch, tmp_path):
    real_read = tour.read_source
    count = 0

    def changing_read(root, path):
        nonlocal count
        data = real_read(root, path)
        if path == tour.PROOF:
            count += 1
            if count > 1:
                return data + b"\n"
        return data

    monkeypatch.setattr(tour, "read_source", changing_read)
    output = tmp_path / "tour"
    with pytest.raises(tour.TourError, match="changed during generation"):
        tour.write_or_check(output)
    assert not output.exists()


def test_output_symlink_is_rejected_before_any_file_is_overwritten(tmp_path):
    output = tmp_path / "tour"
    output.mkdir()
    old_json = output / "tour.json"
    old_json.write_text("existing tour")
    outside = tmp_path / "outside.html"
    outside.write_text("existing document")
    try:
        (output / "index.html").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this platform")
    with pytest.raises(tour.TourError, match="output symlink"):
        tour.write_or_check(output)
    assert outside.read_text() == "existing document"
    assert old_json.read_text() == "existing tour"
