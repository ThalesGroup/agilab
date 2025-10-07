#!/usr/bin/env python3
import xml.etree.ElementTree as ET
from pathlib import Path
import sys, os

def jb_base_dirs():
    home = Path.home()
    if sys.platform == "darwin":
        yield home / "Library" / "Application Support" / "JetBrains"
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata: yield Path(appdata) / "JetBrains"
    else:
        yield home / ".config" / "JetBrains"

def find_tables():
    for base in jb_base_dirs():
        if not base.exists(): continue
        for prod in ("PyCharm*", "PyCharmCE*"):
            for candidate in base.glob(prod):
                p = candidate / "options" / "jdk.table.xml"
                if p.exists():
                    yield p

def ensure_component(root):
    comp = root.find("./component[@name='ProjectJdkTable']")
    return comp if comp is not None else ET.SubElement(root, "component", {"name":"ProjectJdkTable"})

def main():
    any_changed = False
    for xml_path in find_tables():
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError:
            # start fresh minimal structure if corrupted
            root = ET.Element("application")
            ET.SubElement(root, "component", {"name":"ProjectJdkTable"})
            tree = ET.ElementTree(root)
        root = tree.getroot()
        comp = ensure_component(root)
        changed = False
        for jdk in comp.findall("jdk"):
            # we only care about Python SDKs
            t = jdk.find("type")
            if t is not None and t.get("value") != "Python SDK":
                continue
            if jdk.find("roots") is None:
                ET.SubElement(jdk, "roots")
                changed = True
            if jdk.find("additional") is None:
                ET.SubElement(jdk, "additional")
                changed = True
        if changed:
            with open(xml_path, "wb") as f:
                tree.write(f, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)
            print(f"[fix] Added <roots/>/<additional/> where missing in {xml_path}")
            any_changed = True
        else:
            print(f"[ok] {xml_path} already has <roots/> on Python SDKs")
    if not any_changed:
        print("[done] No changes needed.")

if __name__ == "__main__":
    main()

