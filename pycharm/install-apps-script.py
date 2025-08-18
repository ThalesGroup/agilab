#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Iterable, Dict, List, Tuple
import xml.etree.ElementTree as ET

# =============================================================================
# Config
# =============================================================================

@dataclass(frozen=True)
class Config:
    root: Path
    idea: Path
    modules_dir: Path
    runcfg_dir: Path
    project_name: str
    project_sdk_name: str  # e.g., "uv (agilab)"
    apps_dir: Path
    core_dir: Path
    gen_script: Path
    sdk_type: str = "Python SDK"

    # behavior flags
    attach_only_venvs: bool = True
    ensure_uv_venvs_apps: bool = True   # apps: create .venv if missing
    ensure_uv_venvs_core: bool = False  # core: attach only if .venv already exists (no run configs)

# allow adding modules that resolve outside the repo
ALLOW_EXTERNAL_MODULES = False

def find_idea_dir(root: Path) -> Path:
    for name in (".idea", "idea"):
        d = root / name
        if d.exists():
            return d
    return root / ".idea"

ROOT = Path(__file__).parents[1]
IDEA = find_idea_dir(ROOT)
CFG = Config(
    root=ROOT,
    idea=IDEA,
    modules_dir=IDEA / "modules",
    runcfg_dir=IDEA / "runConfigurations",
    project_name=IDEA.parent.name,
    project_sdk_name=f"uv ({IDEA.parent.name})",
    apps_dir=ROOT / "src" / IDEA.parent.name / "apps",
    core_dir=ROOT / "src" / IDEA.parent.name / "core",
    gen_script=(ROOT / "pycharm" / "gen-app-script.py") if (ROOT / "pycharm" / "gen-app-script.py").exists() else (ROOT / "gen-app-script.py"),
)

# =============================================================================
# Logging
# =============================================================================

def log(msg: str) -> None:
    print(f"[install-apps] {msg}")

# =============================================================================
# XML helpers
# =============================================================================

def _indent(tree: ET.ElementTree) -> None:
    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass

def write_xml(tree: ET.ElementTree, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _indent(tree)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)

def read_xml(path: Path) -> ET.ElementTree:
    return ET.parse(str(path))

def as_project_macro(p: Path) -> str:
    rel = p.resolve().relative_to(CFG.root.resolve())
    return f"$PROJECT_DIR$/{rel.as_posix()}"

def as_project_url(p: Path) -> str:
    return f"file://{as_project_macro(p)}"

def content_url_for(dir_path: Path) -> str:
    try:
        rel = dir_path.relative_to(CFG.root)   # keep macros, no resolve here
        return f"file://$PROJECT_DIR$/{rel.as_posix()}"
    except ValueError:
        return f"file://{dir_path.resolve().as_posix()}"

def _ensure_modules_xml() -> ET.ElementTree:
    modules_xml = CFG.idea / "modules.xml"
    if modules_xml.exists():
        try:
            return read_xml(modules_xml)
        except ET.ParseError:
            pass  # recreate
    project = ET.Element("project", {"version": "4"})
    ET.SubElement(ET.SubElement(project, "component", {"name": "ProjectModuleManager"}), "modules")
    tree = ET.ElementTree(project)
    write_xml(tree, modules_xml)
    return tree

# ---- modules.xml merge helpers ----

def _modules_node(tree: ET.ElementTree) -> ET.Element:
    root = tree.getroot()
    comp = root.find("./component[@name='ProjectModuleManager']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectModuleManager"})
    mods = comp.find("modules")
    if mods is None:
        mods = ET.SubElement(comp, "modules")
    return mods

def _norm_path_attr(val: Optional[str]) -> str:
    return (val or "").strip()

def _entry_key(el: ET.Element) -> Tuple[str, str]:
    return (_norm_path_attr(el.get("filepath")), _norm_path_attr(el.get("fileurl")))

