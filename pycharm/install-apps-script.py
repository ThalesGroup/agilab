#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, List
import xml.etree.ElementTree as ET

# ----------------------------- paths / constants ----------------------------- #
ROOT = Path(__file__).parents[1]

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

# Optionally auto-create missing .venv with uv venv (so the SDKs are true uv)
ENSURE_UV_VENVS = True
UV_EXE = os.environ.get("UV_EXE", "uv")


# Optional modules.xml template (use {{MODULES}} placeholder)
MODULES_TEMPLATE = ROOT / "pycharm" / "templates" / "_template_app_modules.xml"

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
    """
    Return the python inside <project_dir>/.venv that looks like a real venv.
    Accept uv venvs where .venv/bin/python is a symlink to a shared CPython.
    """
    venv_dir = project_dir / ".venv"
    # must look like a venv
    has_marker = (venv_dir / "pyvenv.cfg").exists() or \
                 (venv_dir / "bin" / "activate").exists() or \
                 (venv_dir / "Scripts" / "activate").exists()

    if not has_marker:
        return None

    for c in (
        venv_dir / "bin" / "python3",
        venv_dir / "bin" / "python",
        venv_dir / "Scripts" / "python.exe",
    ):
        if c.exists():
            # accept even if it resolves outside .venv (typical for uv)
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
            content.set("url", "file://$PROJECT_DIR$")
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

        # accept either {{MODULES}} or <!-- MODULES -->
        if "{{MODULES}}" in body:
            body = body.replace("{{MODULES}}", modules_block)
        elif "<!-- MODULES -->" in body:
            body = body.replace("<!-- MODULES -->", modules_block)
        else:
            # fallback: inject before </modules>
            insert_at = body.rfind("</modules>")
            if insert_at == -1:
                raise ValueError("No placeholder and no </modules> tag in template")
            body = body[:insert_at] + modules_block + "\n" + body[insert_at:]

        out = IDEA / "modules.xml"
        out.parent.mkdir(parents=True, exist_ok=True)
        if not body.endswith("\n"):
            body += "\n"
        out.write_text(body, encoding="utf-8")
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
    """
    Ensure a 'uv (<module_name>)' SDK exists.
    - Only use the app's own .venv (create with uv if allowed).
    - Do NOT fall back to root venv for app modules.
    """
    py = ensure_uv_venv(app_dir) if ENSURE_UV_VENVS else venv_python_for(app_dir)
    if not py:
        debug(f"{module_name}: no .venv → not creating SDK")
        return None
    sdk_name = f"uv ({module_name})"
    _table_upsert_batch({sdk_name: str(py)})
    return sdk_name

# ---------- discovery / attach / cleanup ----------
def _eligible_core_projects() -> list[Path]:
    if not CORE_DIR.exists():
        return []
    out: list[Path] = []
    for p in sorted(CORE_DIR.iterdir()):
        if not p.is_dir():
            continue
        if p.name.startswith((".", "__")):
            continue
        if venv_python_for(p):
            out.append(p)
    return out

def _eligible_apps(require_venv: bool) -> list[Path]:
    """Only subprojects ending with _project (optionally require .venv)."""
    if not APPS_DIR.exists():
        return []
    apps: list[Path] = []
    for p in sorted(APPS_DIR.iterdir()):
        if p.is_dir() and p.name.endswith("_project") or (require_venv and not (venv_python_for(p) is None)):
            apps.append(p)
    return apps

def attach_all_subprojects(root_py: Optional[Path]) -> None:
    to_attach = _eligible_apps(require_venv=ATTACH_ONLY_VENVS)
    attached_names = [a.name for a in to_attach]

    if not to_attach:
        debug("No eligible subprojects found under src/agilab/apps")
    else:
        for a in to_attach:
            module_name = a.name
            iml = ensure_app_module_iml(a)

            # Create/detect per-app venv; DO NOT fall back to root
            py = ensure_uv_venv(a) if ENSURE_UV_VENVS else venv_python_for(a)
            if py:
                preferred = f"uv ({module_name})"
                actual = _sdk_name_for_home(str(py), preferred)
                _table_upsert_batch({actual: str(py)})   # ensure SDK exists
                set_module_sdk(iml, actual)              # bind module to its own SDK
                debug(f"{module_name}: module SDK set to '{actual}'")
                attached_names.append(module_name)
            else:
                debug(f"{module_name}: leaving module on inheritedJdk (no interpreter available)")
    # Drop any stale module .iml that isn’t attached now (except the root)
    for iml in MODULES_DIR.glob("*.iml"):
        name = iml.stem
        if name != PROJECT_NAME and name not in attached_names:
            remove_module(name)

    # modules.xml via template (if present) or fallback build
    rebuild_modules_xml_from_disk()

    # Generate run configs for attached apps only
    if GEN_SCRIPT.exists():
        for name in attached_names:
            debug(f"Generating run configs for '{name}' via {GEN_SCRIPT.name} …")
            subprocess.run([sys.executable, str(GEN_SCRIPT), name], check=True, cwd=str(ROOT))
    else:
        debug(f"Missing {GEN_SCRIPT}; skipping run configuration generation.")

    # NEW: generate for core
    generate_core_run_configs(core_dirs)

    # optional: patch everything (apps + core) to enforce WORKING_DIRECTORY/env/module
    patch_run_configs_for([p.name for p in app_dirs + core_dirs])
    debug("Patched run/debug configs with app/core working dir and env vars.")

    return attached_names



