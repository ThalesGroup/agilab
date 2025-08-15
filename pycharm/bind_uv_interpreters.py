#!/usr/bin/env python3
from __future__ import annotations
import os, sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, List

ROOT = Path.cwd()
IDEA = ROOT / ".idea"
MODULES_DIR = IDEA / "modules"
SDK_TYPE = "Python SDK"

def dbg(msg: str): print(f"[bind] {msg}")

def read_xml(p: Path) -> ET.ElementTree:
    return ET.parse(str(p))

def write_xml(tree: ET.ElementTree, p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        tree.write(f, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)

def venv_python_for(dir_: Path) -> Optional[Path]:
    for c in (
        dir_ / ".venv" / "bin" / "python3",
        dir_ / ".venv" / "bin" / "python",
        dir_ / ".venv" / "Scripts" / "python.exe",
    ):
        if c.exists(): return c.resolve()
    return None

# ---------- JetBrains jdk.table.xml helpers ----------
def _jb_bases() -> List[Path]:
    home = Path.home()
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "JetBrains"]
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / "JetBrains"] if appdata else []
    else:
        return [home / ".config" / "JetBrains"]

def _find_tables() -> List[Path]:
    out: List[Path] = []
    for base in _jb_bases():
        if not base.exists(): continue
        for prod in ("PyCharm*", "PyCharmCE*"):
            for p in base.glob(prod):
                options = p / "options"
                if options.exists():
                    out.append(options / "jdk.table.xml")
    return out

def _ensure_component(root: ET.Element) -> ET.Element:
    comp = root.find("./component[@name='ProjectJdkTable']")
    return comp if comp is not None else ET.SubElement(root, "component", {"name":"ProjectJdkTable"})

def _ensure_roots_additional(jdk: ET.Element):
    if jdk.find("roots") is None: ET.SubElement(jdk, "roots")
    if jdk.find("additional") is None: ET.SubElement(jdk, "additional")

def _load_or_init_table(p: Path) -> ET.ElementTree:
    if p.exists():
        try: return read_xml(p)
        except ET.ParseError: pass
    root = ET.Element("application")
    ET.SubElement(root, "component", {"name":"ProjectJdkTable"})
    return ET.ElementTree(root)

def _find_jdk(comp: ET.Element, name: str) -> Optional[ET.Element]:
    for j in comp.findall("jdk"):
        nm = j.find("name")
        if nm is not None and nm.get("value") == name:
            return j
    return None

def upsert_sdk(sdk_name: str, home: Path):
    changed_any = False
    for table in _find_tables():
        tree = _load_or_init_table(table)
        root = tree.getroot()
        comp = _ensure_component(root)
        jdk = _find_jdk(comp, sdk_name)
        if jdk is None:
            jdk = ET.SubElement(comp, "jdk", {"version": "2"})
            ET.SubElement(jdk, "name", {"value": sdk_name})
            ET.SubElement(jdk, "type", {"value": SDK_TYPE})
            ET.SubElement(jdk, "homePath", {"value": str(home)})
            _ensure_roots_additional(jdk)
            write_xml(tree, table)
            dbg(f"SDK created '{sdk_name}' -> {home} in {table}")
            changed_any = True
        else:
            # ensure children and home path
            type_el = jdk.find("type") or ET.SubElement(jdk, "type", {"value": SDK_TYPE})
            type_el.set("value", SDK_TYPE)
            home_el = jdk.find("homePath") or ET.SubElement(jdk, "homePath", {"value": str(home)})
            if home_el.get("value") != str(home):
                home_el.set("value", str(home))
                changed_any = True
            _ensure_roots_additional(jdk)
            if changed_any:
                write_xml(tree, table)
                dbg(f"SDK updated '{sdk_name}' -> {home} in {table}")
    if not changed_any:
        dbg(f"SDK '{sdk_name}' already present with correct home")

# ---------- project (misc.xml) ----------
def set_project_sdk(name: str):
    misc = IDEA / "misc.xml"
    if misc.exists():
        tree = read_xml(misc)
        root = tree.getroot()
    else:
        root = ET.Element("project", {"version":"4"})
        tree = ET.ElementTree(root)
    prm = root.find("./component[@name='ProjectRootManager']") \
          or ET.SubElement(root, "component", {"name":"ProjectRootManager", "version":"2"})
    prm.set("version", "2")
    prm.set("project-jdk-name", name)
    prm.set("project-jdk-type", SDK_TYPE)
    write_xml(tree, misc)
    dbg(f"misc.xml -> project-jdk-name='{name}'")

# ---------- modules ----------
def set_module_sdk(iml: Path, sdk_name: str):
    tree = read_xml(iml)
    root = tree.getroot()
    comp = root.find("./component[@name='NewModuleRootManager']") \
          or ET.SubElement(root, "component", {"name":"NewModuleRootManager"})
    # drop inherited / old jdk entries
    for oe in list(comp.findall("orderEntry")):
        if oe.get("type") in {"inheritedJdk", "jdk"}:
            comp.remove(oe)
    ET.SubElement(comp, "orderEntry", {"type":"jdk", "jdkName":sdk_name, "jdkType":SDK_TYPE})
    write_xml(tree, iml)
    dbg(f"{iml.name}: jdkName='{sdk_name}'")

def main() -> int:
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Root SDK = uv (agilab)
    root_py = venv_python_for(ROOT)
    if root_py:
        upsert_sdk(f"uv ({ROOT.name})", root_py)
        set_project_sdk(f"uv ({ROOT.name})")
    else:
        dbg("No ROOT/.venv python found; project SDK will not be set.")

    # 2) Per-module SDKs
    for iml in sorted(MODULES_DIR.glob("*.iml")):
        stem = iml.stem  # keep exact stem (e.g., flight_project)
        # try to locate app dir: src/agilab/apps/<stem>
        app_dir = ROOT / "src" / "agilab" / "apps" / stem
        py = venv_python_for(app_dir) or root_py
        if py is None:
            dbg(f"{stem}: no .venv found (and no root venv) -> leave inheritedJdk")
            continue
        sdk_name = f"uv ({stem})"
        upsert_sdk(sdk_name, py)
        set_module_sdk(iml, sdk_name)

    print("[bind] Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
