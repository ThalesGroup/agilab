from __future__ import annotations

from pathlib import Path
import runpy
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    REPO_ROOT
    / ".claude"
    / "skills"
    / "svg-diagrams"
    / "scripts"
    / "check_svg_markers.py"
)


def _load_module():
    return SimpleNamespace(
        **runpy.run_path(str(MODULE_PATH), run_name="svg_marker_skill_test")
    )


def _write_svg(path: Path, marker: str, connector: str = "") -> Path:
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg"><defs>{marker}</defs>{connector}</svg>',
        encoding="utf-8",
    )
    return path


def test_missing_marker_units_is_rejected(tmp_path) -> None:
    module = _load_module()
    svg = _write_svg(tmp_path / "implicit.svg", '<marker id="arrow"/>')

    errors, marker_count = module.check_svg(svg)

    assert marker_count == 1
    assert any("markerUnits is implicit" in error for error in errors)


def test_explicit_marker_unit_modes_are_accepted(tmp_path) -> None:
    module = _load_module()
    for marker_units in ("userSpaceOnUse", "strokeWidth"):
        svg = _write_svg(
            tmp_path / f"{marker_units}.svg",
            f'<marker id="arrow" markerUnits="{marker_units}"/>',
            '<path marker-end="url(#arrow)"/>',
        )

        assert module.check_svg(svg) == ([], 1)


def test_unresolved_marker_reference_is_rejected_in_attributes_and_css(
    tmp_path,
) -> None:
    module = _load_module()
    svg = _write_svg(
        tmp_path / "unresolved.svg",
        '<marker id="arrow" markerUnits="userSpaceOnUse"/>',
        "<style>.a { marker-end: url(#missing); }</style>"
        '<path marker-start="url(#arrow)" marker-end="url(#also-missing)"/>',
    )

    errors, _ = module.check_svg(svg)

    assert errors == [
        "marker reference #also-missing: no matching <marker id=...> definition",
        "marker reference #missing: no matching <marker id=...> definition",
    ]


def test_cli_returns_nonzero_for_malformed_svg(tmp_path, capsys) -> None:
    module = _load_module()
    svg = tmp_path / "broken.svg"
    svg.write_text("<svg>", encoding="utf-8")

    assert module.main([str(svg)]) == 1
    assert "cannot parse SVG" in capsys.readouterr().err
