#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
install-apps-script.py (CLEAN)
- Populate JetBrains jdk.table.xml with SDKs for every project that already has .venv
- Set project interpreter (misc.xml) to "uv (<root project>)"
- Point each module .iml to its own "uv (<module>)" SDK if it has .venv, else fallback to "uv (<root project>)"
- Rebuild modules.xml, and pretty-print all written XML
- Provide safe repair of jdk.table.xml (sanitization) and atomic writes

CLI:
  --repair-jdk-table                 : sanitize/repair jdk.table.xml (no project mutation)
  --register-all-venvs [ROOT]        : scan ROOT (or CWD) for .venv and register SDKs; then apply project wiring
"""

from __future__ import annotations
import os
import sys
import glob
import tempfile
from pathlib import Path
from typing import Iterable, Tuple

import xml.etree.ElementTree as ET
from xml.dom import minidom

PRINT_PREFIX = "[install-apps]"
SDK_TYPE = "Python SDK"


# --------------------------------------------------------------------------- #
# XML helpers
# --------------------------------------------------------------------------- #

def _prettify(elem: ET.Element) -> str:
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), prefix=path.name + ".", suffix=".tmp", encoding="utf-8") as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def pp_xml_to_file(tree: ET.ElementTree, out_path: Path) -> None:
    """Pretty-print an ElementTree to file with UTF-8, via atomic write."""
    try:
        xml_text = _prettify(tree.getroot())
        atomic_write_text(out_path, xml_text)
    except Exception:
        # Fallback to normal write if minidom hits odd whitespace nodes
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(out_path, encoding="utf-8", xml_declaration=True)


# --------------------------------------------------------------------------- #
# JetBrains config discovery
# --------------------------------------------------------------------------- #

def find_latest_pycharm_options_dir() -> Path | None:
    """
    macOS : ~/Library/Application Support/JetBrains/PyCharm*/options
    Linux : ~/.config/JetBrains/PyCharm*/options
    Windows: %APPDATA%/JetBrains/PyCharm*/options

    Returns the 'options' directory containing jdk.table.xml, or None.
    """
    home = Path.home()
    candidates = []

    # macOS
    mac_root = home / "Library" / "Application Support" / "JetBrains"
    if mac_root.exists():
        candidates.extend(sorted(mac_root.glob("PyCharm*")))

    # Linux
    linux_root = home / ".config" / "JetBrains"
    if linux_root.exists():
        candidates.extend(sorted(linux_root.glob("PyCharm*")))

    # Windows
    win_appdata = os.environ.get("APPDATA", "")
    if win_appdata:
        win_root = Path(win_appdata) / "JetBrains"
        if win_root.exists():
            candidates.extend(sorted(win_root.glob("PyCharm*")))

    options = [c / "options" for c in candidates if (c / "options").exists()]
    return options[-1] if options else None


# --------------------------------------------------------------------------- #
# jdk.table.xml utilities (single canonical schema using child nodes)
# --------------------------------------------------------------------------- #

def _ensure_project_jdk_table(root: ET.Element) -> ET.Element:
    comp = root.find(".//component[@name='ProjectJdkTable']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
    return comp


def _sanitize_table(root: ET.Element) -> int:
    """Remove <jdk> entries missing required child fields."""
    comp = _ensure_project_jdk_table(root)
    removed = 0
    for jdk in list(comp.findall("jdk")):
        name_el = jdk.find("name")
        type_el = jdk.find("type")
        home_el = jdk.find("homePath")
        ok = (
            name_el is not None and name_el.get("value") and
            type_el is not None and type_el.get("value") and
            home_el is not None and home_el.get("value")
        )
        if not ok:
            comp.remove(jdk)
            removed += 1
    return removed


def _find_jdk_by_name(comp: ET.Element, name: str):
    for jdk in comp.findall("jdk"):
        ne = jdk.find("name")
        if ne is not None and ne.get("value") == name:
            return jdk
    return None


def load_or_init_jdk_table(jdk_table_xml: Path) -> ET.ElementTree:
    if jdk_table_xml.exists():
        try:
            return ET.parse(jdk_table_xml)
        except ET.ParseError:
            # Backup corrupted file and start fresh
            backup = jdk_table_xml.with_suffix(".corrupted.bak")
            try:
                backup.write_bytes(jdk_table_xml.read_bytes())
            except Exception:
                pass
    # fresh
    root = ET.Element("application")
    _ensure_project_jdk_table(root)
    return ET.ElementTree(root)


def upsert_python_sdk(jdk_table_xml: Path, sdk_name: str, home: Path) -> None:
    """
    Create or update a Python SDK entry in jdk.table.xml.
    Uses child-node schema:
      <jdk version="2">
        <name value="..."/>
        <type value="Python SDK"/>
        <homePath value="/path/to/python"/>
        <roots>...</roots>  <!-- optional -->
      </jdk>
    """
    tree = load_or_init_jdk_table(jdk_table_xml)
    root = tree.getroot()
    comp = _ensure_project_jdk_table(root)

    # sanitize first to avoid IDE NPE on load
    _sanitize_table(root)

    jdk = _find_jdk_by_name(comp, sdk_name)
    if jdk is None:
        jdk = ET.SubElement(comp, "jdk", {"version": "2"})
        ET.SubElement(jdk, "name", {"value": sdk_name})
        ET.SubElement(jdk, "type", {"value": SDK_TYPE})
        ET.SubElement(jdk, "homePath", {"value": str(home)})
        ET.SubElement(jdk, "roots")
        # (optional) ET.SubElement(jdk, "additional")
        print(f"{PRINT_PREFIX} Added SDK '{sdk_name}' -> {home}")
    else:
        # ensure children exist and are updated
        (jdk.find("name") or ET.SubElement(jdk, "name")).set("value", sdk_name)
        (jdk.find("type") or ET.SubElement(jdk, "type")).set("value", SDK_TYPE)
        (jdk.find("homePath") or ET.SubElement(jdk, "homePath")).set("value", str(home))
        if jdk.find("roots") is None:
            ET.SubElement(jdk, "roots")
        print(f"{PRINT_PREFIX} Updated SDK '{sdk_name}' -> {home}")

    pp_xml_to_file(tree, jdk_table_xml)


def repair_jdk_table(jdk_table_xml: Path) -> int:
    """Sanitize jdk.table.xml in place. Returns number of removed invalid entries."""
    tree = load_or_init_jdk_table(jdk_table_xml)
    root = tree.getroot()
    removed = _sanitize_table(root)
    pp_xml_to_file(tree, jdk_table_xml)
    return removed


# --------------------------------------------------------------------------- #
# Project (.idea) helpers
# --------------------------------------------------------------------------- #

def set_project_interpreter_misc(misc_xml: Path, sdk_name: str) -> None:
    """
    Ensure misc.xml has:
      <component name="ProjectRootManager" version="2"
                 project-jdk-name="sdk_name" project-jdk-type="Python SDK" />
    """
    if misc_xml.exists():
        try:
            tree = ET.parse(misc_xml)
        except ET.ParseError:
            # reset if corrupted
            tree = ET.ElementTree(ET.Element("project", {"version": "4"}))
    else:
        tree = ET.ElementTree(ET.Element("project", {"version": "4"}))

    root = tree.getroot()
    comp = root.find("./component[@name='ProjectRootManager']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectRootManager", "version": "2"})
    comp.set("version", "2")
    comp.set("project-jdk-name", sdk_name)
    comp.set("project-jdk-type", SDK_TYPE)

    pp_xml_to_file(tree, misc_xml)
    print(f"{PRINT_PREFIX} [misc.xml] Project interpreter set to '{sdk_name}'.")


def set_module_sdk_in_iml(iml_path: Path, sdk_name: str) -> None:
    """
    Ensure module .iml points to the given SDK, replacing inheritedJdk if present.
    """
    try:
        tree = ET.parse(iml_path)
    except ET.ParseError:
        return
    root = tree.getroot()

    mgr = root.find("./component[@name='NewModuleRootManager']")
    if mgr is None:
        mgr = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})

    # Remove inheritedJdk entries
    for oe in list(mgr.findall("orderEntry")):
        if oe.attrib.get("type") == "inheritedJdk":
            mgr.remove(oe)

    # Update or create jdk entry
    jdk_entry = None
    for oe in mgr.findall("orderEntry"):
        if oe.attrib.get("type") == "jdk":
            jdk_entry = oe
            break
    if jdk_entry is None:
        jdk_entry = ET.SubElement(mgr, "orderEntry", {"type": "jdk"})
    jdk_entry.set("jdkName", sdk_name)
    jdk_entry.set("jdkType", SDK_TYPE)

    pp_xml_to_file(tree, iml_path)
    print(f"{PRINT_PREFIX} {iml_path.name}: module SDK set to '{sdk_name}'")


def rebuild_modules_xml(project_idea: Path, iml_files: list[Path]) -> None:
    """
    Rebuild .idea/modules.xml listing all modules, beautified.
    """
    modules_xml = project_idea / "modules.xml"
    root = ET.Element("project", {"version": "4"})
    comp = ET.SubElement(root, "component", {"name": "ProjectModuleManager"})
    mods = ET.SubElement(comp, "modules")

    project_dir = project_idea.parent

    for iml in sorted(iml_files):
        rel = iml.relative_to(project_dir)
        attrs = {
            "fileurl": f"file://$PROJECT_DIR$/{rel.as_posix()}",
            "filepath": f"$PROJECT_DIR$/{rel.as_posix()}",
        }
        ET.SubElement(mods, "module", attrs)

    tree = ET.ElementTree(root)
    pp_xml_to_file(tree, modules_xml)
    print(f"{PRINT_PREFIX} [modules.xml] rebuilt with {len(iml_files)} modules (macro paths)")


# --------------------------------------------------------------------------- #
# Discovery of projects with .venv
# --------------------------------------------------------------------------- #

def _venv_python_candidates(project_dir: Path) -> Iterable[Path]:
    # mac/linux
    yield project_dir / ".venv" / "bin" / "python3"
    yield project_dir / ".venv" / "bin" / "python"
    # windows
    yield project_dir / ".venv" / "Scripts" / "python.exe"


def discover_projects_with_venv(root: Path, max_depth: int = 6) -> dict[str, Path]:
    """
    Discover every directory that contains a .venv python.
    Returns mapping: module_name -> venv_python_path
    """
    root = root.resolve()
    venvs: dict[str, Path] = {}

    # include root if it has a venv
    for cand in _venv_python_candidates(root):
        if cand.exists():
            venvs[root.name] = cand
            break

    # depth-limited search
    for p in root.rglob(".venv"):
        try:
            depth = len(p.relative_to(root).parts)
        except Exception:
            continue
        if depth > max_depth:
            continue
        proj = p.parent
        if any(part in {".git", ".idea", "__pycache__"} for part in proj.parts):
            continue
        for cand in _venv_python_candidates(proj):
            if cand.exists():
                venvs[proj.name] = cand
                break

    return venvs


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def wire_project(repo_root: Path, register_sdks: bool = True) -> None:
    """
    Register SDKs from discovered .venv and wire project files.
    """
    projects = discover_projects_with_venv(repo_root)
    idea = repo_root / ".idea"
    idea.mkdir(exist_ok=True)
    root_sdk_name = f"uv ({repo_root.name})"

    options_dir = find_latest_pycharm_options_dir()
    jdk_table_xml = options_dir / "jdk.table.xml" if options_dir else None

    if register_sdks and jdk_table_xml is not None:
        for mod_name, py_path in projects.items():
            sdk_name = f"uv ({mod_name})"
            upsert_python_sdk(jdk_table_xml, sdk_name, py_path)
    elif register_sdks:
        print(f"{PRINT_PREFIX} No JetBrains options dir found; open PyCharm once so it creates the config.")

    # Set project interpreter to root SDK
    set_project_interpreter_misc(idea / "misc.xml", root_sdk_name)

    # Update every module .iml
    iml_files = [Path(p) for p in glob.glob(str(repo_root / "**" / "*.iml"), recursive=True)]
    for iml in sorted(iml_files):
        mod_name = iml.stem
        if mod_name in projects:
            sdk_name = f"uv ({mod_name})"
        else:
            sdk_name = root_sdk_name
        set_module_sdk_in_iml(iml, sdk_name)

    # Rebuild modules.xml
    rebuild_modules_xml(idea, iml_files)

    print(f"{PRINT_PREFIX} Done wiring project at {repo_root}")


def main(argv: list[str]) -> int:
    # Flags
    if "--repair-jdk-table" in argv:
        options_dir = find_latest_pycharm_options_dir()
        if not options_dir:
            print(f"{PRINT_PREFIX} No JetBrains options dir found (open PyCharm once). Nothing to repair.")
            return 0
        xml_path = options_dir / "jdk.table.xml"
        removed = repair_jdk_table(xml_path)
        print(f"{PRINT_PREFIX} Repaired {xml_path}; removed {removed} invalid entries")
        return 0

    if "--register-all-venvs" in argv:
        idx = argv.index("--register-all-venvs")
        try:
            root = Path(argv[idx+1])
            if str(root).startswith("--"):
                raise ValueError
        except Exception:
            root = Path.cwd()
        wire_project(root, register_sdks=True)
        return 0

    # default: operate in CWD
    wire_project(Path.cwd(), register_sdks=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
