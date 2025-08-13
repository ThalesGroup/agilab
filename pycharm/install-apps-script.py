#!/usr/bin/env python3
"""
Minimal: attach all `.venv` projects under CWD into one PyCharm workspace
and register each `.venv` as a Python SDK (no CLI options, no IDE launch).

Defaults kept:
- root = workspace = Path.cwd()
- recurse without depth limit
- no excludes
- SDK name template: "uv ({name})"
- Auto-detect PyCharm config dir and merge into options/jdk.table.xml
"""

from __future__ import annotations
import os
import re
import platform
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

# ----------------------------- tiny helpers ----------------------------- #

def debug(msg: str):
    print(f"[attach] {msg}")

def prettify_xml(elem: ET.Element) -> str:
    rough = ET.tostring(elem, encoding="utf-8")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

def path_depth(base: Path, p: Path) -> int:
    try:
        rel = p.relative_to(base)
        return len(rel.parts)
    except Exception:
        return 0

# --------------------------- project scanning --------------------------- #

def find_projects(root: Path) -> list[Path]:
    projects = []
    for dirpath, dirnames, _files in os.walk(root):
        d = Path(dirpath)
        if (d / ".venv").is_dir():
            projects.append(d)
            dirnames[:] = []  # don't dive inside a found project
    return sorted(set(projects))

def find_venv_python(proj: Path) -> Path | None:
    for p in (
        proj / ".venv" / "bin" / "python3",
        proj / ".venv" / "bin" / "python",
        proj / ".venv" / "Scripts" / "python.exe",  # Windows
    ):
        if p.exists():
            return p.resolve()
    return None

def get_python_version_str(py: Path) -> str | None:
    try:
        out = subprocess.check_output(
            [str(py), "-c", "import sys;print('Python %d.%d.%d' % sys.version_info[:3])"],
            text=True
        )
        return out.strip()
    except Exception:
        return None

def make_safe_name(root: Path, proj: Path) -> str:
    try:
        rel = proj.relative_to(root)
        name = "-".join(rel.parts)
    except Exception:
        name = proj.name
    return re.sub(r"[^A-Za-z0-9_.\-]+", "_", name) or "module"

# ------------------------ workspace + modules (.idea) --------------------- #

def ensure_workspace(workspace: Path) -> None:
    (workspace / ".idea").mkdir(parents=True, exist_ok=True)
    (workspace / ".idea" / ".name").write_text(workspace.name, encoding="utf-8")

def write_modules_xml(workspace: Path, modules: list[tuple[str, Path]]) -> None:
    idea = workspace / ".idea"
    mods_dir = idea / "modules"
    mods_dir.mkdir(parents=True, exist_ok=True)

    root = ET.Element("project", {"version": "4"})
    comp = ET.SubElement(root, "component", {"name": "ProjectModuleManager"})
    mods = ET.SubElement(comp, "modules")

    for safe_name, proj in modules:
        iml_rel = f".idea/modules/{safe_name}.iml"
        ET.SubElement(
            mods, "module",
            {"fileurl": f"file://$PROJECT_DIR$/{iml_rel}",
             "filepath": f"$PROJECT_DIR$/{iml_rel}"}
        )

    (idea / "modules.xml").write_text(prettify_xml(root), encoding="utf-8")
    debug(f"Wrote {(idea / 'modules.xml')}")

def write_iml(workspace: Path, safe_name: str, project_dir: Path, sdk_name: str) -> None:
    idea = workspace / ".idea"
    mods_dir = idea / "modules"
    mods_dir.mkdir(parents=True, exist_ok=True)
    iml_path = mods_dir / f"{safe_name}.iml"

    mod = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(mod, "component", {"name": "NewModuleRootManager"})
    content = ET.SubElement(comp, "content", {"url": f"file://{project_dir}"})

    for excl in (".venv", ".git", "__pycache__", "build", "dist", ".mypy_cache", ".pytest_cache", ".ruff_cache"):
        ET.SubElement(content, "excludeFolder", {"url": f"file://{project_dir / excl}"})

    ET.SubElement(comp, "orderEntry", {"type": "jdk", "jdkType": "Python SDK", "jdkName": sdk_name})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})

    iml_path.write_text(prettify_xml(mod), encoding="utf-8")
    debug(f"Wrote {iml_path}")

# ----------------------- PyCharm config (SDK table) ----------------------- #

