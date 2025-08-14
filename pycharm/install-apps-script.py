#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, List
import xml.etree.ElementTree as ET

# ----------------------------- paths / constants ----------------------------- #
ROOT = Path.cwd()

def find_idea_dir(root: Path) -> Path:
    for name in (".idea", "idea"):
        d = root / name
        if d.exists():
            return d
    return root / ".idea"

IDEA = find_idea_dir(ROOT)
MODULES_DIR = IDEA / "modules"
RUNCFG_DIR = IDEA / "runConfigurations"
APPS_DIR = ROOT / "src" / "agilab" / "apps"
GEN_SCRIPT = (ROOT / "pycharm" / "gen-app-script.py") if (ROOT / "pycharm" / "gen-app-script.py").exists() else (ROOT / "gen-app-script.py")

PROJECT_NAME = "agilab"           # shows as "Project: agilab" in Settings
SDK_TYPE = "Python SDK"
PROJECT_SDK_NAME = "uv (agilab)"  # root project interpreter name

# ----------------------------- utils ----------------------------- #
def debug(msg: str) -> None:
    print(f"[install-apps] {msg}")

def _write_xml(elem_or_tree, dest: Path) -> None:
    """Compact XML write (no pretty print), LF-only, binary to avoid bytes/str issue."""
    tree = elem_or_tree if isinstance(elem_or_tree, ET.ElementTree) else ET.ElementTree(elem_or_tree)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:  # binary mode (ElementTree writes bytes when encoding is set)
        tree.write(f, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)

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

def _rel_from_root(path: Path) -> Optional[Path]:
    try:
        return path.relative_to(ROOT)  # DO NOT .resolve()
    except ValueError:
        return None

def app_rel_content_url(app_dir: Path) -> str:
    rel = _rel_from_root(app_dir)
    if rel is not None:
        return f"file://$PROJECT_DIR$/{rel.as_posix()}"
    return f"file://{app_dir.resolve().as_posix()}"

# ----------------------------- root project name & module ----------------------------- #
def ensure_project_name(name: str) -> None:
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
                ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
            else:
                content.set("url", "file://$PROJECT_DIR$")
            _write_xml(tree, iml)
        except ET.ParseError:
            pass
        return iml

    m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
    ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
    ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
    _write_xml(m, iml)
    debug(f"Root module IML created: {iml}")
    return iml

# ----------------------------- modules.xml / .iml for apps ----------------------------- #
def ensure_app_module_iml(app_dir: Path) -> Path:
    app = app_dir.name  # keeps *_project for the IML filename
    iml_path = MODULES_DIR / f"{app}.iml"
    if iml_path.exists():
        try:
            tree = read_xml(iml_path)
            root = tree.getroot()
            comp = root.find("./component[@name='NewModuleRootManager']")
            if comp is None:
                comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
            content = comp.find("content")
            url = app_rel_content_url(app_dir)
            if content is None:
                ET.SubElement(comp, "content", {"url": url})
            else:
                content.set("url", url)
            _write_xml(tree, iml_path)
        except ET.ParseError:
            pass
        return iml_path

    m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
    ET.SubElement(comp, "content", {"url": app_rel_content_url(app_dir)})
    ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
    _write_xml(m, iml_path)
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
    _write_xml(tree, iml_path)

