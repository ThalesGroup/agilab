#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
install-apps-script.py
- Populate JetBrains jdk.table.xml with SDKs for every project that already has .venv
- Set project interpreter (misc.xml) to "uv (agilab)"
- Point each module .iml to its own "uv (<module>)" SDK if it has .venv, else fallback to "uv (agilab)"
- Rebuild modules.xml (optional but kept), and beautify all written XML
"""

from __future__ import annotations
import os
import re
import sys
import glob
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom

def _write_xml(elem_or_tree, dest: Path) -> None:
    """Compact XML write (no pretty print)."""
    import xml.etree.ElementTree as ET
    tree = elem_or_tree if isinstance(elem_or_tree, ET.ElementTree) else ET.ElementTree(elem_or_tree)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dest), encoding="UTF-8", xml_declaration=True, short_empty_elements=True)



PRINT_PREFIX = "[install-apps]"
SDK_TYPE = "Python SDK"

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def pp_xml_to_file(tree: ET.ElementTree, out_path: Path) -> None:
    """Pretty-print an ElementTree to file with UTF-8, preserving newlines/indent."""
    try:
        raw = ET.tostring(tree.getroot(), encoding="utf-8")
        pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(pretty)
    except Exception:
        # Fallback to normal write if minidom hits odd whitespace nodes
        tree.write(out_path, encoding="utf-8", xml_declaration=True)


def find_latest_pycharm_config_dir() -> Path | None:
    """
    macOS: ~/Library/Application Support/JetBrains/PyCharm*/options
    Linux: ~/.config/JetBrains/PyCharm*/options
    Windows: %APPDATA%\JetBrains\PyCharm*\options

    Returns the 'options' directory (the parent of jdk.table.xml).
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
    win_root = Path(os.environ.get("APPDATA", "")) / "JetBrains"
    if win_root.exists():
        candidates.extend(sorted(win_root.glob("PyCharm*")))

    # Prefer the lexicographically latest PyCharm dir (usually the newest version)
    candidates = [c / "options" for c in candidates if (c / "options").exists()]
    return candidates[-1] if candidates else None


def ensure_jdk_table_with_sdk(jdk_table_xml: Path, sdk_name: str, home_path: str) -> None:
    """
    Create/update a <jdk name="sdk_name" type="Python SDK"> entry with <homePath>home_path</homePath>.
    Always beautifies the XML after writing.
    """
    if jdk_table_xml.exists():
        tree = ET.parse(jdk_table_xml)
        root = tree.getroot()
    else:
        root = ET.Element("application")
        ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
        tree = ET.ElementTree(root)

    comp = root.find("./component[@name='ProjectJdkTable']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})

    # Try to find existing SDK
    existing = None
    for jdk in comp.findall("jdk"):
        if jdk.attrib.get("type") == SDK_TYPE and jdk.attrib.get("name") == sdk_name:
            existing = jdk
            break

    if existing is None:
        jdk = ET.SubElement(comp, "jdk", {"version": "2", "name": sdk_name, "type": SDK_TYPE})
        ET.SubElement(jdk, "homePath").text = home_path
        ET.SubElement(jdk, "roots")
        ET.SubElement(jdk, "additional")
        print(f"{PRINT_PREFIX} Added SDK '{sdk_name}' -> {home_path}")
    else:
        hp = existing.find("homePath")
        old = hp.text if hp is not None else ""
        if hp is None:
            hp = ET.SubElement(existing, "homePath")
        if old != home_path:
            hp.text = home_path
            print(f"{PRINT_PREFIX} Updated SDK '{sdk_name}' homePath: {old} -> {home_path}")
        else:
            print(f"{PRINT_PREFIX} SDK unchanged '{sdk_name}' -> {home_path}")

    # ✅ Always beautify output
    pp_xml_to_file(tree, jdk_table_xml)


def set_project_interpreter_misc(misc_xml: Path, sdk_name: str) -> None:
    """
    Ensure misc.xml has:
      <component name="ProjectRootManager" ... project-jdk-name="sdk_name" project-jdk-type="Python SDK" />
    """
    if misc_xml.exists():
        tree = ET.parse(misc_xml)
        root = tree.getroot()
    else:
        root = ET.Element("project", {"version": "4"})
        tree = ET.ElementTree(root)

    comp = root.find("./component[@name='ProjectRootManager']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectRootManager", "version": "2"})

    old_name = comp.attrib.get("project-jdk-name", "")
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

    # The typical structure is <module><component name="NewModuleRootManager"> <orderEntry ... />
    mgr = root.find("./component[@name='NewModuleRootManager']")
    if mgr is None:
        # create minimal structure
        mgr = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})

    # Remove existing inheritedJdk entries; update or create a jdk entry
    updated = False
    for oe in list(mgr.findall("orderEntry")):
        if oe.attrib.get("type") == "inheritedJdk":
            mgr.remove(oe)

    for oe in mgr.findall("orderEntry"):
        if oe.attrib.get("type") == "jdk":
            if oe.attrib.get("jdkName") != sdk_name or oe.attrib.get("jdkType") != SDK_TYPE:
                oe.set("jdkName", sdk_name)
                oe.set("jdkType", SDK_TYPE)
                updated = True
            else:
                # already correct
                updated = True
            break

    if not updated:
        ET.SubElement(mgr, "orderEntry", {"type": "jdk", "jdkName": sdk_name, "jdkType": SDK_TYPE})

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
        url = f"file://$PROJECT_DIR$/{rel.as_posix()}"
        fileurl = url
        group = None  # optional; we can omit grouping here
        attrs = {"fileurl": fileurl, "filepath": f"$PROJECT_DIR$/{rel.as_posix()}"}
        if group:
            attrs["group"] = group
        ET.SubElement(mods, "module", attrs)

    tree = ET.ElementTree(root)
    pp_xml_to_file(tree, modules_xml)
    print(f"{PRINT_PREFIX} [modules.xml] rebuilt with {len(iml_files)} modules (macro paths)")


