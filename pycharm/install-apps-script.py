#!/usr/bin/env python3
"""
Attach all `.venv` projects into ONE PyCharm workspace (in CWD), create per-app
modules, then delegate run configuration generation to gen-app-script.py
(per app, with module-name = app dir name without '_project').

HARD GUARANTEES:
- No writes inside subproject `.idea/` (only root .idea/*).
- No reliance on global SDK registration (gen-app-script handles run configs).
- No installers invoked.

What this DOES:
- Creates/updates .idea/modules/<app>.iml for every *_project in src/agilab/apps
- Updates .idea/modules.xml to include all those modules
- Calls gen-app-script.py <module_name> for each app (module_name = app[:-8])
"""

from __future__ import annotations
import sys
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# ----------------------------- constants/paths ----------------------------- #

ROOT = Path.cwd()
IDEA = ROOT / ".idea"
MODULES_DIR = IDEA / "modules"
RUNCFG_DIR = IDEA / "runConfigurations"  # not written here; gen-app-script.py does it
APPS_DIR = ROOT / "src" / "agilab" / "apps"
GEN_SCRIPT = ROOT / "gen-app-script.py"

# ----------------------------- helpers ----------------------------- #

def debug(msg: str) -> None:
    print(f"[install-apps] {msg}")

def ensure_dirs() -> None:
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

def venv_python_for(project_dir: Path) -> Optional[Path]:
    """Return the project's .venv python, if present."""
    candidates = [
        project_dir / ".venv" / "bin" / "python3",        # unix/mac
        project_dir / ".venv" / "bin" / "python",         # unix/mac alt
        project_dir / ".venv" / "Scripts" / "python.exe", # windows
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None

def write_xml(tree: ET.ElementTree, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dest), encoding="UTF-8", xml_declaration=True)

def ensure_module(app: str, content_root: Path) -> None:
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

    # Load or create modules.xml
    if modules_xml.exists():
        tree = ET.parse(modules_xml)
        root = tree.getroot()
    else:
        root = ET.Element("project", {"version": "4"})
        ET.SubElement(root, "component", {"name": "ProjectModuleManager"})
        comp = root.find("./component[@name='ProjectModuleManager']")
        ET.SubElement(comp, "modules")
        tree = ET.ElementTree(root)

    # Append module entry if not present
    comp = root.find("./component[@name='ProjectModuleManager']/modules")
    existing = [m.get("fileurl") for m in comp.findall("module")]
    fileurl = f"file://{iml_path}"
    if fileurl not in existing:
        ET.SubElement(comp, "module", {"fileurl": fileurl, "filepath": str(iml_path)})
        write_xml(tree, modules_xml)
        debug(f"modules.xml updated with {fileurl}")

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

    if not GEN_SCRIPT.exists():
        debug(f"Missing {GEN_SCRIPT}, cannot generate run configurations.")
        return 1

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
        debug(f"Generating run configs for module '{module_name}' via {GEN_SCRIPT.name}...")
        # Use the same interpreter that runs this script; swap to 'uv run python' if you prefer.
        subprocess.run(
            [sys.executable, str(GEN_SCRIPT), module_name],
            check=True,
            cwd=str(ROOT),
        )

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
