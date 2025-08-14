#!/usr/bin/env python3
import os
import sys
import filecmp
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# ---------- paths ----------
SCRIPT_DIR = Path(__file__).resolve().parent  # .../pycharm
TEMPLATES = [
    "_template_app_egg_manager.xml",
    "_template_app_lib_worker.xml",
    "_template_app_preinstall_manager.xml",
    "_template_app_postinstall_worker.xml",
    "_template_app_run.xml",
    "_template_app_distribute.xml",
    "_template_app_test_manager.xml",
    "_template_app_test_worker.xml",
    "_template_app_test.xml",
]

# ---------- helpers ----------
def venv_python_for(project_dir: Path) -> Optional[Path]:
    """Return the project's .venv python, if present."""
    candidates = [
        project_dir / ".venv" / "bin" / "python3",       # unix/mac
        project_dir / ".venv" / "bin" / "python",        # unix/mac alt
        project_dir / ".venv" / "Scripts" / "python.exe" # windows
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None

def parse_template(name: str) -> ET.ElementTree:
    tpl_path = SCRIPT_DIR / name
    if not tpl_path.exists():
        raise FileNotFoundError(f"Template not found: {tpl_path}")
    return ET.parse(str(tpl_path))

def ensure_option(config_elem: ET.Element, name: str, value: str) -> None:
    """Ensure <option name=... value=.../> exists (create or update)."""
    for o in config_elem.iter("option"):
        if o.get("name") == name:
            o.set("value", value)
            return
    ET.SubElement(config_elem, "option", {"name": name, "value": value})

def add_folder_name_to_config(tree: ET.ElementTree, folder_name: str) -> None:
    config_elem = next(tree.getroot().iter("configuration"), None)
    if config_elem is not None:
        config_elem.attrib["folderName"] = folder_name

def patch_sdk_home(tree: ET.ElementTree, py: Path) -> None:
    """Set SDK_HOME to the provided interpreter and disable module SDK."""
    config_elem = next(tree.getroot().iter("configuration"), None)
    if config_elem is None:
        return
    ensure_option(config_elem, "SDK_HOME", str(py))
    ensure_option(config_elem, "IS_MODULE_SDK", "false")
    # SDK_NAME optional when SDK_HOME is set; leave as-is if present.

def update_workspace_xml(config_name: str, config_type: str, folder_name: str) -> None:
    """Ensure the run configuration entry appears in workspace.xml (RunManager component)."""
    idea = Path.cwd() / ".idea"
    idea.mkdir(exist_ok=True)
    workspace_path = idea / "workspace.xml"

    # Minimal skeleton if missing
    if not workspace_path.exists():
        root = ET.Element("project", {"version": "4"})
        ET.SubElement(root, "component", {"name": "RunManager"})
        ET.ElementTree(root).write(workspace_path, encoding="UTF-8", xml_declaration=True)

    tree = ET.parse(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    if runmanager is None:
        runmanager = ET.SubElement(root, "component", {"name": "RunManager"})

    # find existing
    config_el = None
    for conf in runmanager.findall("configuration"):
        if conf.attrib.get("name") == config_name and conf.attrib.get("type") == config_type:
            config_el = conf
            break

    if config_el is None:
        # factoryName isn't strictly needed; PyCharm fills it. Keep type only.
        config_el = ET.SubElement(runmanager, "configuration", {
            "name": config_name,
            "type": config_type,
            "folderName": folder_name
        })
    else:
        config_el.attrib["folderName"] = folder_name

    tree.write(workspace_path, encoding="UTF-8", xml_declaration=True)
    print(f"Updated workspace.xml for config '{config_name}' in folder '{folder_name}'.")

def update_folders_xml(folder_name: str) -> None:
    """Ensure the folder exists in .idea/runConfigurations/folders.xml."""
    output_dir = Path.cwd() / ".idea" / "runConfigurations"
    output_dir.mkdir(parents=True, exist_ok=True)
    folders_xml_path = output_dir / "folders.xml"

    if folders_xml_path.exists():
        tree = ET.parse(folders_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element("component", {"name": "RunManager"})
        tree = ET.ElementTree(root)

    existing = root.find(f"./folder[@name='{folder_name}']")
    if existing is None:
        ET.SubElement(root, "folder", {"name": folder_name})
        tree.write(folders_xml_path, encoding="UTF-8", xml_declaration=True)
        print(f"Added folder '{folder_name}' to folders.xml")
    else:
        print(f"Folder '{folder_name}' already exists in folders.xml")

def replace_placeholders(tree: ET.ElementTree, app: str) -> None:
    """Replace {APP} placeholders in attributes and text."""
    for el in tree.getroot().iter():
        # attributes
        for k, v in list(el.attrib.items()):
            if v and "{APP}" in v:
                el.set(k, v.replace("{APP}", app))
        # text
        if el.text and "{APP}" in el.text:
            el.text = el.text.replace("{APP}", app)

# ---------- new helpers added ----------
def ensure_method(config_elem: ET.Element) -> None:
    if config_elem.find("method") is None:
        ET.SubElement(config_elem, "method", {"v": "2"})

def ensure_common_python_options(config_elem: ET.Element, workdir: Path) -> None:
    # Required/handy options for Python run configs
    ensure_option(config_elem, "WORKING_DIRECTORY", str(workdir))
    ensure_option(config_elem, "ADD_CONTENT_ROOTS", "true")
    ensure_option(config_elem, "ADD_SOURCE_ROOTS", "true")
    ensure_option(config_elem, "PARENT_ENVS", "true")
    ensure_option(config_elem, "INTERPRETER_OPTIONS", "")

def bind_module(config_elem: ET.Element, module_name: str) -> None:
    m = config_elem.find("module")
    if m is None:
        ET.SubElement(config_elem, "module", {"name": module_name})
    elif m.get("name") != module_name:
        m.set("name", module_name)

def set_sdk_name(config_elem: ET.Element, sdk_name: str) -> None:
    # purely cosmetic when SDK_HOME is set; but helpful in UI
    if config_elem.get("SDK_NAME") != sdk_name:
        config_elem.set("SDK_NAME", sdk_name)

def resolve_module_name(app: str, project_root: Path) -> str:
    """
    Pick the module name by inspecting .idea/modules.xml and matching
    content root to a likely app directory. Fall back to `app`.
    """
    modules_xml = project_root / ".idea" / "modules.xml"
    if not modules_xml.exists():
        return app
    try:
        tree = ET.parse(modules_xml)
    except ET.ParseError:
        return app

    # Heuristics: prefer a module whose content root path ends with the app name
    candidates = [
        (project_root / "src" / "agilab" / "apps" / app),
        (project_root / "apps" / app),
        (project_root / app),
    ]
    candidates = [c.resolve() for c in candidates if c.exists()]

    modules_parent = tree.getroot().find("./component[@name='ProjectModuleManager']/modules")
    if modules_parent is None:
        return app

    def iml_path(m: ET.Element):
        fp = m.get("filepath") or m.get("fileurl") or ""
        p = fp.replace("file://$PROJECT_DIR$/", "").replace("$PROJECT_DIR$/", "").replace("file://", "")
        return (project_root / p).resolve()

    for m in modules_parent.findall("module"):
        p = iml_path(m)
        if not (p and p.exists()):
            continue
        try:
            t = ET.parse(p)
        except ET.ParseError:
            continue
        content = t.getroot().find("./component[@name='NewModuleRootManager']/content")
        if content is None:
            continue
        url = content.get("url", "")
        if not url.startswith("file://"):
            continue
        root = Path(url[len("file://"):]).resolve()
        if any(str(root).endswith(str(c)) for c in candidates):
            # module name is the .iml file stem
            return p.stem

    return app

# ---------- main ----------
def main() -> int:
    ensure_dirs()

    if not APPS_DIR.exists():
        debug(f"Apps directory not found: {APPS_DIR}")
        return 1

    apps = sorted([p for p in APPS_DIR.iterdir() if p.is_dir() and p.name.endswith("_project")])
    if not apps:
        debug("No *_project apps found.")
        return 0

    gen_script = ROOT / "gen-app-script.py"
    if not gen_script.exists():
        debug(f"Missing {gen_script}, cannot generate run configurations.")
        return 1

    import subprocess, sys

    for app_dir in apps:
        app = app_dir.name  # e.g. "flight_trajectory_project"
        py = venv_python_for(app_dir)
        if not py:
            debug(f"Skip {app}: .venv python not found.")
            continue

        # 1) per-app module
        ensure_module(app, app_dir)

        # 2) run configurations via gen-app-script.py (per app)
        module_name = app[:-8] if app.endswith("_project") else app  # strip "_project"
        debug(f"Calling {gen_script} for module '{module_name}'...")
        subprocess.run(
            [sys.executable, str(gen_script), "--module-name", module_name],
            check=True,
            cwd=str(ROOT),
        )

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
