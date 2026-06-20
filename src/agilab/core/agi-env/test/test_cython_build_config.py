"""Component-local coverage for AGILAB Cython build configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agi_env import cython_build_config as config


def _write_pyproject(project_dir: Path, body: str) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(body, encoding="utf-8")
    return pyproject


def test_parse_cython_directive_overrides_handles_bundles_and_booleans() -> None:
    parsed = config.parse_cython_directive_overrides(
        " unchecked, cdivision=true, profile, wraparound=no, =ignored, nonecheck=off "
    )

    assert parsed == {
        "boundscheck": False,
        "wraparound": False,
        "initializedcheck": False,
        "nonecheck": False,
        "cdivision": True,
        "profile": True,
    }


def test_parse_cython_directive_overrides_rejects_bad_names_and_values() -> None:
    with pytest.raises(ValueError, match=r"boundschek.*demo/pyproject.toml"):
        config.parse_cython_directive_overrides(
            "boundschek=false", source="demo/pyproject.toml"
        )

    with pytest.raises(ValueError, match=r"Unsupported Cython directive boolean value"):
        config.parse_cython_directive_overrides("boundscheck=maybe", source="env")


def test_validate_cython_directives_accepts_opt_out_values() -> None:
    for raw in config.CYTHON_FLAG_FALSE_VALUES:
        config.validate_cython_directives_spec(raw, source="test")

    config.validate_cython_directives_spec("boundscheck=false", source="test")
    with pytest.raises(ValueError, match="Unknown Cython compiler directive"):
        config.validate_cython_directives_spec("nochecks", source="test")


def test_read_project_cython_config_edges(tmp_path: Path) -> None:
    assert config.read_project_cython_config(None) == config.ProjectCythonConfig(
        None, None, None
    )
    assert config.read_project_cython_config(tmp_path / "missing") == config.ProjectCythonConfig(
        None, None, None
    )

    pyproject = _write_pyproject(tmp_path / "empty", "[project]\nname = 'demo'\n")
    assert config.read_project_cython_config(tmp_path / "empty") == config.ProjectCythonConfig(
        None, None, pyproject
    )

    pyproject = _write_pyproject(tmp_path / "not-table", "[tool.agilab]\ncython = 'bad'\n")
    assert config.read_project_cython_config(
        tmp_path / "not-table"
    ) == config.ProjectCythonConfig(None, None, pyproject)

    pyproject = _write_pyproject(
        tmp_path / "configured",
        "[tool.agilab.cython]\nenabled = false\ndirectives = 'unchecked'\n",
    )
    assert config.read_project_cython_config(
        tmp_path / "configured"
    ) == config.ProjectCythonConfig(False, "unchecked", pyproject)


def test_read_project_cython_config_rejects_malformed_declarations(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path / "invalid", "not toml [\n")
    with pytest.raises(ValueError, match="Invalid TOML") as excinfo:
        config.read_project_cython_config(tmp_path / "invalid")
    assert str(pyproject) in str(excinfo.value)

    _write_pyproject(tmp_path / "bad-enabled", "[tool.agilab.cython]\nenabled = 'yes'\n")
    with pytest.raises(ValueError, match="enabled must be a boolean"):
        config.read_project_cython_config(tmp_path / "bad-enabled")

    _write_pyproject(tmp_path / "bad-directives", "[tool.agilab.cython]\ndirectives = true\n")
    with pytest.raises(ValueError, match="directives must be a string"):
        config.read_project_cython_config(tmp_path / "bad-directives")

    pyproject = _write_pyproject(tmp_path / "unknown", "[tool.agilab.cython]\nenable = true\n")
    with pytest.raises(ValueError, match="Unknown .* keys") as excinfo:
        config.read_project_cython_config(tmp_path / "unknown")
    assert "enable" in str(excinfo.value)
    assert str(pyproject) in str(excinfo.value)


def test_resolve_cython_directives_spec_precedence(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "app"
    _write_pyproject(project, "[tool.agilab.cython]\ndirectives = 'unchecked'\n")

    assert config.resolve_cython_directives_spec(
        environ={config.CYTHON_DIRECTIVES_ENV: "cdivision=true"},
        project_dir=project,
    ) == ("cdivision=true", config.CYTHON_DIRECTIVES_ENV)
    assert config.resolve_cython_directives_spec(
        env_value="boundscheck=true",
        project_dir=project,
    ) == ("boundscheck=true", config.CYTHON_DIRECTIVES_ENV)
    assert config.resolve_cython_directives_spec(environ={}, project_dir=project) == (
        "unchecked",
        str(project / "pyproject.toml"),
    )
    assert config.resolve_cython_directives_spec(
        environ={config.CYTHON_DIRECTIVES_ENV: "   "},
        project_dir=tmp_path / "missing",
    ) == (None, None)

    monkeypatch.setenv(config.CYTHON_DIRECTIVES_ENV, "profile=true")
    assert config.resolve_cython_directives_spec(project_dir=project) == (
        "profile=true",
        config.CYTHON_DIRECTIVES_ENV,
    )


def test_stamp_helpers_preserve_encoding_window_and_match_expected_source() -> None:
    source = "# coding: utf-8\n# header\nprint('x')\n"
    stamp = config.cython_pyx_stamp_line(source, type_preprocess=True)

    assert stamp.startswith(config.CYTHON_PYX_STAMP_PREFIX)
    assert f"src-sha256={config.cython_source_sha256(source)}" in stamp
    assert "type-preprocess=1" in stamp

    stamped = config.add_cython_pyx_stamp(source, stamp_line=stamp)
    assert stamped.splitlines()[0:3] == ["# coding: utf-8", "# header", stamp]
    assert config.cython_pyx_stamp_matches(stamped, source, type_preprocess=True)
    assert not config.cython_pyx_stamp_matches(stamped, source, type_preprocess=False)
    assert not config.cython_pyx_stamp_matches(
        "\n".join(["# filler"] * 8 + [stamp]),
        source,
        type_preprocess=True,
    )

    assert config.add_cython_pyx_stamp("", stamp_line=f"{stamp}\n") == f"{stamp}\n"


def test_overlay_specs_and_public_exports_are_consistent() -> None:
    assert config.cython_build_overlay_specs() == ("setuptools", config.CYTHON_BUILD_REQUIREMENT)

    exported = set(config.__all__)
    for name in (
        "CYTHON_DIRECTIVES_ENV",
        "ProjectCythonConfig",
        "parse_cython_directive_overrides",
        "resolve_cython_directives_spec",
        "cython_pyx_stamp_matches",
    ):
        assert name in exported
        assert hasattr(config, name)

    assert os.environ.get(config.CYTHON_DIRECTIVES_ENV) is None
