from __future__ import annotations

from pathlib import Path
import json
import re
import threading
import tomllib
from urllib.request import urlopen

from packaging.requirements import Requirement

from agi_web import python_ui as ui
from agi_web.react_python_host import ReactPythonServer


ROOT = Path(__file__).resolve().parents[1]


def _first_party_sources(root: Path, pattern: str) -> list[Path]:
    return [
        path for path in sorted(root.rglob(pattern))
        if not any(part == "build" or part.startswith(".venv") for part in path.relative_to(root).parts)
    ]


def test_first_party_profiles_do_not_require_streamlit() -> None:
    manifests = [ROOT / "pyproject.toml", *_first_party_sources(ROOT / "src" / "agilab", "pyproject.toml")]
    offenders = []
    for manifest in manifests:
        payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
        project = payload.get("project", {})
        dependencies = list(project.get("dependencies", []))
        for extra in project.get("optional-dependencies", {}).values():
            dependencies.extend(extra)
        for group in payload.get("dependency-groups", {}).values():
            dependencies.extend(value for value in group if isinstance(value, str))
        for dependency in dependencies:
            name = Requirement(dependency).name.lower().replace("_", "-")
            if name == "streamlit" or name.startswith("streamlit-"):
                offenders.append(f"{manifest.relative_to(ROOT)}: {dependency}")
    assert offenders == []


def test_native_host_serves_its_bundled_react_assets_and_view() -> None:
    server = ReactPythonServer(("127.0.0.1", 0), lambda: ui.title("AGILAB native runtime"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base, timeout=5) as response:
            document = response.read().decode()
        asset_paths = re.findall(r'(?:src|href)="([^"]+)"', document)
        assert asset_paths == ["/assets/agilab_react_python_host.css", "/assets/agilab_react_python_host.js"]
        for asset in asset_paths:
            with urlopen(base + asset, timeout=5) as response:
                content_type = response.headers.get_content_type()
                body = response.read()
            assert body
            assert content_type == ("text/css" if asset.endswith(".css") else "text/javascript")
        with urlopen(base + "/api/view", timeout=5) as response:
            view = json.load(response)
        assert not view["error"]
        assert view["config"]["server_address"] == "127.0.0.1"
        assert view["nodes"]["main"][0]["kind"] == "title"
        assert view["nodes"]["main"][0]["props"]["body"] == "AGILAB native runtime"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_native_launcher_configs_do_not_inject_streamlit_environment() -> None:
    for role in ("dev", "enduser"):
        config = ROOT / ".idea" / "runConfigurations" / f"agilab_run__{role}_.xml"
        source = config.read_text(encoding="utf-8")
        assert "STREAMLIT_" not in source
        assert 'value="streamlit"' not in source


def test_source_inventory_excludes_local_virtual_environments(tmp_path: Path) -> None:
    source = tmp_path / "page.py"
    source.write_text("from agi_web import python_ui\n", encoding="utf-8")
    installed = tmp_path / ".venv.agilab-linking" / "lib" / "site-packages" / "installed.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("irrelevant = True\n", encoding="utf-8")
    assert _first_party_sources(tmp_path, "*.py") == [source]
