#!/usr/bin/env python3
"""
Repair a PyCharm project so it can open:
- Fix misc.xml
- Ensure root module
- Ensure all subprojects are attached
- Rebuild modules.xml
- Set SDKs if .venv found
"""

import os
import sys
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
IDEA = ROOT / ".idea"
MODULES_DIR = IDEA / "modules"
SDK_TYPE = "Python SDK"

def debug(msg):
    print(f"[fix] {msg}")

def backup_idea():
    if IDEA.exists():
        backup = ROOT / f".idea.bak"
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(IDEA, backup)
        debug(f"Backup created: {backup}")

def read_xml(path):
    return ET.parse(str(path))

def write_xml(tree, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="UTF-8", xml_declaration=True)

def venv_python_for(project_dir):
    for c in (
        project_dir / ".venv" / "bin" / "python3",
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ):
        if c.exists():
            return c.resolve()
    return None

def ensure_misc_xml(sdk_name=None):
    misc = IDEA / "misc.xml"
    if misc.exists():
        tree = read_xml(misc)
        root = tree.getroot()
    else:
        root = ET.Element("project", {"version": "4"})
        tree = ET.ElementTree(root)
    prm = root.find("./component[@name='ProjectRootManager']")
    if prm is None:
        prm = ET.SubElement(root, "component", {"name": "ProjectRootManager"})
    if sdk_name:
        prm.set("project-jdk-name", sdk_name)
        prm.set("project-jdk-type", SDK_TYPE)
    write_xml(tree, misc)
    debug("misc.xml fixed")

def ensure_root_module(name):
    iml = MODULES_DIR / f"{name}.iml"
    m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
    ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
    ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
    write_xml(ET.ElementTree(m), iml)
    debug(f"Root module IML created: {iml}")

def ensure_app_module(app_dir, sdk_name=None):
    app = app_dir.name
    iml = MODULES_DIR / f"{app}.iml"
    m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
    ET.SubElement(comp, "content", {"url": f"file://$PROJECT_DIR$/src/agilab/apps/{app}"})
    if sdk_name:
        ET.SubElement(comp, "orderEntry", {"type": "jdk", "jdkName": sdk_name, "jdkType": SDK_TYPE})
    else:
        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
    write_xml(ET.ElementTree(m), iml)
    debug(f"App module IML created: {iml}")

def rebuild_modules_xml():
    imls = sorted(p for p in MODULES_DIR.glob("*.iml") if p.exists())
    project = ET.Element("project", {"version": "4"})
    comp = ET.SubElement(project, "component", {"name": "ProjectModuleManager"})
    mods = ET.SubElement(comp, "modules")
    for p in imls:
        fileurl = f"file://$PROJECT_DIR$/{p.relative_to(ROOT).as_posix()}"
        filepath = f"$PROJECT_DIR$/{p.relative_to(ROOT).as_posix()}"
        ET.SubElement(mods, "module", {"fileurl": fileurl, "filepath": filepath})
    write_xml(ET.ElementTree(project), IDEA / "modules.xml")
    debug("modules.xml rebuilt")

def main():
    if not IDEA.exists():
        IDEA.mkdir()
    MODULES_DIR.mkdir(parents=True, exist_ok=True)

    backup_idea()

    root_py = venv_python_for(ROOT)
    root_sdk = f"uv ({ROOT.name})" if root_py else None

    ensure_misc_xml(root_sdk)
    ensure_root_module(ROOT.name)

    apps_dir = ROOT / "src" / "agilab" / "apps"
    if apps_dir.exists():
        for app_dir in sorted(p for p in apps_dir.iterdir() if p.is_dir() and p.name.endswith("_project")):
            py = venv_python_for(app_dir)
            sdk_name = f"uv ({app_dir.stem.replace('_project','')})" if py else None
            ensure_app_module(app_dir, sdk_name)

    rebuild_modules_xml()

    debug("Done repairing project")

if __name__ == "__main__":
    main()

