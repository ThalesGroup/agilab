#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, List

# ----------------------------- paths / constants ----------------------------- #
ROOT = Path.cwd()

def find_idea_dir(root: Path) -> Path:
    for name in (".idea", "idea"):
        d = root / name
        if d.exists():
            return d
    return root / ".idea"

IDEA = find_idea_dir(ROOT)
IDEA_NAME = IDEA.name  # ".idea" or "idea"
MODULES_DIR = IDEA / "modules"
RUNCFG_DIR = IDEA / "runConfigurations"
APPS_DIR = ROOT / "src" / "agilab" / "apps"
GEN_SCRIPT = ROOT / "pycharm" / "gen-app-script.py" if (ROOT / "pycharm" / "gen-app-script.py").exists() else ROOT / "gen-app-script.py"

PROJECT_NAME = "agilab"           # shows as "Project: agilab" in Settings
SDK_TYPE = "Python SDK"
PROJECT_SDK_NAME = "uv (agilab)"  # root project interpreter name

# ----------------------------- utils ----------------------------- #
def debug(msg: str) -> None:
    print(f"[install-apps] {msg}")

def pretty_write_xml(elem_or_tree: ET.Element | ET.ElementTree, dest: Path) -> None:
    tree = elem_or_tree if isinstance(elem_or_tree, ET.ElementTree) else ET.ElementTree(elem_or_tree)
    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dest), encoding="UTF-8", xml_declaration=True)

def read_xml(path: Path) -> ET.ElementTree:
    return ET.parse(str(path))

def venv_python_for(project_dir: Path) -> Optional[Path]:
    for c in (
        project_dir / ".venv" / "bin" / "python3",
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ):
        if c.exists():
            return c.resolve()
    return None

def as_project_macro(path: Path) -> str:
    rel = path.resolve().relative_to(ROOT.resolve())
    return f"$PROJECT_DIR$/{rel.as_posix()}"

def as_project_url(path: Path) -> str:
    return f"file://{as_project_macro(path)}"

def app_rel_content_url(app_dir: Path) -> str:
    rel = app_dir.resolve().relative_to(ROOT.resolve())
    return f"file://$PROJECT_DIR$/{rel.as_posix()}"

# ----------------------------- root project name & module ----------------------------- #
def ensure_project_name(name: str) -> None:
    """Make Settings show 'Project: <name>' by writing .idea/.name."""
    name_file = IDEA / ".name"
    try:
        old = name_file.read_text(encoding="utf-8").strip()
    except Exception:
        old = ""
    if old != name:
        name_file.parent.mkdir(parents=True, exist_ok=True)
        name_file.write_text(name + "\n", encoding="utf-8")
        debug(f"Set project name to '{name}' (.idea/.name)")

def ensure_root_module_iml(name: str) -> Path:
    """
    Create/ensure a root module that points to $PROJECT_DIR$.
    e.g. .idea/modules/agilab.iml
    """
    iml = MODULES_DIR / f"{name}.iml"
    if iml.exists():
        try:
            tree = read_xml(iml)
            root = tree.getroot()
            comp = root.find("./component[@name='NewModuleRootManager']")
            if comp is None:
                comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
            content = comp.find("content")
            if content is None:
                content = ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
            else:
                content.set("url", "file://$PROJECT_DIR$")
            pretty_write_xml(tree, iml)
        except ET.ParseError:
            pass
        return iml

    m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
    ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
    ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
    pretty_write_xml(m, iml)
    debug(f"Root module IML created: {iml}")
    return iml

# ----------------------------- modules.xml / .iml for apps ----------------------------- #
def ensure_app_module_iml(app_dir: Path) -> Path:
    app = app_dir.name
    iml_path = MODULES_DIR / f"{app}.iml"
    if iml_path.exists():
        try:
            tree = read_xml(iml_path)
            root = tree.getroot()
            comp = root.find("./component[@name='NewModuleRootManager']")
            if comp is None:
                comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
            content = comp.find("content")
            if content is None:
                content = ET.SubElement(comp, "content", {"url": app_rel_content_url(app_dir)})
            else:
                content.set("url", app_rel_content_url(app_dir))
            pretty_write_xml(tree, iml_path)
        except ET.ParseError:
            pass
        return iml_path

    m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
    ET.SubElement(comp, "content", {"url": app_rel_content_url(app_dir)})
    ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
    pretty_write_xml(m, iml_path)
    debug(f"IML created: {iml_path}")
    return iml_path

