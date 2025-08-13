#!/usr/bin/env python3
"""
Attach all `.venv` projects into ONE PyCharm workspace (in CWD) and register
each `.venv` as an IDE-level Python SDK.

HARD GUARANTEES (by design of main()):
- Per-project mutation: NO writes to subproject `.idea/misc.xml`, `.idea/workspace.xml`, or existing `.iml`.
- Run configurations: NONE written (no RunManager, no SDK_HOME pinning, no aggregated runs).
- Black plugin alignment: NOT touched.
- Installers: NOT invoked.

What main() DOES:
- Creates .idea/ (in CWD) with modules.xml and .idea/modules/<module>.iml
- Registers SDKs in <PyCharm config>/options/jdk.table.xml so interpreters appear in Settings.

Extra helper functions are provided (not used by main()):
- venv_python_for(), patch_sdk_home(), update_workspace_xml(), update_folders_xml(),
  add_folder_name_to_config(), parse_template(), patch_run_config_sdk_home(),
  generate_run_configs()  -> these let you add run-config aggregation later without
  touching subprojects, by writing only into the root .idea/runConfigurations.
"""

from __future__ import annotations
import os
import re
import platform
import subprocess
import tempfile
import filecmp
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from typing import Optional

# ----------------------------- helpers ----------------------------- #

def debug(msg: str):
    print(f"[attach] {msg}")

def prettify_xml(elem: ET.Element) -> str:
    rough = ET.tostring(elem, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

def make_safe_name(root: Path, proj: Path) -> str:
    try:
        rel = proj.relative_to(root)
        name = "-".join(rel.parts)
    except Exception:
        name = proj.name
    return re.sub(r"[^A-Za-z0-9_.\\-]+", "_", name) or "module"

def _text_or_value(elem: ET.Element | None) -> str | None:
    if elem is None:
        return None
    return elem.attrib.get("value") or (elem.text.strip() if elem.text else None)

# --------------------------- discovery ---------------------------- #

def find_projects(root: Path) -> list[Path]:
    """Find folders that contain a `.venv` (skip descending into `.idea/`)."""
    projects = set()
    for dirpath, dirnames, _files in os.walk(root):
        d = Path(dirpath)
        # do not descend into .idea of any subproject
        dirnames[:] = [n for n in dirnames if n != ".idea"]
        if (d / ".venv").is_dir():
            projects.add(d)
            # don't descend inside a found project (avoid nested duplicates)
            dirnames[:] = []
    return sorted(projects)

def find_venv_python(proj: Path) -> Path | None:
    for p in (
        proj / ".venv" / "bin" / "python3",
        proj / ".venv" / "bin" / "python",
        proj / ".venv" / "Scripts" / "python.exe",
    ):
        if p.exists():
            return p.resolve()
    return None

# alias kept for compatibility with earlier snippets
def venv_python_for(project_dir: Path) -> Path | None:
    return find_venv_python(project_dir)

def get_python_version_str(py: Path) -> str | None:
    try:
        out = subprocess.check_output(
            [str(py), "-c", "import sys;print('Python %d.%d.%d' % sys.version_info[:3])"],
            text=True
        )
        return out.strip()
    except Exception:
        return None

# ---------------------- workspace + modules ---------------------- #

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
    """Create per-module .iml ONLY under the unified workspace. Never touch subprojects."""
    idea = workspace / ".idea"
    mods_dir = idea / "modules"
    mods_dir.mkdir(parents=True, exist_ok=True)
    iml_path = mods_dir / f"{safe_name}.iml"

    mod = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(mod, "component", {"name": "NewModuleRootManager"})
    content = ET.SubElement(comp, "content", {"url": f"file://{project_dir}"})

    # keep local junk out of indexing
    for excl in (".venv", ".git", "__pycache__", "build", "dist", ".mypy_cache", ".pytest_cache", ".ruff_cache"):
        ET.SubElement(content, "excludeFolder", {"url": f"file://{project_dir / excl}"})

    # explicit SDK (module-level); no inheritedJdk to make selection clear
    ET.SubElement(comp, "orderEntry", {"type": "jdk", "jdkType": "Python SDK", "jdkName": sdk_name})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})

    iml_path.write_text(prettify_xml(mod), encoding="utf-8")
    debug(f"Wrote {iml_path}")

