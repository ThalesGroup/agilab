#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, List, Dict
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Settings / Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent

def find_idea_dir(root: Path) -> Path:
    for name in (".idea", "idea"):
        d = root / name
        if d.exists():
            return d
    return root / ".idea"

IDEA = find_idea_dir(ROOT)
MODULES_DIR = IDEA / "modules"
RUNCFG_DIR = IDEA / "runConfigurations"
PROJECT_NAME = IDEA.parent.name
PROJECT_SDK_NAME = f"uv ({PROJECT_NAME})"
APPS_DIR = ROOT / "src" / PROJECT_NAME / "apps"
CORE_DIR = ROOT / "src" / PROJECT_NAME / "core"
GEN_SCRIPT = (ROOT / "pycharm" / "gen-app-script.py") if (ROOT / "pycharm" / "gen-app-script.py").exists() else (ROOT / "gen-app-script.py")
SDK_TYPE = "Python SDK"

# Attach only subprojects that already have a .venv
ATTACH_ONLY_VENVS = True

# Behavior flags
ENSURE_UV_VENVS_APPS = True   # apps: create .venv if missing
ENSURE_UV_VENVS_CORE = False  # core: attach only if .venv already exists (no run configs)

# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def debug(msg: str) -> None:
    print(f"[install-apps] {msg}")

def read_xml(path: Path) -> ET.ElementTree:
    return ET.parse(str(path))

def _indent_inplace(tree: ET.ElementTree) -> None:
    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass

