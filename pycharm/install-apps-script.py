#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Settings / Paths
# ---------------------------------------------------------------------------

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
CORE_DIR = ROOT / "src" / "agilab" / "core"

GEN_SCRIPT = (ROOT / "pycharm" / "gen-app-script.py"
              if (ROOT / "pycharm" / "gen-app-script.py").exists()
              else ROOT / "gen-app-script.py")

PROJECT_NAME = "agilab"
SDK_TYPE = "Python SDK"
PROJECT_SDK_NAME = "uv (agilab)"

# Behavior flags
ENSURE_UV_VENVS = True   # create missing .venv via `uv venv` for root/apps/core
# Apps: attach all *_project (SDK only if venv exists). Core: attach only if venv exists.

# ---------------------------------------------------------------------------
# Utilities
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
    # write as UTF-8 with LF line endings
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
    """Create a .venv with `uv venv` if missing; return interpreter path or None."""
    py = venv_python_for(path)
    if py:
        return py
    try:
        debug(f"{path.name}: creating .venv via `uv venv` …" if path != ROOT else "agilab: creating .venv via `uv venv` …")
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
        return path.relative_to(ROOT)  # no resolve() to keep symlinks/macros intact
    except ValueError:
        return None

def app_rel_content_url(app_dir: Path) -> str:
    rel = _rel_from_root(app_dir)
    if rel is not None:
        return f"file://$PROJECT_DIR$/{rel.as_posix()}"
    return f"file://{app_dir.resolve().as_posix()}"

# ---------------------------------------------------------------------------
# .idea basics
# ---------------------------------------------------------------------------

def ensure_project_name(name: str) -> None:
    name_file = IDEA / ".name"
    old = ""
    if name_file.exists():
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
    tree = ET.ElementTree(m)
    _write_xml(tree, iml)
    debug(f"Root module IML created: {iml}")
    return iml

def ensure_app_module_iml(app_dir: Path) -> Path:
    app = app_dir.name
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
    tree = ET.ElementTree(m)
    _write_xml(tree, iml_path)
    debug(f"IML created: {iml_path}")
    return iml_path