def _app_macros(app: str):
    workdir = f"$PROJECT_DIR$/src/agilab/apps/{app}"
    venv    = f"{workdir}/.venv"
    pyexe   = f"{venv}/Scripts/python.exe" if os.name == "nt" else f"{venv}/bin/python"
    return workdir, venv, pyexe

def _ensure_child(parent: ET.Element, tag: str, attrs: dict | None = None) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag, attrs or {})
    return el

def _ensure_env(envs: ET.Element, name: str, value: str):
    el = envs.find(f"./env[@name='{name}']")
    if el is None:
        ET.SubElement(envs, "env", {"name": name, "value": value})
    else:
        el.set("value", value)

import os
import xml.etree.ElementTree as ET

def _app_macros(app: str):
    workdir = f"$PROJECT_DIR$/src/agilab/apps/{app}"
    venv    = f"{workdir}/.venv"
    pyexe   = f"{venv}/Scripts/python.exe" if os.name == "nt" else f"{venv}/bin/python"
    return workdir, venv, pyexe

def _ensure_child(parent: ET.Element, tag: str, attrs: dict | None = None) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag, attrs or {})
    return el

def _ensure_env(envs: ET.Element, name: str, value: str):
    el = envs.find(f"./env[@name='{name}']")
    if el is None:
        ET.SubElement(envs, "env", {"name": name, "value": value})
    else:
        el.set("value", value)

def patch_run_configs_for(app_names: list[str]):
    rc_dir = RUNCFG_DIR
    if not rc_dir.exists():
        return

    for xml in sorted(rc_dir.glob("*.xml")):
        try:
            tree = ET.parse(str(xml))
        except ET.ParseError:
            continue

        root = tree.getroot()
        cfg = root.find(".//configuration")
        if cfg is None:
            continue

        # which app does this config belong to?
        cfg_name = cfg.get("name", "")
        app = next((a for a in app_names if xml.name.startswith(f"_{a}_") or a in cfg_name), None)
        if not app:
            continue

        workdir = f"$PROJECT_DIR$/src/agilab/apps/{app}"
        venv    = f"{workdir}/.venv"
        pyexe   = f"{venv}/Scripts/python.exe" if os.name == "nt" else f"{venv}/bin/python"

        # 1) Always bind to module SDK
        mod = cfg.find("./module")
        if mod is None:
            ET.SubElement(cfg, "module", {"name": app})
        else:
            mod.set("name", app)

        # 2) Never override with a specific SDK path
        sdk_home = cfg.find("./option[@name='SDK_HOME']")
        if sdk_home is not None:
            sdk_home.set("value", "")

        # 3) Working dir + envs (force overwrite)
        wd = cfg.find("./option[@name='WORKING_DIRECTORY']")
        if wd is None:
            ET.SubElement(cfg, "option", {"name": "WORKING_DIRECTORY", "value": workdir})
        else:
            wd.set("value", workdir)

        envs = _ensure_child(cfg, "envs")
        def ensure_env(k, v):
            e = envs.find(f"./env[@name='{k}']")
            (e.set("value", v) if e is not None else ET.SubElement(envs, "env", {"name": k, "value": v}))
        ensure_env("PROJECT_PATH", workdir)
        ensure_env("VIRTUAL_ENV", venv)
        ensure_env("PYTHON_EXECUTABLE", pyexe)

        xml.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8", newline="\n")

def _all_jdk_tables() -> list[Path]:
    tables = []
    for base in _jb_base_dirs():
        for product in ("PyCharm*", "PyCharmCE*"):
            for candidate in base.glob(product):
                p = candidate / "options" / "jdk.table.xml"
                if p.parent.exists():
                    tables.append(p)  # include even if file not created yet
    return tables

def _sdk_name_for_home(home_path: str, preferred: str) -> str:
    """
    If an SDK already exists for this interpreter homePath, reuse its existing name.
    Otherwise return 'preferred'.
    """
    for tbl in _all_jdk_tables():
        if not tbl.exists():
            continue
        try:
            tree = ET.parse(str(tbl))
        except ET.ParseError:
            continue
        comp = tree.getroot().find("./component[@name='ProjectJdkTable']")
        if comp is None:
            continue
        for jdk in comp.findall("jdk"):
            hp = jdk.find("homePath")
            hpv = (hp.get("value") if hp is not None else jdk.attrib.get("homePath")) or ""
            if hpv == home_path:
                nm = jdk.find("name")
                return nm.get("value") if nm is not None else jdk.attrib.get("name", preferred)
    return preferred

def _core_template_dir() -> Path:
    # look next to gen script first, then project root
    for base in (ROOT / "pycharm", ROOT):
        d = base
        if d.exists():
            return d
    return ROOT