def _write_xml(tree: ET.ElementTree, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _indent_inplace(tree)
    tree.write(str(dest), encoding="UTF-8", xml_declaration=True, short_empty_elements=True)

def venv_python_for(project_dir: Path) -> Optional[Path]:
    candidates = [
        project_dir / ".venv" / "bin" / "python3",
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ]
    for c in candidates:
        if c.exists():
            try:
                return c.resolve()
            except Exception:
                return c
    return None

def ensure_uv_venv(path: Path) -> Optional[Path]:
    py = venv_python_for(path)
    if py:
        return py
    try:
        debug(f"{path.name if path != ROOT else PROJECT_NAME}: creating .venv via `uv venv` …")
        subprocess.run(["uv", "venv"], cwd=str(path), check=True)
    except Exception as e:
        debug(f"{path.name}: uv venv failed: {e}")
        return None
    return venv_python_for(path)

def as_project_macro(path: Path) -> str:
    rel = path.resolve().relative_to(ROOT.resolve())
    return f"$PROJECT_DIR$/{rel.as_posix()}"

def as_project_url(path: Path) -> str:
    return f"file://{as_project_macro(path)}"

def _rel_from_root(path: Path) -> Optional[Path]:
    try:
        return path.relative_to(ROOT)  # do not resolve to keep macros
    except ValueError:
        return None

def content_url_for(dir_path: Path) -> str:
    rel = _rel_from_root(dir_path)
    return f"file://$PROJECT_DIR$/{rel.as_posix()}" if rel is not None else f"file://{dir_path.resolve().as_posix()}"

# ---------------------------------------------------------------------------
# Project basics
# ---------------------------------------------------------------------------

def ensure_project_name(name: str) -> None:
    name_file = IDEA / ".name"
    prev = ""
    if name_file.exists():
        try:
            prev = name_file.read_text(encoding="utf-8").strip()
        except Exception:
            prev = ""
    if prev != name:
        name_file.parent.mkdir(parents=True, exist_ok=True)
        name_file.write_text(name + "\n", encoding="utf-8")
        debug(f"Set project name to '{name}' (.idea/.name)")

def ensure_root_module_iml(name: str) -> Path:
    """Root module .iml (kept simple, using inheritedJdk; we bind explicitly later)."""
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
    _write_xml(ET.ElementTree(m), iml)
    debug(f"Root module IML created: {iml}")
    return iml

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
    _write_xml(tree, misc)
    debug(f"Project SDK set to '{name}' in misc.xml")

def remove_module(name: str) -> None:
    iml = MODULES_DIR / f"{name}.iml"
    try:
        if iml.exists():
            iml.unlink()
            debug(f"Removed stale module: {name}")
    except Exception:
        pass

def rebuild_modules_xml_from_disk() -> None:
    """Rebuild .idea/modules.xml from the .iml files present in .idea/modules."""
    imls = sorted(p for p in MODULES_DIR.glob("*.iml") if p.exists() and p.name != "module.iml")
    project = ET.Element("project", {"version": "4"})
    comp = ET.SubElement(project, "component", {"name": "ProjectModuleManager"})
    mods = ET.SubElement(comp, "modules")
    for p in imls:
        ET.SubElement(mods, "module", {"fileurl": as_project_url(p), "filepath": as_project_macro(p)})
    _write_xml(ET.ElementTree(project), IDEA / "modules.xml")
    debug(f"modules.xml rebuilt with {len(imls)} module(s)")

# ---------------------------------------------------------------------------
# Template-based module writing (NO REGRESSION)
# ---------------------------------------------------------------------------

def _find_module_template() -> Optional[Path]:
    """
    Look for an .iml template in common places, in this order:
      - pycharm/_template_module.iml
      - pycharm/templates/_template_module.iml
      - pycharm/_template_app_modules.xml  (legacy name used previously)
    Returns the first that exists.
    """
    candidates = [
        ROOT / "pycharm" / "_template_module.iml",
        ROOT / "pycharm" / "templates" / "_template_module.iml",
        ROOT / "pycharm" / "_template_app_modules.xml",  # legacy, kept for backwards compat
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

def _write_module_from_template(module_name: str, dir_path: Path) -> Path:
    """
    Write .idea/modules/<module_name>.iml using your template (no regression).
    Supported placeholders (compatible with older versions):
      $MODULE_NAME$   -> module_name
      $CONTENT_URL$   -> file://$PROJECT_DIR$/...
      $MODULE_URL$    -> same as $CONTENT_URL$ (compat alias)
    If no template is found, falls back to a minimal IML with inheritedJdk.
    """
    iml_path = MODULES_DIR / f"{module_name}.iml"
    tpl = _find_module_template()
    if not tpl:
        # Fallback: minimal IML (same as earlier code path)
        return ensure_app_module_iml(dir_path)

    try:
        text = tpl.read_text(encoding="utf-8")
    except Exception:
        return ensure_app_module_iml(dir_path)

    url = content_url_for(dir_path)
    text = (text
            .replace("$MODULE_NAME$", module_name)
            .replace("$CONTENT_URL$", url)
            .replace("$MODULE_URL$", url))

    iml_path.parent.mkdir(parents=True, exist_ok=True)
    iml_path.write_text(text, encoding="utf-8")
    debug(f"IML from template: {iml_path}")
    return iml_path

def ensure_app_module_iml(dir_path: Path) -> Path:
    """
    Kept as a thin wrapper for historical behavior:
    - Prefer template-based module creation.
    - If template missing or unreadable, build a simple IML.
    """
    name = dir_path.name
    tpl = _find_module_template()
    if tpl:
        return _write_module_from_template(name, dir_path)

    # No template found → create minimal module
    m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
    comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
    ET.SubElement(comp, "content", {"url": content_url_for(dir_path)})
    ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
    ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
    iml_path = MODULES_DIR / f"{name}.iml"
    _write_xml(ET.ElementTree(m), iml_path)
    debug(f"IML created: {iml_path}")
    return iml_path

# ---------------------------------------------------------------------------
# JDK table helpers (global SDKs)
# ---------------------------------------------------------------------------

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

def _all_jdk_tables() -> list[Path]:
    tables = []
    for base in _jb_base_dirs():
        for product in ("PyCharm*", "PyCharmCE*"):
            for candidate in base.glob(product):
                p = candidate / "options" / "jdk.table.xml"
                p.parent.mkdir(parents=True, exist_ok=True)
                tables.append(p)
    return tables

def _ensure_component(root: ET.Element) -> ET.Element:
    comp = root.find("./component[@name='ProjectJdkTable']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
    return comp

def _ensure_roots(jdk: ET.Element) -> None:
    if jdk.find("roots") is None:
        ET.SubElement(jdk, "roots")

_SDK_NAME_CACHE: Dict[str, str] = {}

def _sdk_name_for_home(home_path: str, preferred: str) -> str:
    if home_path in _SDK_NAME_CACHE:
        return _SDK_NAME_CACHE[home_path]
    for tbl in _all_jdk_tables():
        if not tbl.exists():
            continue
        try:
            tree = ET.parse(str(tbl))
        except ET.ParseError:
            continue
        comp = _ensure_component(tree.getroot())
        for jdk in comp.findall("jdk"):
            hp_el = jdk.find("homePath")
            hp_val = (hp_el.get("value") if hp_el is not None else jdk.attrib.get("homePath")) or ""
            if hp_val == home_path:
                nm_el = jdk.find("name")
                name_val = nm_el.get("value") if nm_el is not None else jdk.attrib.get("name", preferred)
                _SDK_NAME_CACHE[home_path] = name_val
                return name_val
    _SDK_NAME_CACHE[home_path] = preferred
    return preferred

def _load_or_init_table(path: Path) -> ET.ElementTree:
    if path.exists():
        try:
            return ET.parse(str(path))
        except ET.ParseError:
            root = ET.Element("application")
            _ensure_component(root)
            return ET.ElementTree(root)
    root = ET.Element("application")
    _ensure_component(root)
    return ET.ElementTree(root)

def _table_upsert_batch(name_to_home: Dict[str, str]) -> None:
    updated_any = False
    for table in _all_jdk_tables():
        tree = _load_or_init_table(table)
        root = tree.getroot()
        comp = _ensure_component(root)
        changed = False

        for name, home in name_to_home.items():
            found = None
            for jdk in comp.findall("jdk"):
                nm = jdk.find("name")
                if nm is not None and nm.get("value") == name:
                    found = jdk
                    break
                if nm is None and jdk.attrib.get("name") == name:
                    found = jdk
                    break

            if found is None:
                jdk = ET.SubElement(comp, "jdk", {"version": "2"})
                ET.SubElement(jdk, "name", {"value": name})
                ET.SubElement(jdk, "type", {"value": SDK_TYPE})
                ET.SubElement(jdk, "homePath", {"value": home})
                _ensure_roots(jdk)
                changed = True
            else:
                name_el = found.find("name") or ET.SubElement(found, "name", {"value": name})
                name_el.set("value", name)
                type_el = found.find("type") or ET.SubElement(found, "type", {"value": SDK_TYPE})
                type_el.set("value", SDK_TYPE)
                home_el = found.find("homePath") or ET.SubElement(found, "homePath", {"value": home})
                if home_el.get("value") != home:
                    home_el.set("value", home)
                    changed = True
                _ensure_roots(found)

        if changed:
            _write_xml(tree, table)
            updated_any = True
            debug(f"Updated {table} with {len(name_to_home)} SDK(s)")
    if not updated_any:
        debug("No JetBrains jdk.table.xml found yet (open PyCharm once).")

def _table_prune_sdks(keep_names: set[str]) -> None:
    for table in _all_jdk_tables():
        if not table.exists():
            continue
        try:
            tree = ET.parse(str(table))
        except ET.ParseError:
            continue
        root = tree.getroot()
        comp = _ensure_component(root)
        removed = 0
        for jdk in list(comp.findall("jdk")):
            nm_el = jdk.find("name")
            nm = nm_el.get("value") if nm_el is not None else jdk.attrib.get("name", "")
            tp_el = jdk.find("type")
            tp = tp_el.get("value") if tp_el is not None else jdk.attrib.get("type", "")
            if tp == SDK_TYPE and nm.startswith("uv (") and nm not in keep_names:
                comp.remove(jdk)
                removed += 1
        if removed:
            _write_xml(tree, table)
            debug(f"Pruned SDKs in {table}, kept: {sorted(keep_names)}")

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _eligible_apps(require_venv: bool) -> list[Path]:
    apps: list[Path] = []
    if not APPS_DIR.exists():
        return apps
    for p in sorted(APPS_DIR.iterdir()):
        if not p.is_dir():
            continue
        if not p.name.endswith("_project"):
            continue
        if require_venv and venv_python_for(p) is None:
            continue
        apps.append(p)
    return apps

def _eligible_core(require_venv: bool) -> list[Path]:
    cores: list[Path] = []
    if not CORE_DIR.exists():
        return cores
    for p in sorted(CORE_DIR.iterdir()):
        if not p.is_dir():
            continue
        if p.name.startswith((".", "__")):
            continue
        if require_venv and venv_python_for(p) is None:
            continue
        cores.append(p)
    return cores

# ---------------------------------------------------------------------------
# Run/debug configs (apps only, via your existing generator)
# ---------------------------------------------------------------------------

def generate_app_run_configs(app_names: list[str]) -> None:
    if not GEN_SCRIPT.exists():
        debug(f"Missing {GEN_SCRIPT}; skipping run configuration generation.")
        return
    for name in app_names:
        debug(f"Generating run configs for '{name}' via {GEN_SCRIPT.name} …")
        subprocess.run([sys.executable, str(GEN_SCRIPT), name], check=True, cwd=str(ROOT))

# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def main() -> int:
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

    ensure_project_name(PROJECT_NAME)

    # Root interpreter → ensure uv venv (project-level)
    root_py = ensure_uv_venv(ROOT)
    if root_py:
        _table_upsert_batch({PROJECT_SDK_NAME: str(root_py)})
        set_project_sdk(PROJECT_SDK_NAME, SDK_TYPE)
    else:
        debug("Root .venv not found; run `uv venv` at repo root if you want a project SDK.")

    # Root module + bind root SDK (if present)
    root_iml = ensure_root_module_iml(PROJECT_NAME)
    if root_py:
        set_module_sdk(root_iml, PROJECT_SDK_NAME)

    # Discover apps/core
    apps = _eligible_apps(require_venv=False if ENSURE_UV_VENVS_APPS else ATTACH_ONLY_VENVS)
    cores = _eligible_core(require_venv=True)  # core: only attach if venv exists

    # For apps: ensure venv if requested
    realized_apps: list[Path] = []
    for a in apps:
        py = ensure_uv_venv(a) if ENSURE_UV_VENVS_APPS else venv_python_for(a)
        if not py:
            if ATTACH_ONLY_VENVS:
                debug(f"{a.name}: no .venv → skipping.")
                continue
            else:
                # (shouldn't happen with ENSURE_UV_VENVS_APPS=True)
                debug(f"{a.name}: still no .venv → skipping.")
                continue
        # Write module from template (no regression) and bind its *own* SDK
        iml = _write_module_from_template(a.name, a)
        sdk_name = f"uv ({a.name})"
        _table_upsert_batch({sdk_name: str(py)})
        set_module_sdk(iml, sdk_name)
        realized_apps.append(a)

    # For core: attach only if it already has its own .venv (no run configs)
    realized_cores: list[Path] = []
    for c in cores:
        py = venv_python_for(c) if not ENSURE_UV_VENVS_CORE else ensure_uv_venv(c)
        if not py:
            continue
        iml = _write_module_from_template(c.name, c)
        sdk_name = f"uv ({c.name})"
        _table_upsert_batch({sdk_name: str(py)})
        set_module_sdk(iml, sdk_name)
        realized_cores.append(c)

    # Prune stale modules: keep root + realized apps/cores
    keep_names = {PROJECT_NAME} | {p.name for p in realized_apps} | {p.name for p in realized_cores}
    for iml in MODULES_DIR.glob("*.iml"):
        name = iml.stem
        if name not in keep_names:
            remove_module(name)

    # Rebuild modules.xml from disk
    rebuild_modules_xml_from_disk()

    # Generate run/debug configs ONLY for apps (your generator handles envs/templates)
    generate_app_run_configs([p.name for p in realized_apps])

    # Keep exactly one interpreter per project
    keep_sdk_names: set[str] = {PROJECT_SDK_NAME} | {f"uv ({p.name})" for p in realized_apps} | {f"uv ({p.name})" for p in realized_cores}
    _table_prune_sdks(keep_sdk_names)

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
