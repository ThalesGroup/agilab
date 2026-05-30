from __future__ import annotations

from pathlib import Path

from agi_cluster.agi_distributor import deployment_install_spec_support


def test_resolve_install_spec_prefers_local_python_project(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    assert deployment_install_spec_support._resolve_install_spec(project, "demo") == str(project)

    monkeypatch.setattr(
        deployment_install_spec_support,
        "_resolve_distribution_install_spec",
        lambda package_name: f"{package_name}==1.2.3",
    )
    assert deployment_install_spec_support._resolve_install_spec(None, "demo") == "demo==1.2.3"


def test_local_project_install_spec_returns_false_when_path_expansion_fails(monkeypatch):
    original_expanduser = Path.expanduser

    def _raise_expanduser(path):
        if str(path) == "broken":
            raise ValueError("cannot expand")
        return original_expanduser(path)

    monkeypatch.setattr(Path, "expanduser", _raise_expanduser)

    assert deployment_install_spec_support._is_local_project_install_spec("broken") is False