def set_module_sdk(iml_path: Path, sdk_name: str) -> None:
    tree = read_xml(iml_path)
    root = tree.getroot()
    comp = root.find("./component[@name='NewModuleRootManager']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
    for oe in list(comp.findall("orderEntry")):
        if oe.get("type") in {"inheritedJdk", "jdk"}:
            comp.remove(oe)
    ET.SubElement(comp, "orderEntry", {"type": "jdk", "jdkName": sdk_name, "jdkType": SDK_TYPE})
    pretty_write_xml(tree, iml_path)

def rebuild_modules_xml_from_disk() -> None:
    """List exactly the .iml files present, using $PROJECT_DIR$ macros."""
    imls = sorted(p for p in MODULES_DIR.glob("*.iml") if p.exists() and p.name != "module.iml")
    project = ET.Element("project", {"version": "4"})
    comp = ET.SubElement(project, "component", {"name": "ProjectModuleManager"})
    mods = ET.SubElement(comp, "modules")
    for p in imls:
        ET.SubElement(mods, "module", {"fileurl": as_project_url(p), "filepath": as_project_macro(p)})
    tree = ET.ElementTree(project)
    pretty_write_xml(tree, IDEA / "modules.xml")
    debug(f"modules.xml rebuilt with {len(imls)} modules (macro paths)")

# ----------------------------- JetBrains SDK registry ----------------------------- #
def _jb_base_dirs() -> List[Path]:
    home = Path.home()
    bases: List[Path] = []
    if sys.platform == "darwin":
        bases.append(home / "Library" / "Application Support" / "JetBrains")
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            bases.append(Path(appdata) / "JetBrains")
    else:
        bases.append(home / ".config" / "JetBrains")
    return [b for b in bases if b.exists()]

def _find_jdk_tables() -> List[Path]:
    tables: List[Path] = []
    for base in _jb_base_dirs():
        for product in ("PyCharm*", "PyCharmCE*"):
            for candidate in base.glob(product):
                p = candidate / "options" / "jdk.table.xml"
                if p.exists():
                    tables.append(p)
    return tables

def _load_or_init_jdk_table(path: Path) -> ET.ElementTree:
    if path.exists():
        try:
            return read_xml(path)
        except ET.ParseError:
            pass
    root = ET.Element("application")
    ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
    return ET.ElementTree(root)

def _ensure_jdk_entry(tree: ET.ElementTree, name: str, home: str) -> bool:
    root = tree.getroot()
    comp = root.find("./component[@name='ProjectJdkTable']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
    for jdk in comp.findall("jdk"):
        nm = jdk.find("./name")
        if nm is not None and nm.get("value") == name:
            hp = jdk.find("./homePath")
            if hp is None:
                ET.SubElement(jdk, "homePath", {"value": home})
                return True
            if hp.get("value") != home:
                hp.set("value", home)
                return True
            return False
    jdk = ET.SubElement(comp, "jdk", {"version": "2"})
    ET.SubElement(jdk, "name", {"value": name})
    ET.SubElement(jdk, "type", {"value": SDK_TYPE})
    ET.SubElement(jdk, "homePath", {"value": home})
    return True

def register_sdk_globally(name: str, home_python: Path) -> None:
    modified_any = False
    for table in _find_jdk_tables():
        tree = _load_or_init_jdk_table(table)
        if _ensure_jdk_entry(tree, name, str(home_python)):
            pretty_write_xml(tree, table)
            modified_any = True
            debug(f"Registered SDK '{name}' at {home_python} in {table}")
    if not modified_any:
        debug("No JetBrains jdk.table.xml found; SDKs appear after PyCharm creates it (open PyCharm once).")

# ----------------------------- project SDK (misc.xml) ----------------------------- #
def set_project_sdk(name: str, sdk_type: str = SDK_TYPE) -> None:
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
    prm.set("project-jdk-name", name)
    prm.set("project-jdk-type", sdk_type)
    pretty_write_xml(tree, misc)
    debug(f"Project SDK set to '{name}' in misc.xml")

# ----------------------------- main ----------------------------- #
def main() -> int:
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

    # Make the project show up as "Project: agilab" in Settings
    ensure_project_name(PROJECT_NAME)

    # Root project SDK -> uv (agilab) bound to ROOT/.venv python
    root_py = venv_python_for(ROOT)
    if root_py:
        register_sdk_globally(PROJECT_SDK_NAME, root_py)
        set_project_sdk(PROJECT_SDK_NAME, SDK_TYPE)
    else:
        debug("Root .venv python not found; run `uv venv` at repo root if you want a project SDK.")

    # Ensure a root module that points to $PROJECT_DIR$ (appears in Project Structure)
    ensure_root_module_iml(PROJECT_NAME)

    # Discover apps & create/patch modules
    if not APPS_DIR.exists():
        debug(f"Apps directory not found: {APPS_DIR}")
        return 1

    apps = sorted(p for p in APPS_DIR.iterdir() if p.is_dir() and p.name.endswith("_project"))
    if not apps:
        debug("No *_project apps found.")

    for app_dir in apps:
        app = app_dir.name
        iml_path = ensure_app_module_iml(app_dir)

        py = venv_python_for(app_dir)
        if not py:
            debug(f"{app}: .venv python not found, leaving module on inheritedJdk.")
        else:
            base = app[:-8] if app.endswith("_project") else app
            sdk_name = f"uv ({base})"
            register_sdk_globally(sdk_name, py)
            set_module_sdk(iml_path, sdk_name)
            debug(f"{app}: module SDK set to '{sdk_name}' ({py})")

    # Rebuild modules.xml from actual .iml files using $PROJECT_DIR$ macros
    rebuild_modules_xml_from_disk()

    # Generate run configurations per app
    if GEN_SCRIPT.exists():
        for app_dir in apps:
            app = app_dir.name
            module_name = app[:-8] if app.endswith("_project") else app
            debug(f"Generating run configs for module '{module_name}' via {GEN_SCRIPT.name}...")
            subprocess.run([sys.executable, str(GEN_SCRIPT), module_name], check=True, cwd=str(ROOT))
    else:
        debug(f"Missing {GEN_SCRIPT}; skipping run configuration generation.")

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