def discover_projects_with_venv(repo_root: Path) -> dict[str, Path]:
    """
    Discover every directory that contains a .venv/bin/python (mac/Linux) or .venv/Scripts/python.exe (Windows).
    Returns mapping: module_name -> venv_python_path
    - Module name is the folder name. For foo_project -> module 'foo_project' (SDK name 'uv (foo_project)').
    """
    venvs: dict[str, Path] = {}

    def venv_python(p: Path) -> Path | None:
        unix = p / ".venv" / "bin" / "python"
        win = p / ".venv" / "Scripts" / "python.exe"
        if unix.exists():
            return unix
        if win.exists():
            return win
        return None

    # include root if it has a venv
    root_py = venv_python(repo_root)
    if root_py:
        venvs[repo_root.name] = root_py

    # depth-limited search (reasonable perf)
    for p in repo_root.rglob(".venv"):
        proj = p.parent
        if any(part in {".git", ".idea", "__pycache__"} for part in proj.parts):
            continue
        py = venv_python(proj)
        if py:
            venvs[proj.name] = py

    return venvs


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    repo_root = Path.cwd()
    idea = repo_root / ".idea"
    idea.mkdir(exist_ok=True)

    # 1) Discover every real project that already has its own .venv
    projects = discover_projects_with_venv(repo_root)
    # Ensure root exists (even if no .venv) so that fallback works
    root_sdk_name = f"uv ({repo_root.name})"

    # 2) Find JetBrains jdk.table.xml
    options_dir = find_latest_pycharm_config_dir()
    if not options_dir:
        print(f"{PRINT_PREFIX} No JetBrains jdk.table.xml found; SDKs usually appear after PyCharm creates it (open PyCharm once).")
    else:
        jdk_table_xml = options_dir / "jdk.table.xml"
        # Ensure an SDK entry for every discovered .venv
        for mod_name, py_path in projects.items():
            sdk_name = f"uv ({mod_name})"
            ensure_jdk_table_with_sdk(jdk_table_xml, sdk_name, str(py_path))

    # 3) Set project interpreter in misc.xml to uv (agilab) (root name)
    set_project_interpreter_misc(idea / "misc.xml", root_sdk_name)

    # 4) Update every module .iml to point to its own SDK if it has one, else fallback to root
    #    We will consider all *.iml under the repo
    iml_files = [Path(p) for p in glob.glob(str(repo_root / "**" / "*.iml"), recursive=True)]
    # Prioritize: if module name (from file name) has a venv, use it; else fallback to root
    for iml in sorted(iml_files):
        mod_name = iml.stem  # e.g., flight_project.iml -> "flight_project"
        if mod_name in projects:
            sdk_name = f"uv ({mod_name})"
        else:
            sdk_name = root_sdk_name
        set_module_sdk_in_iml(iml, sdk_name)

    # 5) Rebuild modules.xml with beautified output
    rebuild_modules_xml(idea, iml_files)

    print(f"{PRINT_PREFIX} Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