def set_module_sdk(iml_path: Path, sdk_name: str) -> None:
    tree = read_xml(iml_path)
    root = tree.getroot()
    comp = root.find("./component[@name='NewModuleRootManager']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
    # remove any existing jdk/inheritedJdk first
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
    imls = sorted(p for p in MODULES_DIR.glob("*.iml") if p.exists() and p.name != "module.iml")
    project = ET.Element("project", {"version": "4"})
    comp = ET.SubElement(project, "component", {"name": "ProjectModuleManager"})
    mods = ET.SubElement(comp, "modules")
    for p in imls:
        ET.SubElement(mods, "module", {"fileurl": as_project_url(p), "filepath": as_project_macro(p)})
    tree = ET.ElementTree(project)
    _write_xml(tree, IDEA / "modules.xml")
    debug(f"modules.xml rebuilt with {len(imls)} module(s)")

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
                # create parent if missing so we can write later
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
    """Return existing SDK name for this interpreter home if present; else preferred."""
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
            # new schema (child elements) or legacy (attributes)
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
            # start fresh if corrupted
            root = ET.Element("application")
            _ensure_component(root)
            return ET.ElementTree(root)
    root = ET.Element("application")
    _ensure_component(root)
    return ET.ElementTree(root)

def _table_upsert_batch(name_to_home: Dict[str, str]) -> None:
    """Batch create/update SDKs; always ensure <roots/> exists."""
    any_updated = False
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
                # attribute style fallback
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
                # normalize into element style
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
            any_updated = True
            debug(f"Updated {table} with {len(name_to_home)} SDK(s)")
    if not any_updated:
        debug("No JetBrains jdk.table.xml found yet (open PyCharm once).")

def _table_prune_sdks(keep_names: set[str]) -> None:
    """Remove Python SDKs not in keep_names (only uv entries we created)."""
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
# Run configuration patching
# ---------------------------------------------------------------------------

def _app_macros_for_dir(dirname: str, base: str) -> tuple[str, str, str]:
    workdir = f"$PROJECT_DIR$/src/agilab/{base}/{dirname}"
    venv    = f"{workdir}/.venv"
    pyexe   = f"{venv}/Scripts/python.exe" if os.name == "nt" else f"{venv}/bin/python"
    return workdir, venv, pyexe

def patch_run_configs_for(names: list[str]) -> None:
    """Ensure each config for given names has module binding + working dir + env vars."""
    for name in names:
        # decide if it's app or core by presence on disk
        base = "apps" if (APPS_DIR / name).exists() else "core"
        workdir, venv, pyexe = _app_macros_for_dir(name, base=base)

        for xml_path in sorted(RUNCFG_DIR.glob(f"_{name}_*.xml")):
            try:
                tree = read_xml(xml_path)
            except ET.ParseError:
                continue
            root = tree.getroot()
            cfg = root.find("./configuration")
            if cfg is None:
                # some templates wrap configuration inside component
                cfgs = root.findall(".//configuration")
                cfg = cfgs[0] if cfgs else None
            if cfg is None:
                continue

            # bind to module
            mod = cfg.find("module")
            if mod is None:
                ET.SubElement(cfg, "module", {"name": name})
            else:
                mod.set("name", name)

            # ensure module SDK (not SDK_HOME)
            opt_sdk = cfg.find("./option[@name='SDK_HOME']")
            if opt_sdk is None:
                ET.SubElement(cfg, "option", {"name": "SDK_HOME", "value": ""})
            else:
                opt_sdk.set("value", "")

            # working dir
            opt_wd = cfg.find("./option[@name='WORKING_DIRECTORY']")
            if opt_wd is None:
                ET.SubElement(cfg, "option", {"name": "WORKING_DIRECTORY", "value": workdir})
            else:
                opt_wd.set("value", workdir)

            # env vars (rewrite the trio we manage)
            envs = cfg.find("envs")
            if envs is None:
                envs = ET.SubElement(cfg, "envs")
            # remove existing of those names
            for env in list(envs.findall("env")):
                if env.get("name") in {"PROJECT_PATH", "VIRTUAL_ENV", "PYTHON_EXECUTABLE"}:
                    envs.remove(env)
            ET.SubElement(envs, "env", {"name": "PROJECT_PATH", "value": workdir})
            ET.SubElement(envs, "env", {"name": "VIRTUAL_ENV", "value": venv})
            ET.SubElement(envs, "env", {"name": "PYTHON_EXECUTABLE", "value": pyexe})

            _write_xml(tree, xml_path)
    debug("Patched run/debug configs with app/core working dir and env vars.")

# ---------------------------------------------------------------------------
# Core run configs (template or default)
# ---------------------------------------------------------------------------

def _core_template_dir() -> Path:
    for base in (ROOT / "pycharm", ROOT):
        if base.exists():
            return base
    return ROOT

def _write_text_xml(path: Path, root: ET.Element):
    path.parent.mkdir(parents=True, exist_ok=True)
    xml = ET.tostring(root, encoding="unicode")
    path.write_text(xml, encoding="utf-8", newline="\n")

def _materialize_core_from_template(core_name: str) -> bool:
    tpl = _core_template_dir() / "_template_core_run.xml"
    if not tpl.exists():
        return False
    text = tpl.read_text(encoding="utf-8").replace("{APP}", core_name)
    out = RUNCFG_DIR / f"_{core_name}_run.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    return True  # patching happens once later

def _create_default_pytest_core_run(core_name: str):
    workdir, venv, pyexe = _app_macros_for_dir(core_name, base="core")
    cfg_name = f"{core_name} tests"
    comp = ET.Element("component", {"name": "ProjectRunConfigurationManager"})
    cfg = ET.SubElement(comp, "configuration", {
        "type": "tests",
        "factoryName": "py.test",
        "name": cfg_name,
    })
    ET.SubElement(cfg, "module", {"name": core_name})
    ET.SubElement(cfg, "option", {"name": "WORKING_DIRECTORY", "value": workdir})
    ET.SubElement(cfg, "option", {"name": "ADD_CONTENT_ROOTS", "value": "true"})
    ET.SubElement(cfg, "option", {"name": "ADD_SOURCE_ROOTS", "value": "true"})
    ET.SubElement(cfg, "option", {"name": "testType", "value": "TEST_FOLDER"})
    ET.SubElement(cfg, "option", {"name": "FOLDER_NAME", "value": workdir})
    ET.SubElement(cfg, "option", {"name": "SDK_HOME", "value": ""})
    envs = ET.SubElement(cfg, "envs")
    ET.SubElement(envs, "env", {"name": "PROJECT_PATH", "value": workdir})
    ET.SubElement(envs, "env", {"name": "VIRTUAL_ENV", "value": venv})
    ET.SubElement(envs, "env", {"name": "PYTHON_EXECUTABLE", "value": pyexe})
    ET.SubElement(cfg, "method", {"v": "2"})
    out = RUNCFG_DIR / f"_{core_name}_tests.xml"
    _write_text_xml(out, comp)

def generate_core_run_configs(core_dirs: list[Path]):
    if not core_dirs:
        return
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)
    for d in core_dirs:
        name = d.name
        if not _materialize_core_from_template(name):
            _create_default_pytest_core_run(name)