def jetbrains_config_candidates() -> list[Path]:
    system = platform.system().lower()
    home = Path.home()
    cands: list[Path] = []

    if system == "darwin":
        for base in [home / "Library" / "Application Support" / "JetBrains",
                     home / "Library" / "Preferences"]:
            if base.exists():
                cands += [p for p in base.glob("PyCharm*")]
    elif system == "linux":
        for base in [home / ".config" / "JetBrains",
                     home / ".local" / "share" / "JetBrains"]:
            if base.exists():
                cands += [p for p in base.glob("PyCharm*")]
    else:  # Windows
        for env in ("APPDATA", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                b = Path(root) / "JetBrains"
                if b.exists():
                    cands += [p for p in b.glob("PyCharm*")]

    return sorted({p for p in cands if (p / "options").exists()})

def choose_best_config_dir(cands: list[Path]) -> Path | None:
    if not cands:
        return None
    best, best_m = None, -1.0
    for c in cands:
        try:
            m = (c / "options").stat().st_mtime
        except Exception:
            m = 0.0
        if m > best_m:
            best, best_m = c, m
    return best or cands[-1]

def load_or_create_jdk_table(jdk_file: Path) -> ET.ElementTree:
    if jdk_file.exists():
        try:
            return ET.parse(jdk_file)
        except Exception:
            pass
    root = ET.Element("application")
    ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
    return ET.ElementTree(root)

def get_or_create_component(root: ET.Element, name: str) -> ET.Element:
    for c in root.findall("component"):
        if c.attrib.get("name") == name:
            return c
    return ET.SubElement(root, "component", {"name": name})

def find_jdk(component: ET.Element, sdk_name: str) -> ET.Element | None:
    for j in component.findall("jdk"):
        n = j.find("name")
        if n is not None and n.attrib.get("value") == sdk_name:
            return j
    return None

def ensure_python_sdk(component: ET.Element, *, sdk_name: str, python_path: Path, version: str | None) -> None:
    j = find_jdk(component, sdk_name)
    if j is None:
        j = ET.SubElement(component, "jdk", {"version": "2"})
        ET.SubElement(j, "name", {"value": sdk_name})
        ET.SubElement(j, "type", {"value": "Python SDK"})
        ET.SubElement(j, "homePath", {"value": str(python_path)})
        if version:
            ET.SubElement(j, "version", {"value": version})
    else:
        hp = j.find("homePath")
        if hp is None:
            ET.SubElement(j, "homePath", {"value": str(python_path)})
        else:
            hp.attrib["value"] = str(python_path)
        if version:
            ver = j.find("version")
            if ver is None:
                ET.SubElement(j, "version", {"value": version})
            else:
                ver.attrib["value"] = version

def backup_file(p: Path) -> None:
    if p.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        p.with_suffix(p.suffix + f".bak-{ts}").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        debug(f"Backed up {p}")

def write_pretty_xml(tree: ET.ElementTree, dest: Path) -> None:
    xml_bytes = ET.tostring(tree.getroot(), encoding="utf-8")
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(pretty, encoding="utf-8")
    debug(f"Wrote {dest}")

# ---------------------------------- main ---------------------------------- #

def main() -> int:
    root = Path.cwd().resolve()
    workspace = root  # default: workspace at root
    sdk_name_tpl = "uv ({name})"

    debug(f"Root/workspace : {workspace}")

    projects = find_projects(root)
    if not projects:
        print("No projects with `.venv` found.", flush=True)
        return 2

    # Build module + SDK specs
    modules = []         # (safe_name, project_dir, sdk_name)
    sdk_specs = []       # (sdk_name, python_path, version)
    for proj in projects:
        safe = make_safe_name(root, proj)
        py = find_venv_python(proj)
        if not py:
            debug(f"WARNING: {proj} has no python in .venv; skipping.")
            continue
        ver = get_python_version_str(py)
        sdk_name = sdk_name_tpl.format(name=safe)
        modules.append((safe, proj, sdk_name))
        sdk_specs.append((sdk_name, py, ver))

    if not modules:
        print("Projects found, but none had a usable `.venv` python.", flush=True)
        return 3

    # Create workspace + modules
    ensure_workspace(workspace)
    write_modules_xml(workspace, [(safe, proj) for (safe, proj, _sdk) in modules])
    for safe, proj, sdk in modules:
        write_iml(workspace, safe, proj, sdk)

    # Detect PyCharm config dir
    config_dir = choose_best_config_dir(jetbrains_config_candidates())
    if not config_dir:
        debug("No JetBrains PyCharm config directory found. (Open PyCharm once, then re-run.)")
        return 4

    jdk_file = config_dir / "options" / "jdk.table.xml"
    debug(f"Using config dir: {config_dir}")

    # Merge SDKs into jdk.table.xml
    tree = load_or_create_jdk_table(jdk_file)
    comp = get_or_create_component(tree.getroot(), "ProjectJdkTable")
    for sdk_name, py, ver in sdk_specs:
        ensure_python_sdk(comp, sdk_name=sdk_name, python_path=py, version=ver)

    backup_file(jdk_file)
    write_pretty_xml(tree, jdk_file)

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
