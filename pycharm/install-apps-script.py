#!/usr/bin/env python3
"""
Attach all `.venv` projects into ONE PyCharm workspace (in CWD), create per-app
modules, and generate run configurations from your templates.

HARD GUARANTEES:
- Per-project mutation: NO writes inside subproject `.idea/` (we only touch root .idea).
- Global SDK registry: NOT required (we set SDK_HOME to each app's actual .venv).
- Black plugin alignment: NOT touched.
- Installers: NOT invoked.

What this DOES:
- Creates .idea/ with modules.xml and .idea/modules/<app>.iml for every *_project in src/agilab/apps
- Generates .idea/runConfigurations/* using your templates, filling {APP}, SDK_NAME, and SDK_HOME
- Optionally selects the first generated run config in workspace.xml
"""

from __future__ import annotations
import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path
from typing import Optional

# ----------------------------- constants/paths ----------------------------- #

ROOT = Path.cwd()
IDEA = ROOT / ".idea"
MODULES_DIR = IDEA / "modules"
RUNCFG_DIR = IDEA / "runConfigurations"
APPS_DIR = ROOT / "src" / "agilab" / "apps"

# Your uploaded templates (already in project root per your share)
RUN_TPL = ROOT / "_template_app_run.xml"                 # name: "{APP} run"
TEST_WORKER_TPL = ROOT / "_template_app_test_worker.xml" # name: "{APP} test worker"

# ----------------------------- helpers ----------------------------- #

def debug(msg: str):
    print(f"[install-apps] {msg}")

def pretty_xml_str(elem: ET.Element) -> str:
    rough = ET.tostring(elem, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

def ensure_dirs():
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

def venv_python_for(project_dir: Path) -> Optional[Path]:
    """Return the project's .venv python, if present."""
    candidates = [
        project_dir / ".venv" / "bin" / "python3",             # unix/mac
        project_dir / ".venv" / "bin" / "python",              # unix/mac alt
        project_dir / ".venv" / "Scripts" / "python.exe",      # windows
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None

def read_xml(p: Path) -> ET.ElementTree:
    return ET.parse(str(p))

def write_xml(tree: ET.ElementTree, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dest), encoding="UTF-8", xml_declaration=True)

def ensure_module(app: str, content_root: Path):
    """
    Create .idea/modules/{app}.iml and add it to .idea/modules.xml if missing.
    """
    modules_xml = IDEA / "modules.xml"
    iml_path = MODULES_DIR / f"{app}.iml"

    # Minimal Python module IML
    if not iml_path.exists():
        module = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
        comp = ET.SubElement(module, "component", {"name": "NewModuleRootManager"})
        ET.SubElement(comp, "content", {"url": f"file://{content_root}"})
        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
        write_xml(ET.ElementTree(module), iml_path)
        debug(f"Module IML created: {iml_path}")

    # Update modules.xml
    if modules_xml.exists():
        tree = ET.parse(modules_xml)
        root = tree.getroot()
    else:
        root = ET.Element("project", {"version": "4"})
        ET.SubElement(root, "component", {"name": "ProjectModuleManager"})
        # add <modules/> child
        comp = root.find("./component[@name='ProjectModuleManager']")
        ET.SubElement(comp, "modules")
        tree = ET.ElementTree(root)

    comp = root.find("./component[@name='ProjectModuleManager']/modules")
    existing = [m.get("fileurl") for m in comp.findall("module")]
    fileurl = f"file://{iml_path}"
    if fileurl not in existing:
        ET.SubElement(comp, "module", {"fileurl": fileurl, "filepath": str(iml_path)})
        write_xml(tree, modules_xml)
        debug(f"modules.xml updated with {fileurl}")

def _replace_placeholders(root: ET.Element, app: str):
    for el in root.iter():
        for k, v in list(el.attrib.items()):
            el.set(k, v.replace("{APP}", app))
        if el.text:
            el.text = el.text.replace("{APP}", app)

def _ensure_option(config_elem: ET.Element, name: str, value: str):
    for o in config_elem.iter("option"):
        if o.get("name") == name:
            o.set("value", value)
            return
    ET.SubElement(config_elem, "option", {"name": name, "value": value})

def render_from_template(tpl_path: Path, app: str, sdk_name: str, sdk_home: str) -> ET.ElementTree:
    """
    Render a run configuration from template:
    - replace {APP}
    - ensure SDK_NAME and SDK_HOME are set
    - set folder/folderName to app (grouping in UI)
    """
    tree = read_xml(tpl_path)
    root = tree.getroot()
    _replace_placeholders(root, app)

    config = next(root.iter("configuration"), None)
    if config is not None:
        _ensure_option(config, "SDK_NAME", sdk_name)
        _ensure_option(config, "SDK_HOME", sdk_home)
        # newer IDEs use "folder", older "folderName"
        if "folder" in config.attrib:
            config.set("folder", app)
        else:
            config.set("folderName", app)

    return tree

def write_run_config(name: str, tree: ET.ElementTree):
    dest = RUNCFG_DIR / name
    write_xml(tree, dest)
    debug(f"Run config written: {dest}")

def select_in_workspace(config_display_name: str):
    """
    Ensure RunManager exists and select a config by its display name.
    Display name in PyCharm is usually "Python.<configuration name>".
    """
    ws = IDEA / "workspace.xml"
    if not ws.exists():
        return
    tree = ET.parse(ws)
    root = tree.getroot()
    rm = root.find("./component[@name='RunManager']")
    if rm is None:
        rm = ET.SubElement(root, "component", {"name": "RunManager"})
    rm.set("selected", f"Python.{config_display_name}")
    write_xml(tree, ws)
    debug(f"workspace.xml RunManager selected={rm.get('selected')}")

# ----------------------------- main flow ----------------------------- #

def main() -> int:
    ensure_dirs()

    if not APPS_DIR.exists():
        debug(f"Apps directory not found: {APPS_DIR}")
        return 1

    apps = sorted([p for p in APPS_DIR.iterdir() if p.is_dir() and p.name.endswith("_project")])
    if not apps:
        debug("No *_project apps found.")
        return 0

    first_selection: Optional[str] = None

    for app_dir in apps:
        app = app_dir.name  # e.g. flight_trajectory_project
        py = venv_python_for(app_dir)
        if not py:
            debug(f"Skip {app}: .venv python not found.")
            continue

        # 1) per-app module
        ensure_module(app, app_dir)

        # 2) run configurations from your templates
        #    a) app run
        if RUN_TPL.exists():
            run_tree = render_from_template(RUN_TPL, app, sdk_name=f"uv ({app})", sdk_home=str(py))
            write_run_config(f"{app}-run.xml", run_tree)
            if first_selection is None:
                first_selection = f"{app} run"
        else:
            debug(f"Missing template: {RUN_TPL.name}")

        #    b) test worker
        if TEST_WORKER_TPL.exists():
            # you used uv ({APP}_worker) in this template
            test_tree = render_from_template(TEST_WORKER_TPL, app, sdk_name=f"uv ({app.replace('_project','')}_worker)", sdk_home=str(py))
            write_run_config(f"{app}-test-worker.xml", test_tree)
        else:
            debug(f"Missing template: {TEST_WORKER_TPL.name}")

    # 3) select a default run
    if first_selection:
        select_in_workspace(first_selection)

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