# ------------------- PyCharm config (SDK table) ------------------ #

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
    # Prefer the highest version suffix like PyCharm2025.1
    def ver_key(p: Path):
        m = re.search(r"PyCharm(\d{4}\.\d+)", p.name)
        return tuple(map(float, m.group(1).split("."))) if m else (0.0,)
    cands_sorted = sorted(cands, key=ver_key, reverse=True)
    return cands_sorted[0]

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

def ensure_python_sdk(component: ET.Element, *, sdk_name: str, python_path: Path, version: str | None) -> None:
    # find by name (support both text or @value)
    target = None
    for j in component.findall("jdk"):
        n = j.find("name")
        if _text_or_value(n) == sdk_name:
            target = j; break
    if target is None:
        target = ET.SubElement(component, "jdk", {"version": "2"})
        ET.SubElement(target, "name", {"value": sdk_name})
        ET.SubElement(target, "type", {"value": "Python SDK"})
    # update home/version (support attribute or text)
    hp = target.find("homePath")
    if hp is None:
        ET.SubElement(target, "homePath", {"value": str(python_path)})
    else:
        if "value" in hp.attrib:
            hp.attrib["value"] = str(python_path)
        else:
            hp.text = str(python_path)
    if version:
        ver = target.find("version")
        if ver is None:
            ET.SubElement(target, "version", {"value": version})
        else:
            if "value" in ver.attrib:
                ver.attrib["value"] = version
            else:
                ver.text = version

def write_pretty_xml(tree: ET.ElementTree, dest: Path) -> None:
    xml_bytes = ET.tostring(tree.getroot(), encoding="utf-8")
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(pretty, encoding="utf-8")
    debug(f"Wrote {dest}")

# --------------- helpers for run-config (not invoked) ------------- #
# These helpers let you aggregate run/debug configs into the root .idea
# WITHOUT touching subprojects. They are provided but not used by main().

def patch_sdk_home(tree: ET.ElementTree, py: Path) -> None:
    root = tree.getroot()
    for opt in root.iter("option"):
        n = opt.get("name")
        if n == "SDK_HOME":
            opt.set("value", str(py))
        elif n == "IS_MODULE_SDK":
            opt.set("value", "false")

