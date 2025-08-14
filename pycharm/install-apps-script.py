#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Set PyCharm interpreters for the project and modules.

- Project interpreter -> 'uv (agilab)' in .idea/misc.xml
- Module interpreter  -> 'uv (<module_name>)' in each *.iml
  BUT: if a module already has a custom SDK set in the .iml, keep it (preserve existing).

Notes:
- We don't touch jdk.table.xml here (PyCharm will create/update it).
- We rebuild .idea/modules.xml from discovered .iml files.
"""

from __future__ import annotations

import os
import sys
import pathlib
import xml.etree.ElementTree as ET

IDEA_DIR = pathlib.Path(".idea")
MISC_XML = IDEA_DIR / "misc.xml"
MODULES_XML = IDEA_DIR / "modules.xml"

# -------------------------- small helpers --------------------------

def p(msg: str) -> None:
    print(f"[install-apps] {msg}")

def ensure_idea_dir() -> None:
    IDEA_DIR.mkdir(exist_ok=True)

def read_xml(path: pathlib.Path) -> ET.ElementTree:
    if not path.exists():
        # Create minimal skeletons as needed
        if path == MISC_XML:
            root = ET.Element("project", {"version": "4"})
            ET.SubElement(root, "component", {"name": "ProjectRootManager"})
            tree = ET.ElementTree(root)
            tree.write(path, encoding="utf-8", xml_declaration=True)
        elif path == MODULES_XML:
            root = ET.Element("project", {"version": "4"})
            ET.SubElement(root, "component", {"name": "ProjectModuleManager"})
            tree = ET.ElementTree(root)
            tree.write(path, encoding="utf-8", xml_declaration=True)
        else:
            # Default empty project file
            root = ET.Element("project", {"version": "4"})
            tree = ET.ElementTree(root)
            tree.write(path, encoding="utf-8", xml_declaration=True)
    return ET.parse(path)

# --------------------- project interpreter (misc.xml) ---------------------

def set_project_interpreter(name: str) -> None:
    tree = read_xml(MISC_XML)
    root = tree.getroot()

    comp = root.find("./component[@name='ProjectRootManager']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectRootManager"})

    # In PyCharm, project SDK is stored as attributes on ProjectRootManager
    # jdkName + jdkType="Python SDK"
    comp.set("project-jdk-name", name)
    comp.set("project-jdk-type", "Python SDK")

    tree.write(MISC_XML, encoding="utf-8", xml_declaration=True)
    p(f"[misc.xml] Project interpreter set to '{name}'.")

# --------------------- module interpreter (.iml) ---------------------

def iml_get_existing_sdk_name(iml_path: pathlib.Path) -> str | None:
    """Return existing SDK name from .iml if present, else None."""
    try:
        tree = ET.parse(iml_path)
    except ET.ParseError:
        return None

    comp = tree.getroot().find("./component[@name='NewModuleRootManager']")
    if comp is None:
        return None

    for oe in comp.findall("orderEntry"):
        if oe.get("type") == "jdk":
            return oe.get("jdkName")
    return None

def iml_set_module_sdk(iml_path: pathlib.Path, sdk_name: str, preserve_existing: bool = True) -> bool:
    """
    Ensure .iml sets the module SDK to `sdk_name`.
    If `preserve_existing` and a different SDK is already set, do nothing and return False.
    Return True if the file was changed.
    """
    try:
        tree = ET.parse(iml_path)
    except ET.ParseError:
        return False

    root = tree.getroot()
    comp = root.find("./component[@name='NewModuleRootManager']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})

    # Respect an existing custom SDK if present
    existing = None
    for oe in comp.findall("orderEntry"):
        if oe.get("type") == "jdk":
            existing = oe.get("jdkName")
            break

    if preserve_existing and existing and existing != sdk_name:
        # Keep the user-defined interpreter
        p(f"{iml_path.name}: kept existing module SDK '{existing}' (preserve existing)")
        return False

    # Remove current SDK entries (jdk or inheritedJdk)
    for oe in list(comp.findall("orderEntry")):
        if oe.get("type") in ("jdk", "inheritedJdk"):
            comp.remove(oe)

    ET.SubElement(comp, "orderEntry", {
        "type": "jdk",
        "jdkName": sdk_name,
        "jdkType": "Python SDK",
    })

    tree.write(iml_path, encoding="utf-8", xml_declaration=True)
    return True

# --------------------- discover modules & rebuild modules.xml ---------------------

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".mypy_cache", ".pytest_cache",
    ".tox", ".venv", "venv", "node_modules", "__pycache__",
}

def discover_iml_files(base: pathlib.Path) -> list[pathlib.Path]:
    """Find all .iml files under the repo (including under .idea)."""
    imls: list[pathlib.Path] = []
    for root, dirs, files in os.walk(base):
        # prune large/irrelevant dirs except '.idea' because it contains module .iml files
        pruned = []
        for d in list(dirs):
            if d in SKIP_DIRS and d != ".idea":
                pruned.append(d)
        for d in pruned:
            dirs.remove(d)

        for f in files:
            if f.endswith(".iml"):
                imls.append(pathlib.Path(root) / f)
    return sorted(imls)

def rebuild_modules_xml(iml_paths: list[pathlib.Path]) -> None:
    tree = read_xml(MODULES_XML)
    root = tree.getroot()
    comp = root.find("./component[@name='ProjectModuleManager']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectModuleManager"})

    modules_el = comp.find("modules")
    if modules_el is not None:
        comp.remove(modules_el)
    modules_el = ET.SubElement(comp, "modules")

    for iml in iml_paths:
        # store relative macro path like $PROJECT_DIR$/.idea/xyz.iml or module-root/module.iml
        rel = iml.relative_to(pathlib.Path.cwd())
        href = f"$PROJECT_DIR$/{rel.as_posix()}"
        ET.SubElement(modules_el, "module", {
            "fileurl": f"file://{href}",
            "filepath": href,
        })

    tree.write(MODULES_XML, encoding="utf-8", xml_declaration=True)
    p(f"[modules.xml] rebuilt with {len(iml_paths)} modules (macro paths)")

# ------------------------------- main --------------------------------

def main() -> int:
    ensure_idea_dir()

    # 1) Project interpreter -> uv (agilab)
    set_project_interpreter("uv (agilab)")

    # 2) For each module .iml: set to 'uv (<module>)' unless it already has a custom one
    iml_paths = discover_iml_files(pathlib.Path.cwd())
    for iml in iml_paths:
        module_name = iml.stem  # "<name>.iml" -> "<name>"
        desired_sdk = f"uv ({module_name})"
        changed = iml_set_module_sdk(iml, desired_sdk, preserve_existing=True)
        if changed:
            p(f"{iml.name}: module SDK set to '{desired_sdk}'")
        # else a message was printed if we preserved an existing SDK

    # 3) Rebuild modules.xml from discovered .iml files
    rebuild_modules_xml(iml_paths)

    p("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
