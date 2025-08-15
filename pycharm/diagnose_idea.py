#!/usr/bin/env python3
from __future__ import annotations
import sys, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path.cwd()
IDEA = ROOT / ".idea"
MODULES_DIR = IDEA / "modules"

def check_xml(path: Path):
    try:
        tree = ET.parse(str(path))
        return True, tree.getroot().tag
    except Exception as e:
        return False, str(e)

def main():
    if not IDEA.exists():
        print("[diag] No .idea directory found"); return 1
    bad = []
    for p in sorted(IDEA.rglob("*.xml")):
        ok, info = check_xml(p)
        print(f"[diag] {p.relative_to(ROOT)}: {'OK' if ok else 'BROKEN'} {'' if ok else '→ ' + info}")
        if not ok: bad.append(p)

    # Extra structure checks
    for iml in sorted(MODULES_DIR.glob("*.iml")):
        try:
            r = ET.parse(iml).getroot()
            if r.tag != "module":
                print(f"[diag] {iml}: root tag != <module>")
            comp = r.find("./component[@name='NewModuleRootManager']")
            if comp is None:
                print(f"[diag] {iml}: missing NewModuleRootManager")
            # content url
            c = comp.find("content") if comp is not None else None
            if c is None or "url" not in c.attrib:
                print(f"[diag] {iml}: missing <content url=…>")
        except Exception as e:
            print(f"[diag] {iml}: PARSE ERROR → {e}")
            bad.append(iml)

    if bad:
        print("\n[diag] BROKEN FILES:")
        for p in bad: print(" -", p)
        return 2
    print("\n[diag] All XMLs parse. If the project still won’t open, it’s likely stale caches.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