def update_workspace_xml(workspace: Path, config_name: str, config_type: str, folder_name: str) -> None:
    workspace_path = workspace / ".idea" / "workspace.xml"
    if not workspace_path.exists():
        prj = ET.Element('project', version="4")
        ET.SubElement(prj, 'component', {'name': 'RunManager'})
        ET.ElementTree(prj).write(workspace_path, encoding="utf-8", xml_declaration=True)
    tree = ET.parse(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    if runmanager is None:
        runmanager = ET.SubElement(root, 'component', {'name': 'RunManager'})
    config_el = None
    for conf in runmanager.findall('configuration'):
        if conf.attrib.get('name') == config_name and conf.attrib.get('type') == config_type:
            config_el = conf
            break
    if config_el is None:
        config_el = ET.SubElement(runmanager, 'configuration', {
            'name': config_name,
            'type': config_type,
            'folderName': folder_name,
            'factoryName': config_type.replace('ConfigurationType', ''),
        })
    else:
        config_el.attrib['folderName'] = folder_name
    tree.write(workspace_path, encoding="utf-8", xml_declaration=True)

def update_folders_xml(workspace: Path, folder_name: str) -> None:
    output_dir = workspace / '.idea' / 'runConfigurations'
    output_dir.mkdir(parents=True, exist_ok=True)
    folders_xml_path = output_dir / 'folders.xml'
    if folders_xml_path.exists():
        tree = ET.parse(folders_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element('component', attrib={'name': 'RunManager'})
        tree = ET.ElementTree(root)
    existing = root.find(f"./folder[@name='{folder_name}']")
    if existing is None:
        ET.SubElement(root, 'folder', attrib={'name': folder_name})
        tree.write(folders_xml_path, encoding='utf-8', xml_declaration=True)

def add_folder_name_to_config(tree: ET.ElementTree, folder_name: str) -> None:
    config_elem = next(tree.getroot().iter('configuration'), None)
    if config_elem is not None:
        config_elem.attrib['folderName'] = folder_name

def parse_template(tpl_path: Path) -> ET.ElementTree:
    if not tpl_path.exists():
        raise FileNotFoundError(f"Template not found: {tpl_path}")
    return ET.parse(str(tpl_path))

def patch_run_config_sdk_home(tree: ET.ElementTree, project_dir: Path) -> None:
    py = venv_python_for(project_dir)
    if py:
        patch_sdk_home(tree, py)

def generate_run_configs(
    workspace: Path,
    project_dir: Path,
    app_name: str,
    template_paths: list[Path],
    folder_name: Optional[str] = None,
) -> list[Path]:
    """
    Generate run configs INTO the ROOT workspace based on templates, without
    touching subproject .idea/. Writes to root/.idea/runConfigurations.
    Returns the list of generated/updated file paths.
    """
    output_dir = workspace / '.idea' / 'runConfigurations'
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    folder = folder_name or app_name

    for tpl in template_paths:
        tree = parse_template(tpl)
        root = tree.getroot()

        # replace {APP} placeholders
        for el in root.iter():
            for k, v in list(el.attrib.items()):
                if '{APP}' in v:
                    el.attrib[k] = v.replace('{APP}', app_name)
            if el.text and '{APP}' in el.text:
                el.text = el.text.replace('{APP}', app_name)

        # pin SDK_HOME to this project's venv
        patch_run_config_sdk_home(tree, project_dir)
        add_folder_name_to_config(tree, folder)

        base = tpl.name.replace('_template_app', f'_{app_name}')
        out_path = output_dir / base

        # idempotent write
        if out_path.exists():
            fd, tmp_path = tempfile.mkstemp(suffix='.xml')
            os.close(fd)
            tree.write(tmp_path)
            if filecmp.cmp(tmp_path, out_path, shallow=False):
                os.remove(tmp_path)
            else:
                os.replace(tmp_path, out_path)
        else:
            tree.write(out_path)
        written.append(out_path)

        # keep workspace + folders in sync
        config_elem = next(root.iter('configuration'))
        cfg_name = config_elem.attrib.get('name', base.rsplit('.', 1)[0])
        cfg_type = config_elem.attrib.get('type', 'PythonConfigurationType')
        update_workspace_xml(workspace, cfg_name, cfg_type, folder)

    update_folders_xml(workspace, folder)
    return written

# ------------------------------- main ------------------------------ #

def main() -> int:
    root = Path.cwd().resolve()
    workspace = root  # unified workspace at CWD
    debug(f"Root/workspace : {workspace}")

    projects = find_projects(root)
    if not projects:
        print("No projects with `.venv` found.")
        return 2

    # make SDK names unique if collisions
    used_names = set()
    modules = []   # (safe_name, project_dir, sdk_name, py, ver)
    for proj in projects:
        py = find_venv_python(proj)
        if not py:
            debug(f"WARNING: {proj} has no python in .venv; skipping.")
            continue
        ver = get_python_version_str(py)
        base_name = make_safe_name(root, proj)
        sdk_name = f"uv ({base_name})"
        i = 2
        while sdk_name in used_names:
            sdk_name = f"uv ({base_name}-{i})"
            i += 1
        used_names.add(sdk_name)
        modules.append((base_name, proj, sdk_name, py, ver))

    if not modules:
        print("Projects found, but none had a usable `.venv` python.")
        return 3

    # Build unified workspace only
    ensure_workspace(workspace)
    write_modules_xml(workspace, [(safe, proj) for (safe, proj, _sdk, _py, _ver) in modules])
    for safe, proj, sdk, _py, _ver in modules:
        write_iml(workspace, safe, proj, sdk)

    # Register SDKs in IDE jdk.table.xml
    config_dir = choose_best_config_dir(jetbrains_config_candidates())
    if not config_dir:
        debug("No JetBrains PyCharm config directory found. Open PyCharm once, then re-run.")
        return 4
    jdk_file = config_dir / "options" / "jdk.table.xml"
    debug(f"Using config dir: {config_dir}")

    tree = load_or_create_jdk_table(jdk_file)
    comp = get_or_create_component(tree.getroot(), "ProjectJdkTable")
    for _safe, _proj, sdk, py, ver in modules:
        ensure_python_sdk(comp, sdk_name=sdk, python_path=py, version=ver)

    # (backup_file intentionally not re-added by request)
    # write pretty jdk.table.xml
    write_pretty_xml(tree, jdk_file)

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
