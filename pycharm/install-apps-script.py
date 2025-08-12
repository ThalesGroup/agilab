#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
install-apps-script.py — Per-project uv interpreters, optional per-module SDKs,
root-aggregated run configs, and optional per-project installers.

Key flags
---------
--modules-use-own-sdk          : Set each module's .iml to its own "uv (project)" SDK (not inherited)
--pin-sdk-home-in-runs         : (default) Pin SDK_HOME in run configs to that subproject's .venv python
--no-pin-sdk-home-in-runs      : Do not set SDK_HOME in run configs
--write-ide-sdk                : Create/update IDE SDKs (jdk.table.xml) for each "uv (project)" and de-dupe
--run-installer                : Run per-project installer (see --installer-cmd or auto-detect)
"""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional, Dict

# ---------- Console ----------
BLUE = "\033[1;34m"; GREEN = "\033[1;32m"; YELLOW = "\033[1;33m"; RED = "\033[1;31m"; NC = "\033[0m"
def info(m): print(f"{BLUE}[apps]{NC} {m}")
def ok(m):   print(f"{GREEN}[ok]{NC}   {m}")
def warn(m): print(f"{YELLOW}[warn]{NC} {m}")
def err(m):  print(f"{RED}[err]{NC}  {m}")

# ---------- Discover ---------
EXCLUDES = {".git", ".hg", ".svn", ".Trash", "Library", ".cache", ".DS_Store"}
EXCLUDE_SUBSTR = ("JetBrains/PyCharm", "cpython-cache")

def find_projects_with_venv(root: Path, venv_name: str = ".venv") -> list[Path]:
    root_res = root.resolve()
    projects = set()
    for venv in root.rglob(venv_name):
        try:
            if not venv.is_dir():
                continue
            # keep strictly under base
            if not venv.resolve().is_relative_to(root_res):
                continue
            # skip noisy/system paths
            if EXCLUDES & set(venv.parts):
                continue
            s = str(venv)
            if any(x in s for x in EXCLUDE_SUBSTR):
                continue
            projects.add(venv.parent)
        except Exception:
            continue
    return sorted(projects)

# ---------- .venv python ----------
def venv_python_path(project_dir: Path) -> Optional[Path]:
    venv = project_dir / '.venv'
    if os.name == "nt":
        cand = venv / "Scripts" / "python.exe"
        return cand if cand.exists() else None
    else:
        for name in ("python3", "python"):
            cand = venv / "bin" / name
            if cand.exists():
                return cand  # keep .venv path literal (do not resolve symlink)
    return None

# ---------- XML helpers ----------
def _read_or_create_xml(path: Path, root_tag: str = "project") -> Tuple[ET.ElementTree, bool]:
    if path.exists():
        try:
            return ET.parse(path), False
        except ET.ParseError:
            warn(f"Malformed XML at {path}; recreating.")
    root = ET.Element(root_tag, {"version": "4"} if root_tag == "project" else {})
    return ET.ElementTree(root), True

def _write_xml(tree: ET.ElementTree, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass
    with path.open("wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(ET.tostring(tree.getroot(), encoding="utf-8"))
    ok(f"Updated: {path}")

def ensure_idea_dir(project_dir: Path) -> Tuple[Path, bool]:
    idea = project_dir / ".idea"
    if idea.is_dir():
        return idea, False
    try:
        idea.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass
    ok(f"Created: {idea}")
    return idea, True

# ---------- misc.xml (Project interpreter label) ----------
def set_project_sdk_in_misc(tree: ET.ElementTree, sdk_name: str) -> bool:
    root = tree.getroot()
    comp = None
    for c in root.findall("component"):
        if c.get("name") == "ProjectRootManager":
            comp = c
            break
    modified = False
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectRootManager"})
        modified = True
    if comp.get("project-jdk-name") != sdk_name:
        comp.set("project-jdk-name", sdk_name); modified = True
    if comp.get("project-jdk-type") != "Python SDK":
        comp.set("project-jdk-type", "Python SDK"); modified = True
    return modified

# ---------- Align Black plugin SDK (optional nicety) ----------
def normalize_black_sdk(misc_tree: ET.ElementTree, sdk_name: str) -> bool:
    root = misc_tree.getroot()
    comp = None
    for c in root.findall("component"):
        if c.get("name") == "Black":
            comp = c; break
    if comp is None:
        return False
    opt = comp.find("./option[@name='sdkName']")
    if opt is not None and opt.get("value") != sdk_name:
        opt.set("value", sdk_name)
        return True
    return False

# ---------- module name detection ----------
def detect_module_name(idea_dir: Path, project_dir: Path) -> str:
    modules_xml = idea_dir / "modules.xml"
    if modules_xml.exists():
        try:
            tree = ET.parse(modules_xml)
            node = tree.getroot().find("./component[@name='ProjectModuleManager']/modules/module")
            if node is not None:
                fileurl = node.get("fileurl") or node.get("filepath") or ""
                base = Path(fileurl.replace("file://$PROJECT_DIR$/", "").replace("file://", ""))
                stem = base.stem
                if stem:
                    return stem
        except ET.ParseError:
            pass
    imls = list(idea_dir.glob("*.iml"))
    if len(imls) == 1:
        return imls[0].stem
    return project_dir.name

# ---------- .iml helpers ----------
def ensure_modules_inherit_sdk(idea_dir: Path) -> bool:
    changed_any = False
    for iml in idea_dir.glob("*.iml"):
        try:
            tree = ET.parse(iml)
        except ET.ParseError:
            continue
        root = tree.getroot()
        nmr = root.find("./component[@name='NewModuleRootManager']")
        if nmr is None:
            nmr = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
        changed = False
        # remove any explicit jdk entries, ensure inherited
        for oe in list(nmr.findall("orderEntry")):
            if oe.get("type") == "jdk":
                nmr.remove(oe); changed = True
        if not any(oe.get("type") == "inheritedJdk" for oe in nmr.findall("orderEntry")):
            ET.SubElement(nmr, "orderEntry", {"type": "inheritedJdk"}); changed = True
        if changed:
            with iml.open("wb") as f:
                f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write(ET.tostring(root, encoding="utf-8"))
            changed_any = True
    if changed_any:
        ok(f"Updated module(s) to inherit project SDK in {idea_dir}")
    return changed_any

def ensure_modules_use_own_sdk(idea_dir: Path, sdk_name: str) -> bool:
    changed_any = False
    for iml in idea_dir.glob("*.iml"):
        try:
            tree = ET.parse(iml)
        except ET.ParseError:
            continue
        root = tree.getroot()
        nmr = root.find("./component[@name='NewModuleRootManager']")
        if nmr is None:
            nmr = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
        # wipe previous jdk/inherited entries
        for oe in list(nmr.findall("orderEntry")):
            if oe.get("type") in ("inheritedJdk", "jdk"):
                nmr.remove(oe)
        ET.SubElement(nmr, "orderEntry", {"type": "jdk", "jdkName": sdk_name, "jdkType": "Python SDK"})
        with iml.open("wb") as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write(ET.tostring(root, encoding="utf-8"))
        changed_any = True
    if changed_any:
        ok(f"Updated module(s) to use own SDK '{sdk_name}' in {idea_dir}")
    return changed_any

# ---------- workspace.xml (Run config) ----------
def _ensure_option(config: ET.Element, name: str, value: str) -> bool:
    for o in config.findall("option"):
        if o.get("name") == name:
            if o.get("value") != value:
                o.set("value", value); return True
            return False
    ET.SubElement(config, "option", {"name": name, "value": value})
    return True

def ensure_run_config(
    tree: ET.ElementTree,
    project_dir: Path,
    sdk_name: str,
    python_path: Optional[Path],
    module_name: str,
    config_name: str,
) -> bool:
    root = tree.getroot()
    modified = False

    # RunManager
    run_mgr = None
    for c in root.findall("component"):
        if c.get("name") == "RunManager":
            run_mgr = c; break
    if run_mgr is None:
        run_mgr = ET.SubElement(root, "component", {"name": "RunManager"})
        modified = True

    # Keep selected on first created config name
    if run_mgr.get("selected") is None:
        run_mgr.set("selected", f"Python.{config_name}"); modified = True

    # Find or create config
    config = None
    for c in run_mgr.findall("configuration"):
        if c.get("name") == config_name and c.get("type") == "PythonConfigurationType":
            config = c; break
    if config is None:
        config = ET.SubElement(run_mgr, "configuration", {
            "name": config_name,
            "type": "PythonConfigurationType",
            "factoryName": "Python",
        })
        modified = True

    changed = False

    changed |= _ensure_option(config, "SDK_HOME", str(python_path))
    changed |= _ensure_option(config, "WORKING_DIRECTORY", str(project_dir))
    changed |= _ensure_option(config, "ADD_CONTENT_ROOTS", "true")
    changed |= _ensure_option(config, "ADD_SOURCE_ROOTS", "true")
    changed |= _ensure_option(config, "PARENT_ENVS", "true")
    changed |= _ensure_option(config, "INTERPRETER_OPTIONS", "")

    # Cosmetic SDK_NAME
    if config.get("SDK_NAME") != sdk_name:
        config.set("SDK_NAME", sdk_name); changed = True

    # Bind module
    module = config.find("module")
    if module is None:
        ET.SubElement(config, "module", {"name": module_name}); changed = True
    elif module.get("name") != module_name:
        module.set("name", module_name); changed = True

    # Ensure method
    if config.find("method") is None:
        ET.SubElement(config, "method", {"v": "2"}); changed = True

    if changed:
        modified = True
    return modified

# ---------- Aggregate runs into ROOT ----------
def load_root_modules_map(root_dir: Path) -> Dict[Path, str]:
    modules_xml = root_dir / ".idea" / "modules.xml"
    mapping: Dict[Path, str] = {}
    if not modules_xml.exists():
        return mapping
    try:
        tree = ET.parse(modules_xml)
    except ET.ParseError:
        return mapping
    for m in tree.getroot().findall("./component[@name='ProjectModuleManager']/modules/module"):
        fp = (m.get("filepath") or m.get("fileurl") or "")
        if not fp:
            continue
        p = fp.replace("$PROJECT_DIR$/", "")
        iml = (root_dir / p).resolve()
        module_name = Path(p).stem
        proj_dir = iml.parent.parent
        mapping[proj_dir.resolve()] = module_name
    return mapping

# ---------- IDE SDK writer (jdk.table.xml) ----------
def locate_ide_options_dir() -> Optional[Path]:
    roots = []
    if sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Application Support" / "JetBrains")
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            roots.append(Path(appdata) / "JetBrains")
    else:
        roots.append(Path.home() / ".config" / "JetBrains")
    for base in roots:
        if not base.is_dir():
            continue
        candidates = [p for p in base.glob("PyCharm*") if p.is_dir()]
        if not candidates:
            continue
        candidates.sort()
        return candidates[-1] / "options"
    return None

def _load_or_create_jdk_table(path: Path) -> Tuple[ET.ElementTree, ET.Element]:
    if path.exists():
        try:
            tree = ET.parse(path)
            root = tree.getroot()
        except ET.ParseError:
            tree = ET.ElementTree(ET.Element("application"))
            root = tree.getroot()
    else:
        tree = ET.ElementTree(ET.Element("application"))
        root = tree.getroot()
    comp = root.find("./component[@name='ProjectJdkTable']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
    return ET.ElementTree(root), comp

def _find_jdk_by_name(comp: ET.Element, name: str) -> Optional[ET.Element]:
    for jdk in comp.findall("jdk"):
        nm = jdk.find("./name")
        if nm is not None and nm.get("value") == name:
            return jdk
    return None

def _ensure_child_with_value(parent: ET.Element, tag: str, value: str) -> ET.Element:
    node = parent.find(f"./{tag}")
    if node is None:
        node = ET.SubElement(parent, tag, {"value": value})
    elif node.get("value") != value:
        node.set("value", value)
    return node

def _list_jdks(comp: ET.Element) -> List[ET.Element]:
    return list(comp.findall("jdk"))

def _home_values_equal(a: str, b: str) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except Exception:
        return a == b

def _list_jdks_by_home_equiv(comp: ET.Element, home: str) -> List[ET.Element]:
    res = []
    for jdk in _list_jdks(comp):
        hp = jdk.find("./homePath")
        if hp is not None and (hp.get("value") == home or _home_values_equal(hp.get("value"), home)):
            res.append(jdk)
    return res

def dedupe_and_rename_sdk(comp: ET.Element, desired_name: str, home_path: Path) -> bool:
    home = str(home_path)
    jdks = _list_jdks_by_home_equiv(comp, home)
    modified = False
    target = None
    for j in jdks:
        nm = j.find("./name")
        if nm is not None and nm.get("value") == desired_name:
            target = j; break
    if target is None and jdks:
        target = jdks[0]
        nm = target.find("./name")
        if nm is None:
            ET.SubElement(target, "name", {"value": desired_name}); modified = True
        elif nm.get("value") != desired_name:
            nm.set("value", desired_name); modified = True
        _ensure_child_with_value(target, "type", "Python SDK")
        _ensure_child_with_value(target, "homePath", home)
    for j in jdks:
        if j is target: continue
        comp.remove(j); modified = True
    return modified

def write_ide_sdk(options_dir: Path, sdk_name: str, python_home: Path) -> bool:
    jdk_table = options_dir / "jdk.table.xml"
    tree, comp = _load_or_create_jdk_table(jdk_table)
    jdk = _find_jdk_by_name(comp, sdk_name)
    created = False
    if jdk is None:
        jdk = ET.SubElement(comp, "jdk", {"version": "2"})
        _ensure_child_with_value(jdk, "name", sdk_name)
        _ensure_child_with_value(jdk, "type", "Python SDK")
        created = True
    _ensure_child_with_value(jdk, "homePath", str(python_home))
    if jdk.find("./roots") is None:
        roots = ET.SubElement(jdk, "roots")
        ET.SubElement(roots, "annotationsPath").append(ET.Element("root", {"type": "composite"}))
        ET.SubElement(roots, "classPath").append(ET.Element("root", {"type": "composite"}))
        ET.SubElement(roots, "javadocPath").append(ET.Element("root", {"type": "composite"}))
        ET.SubElement(roots, "sourcePath").append(ET.Element("root", {"type": "composite"}))
    if jdk.find("./additional") is None:
        ET.SubElement(jdk, "additional")
    changed_dedupe = dedupe_and_rename_sdk(comp, sdk_name, python_home)
    try:
        jdk_table.parent.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass
    with jdk_table.open("wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(ET.tostring(tree.getroot(), encoding="utf-8"))
    ok(f"IDE SDK {'created' if created else 'updated'}: {sdk_name} -> {python_home}")
    return created or changed_dedupe

# ---------- Installer ----------
def run_installer_for_project(
    agilab_home: Path,
    project_dir: Path,
) -> None:

    cmd = f'uv run --active python {agilab_home / "pycharm/gen-app-script.py"} {project_dir.name}'
    info(f"Installer (install.py) in {project_dir}: {cmd}")
    rc = subprocess.run(cmd, shell=True, cwd=str(project_dir)).returncode
    if rc == 0: ok(f"Installer OK in {project_dir}")
    else: warn(f"Installer returned rc={rc} in {project_dir}")
    return

# ---------- Per-project patch ----------
def patch_project(
    project_dir: Path,
) -> Tuple[bool, Optional[Path], str]:
    """
    Patch a single project.
    Returns: (changed_anything, venv_python_path_or_None, sdk_name)
    """
    changed = False
    project_name = project_dir.name
    sdk_name = f"uv ({project_name})"

    # .venv python (keep literal)
    py_path = venv_python_path(project_dir)
    if not py_path:
        warn(f"{project_name}: no .venv python found under {project_dir}; run configs may skip SDK_HOME.")

    idea_dir, _ = ensure_idea_dir(project_dir)

    # misc.xml + optional Black sync
    misc_path = idea_dir / "misc.xml"
    misc_tree, _ = _read_or_create_xml(misc_path, "project")
    if set_project_sdk_in_misc(misc_tree, sdk_name):
        _write_xml(misc_tree, misc_path); changed = True
    if normalize_black_sdk(misc_tree, sdk_name):
        _write_xml(misc_tree, misc_path); changed = True

    # module SDK policy
    ensure_modules_use_own_sdk(idea_dir, sdk_name)

    # workspace.xml run config (per-project)
    ws_path = idea_dir / "workspace.xml"
    ws_tree, _ = _read_or_create_xml(ws_path, "project")
    module_name = detect_module_name(idea_dir, project_dir)
    if ensure_run_config(ws_tree, project_dir, sdk_name, py_path, module_name, "agilab run"):
        _write_xml(ws_tree, ws_path); changed = True

    ide_options_dir = locate_ide_options_dir()
    write_ide_sdk(ide_options_dir, sdk_name, py_path)

    return changed, py_path, sdk_name


def is_app_project(p: Path) -> bool:
    # only app folders, e.g. src/agilab/apps/<name>
    return "/src/agilab/apps/" in str(p.resolve())


# ---------- Main ----------
def main() -> int:
    # argparse (single parser, single arg)
    ap = argparse.ArgumentParser(
        prog="install-apps-script.py",
        description="Patch PyCharm SDKs/runs per project",
    )
    ap.add_argument(
        "--agilab-home",
        dest="agilab_home",
        required=False,
        type=lambda p: Path(p).expanduser().resolve(),
        help="Path to the Agilab project root (must contain .idea/)",
    )
    args, _unknown = ap.parse_known_args()

    if args.agilab_home:
        base = args.agilab_home
    else:
        base = Path(__file__).resolve().parents[1]

    # hard guard: must be a project root (prevents scanning $HOME)
    if not (base / ".idea").exists():
        err(f"Refusing to run: no .idea under {base}. Pass --agilab-home to your project root.")
        return 2

    info(f"Root: {base}")
    info(f"Scanning subprojects for '.venv'")
    projects = find_projects_with_venv(base)


    total = 0
    # Root project
    root_py: Optional[Path] = None

    # Subprojects
    proj_info: Dict[Path, Tuple[Optional[Path], str]] = {}
    for proj in projects:
        for proj in projects:
            if not is_app_project(proj):
                continue
        try:
            rel = proj.relative_to(base) if proj.resolve().is_relative_to(base.resolve()) else proj
        except Exception:
            rel = proj
        info(f"Project: {rel}")
        try:
            changed, py, sdk_name = patch_project(proj)
            if changed:
                total += 1
            proj_info[proj.resolve()] = (py, sdk_name)
        except Exception as e:
            err(f"{proj}: {e}")

    # Aggregate run configs into ROOT
    if proj_info:
        root_ws_path = base / ".idea" / "workspace.xml"
        root_ws_tree, _ = _read_or_create_xml(root_ws_path, "project")
        mod_map = load_root_modules_map(base)
        agg_changed = False
        for proj_dir, (py, sdk_name) in proj_info.items():
            module_name = mod_map.get(proj_dir, proj_dir.name)
            cfg_name = f"{module_name} run"
            if ensure_run_config(root_ws_tree, proj_dir, sdk_name, py, module_name, cfg_name):
                agg_changed = True
        if agg_changed:
            _write_xml(root_ws_tree, root_ws_path)

    # Run installers
    for proj, (py, _) in proj_info.items():
        if proj == base:
            continue
        run_installer_for_project(base, proj)

    ok(f"Done. Updated {total} project(s).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