def _resolve_macros(raw: str, app_name: str) -> Path:
    s = raw.replace("{APP}", app_name)
    s = s.replace("$PROJECT_DIR$", str(CFG.root))
    s = s.replace("$USER_HOME$", str(Path.home()))
    if s.startswith("file://"):
        s = s[len("file://"):]
    return Path(s)

def _is_within_repo(p: Path) -> bool:
    try:
        return p.resolve().is_relative_to(CFG.root.resolve())
    except AttributeError:
        rp = str(CFG.root.resolve())
        return str(p.resolve()).startswith(rp + os.sep)

# =============================================================================
# Venv (uv)
# =============================================================================

def venv_python_for(project_dir: Path) -> Optional[Path]:
    for c in (
        project_dir / ".venv" / "bin" / "python3",
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ):
        if c.exists():
            try:
                return c.resolve()
            except Exception:
                return c
    return None

def ensure_uv_venv(project_dir: Path) -> Optional[Path]:
    py = venv_python_for(project_dir)
    if py:
        return py
    try:
        name = project_dir.name if project_dir != CFG.root else CFG.project_name
        log(f"{name}: creating .venv via `uv venv` …")
        subprocess.run(["uv", "venv"], cwd=str(project_dir), check=True)
    except Exception as e:
        log(f"{project_dir.name}: uv venv failed: {e}")
        return None
    return venv_python_for(project_dir)

# =============================================================================
# JDK table manager
# =============================================================================