# ---------------------------------------------------------------------------
# Discovery + Realization (single-pass, no redundancy)
# ---------------------------------------------------------------------------

@dataclass
class Mod:
    name: str        # module name == folder name
    path: Path       # folder path
    py: Path | None  # venv python if exists
    is_app: bool     # True for apps/*_project, False for core/*

def discover_modules() -> list[Mod]:
    mods: list[Mod] = []

    # apps: all *_project (SDK only if venv exists)
    if APPS_DIR.exists():
        for p in sorted(APPS_DIR.iterdir()):
            if p.is_dir() and p.name.endswith("_project"):
                py = ensure_uv_venv(p) if ENSURE_UV_VENVS else venv_python_for(p)
                mods.append(Mod(name=p.name, path=p, py=py, is_app=True))

    # core: attach only if venv exists
    if CORE_DIR.exists():
        for p in sorted(CORE_DIR.iterdir()):
            if not p.is_dir():
                continue
            if p.name.startswith((".", "__")):
                continue
            py = ensure_uv_venv(p) if ENSURE_UV_VENVS else venv_python_for(p)
            if py:
                mods.append(Mod(name=p.name, path=p, py=py, is_app=False))

    return mods

def bind_sdks(root_py: Path | None, mods: list[Mod]) -> tuple[str | None, dict[str, str]]:
    """Resolve actual SDK names and batch-register them once."""
    module_sdk_by_name: dict[str, str] = {}
    to_register: dict[str, str] = {}

    root_actual = None
    if root_py:
        root_actual = _sdk_name_for_home(str(root_py), PROJECT_SDK_NAME)
        to_register[root_actual] = str(root_py)

    for m in mods:
        if m.py:
            preferred = f"uv ({m.name})"
            actual = _sdk_name_for_home(str(m.py), preferred)
            module_sdk_by_name[m.name] = actual
            to_register[actual] = str(m.py)

    if to_register:
        _table_upsert_batch(to_register)

    return root_actual, module_sdk_by_name

def realize_project_layout(root_actual: str | None, mods: list[Mod], module_sdk_by_name: dict[str, str]):
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

    ensure_project_name(PROJECT_NAME)
    root_iml = ensure_root_module_iml(PROJECT_NAME)

    if root_actual:
        set_project_sdk(root_actual, SDK_TYPE)
        set_module_sdk(root_iml, root_actual)

    attached_names: set[str] = set()
    for m in mods:
        iml = ensure_app_module_iml(m.path)
        if m.py:
            set_module_sdk(iml, module_sdk_by_name[m.name])
        attached_names.add(m.name)

    # prune stale modules (keep root)
    for iml in MODULES_DIR.glob("*.iml"):
        name = iml.stem
        if name != PROJECT_NAME and name not in attached_names:
            remove_module(name)

    rebuild_modules_xml_from_disk()

def realize_run_configs(mods: list[Mod]):
    app_names = [m.name for m in mods if m.is_app]
    core_dirs = [m.path for m in mods if not m.is_app]

    # apps: via your generator script
    if GEN_SCRIPT.exists():
        for name in app_names:
            debug(f"Generating run configs for '{name}' via {GEN_SCRIPT.name} …")
            subprocess.run([sys.executable, str(GEN_SCRIPT), name], check=True, cwd=str(ROOT))
    else:
        debug(f"Missing {GEN_SCRIPT}; skipping run configuration generation for apps.")

    # core: via template or default pytest
    generate_core_run_configs(core_dirs)

    # one pass to enforce module binding + working dir + env vars
    patch_run_configs_for([m.name for m in mods])

def prune_sdks(root_actual: str | None, module_sdk_by_name: dict[str, str]):
    keep = set(module_sdk_by_name.values())
    if root_actual:
        keep.add(root_actual)
    _table_prune_sdks(keep)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Root interpreter (create if configured)
    root_py = ensure_uv_venv(ROOT) if ENSURE_UV_VENVS else venv_python_for(ROOT)
    if not root_py:
        debug("Root .venv not found; run `uv venv` at repo root if you want a project SDK.")

    # 2) Discover modules once
    mods = discover_modules()

    # 3) Resolve SDK names and batch-register them
    root_actual, module_sdk_by_name = bind_sdks(root_py, mods)

    # 4) Write project + modules (bind module SDKs)
    realize_project_layout(root_actual, mods, module_sdk_by_name)

    # 5) Generate run configs (apps + core), then patch once
    realize_run_configs(mods)

    # 6) Prune SDKs (keep only root + attached modules)
    prune_sdks(root_actual, module_sdk_by_name)

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
