#!/usr/bin/env python3
import xml.etree.ElementTree as ET
from pathlib import Path
import sys
import os

def _jb_base_dirs():
    home = Path.home()
    bases = []
    if sys.platform == "darwin":
        bases.append(home / "Library" / "Application Support" / "JetBrains")
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            bases.append(Path(appdata) / "JetBrains")
    else:
        bases.append(home / ".config" / "JetBrains")
    return [b for b in bases if b.exists()]

def _find_jdk_tables():
    tables = []
    for base in _jb_base_dirs():
        for product in ("PyCharm*", "PyCharmCE*"):
            for candidate in base.glob(product):
                p = candidate / "options" / "jdk.table.xml"
                if p.exists():
                    tables.append(p)
    return tables

def ok_text(s): return (s or "").strip()

def load_or_init(path: Path):
    if path.exists():
        try:
            return ET.parse(path)
        except ET.ParseError:
            pass
    root = ET.Element("application")
    ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
    return ET.ElementTree(root)

def ensure_component(root: ET.Element):
    comp = root.find("./component[@name='ProjectJdkTable']")
    return comp if comp is not None else ET.SubElement(root, "component", {"name": "ProjectJdkTable"})

# --- MAIN ---
tables = _find_jdk_tables()
if not tables:
    print("No jdk.table.xml found. Open PyCharm once to initialize.")
    sys.exit(1)

for xml_path in tables:
    print(f"Repairing {xml_path}...")
    tree = load_or_init(xml_path)
    root = tree.getroot()
    comp = ensure_component(root)

    removed = 0
    for jdk in list(comp.findall("jdk")):
        name_el = jdk.find("name")
        type_el = jdk.find("type")
        home_el = jdk.find("homePath")
        name_ok = name_el is not None and ok_text(name_el.get("value"))
        type_ok = type_el is not None and ok_text(type_el.get("value")) == "Python SDK"
        home_ok = home_el is not None and ok_text(home_el.get("value"))
        if not (name_ok and type_ok and home_ok):
            comp.remove(jdk)
            removed += 1

    seen = {}
    for jdk in comp.findall("jdk"):
        nm = jdk.find("name").get("value")
        seen[nm] = jdk
    for jdk in list(comp.findall("jdk")):
        nm = jdk.find("name").get("value")
        if seen[nm] is not jdk:
            comp.remove(jdk)

    with open(xml_path, "wb") as f:
        tree.write(f, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)

    print(f"  Removed {removed} invalid entries, deduped by name.")