class JdkTable:
    """Manage JetBrains jdk.table.xml across all PyCharm configs (CE and Pro)."""

    def __init__(self, sdk_type: str):
        self.sdk_type = sdk_type

    @staticmethod
    def _jb_base_dirs() -> List[Path]:
        home = Path.home()
        out: List[Path] = []
        if sys.platform == "darwin":
            out.append(home / "Library" / "Application Support" / "JetBrains")
        elif os.name == "nt":
            appdata = os.environ.get("APPDATA")
            if appdata:
                out.append(Path(appdata) / "JetBrains")
        else:
            out.append(home / ".config" / "JetBrains")
        return [b for b in out if b.exists()]

    def _tables(self) -> List[Path]:
        res: List[Path] = []
        for base in self._jb_base_dirs():
            for product in ("PyCharm*", "PyCharmCE*"):
                for candidate in base.glob(product):
                    p = candidate / "options" / "jdk.table.xml"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    res.append(p)
        return res

    @staticmethod
    def _ensure_component(root: ET.Element) -> ET.Element:
        comp = root.find("./component[@name='ProjectJdkTable']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
        return comp

    @staticmethod
    def _ensure_roots(jdk_el: ET.Element) -> None:
        if jdk_el.find("roots") is None:
            ET.SubElement(jdk_el, "roots")

    def _load_or_init(self, path: Path) -> ET.ElementTree:
        if path.exists():
            try:
                return read_xml(path)
            except ET.ParseError:
                root = ET.Element("application")
                self._ensure_component(root)
                return ET.ElementTree(root)
        root = ET.Element("application")
        self._ensure_component(root)
        return ET.ElementTree(root)

    def upsert_many(self, name_to_home: Dict[str, str]) -> None:
        changed_any = False
        for table in self._tables():
            tree = self._load_or_init(table)
            root = tree.getroot()
            comp = self._ensure_component(root)
            changed = False

            for name, home in name_to_home.items():
                target: Optional[ET.Element] = None
                for jdk in comp.findall("jdk"):
                    nm = jdk.find("name")
                    if nm is not None and nm.get("value") == name:
                        target = jdk
                        break
                    if nm is None and jdk.attrib.get("name") == name:
                        target = jdk
                        break

                if target is None:
                    target = ET.SubElement(comp, "jdk", {"version": "2"})
                    ET.SubElement(target, "name", {"value": name})
                    ET.SubElement(target, "type", {"value": self.sdk_type})
                    ET.SubElement(target, "homePath", {"value": home})
                    self._ensure_roots(target)
                    changed = True
                else:
                    name_el = target.find("name")
                    if name_el is None:
                        name_el = ET.SubElement(target, "name", {"value": name})
                    name_el.set("value", name)

                    type_el = target.find("type")
                    if type_el is None:
                        type_el = ET.SubElement(target, "type", {"value": self.sdk_type})
                    type_el.set("value", self.sdk_type)

                    home_el = target.find("homePath")
                    if home_el is None:
                        home_el = ET.SubElement(target, "homePath", {"value": home})
                    if home_el.get("value") != home:
                        home_el.set("value", home)
                        changed = True

                    self._ensure_roots(target)

            if changed:
                write_xml(tree, table)
                changed_any = True
                log(f"Updated {table} with {len(name_to_home)} SDK(s)")
        if not changed_any:
            log("No JetBrains jdk.table.xml found yet (open PyCharm once).")

    def prune_uv_names(self, keep_names: Iterable[str]) -> None:
        keep = set(keep_names)
        for table in self._tables():
            if not table.exists():
                continue
            try:
                tree = read_xml(table)
            except ET.ParseError:
                continue
            root = tree.getroot()
            comp = self._ensure_component(root)
            removed = 0
            for jdk in list(comp.findall("jdk")):
                nm = (jdk.findtext("name") if jdk.find("name") is not None else jdk.attrib.get("name", ""))
                tp = (jdk.find("type").get("value") if jdk.find("type") is not None else jdk.attrib.get("type", ""))
                if tp == self.sdk_type and nm.startswith("uv (") and nm not in keep:
                    comp.remove(jdk)
                    removed += 1
            if removed:
                write_xml(tree, table)
                log(f"Pruned SDKs in {table}, kept: {sorted(keep)}")

# =============================================================================
# Project model (misc.xml, .iml, and modules.xml MERGE from app template)
# =============================================================================

class ProjectModel:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    # ---- misc.xml / root module ----

    def ensure_project_name(self) -> None:
        name_file = self.cfg.idea / ".name"
        content = (name_file.read_text(encoding="utf-8").strip() if name_file.exists() else "")
        if content != self.cfg.project_name:
            name_file.parent.mkdir(parents=True, exist_ok=True)
            name_file.write_text(self.cfg.project_name + "\n", encoding="utf-8")
            log(f"Set project name to '{self.cfg.project_name}' (.idea/.name)")

    def set_project_sdk(self, name: str) -> None:
        misc = self.cfg.idea / "misc.xml"
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
        prm.set("project-jdk-type", CFG.sdk_type)
        write_xml(tree, misc)
        log(f"Project SDK set to '{name}' in misc.xml")

    def ensure_root_module_iml(self) -> Path:
        """Create/update the root module pointing to $PROJECT_DIR$."""
        path = self.cfg.modules_dir / f"{self.cfg.project_name}.iml"
        if path.exists():
            try:
                tree = read_xml(path)
                root = tree.getroot()
                comp = root.find("./component[@name='NewModuleRootManager']")
                if comp is None:
                    comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
                content = comp.find("content")
                if content is None:
                    ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
                else:
                    content.set("url", "file://$PROJECT_DIR$")
                write_xml(tree, path)
            except ET.ParseError:
                pass
            return path

        m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
        comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
        ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
        write_xml(ET.ElementTree(m), path)
        log(f"Root module IML created: {path}")
        return path

    def set_module_sdk(self, iml_path: Path, sdk_name: str) -> None:
        tree = read_xml(iml_path)
        root = tree.getroot()
        comp = root.find("./component[@name='NewModuleRootManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
        for oe in list(comp.findall("orderEntry")):
            if oe.get("type") in {"inheritedJdk", "jdk"}:
                comp.remove(oe)
        ET.SubElement(comp, "orderEntry", {"type": "jdk", "jdkName": sdk_name, "jdkType": self.cfg.sdk_type})
        write_xml(tree, iml_path)

    # ---- .iml helpers for apps/cores ----

    def write_module_minimal(self, module_name: str, dir_path: Path) -> Path:
        iml_path = self.cfg.modules_dir / f"{module_name}.iml"
        m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
        comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
        ET.SubElement(comp, "content", {"url": content_url_for(dir_path)})
        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
        write_xml(ET.ElementTree(m), iml_path)
        log(f"IML created (minimal): {iml_path}")
        return iml_path

    # ---- modules.xml MERGE from pycharm/_template_app_modules.xml ----

    def _merge_modules_from_app_template(self, app_name: str, app_dir: Path) -> List[Path]:
        """
        Merge <module> entries from pycharm/_template_app_modules.xml into .idea/modules.xml,
        after substituting {APP}. Returns the list of 'in-repo' .iml paths referenced by entries.
        """
        tpl = self.cfg.root / "pycharm" / "_template_app_modules.xml"
        if not tpl.exists():
            log("_template_app_modules.xml not found; skipping modules merge.")
            return []

        # substitute tokens and parse
        raw = tpl.read_text(encoding="utf-8").replace("{APP}", app_name)
        try:
            tpl_root = ET.fromstring(raw)
        except ET.ParseError:
            log("_template_app_modules.xml is not parseable; skipping modules merge.")
            return []

        tpl_modules = tpl_root.find(".//modules")
        if tpl_modules is None:
            log("_template_app_modules.xml has no <modules>; skipping modules merge.")
            return []

        tree = _ensure_modules_xml()
        mods = _modules_node(tree)

        # build existing index for dedup
        existing = { _entry_key(m) : m for m in mods.findall("module") }

        added_iml_paths: List[Path] = []
        for m in tpl_modules.findall("module"):
            fp = _norm_path_attr(m.get("filepath"))
            fu = _norm_path_attr(m.get("fileurl"))
            if not fp and not fu:
                continue

            # resolve for policy
            resolved_fp = _resolve_macros(fp or fu, app_name)
            if not ALLOW_EXTERNAL_MODULES and not _is_within_repo(resolved_fp):
                # skip external modules silently (or log if you prefer)
                continue

            key = (fp, fu)
            if key in existing:
                # already present; keep as-is
                continue

            # copy (not reference) to avoid parent conflicts
            new_m = ET.Element("module")
            if fp:
                new_m.set("filepath", fp)
            if fu:
                new_m.set("fileurl", fu)
            mods.append(new_m)
            existing[key] = new_m

            # track in-repo .iml paths so we can ensure app's *_project.iml exists
            if _is_within_repo(resolved_fp):
                added_iml_paths.append(resolved_fp)

        if added_iml_paths:
            write_xml(tree, CFG.idea / "modules.xml")
            log(f"modules.xml merged entries for app '{app_name}' ({len(added_iml_paths)} added).")

        return added_iml_paths

# =============================================================================
# Discovery
# =============================================================================

def eligible_apps(cfg: Config, require_venv: bool) -> List[Path]:
    out: List[Path] = []
    if not cfg.apps_dir.exists():
        return out
    for p in sorted(cfg.apps_dir.iterdir()):
        if not p.is_dir():
            continue
        if not p.name.endswith("_project"):     # rule requested
            continue
        if require_venv and venv_python_for(p) is None:
            continue
        out.append(p)
    return out

def eligible_core(cfg: Config, require_venv: bool) -> List[Path]:
    out: List[Path] = []
    if not cfg.core_dir.exists():
        return out
    for p in sorted(cfg.core_dir.iterdir()):
        if not p.is_dir():
            continue
        if p.name.startswith((".", "__")):
            continue
        if require_venv and venv_python_for(p) is None:
            continue
        out.append(p)
    return out

# =============================================================================
# Run configurations (apps only)
# =============================================================================

def generate_run_configs_for_apps(cfg: Config, app_names: List[str]) -> None:
    if not cfg.gen_script.exists():
        log(f"Missing {cfg.gen_script}; skipping run configuration generation.")
        return
    for name in app_names:
        log(f"Generating run configs for '{name}' via {cfg.gen_script.name} …")
        subprocess.run([sys.executable, str(cfg.gen_script), name], check=True, cwd=str(cfg.root))

# =============================================================================
# Main
# =============================================================================

def main() -> int:
    # Ensure basic dirs
    CFG.idea.mkdir(exist_ok=True)
    CFG.modules_dir.mkdir(parents=True, exist_ok=True)
    CFG.runcfg_dir.mkdir(parents=True, exist_ok=True)

    model = ProjectModel(CFG)
    jdk = JdkTable(CFG.sdk_type)

    # Project label
    model.ensure_project_name()

    # Root venv + SDK + module binding
    root_py = ensure_uv_venv(CFG.root)
    if root_py:
        jdk.upsert_many({CFG.project_sdk_name: str(root_py)})
        model.set_project_sdk(CFG.project_sdk_name)
    else:
        log("Root .venv not found; run `uv venv` at repo root if you want a project SDK.")

    root_iml = model.ensure_root_module_iml()
    if root_py:
        model.set_module_sdk(root_iml, CFG.project_sdk_name)

    # Discover/realize apps (ONLY *_project)
    apps = eligible_apps(CFG, require_venv=not CFG.ensure_uv_venvs_apps and CFG.attach_only_venvs)
    realized_apps: List[Tuple[Path, str]] = []

    # --- Apps: ensure venv, MERGE modules.xml from template, ensure *_project.iml exists, set SDK, run configs ---
    for app in apps:
        py = ensure_uv_venv(app) if CFG.ensure_uv_venvs_apps else venv_python_for(app)
        if not py:
            if CFG.attach_only_venvs:
                log(f"{app.name}: no .venv → skipping.")
                continue
            log(f"{app.name}: still no .venv → skipping.")
            continue

        # 1) merge template module entries for this app
        added_imls = model._merge_modules_from_app_template(app.name, app)

        # 2) ensure the app’s *_project.iml exists (if template pointed to it)
        #    otherwise create a minimal one under .idea/modules/<app>.iml
        target_iml = None
        for p in added_imls:
            if p.name.endswith("_project.iml"):
                target_iml = p
                break
        if target_iml is None:
            target_iml = CFG.modules_dir / f"{app.name}.iml"

        if not target_iml.exists():
            # write a minimal iml pointing to the app source
            model.write_module_minimal(target_iml.stem, app)
            # If the minimal wrote to a different path (modules/<name>.iml), move/rename if needed
            default_path = CFG.modules_dir / f"{target_iml.stem}.iml"
            if default_path != target_iml and default_path.exists():
                target_iml.parent.mkdir(parents=True, exist_ok=True)
                default_path.replace(target_iml)
                log(f"Moved IML to match template path: {target_iml}")

        # 3) register SDK and pin into that module
        sdk_name = f"uv ({app.name})"
        jdk.upsert_many({sdk_name: str(py)})
        model.set_module_sdk(target_iml, sdk_name)

        realized_apps.append((app, sdk_name))

    # --- Core: NO template; minimal IML; NO run/debug generation ---
    cores = eligible_core(CFG, require_venv=True and not CFG.ensure_uv_venvs_core)
    realized_cores: List[Tuple[Path, str]] = []
    for core in cores:
        py = venv_python_for(core) if not CFG.ensure_uv_venvs_core else ensure_uv_venv(core)
        if not py:
            continue
        iml = model.write_module_minimal(core.name, core)
        sdk_name = f"uv ({core.name})"
        jdk.upsert_many({sdk_name: str(py)})
        model.set_module_sdk(iml, sdk_name)
        realized_cores.append((core, sdk_name))

    # NOTE: We DO NOT rebuild modules.xml from disk anymore,
    # because we want to preserve/merge entries coming from the app template.
    # (If you still want to drop stale modules, you can add a pruning step here.)

    # Run/debug configs for apps (only)
    generate_run_configs_for_apps(CFG, [p.name for p, _ in realized_apps])

    # Prune SDKs (keep one per project)
    keep_sdk_names = {CFG.project_sdk_name} | {sdk for _, sdk in realized_apps} | {sdk for _, sdk in realized_cores}
    jdk.prune_uv_names(keep_sdk_names)

    log("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
