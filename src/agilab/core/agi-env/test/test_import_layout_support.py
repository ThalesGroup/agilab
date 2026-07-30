from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from agi_env.runtime.import_layout_support import (
    distribution_installation_matches,
    hosted_editable_source_import_roots,
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


def _write_editable_owner(
    site_packages: Path,
    distribution: str,
    project: Path,
    *,
    editable: bool = True,
) -> None:
    metadata = site_packages / f"{distribution}-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "direct_url.json").write_text(
        json.dumps(
            {
                "url": project.resolve().as_uri(),
                "dir_info": {"editable": editable},
            }
        ),
        encoding="utf-8",
    )


def _write_importable_package(root: Path, module: str) -> Path:
    package = root / module
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    return package


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


def test_hosted_editable_roots_use_only_owned_active_minor_safe_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    venv = tmp_path / "manager-venv"
    (venv / "pyvenv.cfg").parent.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        "version_info = 99.99.1\n",
        encoding="utf-8",
    )
    active_site = (
        venv / "Lib" / "site-packages"
        if os.name == "nt"
        else venv / "lib" / "python99.99" / "site-packages"
    )
    stale_site = venv / "lib" / "python98.98" / "site-packages"
    active_site.mkdir(parents=True)
    stale_site.mkdir(parents=True)

    owned_project = tmp_path / "owned-project"
    owned_root = owned_project / "src"
    _write_importable_package(owned_root, "owned_dep")
    _write_editable_owner(active_site, "owned_project", owned_project)
    (active_site / "10-owned.pth").write_text(
        f"{owned_root}\n",
        encoding="utf-8",
    )

    stale_project = tmp_path / "stale-project"
    stale_root = stale_project / "src"
    _write_importable_package(stale_root, "stale_dep")
    _write_editable_owner(stale_site, "stale_project", stale_project)
    (stale_site / "stale.pth").write_text(f"{stale_root}\n", encoding="utf-8")

    unowned_root = tmp_path / "unowned" / "src"
    _write_importable_package(unowned_root, "unowned_dep")
    (active_site / "20-unowned.pth").write_text(
        f"{unowned_root}\n",
        encoding="utf-8",
    )

    noneditable_project = tmp_path / "noneditable-project"
    noneditable_root = noneditable_project / "src"
    _write_importable_package(noneditable_root, "noneditable_dep")
    _write_editable_owner(
        active_site,
        "noneditable_project",
        noneditable_project,
        editable=False,
    )
    (active_site / "30-noneditable.pth").write_text(
        f"{noneditable_root}\n",
        encoding="utf-8",
    )

    hosted_project = tmp_path / "hosted-runtime-project"
    hosted_root = hosted_project / "src"
    _write_importable_package(hosted_root, "otherwise_safe_dep")
    (hosted_root / "agi_future_runtime").mkdir(parents=True)
    (hosted_root / "streamlit.py").write_text("", encoding="utf-8")
    _write_editable_owner(active_site, "hosted_runtime_project", hosted_project)
    (active_site / "40-hosted-runtime.pth").write_text(
        f"{hosted_root}\n",
        encoding="utf-8",
    )

    native_project = tmp_path / "native-project"
    native_root = native_project / "src"
    native_package = _write_importable_package(native_root, "native_dep")
    (native_package / "accelerator.so").write_bytes(b"")
    _write_editable_owner(active_site, "native_project", native_project)
    (active_site / "50-native.pth").write_text(
        f"{native_root}\n",
        encoding="utf-8",
    )

    mapped_project = tmp_path / "mapped-project"
    mapped_package = _write_importable_package(mapped_project / "src", "mapped_dep")
    aliased_project = tmp_path / "aliased-project"
    aliased_package = _write_importable_package(
        aliased_project / "src",
        "actual_dep",
    )
    escaped_project = tmp_path / "escaped-parent" / "owned_project"
    escaped_package = _write_importable_package(escaped_project, "pkg")
    _write_editable_owner(active_site, "mapped_project", mapped_project)
    _write_editable_owner(active_site, "aliased_project", aliased_project)
    _write_editable_owner(active_site, "escaped_project", escaped_project)
    finder = "__editable___mapped_projects_1_0_finder"
    _write_finder(
        active_site,
        finder,
        "\n".join(
            (
                "MAPPING = {",
                f"    'mapped_dep': {str(mapped_package)!r},",
                f"    'alias_dep': {str(aliased_package)!r},",
                f"    'owned_project.pkg': {str(escaped_package)!r},",
                "}",
                "NAMESPACES = {}",
            )
        ),
    )

    # A root already present in the hosted interpreter remains part of the
    # isolation contract; callers need it in module_roots to evict stale names.
    monkeypatch.syspath_prepend(str(owned_root))

    roots = hosted_editable_source_import_roots(venv)

    assert roots == (owned_root.resolve(), mapped_package.parent.resolve())
    assert stale_root.resolve() not in roots
    assert unowned_root.resolve() not in roots
    assert noneditable_root.resolve() not in roots
    assert hosted_root.resolve() not in roots
    assert native_root.resolve() not in roots
    assert aliased_package.parent.resolve() not in roots
    assert escaped_project.parent.resolve() not in roots
    assert active_site.resolve() not in roots