def _app_macros_for_dir(dirname: str, base: str) -> tuple[str, str, str]:
    workdir = f"$PROJECT_DIR$/src/agilab/{base}/{dirname}"
    venv    = f"{workdir}/.venv"
    pyexe   = f"{venv}/Scripts/python.exe" if os.name == "nt" else f"{venv}/bin/python"
    return workdir, venv, pyexe

def _write_text_xml(path: Path, root: ET.Element):
    path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8", newline="\n")

def _materialize_core_from_template(core_name: str) -> bool:
    tpl_dir = _core_template_dir()
    tpl = tpl_dir / "_template_core_run.xml"
    if not tpl.exists():
        return False
    text = tpl.read_text(encoding="utf-8").replace("{APP}", core_name)
    out = RUNCFG_DIR / f"_{core_name}_run.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    # patch WORKING_DIRECTORY + envs + module tag, just like apps
    return True

def _create_default_pytest_core_run(core_name: str):
    """Create a minimal, valid PyTest run configuration for the core module."""
    workdir, venv, pyexe = _app_macros_for_dir(core_name, base="core")
    cfg_name = f"{core_name} tests"

    comp = ET.Element("component", {"name": "ProjectRunConfigurationManager"})
    cfg = ET.SubElement(comp, "configuration", {
        "type": "tests",              # PyTest
        "factoryName": "py.test",
        "name": cfg_name,
    })
    ET.SubElement(cfg, "module", {"name": core_name})
    ET.SubElement(cfg, "option", {"name": "WORKING_DIRECTORY", "value": workdir})
    ET.SubElement(cfg, "option", {"name": "ADD_CONTENT_ROOTS", "value": "true"})
    ET.SubElement(cfg, "option", {"name": "ADD_SOURCE_ROOTS", "value": "true"})
    # Run tests in folder
    ET.SubElement(cfg, "option", {"name": "testType", "value": "TEST_FOLDER"})
    ET.SubElement(cfg, "option", {"name": "FOLDER_NAME", "value": workdir})
    # Ensure module SDK (not SDK_HOME)
    ET.SubElement(cfg, "option", {"name": "SDK_HOME", "value": ""})
    # Env vars
    envs = ET.SubElement(cfg, "envs")
    ET.SubElement(envs, "env", {"name": "PROJECT_PATH", "value": workdir})
    ET.SubElement(envs, "env", {"name": "VIRTUAL_ENV", "value": venv})
    ET.SubElement(envs, "env", {"name": "PYTHON_EXECUTABLE", "value": pyexe})
    ET.SubElement(cfg, "method", {"v": "2"})

    out = RUNCFG_DIR / f"_{core_name}_tests.xml"
    _write_text_xml(out, comp)

def generate_core_run_configs(core_dirs: list[Path]):
    """
    For each core module:
      - Use _template_core_run.xml if present (with {APP} replacement),
      - else create a default PyTest config bound to that module + venv.
    """
    if not core_dirs:
        return
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)
    for d in core_dirs:
        name = d.name
        if not _materialize_core_from_template(name):
            _create_default_pytest_core_run(name)

# ----------------------------- main ----------------------------- #
def main() -> int:
    IDEA.mkdir(exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

    ensure_project_name(PROJECT_NAME)

    # Root project SDK -> uv (agilab) bound to ROOT/.venv python
    root_py = ensure_uv_venv(ROOT) if ENSURE_UV_VENVS else venv_python_for(ROOT)
    root_iml = ensure_root_module_iml(PROJECT_NAME)

    if root_py:
        # Resolve name that IDE already uses for this interpreter, or keep preferred
        root_preferred = PROJECT_SDK_NAME              # e.g. "uv (agilab)"
        root_actual = _sdk_name_for_home(str(root_py), root_preferred)

        # Register (with UV marker/roots), set project + root module SDK to that name
        _table_upsert_batch({root_actual: str(root_py)})
        set_project_sdk(root_actual, SDK_TYPE)
        set_module_sdk(root_iml, root_actual)
    else:
        debug("Root .venv not found; run `uv venv` at repo root if you want a project SDK.")

    # Attach subprojects and bind interpreters (returns attached names)
    attached = attach_all_subprojects(root_py)

    # Keep exactly one interpreter per project (root + each attached app)
    keep_names: set[str] = { _sdk_name_for_home(str(root_py), PROJECT_SDK_NAME) } if root_py else set()
    keep_names.update(_sdk_name_for_home(str((APPS_DIR / name / '.venv' / ('Scripts/python.exe' if os.name=='nt' else 'bin/python'))), f"uv ({name})")
                        for name in attached)
    # Fall back to preferred names if resolving home fails:
    keep_names.update({f"uv ({name})" for name in attached})
    if root_py:
        keep_names.add(PROJECT_SDK_NAME)

    _table_prune_sdks(keep_names)

    # (Optional) ensure run configs show app workdir/env even if template disagrees
    patch_run_configs_for(attached)
    debug("Patched run/debug configs with app working dir and env vars.")

    debug("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
