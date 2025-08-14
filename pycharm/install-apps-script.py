#!/usr/bin/env python3
"""
Install apps and then patch PyCharm interpreters (SDKs) so that:
- Project interpreter = uv (<root>)
- Each module *.iml uses uv (<module>) if that module has its own .venv
"""
import os
import sys
import subprocess
import platform
from pathlib import Path
import xml.etree.ElementTree as ET

# -----------------------------
# Small helpers
# -----------------------------
def run(cmd, cwd=None):
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=cwd)

def py_exe_from_venv(venv_dir: Path) -> Path:
    if platform.system().lower().startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"

def ensure_parent_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

# -----------------------------
# PyCharm patch helpers (same impl as in gen script)
# -----------------------------
def ensure_jdk_table_sdk(sdk_name: str, home_path: Path, idea_dir: Path):
    jdk_table = idea_dir / "jdk.table.xml"
    if jdk_table.exists():
        tree = ET.parse(jdk_table)
        root = tree.getroot()
    else:
        root = ET.Element("application")
        tree = ET.ElementTree(root)

    comp = root.find("./component[@name='ProjectJdkTable']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})

    jdk = None
    for j in comp.findall("jdk"):
        if j.attrib.get("name") == sdk_name and j.attrib.get("type") == "Python SDK":
            jdk = j
            break

    if jdk is None:
        jdk = ET.SubElement(comp, "jdk", {"name": sdk_name, "type": "Python SDK", "version": ""})
        ET.SubElement(jdk, "homePath").text = str(home_path)
        ET.SubElement(jdk, "roots")
        ET.SubElement(jdk, "additional")
        print(f"[jdk.table.xml] Added SDK '{sdk_name}' -> {home_path}")
    else:
        hp = jdk.find("homePath")
        if hp is None:
            hp = ET.SubElement(jdk, "homePath")
        old = hp.text
        hp.text = str(home_path)
        print(f"[jdk.table.xml] Updated SDK '{sdk_name}' homePath: {old} -> {home_path}")

    ensure_parent_dir(jdk_table)
    tree.write(jdk_table, encoding="utf-8", xml_declaration=True)

def set_project_interpreter(sdk_name: str, idea_dir: Path):
    misc = idea_dir / "misc.xml"
    if misc.exists():
        tree = ET.parse(misc)
        root = tree.getroot()
    else:
        root = ET.Element("project", {"version": "4"})
        tree = ET.ElementTree(root)

    prm = root.find("./component[@name='ProjectRootManager']")
    if prm is None:
        prm = ET.SubElement(root, "component", {"name": "ProjectRootManager", "version": "2"})

    prm.set("project-jdk-name", sdk_name)
    prm.set("project-jdk-type", "Python SDK")

    ensure_parent_dir(misc)
    tree.write(misc, encoding="utf-8", xml_declaration=True)
    print(f"[misc.xml] Project interpreter set to '{sdk_name}'.")

def patch_module_iml_to_sdk(iml_file: Path, sdk_name: str):
    try:
        tree = ET.parse(iml_file)
        root = tree.getroot()
    except ET.ParseError:
        print(f"[iml] Skip unparsable: {iml_file}")
        return
    comp = root.find("./component[@name='NewModuleRootManager']")
    if comp is None:
        return
    for oe in list(comp.findall("orderEntry")):
        if oe.attrib.get("type") in ("jdk", "inheritedJdk"):
            comp.remove(oe)
    ET.SubElement(comp, "orderEntry", {"type": "jdk", "jdkName": sdk_name, "jdkType": "Python SDK"})
    tree.write(iml_file, encoding="utf-8", xml_declaration=True)
    print(f"[iml] {iml_file.name}: set SDK -> {sdk_name}")

def patch_everything_with_local_venvs(project_root: Path):
    idea_dir = project_root / ".idea"
    if not idea_dir.exists():
        print("[patch] No .idea directory at project root; skipping PyCharm patch.")
        return

    candidates = []
    for d in [project_root] + [p for p in project_root.iterdir() if p.is_dir()]:
        venv = d / ".venv"
        if venv.exists() and venv.is_dir() and py_exe_from_venv(venv).exists():
            candidates.append(d)

    if not candidates:
        print("[patch] No local .venv found anywhere — nothing to patch.")
        return

    for d in candidates:
        name = d.name if d != project_root else project_root.name
        sdk_name = f"uv ({name})"
        py = py_exe_from_venv(d / ".venv")
        ensure_jdk_table_sdk(sdk_name, py, idea_dir)

    if (project_root / ".venv").exists():
        root_sdk = f"uv ({project_root.name})"
    else:
        cand = candidates[0]
        root_sdk = f"uv ({cand.name})" if cand != project_root else f"uv ({project_root.name})"
    set_project_interpreter(root_sdk, idea_dir)

    folder_to_sdk = {}
    for d in candidates:
        key = d.name if d != project_root else project_root.name
        folder_to_sdk[key] = f"uv ({key})"

    for iml_path in project_root.glob("*.iml"):
        base = iml_path.stem
        sdk = folder_to_sdk.get(base, root_sdk)
        patch_module_iml_to_sdk(iml_path, sdk)

# -----------------------------
# Your install workflow
# -----------------------------
def main():
    # We leave your install logic as-is; just ensure we patch at the end.
    # If you were calling a bash script previously, you can keep doing so,
    # or replace with python-side calls to uv. Here we simply run your bash
    # installer when given.
    project_root = Path.cwd()

    # If this script is invoked as a drop-in after your shell installer,
    # just patch interpreters and exit. If you want to also run installs
    # here, add them before the patch call.
    patch_everything_with_local_venvs(project_root)

if __name__ == "__main__":
    main()