@pytest.mark.skipif(os.name == "nt", reason="Windows venvs do not use lib/pythonXt")
def test_hosted_editable_roots_support_free_threaded_site_for_pure_source(
    tmp_path: Path,
) -> None:
    venv = tmp_path / "free-threaded-venv"
    (venv / "pyvenv.cfg").parent.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        "version_info = 97.97.0\n",
        encoding="utf-8",
    )
    site_packages = venv / "lib" / "python97.97t" / "site-packages"
    project = tmp_path / "pure-project"
    source_root = project / "src"
    _write_importable_package(source_root, "pure_dep")
    _write_editable_owner(site_packages, "pure_project", project)
    (site_packages / "pure-project.pth").write_text(
        f"{source_root}\n",
        encoding="utf-8",
    )

    assert hosted_editable_source_import_roots(venv) == (source_root.resolve(),)


def test_hosted_editable_roots_reject_native_code_in_build_on_same_minor(
    tmp_path: Path,
) -> None:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    venv = tmp_path / "same-minor-venv"
    (venv / "pyvenv.cfg").parent.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        f"version_info = {version}.0\n",
        encoding="utf-8",
    )
    site_packages = (
        venv / "Lib" / "site-packages"
        if os.name == "nt"
        else venv / "lib" / f"python{version}" / "site-packages"
    )
    project = tmp_path / "native-build-project"
    source_root = project / "src"
    _write_importable_package(source_root, "pure_surface")
    native_build = source_root / "build" / "native_dep.so"
    native_build.parent.mkdir()
    native_build.write_bytes(b"native")
    _write_editable_owner(site_packages, "native_build_project", project)
    (site_packages / "native-build-project.pth").write_text(
        f"{source_root}\n",
        encoding="utf-8",
    )

    assert hosted_editable_source_import_roots(venv) == ()


def test_hosted_editable_roots_reject_external_directory_symlinks(
    tmp_path: Path,
) -> None:
    venv = tmp_path / "symlink-venv"
    (venv / "pyvenv.cfg").parent.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        "version_info = 96.96.0\n",
        encoding="utf-8",
    )
    site_packages = (
        venv / "Lib" / "site-packages"
        if os.name == "nt"
        else venv / "lib" / "python96.96" / "site-packages"
    )
    project = tmp_path / "symlink-project"
    source_root = project / "src"
    source_root.mkdir(parents=True)
    external_package = tmp_path / "external-package"
    external_package.mkdir()
    (external_package / "native_dep.so").write_bytes(b"native")
    try:
        (source_root / "linked_dep").symlink_to(
            external_package,
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    _write_editable_owner(site_packages, "symlink_project", project)
    (site_packages / "symlink-project.pth").write_text(
        f"{source_root}\n",
        encoding="utf-8",
    )

    assert hosted_editable_source_import_roots(venv) == ()
