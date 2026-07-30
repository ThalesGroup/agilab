from __future__ import annotations

import json
from pathlib import Path

from agi_env.runtime.import_layout_support import (
    distribution_installation_matches,
    inspect_pth_import_layout,
    top_level_modules_from_distribution,
    top_level_modules_from_project,
)


def _write_finder(
    site_packages: Path,
    module: str,
    source: str,
) -> None:
    (site_packages / f"{module}.py").write_text(source, encoding="utf-8")
    (site_packages / "editable.pth").write_text(
        f"import {module}; {module}.install()\n",
        encoding="utf-8",
    )


def test_inspect_pth_import_layout_reads_paths_and_pep660_mapping_without_execution(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    relative_root = site_packages / "relative-src"
    relative_root.mkdir()
    mapped_package = tmp_path / "staged" / "distribution-directory"
    mapped_package.mkdir(parents=True)
    (mapped_package / "__init__.py").write_text("", encoding="utf-8")
    namespace_root = tmp_path / "namespace"
    namespace_root.mkdir()
    finder = "__editable___demo_1_0_finder"
    _write_finder(
        site_packages,
        finder,
        "\n".join(
            (
                f"MAPPING = {{'exported_module': {str(mapped_package)!r}}}",
                f"NAMESPACES = {{'demo_namespace': [{str(namespace_root)!r}]}}",
                "def never_called():",
                "    raise AssertionError('finder code must never execute')",
            )
        ),
    )
    with (site_packages / "plain.pth").open("w", encoding="utf-8") as handle:
        handle.write("# comment\nrelative-src\nimport site\n")

    layout = inspect_pth_import_layout(site_packages)

    assert layout.roots == (relative_root.resolve(strict=False),)
    assert layout.module_locations == (
        ("exported_module", mapped_package.resolve(strict=False)),
        ("demo_namespace", namespace_root.resolve(strict=False)),
    )
    assert layout.exposes_module("exported_module") is True
    assert layout.exposes_module("exported_module.child") is True
    assert layout.exposes_module("distribution_directory") is False


def test_inspect_pth_import_layout_rejects_dynamic_or_noncanonical_finders(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    mapped_package = tmp_path / "mapped"
    mapped_package.mkdir()
    finder = "__editable___dynamic_finder"
    _write_finder(
        site_packages,
        finder,
        "MAPPING = dict(exported_module='dynamic')\nNAMESPACES = {}\n",
    )
    (site_packages / "noncanonical.pth").write_text(
        f"import {finder}; {finder}.install(); raise RuntimeError()\n",
        encoding="utf-8",
    )

    layout = inspect_pth_import_layout(site_packages)

    assert layout.module_locations == ()

    _write_finder(
        site_packages,
        finder,
        f"MAPPING = {{'exported_module': {str(mapped_package)!r}}}\n"
        "NAMESPACES = {}\nraise RuntimeError('unsafe import-time code')\n",
    )
    assert inspect_pth_import_layout(site_packages).module_locations == ()


def test_inspect_pth_import_layout_accepts_abi_tagged_editable_extension(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    extension_base = tmp_path / "native_module"
    extension_base.with_name("native_module.cp314-win_amd64.pyd").write_bytes(b"")
    finder = "__editable___native_1_0_finder"
    _write_finder(
        site_packages,
        finder,
        f"MAPPING = {{'native_module': {str(extension_base)!r}}}\nNAMESPACES = {{}}\n",
    )

    layout = inspect_pth_import_layout(site_packages)

    assert layout.exposes_module("native_module") is True


def test_inspect_pth_import_layout_rejects_empty_mapped_package(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    empty_package = tmp_path / "empty-package"
    empty_package.mkdir()
    finder = "__editable___empty_1_0_finder"
    _write_finder(
        site_packages,
        finder,
        f"MAPPING = {{'empty_package': {str(empty_package)!r}}}\nNAMESPACES = {{}}\n",
    )

    assert not inspect_pth_import_layout(site_packages).exposes_module("empty_package")


def test_top_level_modules_from_distribution_prefers_metadata_and_falls_back_to_record(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    metadata = site_packages / "link_sim_project-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: link-sim-project\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(
        "link_sim_worker\n__placeholder__\n",
        encoding="utf-8",
    )

    assert top_level_modules_from_distribution(
        (site_packages,),
        "link_sim_project",
    ) == ("link_sim_worker",)

    (metadata / "top_level.txt").unlink()
    (metadata / "RECORD").write_text(
        "link_sim_worker/__init__.py,,\nlink_sim_project-1.0.dist-info/METADATA,,\n",
        encoding="utf-8",
    )
    assert top_level_modules_from_distribution(
        (site_packages,),
        "link-sim-project",
    ) == ("link_sim_worker",)


def test_top_level_modules_from_project_reads_explicit_setuptools_exports(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "link_sim_project"

[tool.setuptools]
packages = ["link_sim_worker", "link_sim_worker.runtime"]
py-modules = ["link_sim_cli"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert top_level_modules_from_project(tmp_path) == (
        "link_sim_worker",
        "link_sim_cli",
    )


def test_distribution_installation_requires_metadata_and_local_source_provenance(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    shadow_module = site_packages / "link_sim_worker"
    shadow_module.mkdir(parents=True)
    source_project = tmp_path / "link_sim_project"
    source_project.mkdir()

    assert not distribution_installation_matches(
        (site_packages,),
        "link_sim_project",
        expected_projects=(source_project,),
    )

    metadata = site_packages / "link_sim_project-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: link-sim-project\n",
        encoding="utf-8",
    )
    (metadata / "direct_url.json").write_text(
        '{"url":"file:///different/source","dir_info":{"editable":true}}',
        encoding="utf-8",
    )
    assert distribution_installation_matches(
        (site_packages,),
        "link-sim-project",
    )
    assert not distribution_installation_matches(
        (site_packages,),
        "link-sim-project",
        expected_projects=(source_project,),
    )

    (metadata / "direct_url.json").write_text(
        json.dumps(
            {
                "url": source_project.resolve().as_uri(),
                "dir_info": {"editable": True},
            }
        ),
        encoding="utf-8",
    )
    assert distribution_installation_matches(
        (site_packages,),
        "link_sim_project",
        expected_projects=(source_project,),
    )
