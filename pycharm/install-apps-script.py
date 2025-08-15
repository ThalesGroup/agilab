#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, List
import xml.etree.ElementTree as ET

# ----------------------------- paths / constants ----------------------------- #
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
PROJECT_NAME = IDEA.parent.name
PROJECT_SDK_NAME = f"uv ({PROJECT_NAME})"
APPS_DIR = ROOT / "src" / PROJECT_NAME / "apps"
GEN_SCRIPT = (ROOT / "pycharm" / "gen-app-script.py") if (ROOT / "pycharm" / "gen-app-script.py").exists() else (ROOT / "gen-app-script.py")
SDK_TYPE = "Python SDK"

# Attach only subprojects that already have a .venv
ATTACH_ONLY_VENVS = True

# Optionally auto-create missing .venv with uv venv (so the SDKs are true uv)
ENSURE_UV_VENVS = True
UV_EXE = os.environ.get("UV_EXE", "uv")

# Optional modules.xml template (use {{MODULES}} placeholder)
MODULES_TEMPLATE = ROOT / "pycharm" / "templates" / "modules.xml.tmpl"

# ----------------------------- utils ----------------------------- #
def debug(msg: str) -> None:
    print(f"[install-apps] {msg}")

def _write_xml(elem_or_tree, dest: Path) -> None:
    """Binary write avoids str/bytes mismatch on Python 3.13."""
    tree = elem_or_tree if isinstance(elem_or_tree, ET.ElementTree) else ET.ElementTree(elem_or_tree)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        tree.write(f, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)

def read_xml(path: Path) -> ET.ElementTree:
    return ET.parse(str(path))

def venv_python_for(project_dir: Path) -> Optional[Path]:
    for c in (
        project_dir / ".venv" / "bin" / "python3",
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ):
        if c.exists():
            return c.resolve()
    return None

def ensure_uv_venv(project_dir: Path) -> Optional[Path]:
    py = venv_python_for(project_dir)
    if py or not ENSURE_UV_VENVS:
        return py
    try:
        debug(f"{project_dir.name}: creating .venv via `uv venv` …")
        subprocess.run([UV_EXE, "venv"], cwd=str(project_dir), check=True)
    except Exception as e:
        debug(f"{project_dir.name}: uv venv failed: {e}")
        return None
    return venv_python_for(project_dir)

def as_project_macro(path: Path) -> str:
    rel = path.resolve().relative_to(ROOT.resolve())
    return f"$PROJECT_DIR$/{rel.as_posix()}"

def as_project_url(path: Path) -> str:
    return f"file://{as_project_macro(path)}"

def _rel_from_root(path: Path) -> Optional[Path]:
    try:
        return path.relative_to(ROOT)  # DO NOT resolve(); keep macros stable
    except ValueError:
        return None

def app_rel_content_url(app_dir: Path) -> str:
    rel = _rel_from_root(app_dir)
    if rel is not None:
        return f"file://$PROJECT_DIR$/{rel.as_posix()}"
    return f"file://{app_dir.resolve().as_posix()}"

# ----------------------------- root project name & module ----------------------------- #
def ensure_project_name(name: str) -> None:
    name_file = IDEA / ".name"
    try:
        old = name_file.read_text(encoding="utf-8").strip()
    except Exception:
        old = ""
    if old != name:
        name_file.parent.mkdir(parents=True, exist_ok=True)
        name_file.write_text(name + "\n", encoding="utf-8")
        debug(f"Set project name to '{name}' (.idea/.name)")

def ensure_root_module_iml(name: str) -> Path:
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    iml = MODULES_DIR / f"{name}.iml"

    def _write_minimal(dest: Path):
        m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
        comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
        ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
        _write_xml(m, dest)

    if not iml.exists() or iml.stat().st_size == 0:
        _write_minimal(iml)
        debug(f"Root module IML created: {iml}")
        return iml

    try:
        tree = read_xml(iml)
        root = tree.getroot()
        if root.tag != "module":
            raise ET.ParseError("root tag is not <module>")
        comp = root.find("./component[@name='NewModuleRootManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
        content = comp.find("content")
        if content is None:
            ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
        else:
            content.set("url", "file://$PROJECT_DIR$"})
        has_jdk = any(oe.get("type") in {"inheritedJdk", "jdk"} for oe in comp.findall("orderEntry"))
        if not has_jdk:
            ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        has_src = any(oe.get("type") == "sourceFolder" for oe in comp.findall("orderEntry"))
        if not has_src:
            ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
        _write_xml(tree, iml)
        return iml
    except ET.ParseError:
        _write_minimal(iml)
        debug(f"Root module IML repaired: {iml}")
        return iml

# ----------------------------- modules.xml / .iml for apps ----------------------------- #
def ensure_app_module_iml(app_dir: Path) -> Path:
    module_name = app_dir.name
    iml_path = MODULES_DIR / f"{module_name}.iml"
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
    _write_xml(m, iml_path)
    debug(f"IML created: {iml_path}")
    return iml_path

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