def rebuild_modules_xml_from_disk() -> None:
    """Write modules.xml from every IML in .idea/modules (root + subprojects), LF endings."""
    imls = sorted(MODULES_DIR.glob("*.iml"))
    with open(IDEA / "modules.xml", "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<project version="4">\n')
        f.write('  <component name="ProjectModuleManager">\n')
        f.write('    <modules>\n')
        for p in imls:
            # include root and all subprojects
            f.write(f'      <module fileurl="{as_project_url(p)}" filepath="{as_project_macro(p)}"/>\n')
        f.write('    </modules>\n')
        f.write('  </component>\n')
        f.write('</project>\n')
    debug(f"modules.xml rebuilt with {len(imls)} module(s)")

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

def _table_upsert_batch(name_to_home: dict[str, str]) -> None:
    """Remove stale entries by name, then re-insert all with current homePath. One write per table."""
    tables = []
    for tbl in _find_jdk_tables():
        tree = _load_or_init_jdk_table(tbl)
        root = tree.getroot()
        comp = root.find("./component[@name='ProjectJdkTable']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
        tables.append((tbl, tree, comp))

    if not tables:
        debug("No JetBrains jdk.table.xml found; open PyCharm once so it creates it.")
        return

    for path, tree, comp in tables:
        wanted = set(name_to_home.keys())
        for jdk in list(comp.findall("jdk")):
            nm = jdk.find("name")
            if nm is not None and nm.get("value") in wanted:
                comp.remove(jdk)
        for name, home in name_to_home.items():
            j = ET.SubElement(comp, "jdk", {"version": "2"})
            ET.SubElement(j, "name", {"value": name})
            ET.SubElement(j, "type", {"value": SDK_TYPE})
            ET.SubElement(j, "homePath", {"value": home})
        _write_xml(tree, path)
        debug(f"Updated {path} with {len(name_to_home)} SDK(s)")

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
    prm.set("version", "2")
    prm.set("project-jdk-name", name)
    prm.set("project-jdk-type", sdk_type)
    _write_xml(tree, misc)
    debug(f"Project SDK set to '{name}' in misc.xml")

# ---------- subprojects → unique SDKs, IMLs, modules.xml, runConfigs ----------
def _subprojects() -> list[Path]:
    if not APPS_DIR.exists():
        return []
    return sorted(p for p in APPS_DIR.iterdir() if p.is_dir() and p.name.endswith("_project"))

def _base(app_dir: Path) -> str:
    n = app_dir.name
    return n[:-8] if n.endswith("_project") else n

def _sdk_name(base: str) -> str:
    return f"uv ({base})"

def attach_all_subprojects() -> None:
    apps = _subprojects()
    if not apps:
        debug("No *_project apps found.")

    # collect (base -> venv python) for those that have a venv
    pairs: list[tuple[str, Path]] = []
    for a in apps:
        py = venv_python_for(a)
        if py:
            pairs.append((_base(a), py))
        else:
            debug(f"{a.name}: missing .venv python → leaving inheritedJdk")

    # batch update SDK registry
    name_to_home = { _sdk_name(b): str(py) for (b, py) in pairs }
    if name_to_home:
        _table_upsert_batch(name_to_home)

    # ensure each subproject has an IML and bind SDK if available
    for a in apps:
        b = _base(a)
        iml = ensure_app_module_iml(a)
        sdk = _sdk_name(b)
        if sdk in name_to_home:
            set_module_sdk(iml, sdk)

    # rebuild modules.xml from all IMLs (root + subprojects)
    rebuild_modules_xml_from_disk()

    # generate run configs with matching base names
    if GEN_SCRIPT.exists():
        for a in apps:
            b = _base(a)
            debug(f"Generating run configs for '{b}' via {GEN_SCRIPT.name}...")
            subprocess.run([sys.executable, str(GEN_SCRIPT), b], check=True, cwd=str(ROOT))
    else:
        debug(f"Missing {GEN_SCRIPT}; skipping run configuration generation.")

# ----------------------------- main ----------------------------- #
def main() -> int:
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

    ensure_project_name(PROJECT_NAME)
    ensure_root_module_iml(PROJECT_NAME)

    # root project SDK -> uv (agilab)
    root_py = venv_python_for(ROOT)
    if root_py:
        _table_upsert_batch({PROJECT_SDK_NAME: str(root_py)})
        set_project_sdk(PROJECT_SDK_NAME, SDK_TYPE)
    else:
        debug("Root .venv python not found; run `uv venv` at repo root if you want a project SDK.")

    # attach subprojects to the root project
    attach_all_subprojects()

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