def remove_module(module_name: str) -> None:
    iml = MODULES_DIR / f"{module_name}.iml"
    if iml.exists():
        iml.unlink()
        debug(f"Removed module IML: {iml}")

def _build_module_lines() -> list[str]:
    """Return the module lines to embed in modules.xml (using macros)."""
    imls = sorted(MODULES_DIR.glob("*.iml"))
    lines = [
        f'      <module fileurl="{as_project_url(p)}" filepath="{as_project_macro(p)}"/>' for p in imls
    ]
    return lines

def _write_modules_from_template() -> bool:
    if not MODULES_TEMPLATE.exists():
        return False
    try:
        body = MODULES_TEMPLATE.read_text(encoding="utf-8")
        modules_block = "\n".join(_build_module_lines())
        body = body.replace("{{MODULES}}", modules_block)
        out = IDEA / "modules.xml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body + ("\n" if not body.endswith("\n") else ""), encoding="utf-8")
        debug(f"modules.xml written from template: {out}")
        return True
    except Exception as e:
        debug(f"Template write failed: {e}")
        return False

def rebuild_modules_xml_from_disk() -> None:
    """If template exists, use it; else write a compact, valid file."""
    if _write_modules_from_template():
        return
    lines = _build_module_lines()
    with open(IDEA / "modules.xml", "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<project version="4">\n')
        f.write('  <component name="ProjectModuleManager">\n')
        f.write('    <modules>\n')
        for line in lines:
            f.write(line + "\n")
        f.write('    </modules>\n')
        f.write('  </component>\n')
        f.write('</project>\n')
    debug(f"modules.xml rebuilt with {len(lines)} module(s)")

# ----------------------------- JetBrains SDK registry ----------------------------- #
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

def _find_jdk_tables() -> List[Path]:
    """Return candidate jdk.table.xml paths even if the file doesn't exist yet."""
    tables: List[Path] = []
    for base in _jb_base_dirs():
        for product in ("PyCharm*", "PyCharmCE*"):
            for candidate in base.glob(product):
                options = candidate / "options"
                if options.exists():
                    tables.append(options / "jdk.table.xml")
    return tables

def _load_or_init_jdk_table(path: Path) -> ET.ElementTree:
    if path.exists():
        try:
            return read_xml(path)
        except ET.ParseError:
            pass
    root = ET.Element("application")
    ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
    return ET.ElementTree(root)

def _ensure_roots_additional(jdk: ET.Element) -> None:
    if jdk.find("roots") is None: ET.SubElement(jdk, "roots")
    if jdk.find("additional") is None: ET.SubElement(jdk, "additional")

def _ensure_uv_option(jdk: ET.Element) -> None:
    add = jdk.find("additional")
    if add is None:
        add = ET.SubElement(jdk, "additional")
    uv_opt = None
    for o in add.findall("option"):
        if o.get("name") == "UV":
            uv_opt = o
            break
    if uv_opt is None:
        ET.SubElement(add, "option", {"name": "UV", "value": "true"})
    else:
        uv_opt.set("value", "true")

def _table_upsert_batch(name_to_home: dict[str, str]) -> None:
    """Remove old entries by name, then insert fresh ones with uv marker."""
    tables_data = []
    for tbl in _find_jdk_tables():
        tree = _load_or_init_jdk_table(tbl)
        root = tree.getroot()
        comp = root.find("./component[@name='ProjectJdkTable']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
        tables_data.append((tbl, tree, comp))

    if not tables_data:
        debug("No JetBrains jdk.table.xml found; open PyCharm once so it creates it.")
        return

    for path, tree, comp in tables_data:
        wanted = set(name_to_home.keys())
        for jdk in list(comp.findall("jdk")):
            nm_el = jdk.find("name")
            nm = nm_el.get("value") if nm_el is not None else jdk.attrib.get("name")
            if nm in wanted:
                comp.remove(jdk)
        for name, home in name_to_home.items():
            j = ET.SubElement(comp, "jdk", {"version": "2"})
            ET.SubElement(j, "name", {"value": name})
            ET.SubElement(j, "type", {"value": SDK_TYPE})
            ET.SubElement(j, "homePath", {"value": home})
            _ensure_roots_additional(j)
            _ensure_uv_option(j)
        _write_xml(tree, path)
        debug(f"Updated {path} with {len(name_to_home)} SDK(s)")

def _table_prune_sdks(keep_names: set[str]) -> None:
    """Keep only Python SDKs whose name is in keep_names; fix kept ones."""
    for tbl in _find_jdk_tables():
        tree = _load_or_init_jdk_table(tbl)
        root = tree.getroot()
        comp = root.find("./component[@name='ProjectJdkTable']")
        if comp is None:
            continue
        changed = False
        for jdk in list(comp.findall("jdk")):
            name_el = jdk.find("name")
            nm = name_el.get("value") if name_el is not None else jdk.attrib.get("name")
            type_el = jdk.find("type")
            tp = type_el.get("value") if type_el is not None else jdk.attrib.get("type")
            if tp == SDK_TYPE and (nm is None or nm not in keep_names):
                comp.remove(jdk)
                changed = True
            elif tp == SDK_TYPE and nm in keep_names:
                _ensure_roots_additional(jdk)
                _ensure_uv_option(jdk)
                changed = True
        if changed:
            _write_xml(tree, tbl)
            debug(f"Pruned SDKs in {tbl}, kept: {sorted(keep_names)}")

# ----------------------------- project SDK (misc.xml) ----------------------------- #
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
    prm.set("version", "2")
    prm.set("project-jdk-name", name)
    prm.set("project-jdk-type", sdk_type)
    _write_xml(tree, misc)
    debug(f"Project SDK set to '{name}' in misc.xml")

# ----------------------------- ensure module SDK exists ----------------------------- #
def ensure_module_sdk_exists(module_name: str, app_dir: Path, root_py: Optional[Path]) -> Optional[str]:
    """Ensure a 'uv (<module_name>)' SDK exists; prefer per-app uv venv."""
    py = ensure_uv_venv(app_dir) or root_py
    if not py:
        debug(f"{module_name}: no .venv (and no root venv) → cannot create SDK")
        return None
    sdk_name = f"uv ({module_name})"
    _table_upsert_batch({sdk_name: str(py)})
    return sdk_name

# ---------- discovery / attach / cleanup ----------
def _eligible_apps(require_venv: bool) -> list[Path]:
    """Only subprojects ending with _project (optionally require .venv)."""
    if not APPS_DIR.exists():
        return []
    apps: list[Path] = []
    for p in sorted(APPS_DIR.iterdir()):
        if not p.is_dir():
            continue
        if not p.name.endswith("_project"):
            continue
        if require_venv and not venv_python_for(p):
            continue
        apps.append(p)
    return apps

def attach_all_subprojects(root_py: Optional[Path]) -> None:
    to_attach = _eligible_apps(require_venv=ATTACH_ONLY_VENVS)
    attached_names = set(a.name for a in to_attach)

    if not to_attach:
        debug("No eligible subprojects found under src/agilab/apps")
    else:
        for a in to_attach:
            module_name = a.name
            iml = ensure_app_module_iml(a)
            sdk_name = ensure_module_sdk_exists(module_name, a, root_py)
            if sdk_name:
                set_module_sdk(iml, sdk_name)
                debug(f"{module_name}: module SDK set to '{sdk_name}'")
            else:
                debug(f"{module_name}: leaving module on inheritedJdk (no interpreter available)")

    # Remove any existing modules not in the newly attached set (keep the root)
    for iml in MODULES_DIR.glob("*.iml"):
        name = iml.stem
        if name == PROJECT_NAME:
            continue
        if name not in attached_names:
            remove_module(name)

    # modules.xml via template (if present) or fallback build
    rebuild_modules_xml_from_disk()

    # Generate run configs only for attached apps
    if GEN_SCRIPT.exists():
        for a in to_attach:
            module_name = a.name
            debug(f"Generating run configs for '{module_name}' via {GEN_SCRIPT.name} …")
            subprocess.run([sys.executable, str(GEN_SCRIPT), module_name], check=True, cwd=str(ROOT))
    else:
        debug(f"Missing {GEN_SCRIPT}; skipping run configuration generation.")

# ----------------------------- main ----------------------------- #
def main() -> int:
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

    ensure_project_name(PROJECT_NAME)

    # Root project SDK -> uv (agilab) bound to ROOT/.venv python
    root_py = ensure_uv_venv(ROOT) if ENSURE_UV_VENVS else venv_python_for(ROOT)
    if root_py:
        _table_upsert_batch({PROJECT_SDK_NAME: str(root_py)})
        set_project_sdk(PROJECT_SDK_NAME, SDK_TYPE)
    else:
        debug("Root .venv not found; run `uv venv` at repo root if you want a project SDK.")

    # Ensure root module and bind it explicitly (avoid <No Interpreter>)
    root_iml = ensure_root_module_iml(PROJECT_NAME)
    if root_py:
        set_module_sdk(root_iml, PROJECT_SDK_NAME)

    # Attach subprojects and bind interpreters
    attach_all_subprojects(root_py)

    # Keep exactly one interpreter per project (root + each attached app)
    keep_names: set[str] = {PROJECT_SDK_NAME}
    keep_names.update(f"uv ({p.name})" for p in _eligible_apps(require_venv=ATTACH_ONLY_VENVS))
    _table_prune_sdks(keep_names)

    debug("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
