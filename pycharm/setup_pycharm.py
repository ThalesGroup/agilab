import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Iterable, Dict, List
import sys
import subprocess
import xml.etree.ElementTree as ET

class Config:
    def __init__(self, root: Path, sdk_type: str = "Python SDK", allow_external_modules: bool = False):
        self.ALLOW_EXTERNAL_MODULES = allow_external_modules
        self.ROOT = root
        self.IDEA_DIR = root / ".idea"
        self.MODULES_DIR = self.IDEA_DIR / "modules"
        self.RUN_CONFIGS_DIR = self.IDEA_DIR / "runConfigurations"
        self.MISC = self.IDEA_DIR / "misc.xml"
        self.MODULES = self.IDEA_DIR / "modules.xml"
        self.AGISPACE = root / ".." / "agi-space"
        self.AGI_ENV_DIR = Path.home() / ".agilab"
        self.AGI_ENV_FILE = self.AGI_ENV_DIR / ".env"

        self.PROJECT_NAME = self.IDEA_DIR.parent.name
        self.PROJECT_SDK = f"uv ({self.PROJECT_NAME})"
        self.PROJECT_SDK_TYPE = sdk_type
        self.APPS_DIR = self.ROOT / "src" / self.PROJECT_NAME / "apps"
        self.APPS_PAGES_DIR = self.ROOT / "src" / self.PROJECT_NAME / "apps-pages"
        self.CORE_DIR = self.ROOT / "src" / self.PROJECT_NAME / "core"

        self.FILE_TEMPLATE = {
            "app": ("file://$PROJECT_DIR$/.idea/modules/{APP}_project.iml",
                    "$PROJECT_DIR$/.idea/modules/{APP}_project.iml"),
            "worker": ("file://$USER_HOME$/wenv/{APP}_worker/.idea/{APP}_worker.iml",
                       "$USER_HOME$/wenv/{APP}_worker/.idea/{APP}_worker.iml"),
        }

        self.GEN_SCRIPT = self.ROOT / "pycharm" / "gen_app_script.py" if (self.ROOT / "pycharm" / "gen_app_script.py").exists() else self.ROOT / "gen_app_script.py"

        self._env_file_values = self._load_env_file(self.AGI_ENV_FILE)
        self.eligible_apps = self.__eligible_apps()
        self.eligible_core = self.__eligible_core()
        self.eligible_apps_pages = self.__eligible_apps_pages()

    def create_directories(self):
        self.IDEA_DIR.mkdir(exist_ok=True)
        self.MODULES_DIR.mkdir(exist_ok=True)
        self.RUN_CONFIGS_DIR.mkdir(exist_ok=True)

    def _load_env_file(self, env_path: Path) -> Dict[str, str]:
        data: Dict[str, str] = {}
        if not env_path.exists():
            return data
        try:
            for raw_line in env_path.read_text().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.split("#", 1)[0].strip()
                if not key:
                    continue
                data[key.strip()] = value.strip().strip("\"'")
        except OSError as exc:
            logging.warning(f"Failed to read {env_path}: {exc}")
        return data

    def __eligible_apps(self) -> List[Path]:
        out: List[Path] = []
        if not self.APPS_DIR.exists():
            return out
        for p in sorted(self.APPS_DIR.iterdir()):
            if not p.is_dir():
                continue
            if not p.name.endswith("_project"):  # rule requested
                continue
            out.append(p)
        return out

    def __eligible_apps_pages(self) -> List[Path]:
        out: List[Path] = []
        if not self.APPS_PAGES_DIR.exists():
            return out
        for p in sorted(self.APPS_PAGES_DIR.iterdir()):
            if not p.is_dir():
                continue
            if p.name.startswith((".", "__")):
                continue
            out.append(p)
        return out

    def __eligible_core(self) -> List[Path]:
        out: List[Path] = []
        if not self.CORE_DIR.exists():
            return out
        for p in sorted(self.CORE_DIR.iterdir()):
            if not p.is_dir():
                continue
            if p.name.startswith((".", "__")):
                continue
            out.append(p)
        return out

    def resolve_macros(self, raw: str, app_name: str) -> Path:
        s = raw.replace("{APP}", app_name)
        s = s.replace("$PROJECT_DIR$", str(self.ROOT))
        s = s.replace("$USER_HOME$", str(Path.home()))
        if s.startswith("file://"):
            s = s[len("file://"):]
        return Path(s)

    def is_within_repo(self, p: Path) -> bool:
        try:
            return p.resolve().is_relative_to(self.ROOT.resolve())
        except AttributeError:
            rp = str(self.ROOT.resolve())
            return str(p.resolve()).startswith(rp + os.sep)

    def as_project_macro(self, p: Path) -> str:
        rel = p.resolve().relative_to(self.ROOT.resolve())
        return f"$PROJECT_DIR$/{rel.as_posix()}"

    def as_project_url(self, p: Path) -> str:
        return f"file://{self.as_project_macro(p)}"


# ================= XML Utilities =================
def read_xml(file_path: Path):
    """Read an XML file and return its ElementTree."""
    tree = ET.parse(file_path)
    return tree

def _indent(tree: ET.ElementTree) -> None:
    try:
        ET.indent(tree, space="    ")
    except Exception:
        pass

def write_xml(tree: ET.ElementTree, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _indent(tree)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)

# ==================================================================

# ================= Helper Functions =================
def venv_python_for(project_dir: Path) -> Optional[Path]:
    for c in (
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "bin" / "python3",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ):
        if c.exists():
            try:
                return c.absolute()
            except Exception:
                return c
    return None

def content_url_for(cfg: Config, dir_path: Path) -> str:
    try:
        rel = dir_path.relative_to(cfg.ROOT)   # keep macros, no resolve here
        return f"file://$MODULE_DIR$/../../{rel.as_posix()}"
    except ValueError:
        return f"file://{dir_path.resolve().as_posix()}"


def _find_uv_binary() -> Optional[str]:
    candidates: Iterable[Optional[str]] = (
        os.environ.get("UV_BINARY"),
        os.environ.get("UV_BIN"),
        shutil.which("uv"),
    )
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser()
            if path.exists():
                return str(path)
    fallback = Path.home() / ".local" / "bin" / "uv"
    if fallback.exists():
        return str(fallback)
    return None


def _bootstrap_project_venv(project_dir: Path) -> Optional[Path]:
    logging.info("No virtual environment found for %s; attempting uv sync to bootstrap it.", project_dir.name)
    uv_bin = _find_uv_binary()
    if not uv_bin:
        logging.warning("'uv' command not found while bootstrapping %s", project_dir.name)
        return None
    try:
        subprocess.run(
            [uv_bin, "sync", "--project", ".", "--preview-features", "python-upgrade"],
            cwd=project_dir,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logging.warning("uv sync failed for %s: %s", project_dir.name, exc)
        return None
    return venv_python_for(project_dir)


def seed_example_scripts(cfg: Config, app_slug: str) -> None:
    """Copy AGI_* example scripts into ~/log/execute/<app_slug> if missing."""

    if not app_slug:
        return

    examples_dir = cfg.ROOT / "src" / cfg.PROJECT_NAME / "examples" / app_slug
    if not examples_dir.exists():
        return

    target_dir = Path.home() / "log" / "execute" / app_slug
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logging.warning("Unable to create %s: %s", target_dir, exc)
        return

    for source in sorted(examples_dir.glob("AGI_*.py")):
        destination = target_dir / source.name
        if destination.exists():
            continue
        try:
            shutil.copy2(source, destination)
            logging.info("Seeded %s from %s", destination, source)
        except OSError as exc:
            logging.warning("Failed to copy %s to %s: %s", source, destination, exc)

# =======================================================================

# ================= JdkTable Class =================

class JdkTable:
    def __init__(self, sdk_type: str):
        self.sdk_type = sdk_type
        self.jb_dirs = self.__jetbrains_dir()
        self.jdk_tables = self.__get_jdk_tables()

    def __jetbrains_dir(self) -> List[Path]:
        home = Path.home()
        out: List[Path] = []
        if sys.platform == "darwin":
            out.append(home / "Library" / "Application Support" / "JetBrains")
        elif sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if appdata:
                out.append(Path(appdata) / "JetBrains")
        else:
            out.append(home / ".config" / "JetBrains")
        return [p for p in out if p.exists()]

    def __get_jdk_tables(self) -> List[Path]:
        out: List[Path] = []
        for jb_dir in self.jb_dirs:
            for product in ("PyCharm*", "PyCharmCE*"):
                for candidate in jb_dir.glob(product):
                    p = candidate / "options" / "jdk.table.xml"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    out.append(p)
        return out

    def __ensure_roots(self, jdk_el: ET.Element) -> None:
        if jdk_el.find("roots") is None:
            ET.SubElement(jdk_el, "roots")

    def __ensure_component(self, root: ET.Element) -> ET.Element:
        comp = root.find("./component[@name='ProjectJdkTable']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})
        return comp

    def __load_jdk_table(self, path: Path) -> ET.ElementTree:
        if path.exists():
            try:
                return read_xml(path)
            except ET.ParseError:
                root = ET.Element("application")
                self.__ensure_component(root)
                return ET.ElementTree(root)
        root = ET.Element("application")
        self.__ensure_component(root)
        return ET.ElementTree(root)

    def set_associated_project(self, name: str, home: Path) -> None:
        matched_any = False
        changed_any = False
        for jdk_table in self.jdk_tables:
            tree = self.__load_jdk_table(jdk_table)
            root = tree.getroot()
            comp = self.__ensure_component(root)
            changed = False

            target = None
            project_dir = str(Path(home).parent.parent.parent)
            project_dir = project_dir.replace(str(Path.home()), "$USER_HOME$")

            for jdk in comp.findall("jdk"):
                jdk_name = jdk.find("name")
                if (jdk_name is not None and jdk_name.get("value") == name) or \
                        (jdk_name is None and jdk.attrib.get("name") == name):
                    target = jdk
                    break

            if target is not None:
                matched_any = True
                add_el = target.find("additional")
                if add_el is not None:
                    if add_el.get("ASSOCIATED_PROJECT_PATH") != project_dir:
                        add_el.set("ASSOCIATED_PROJECT_PATH", project_dir)
                        changed = True
            if changed:
                write_xml(tree, jdk_table)
                changed_any = True
                logging.info(f"Updated ASSOCIATED_PROJECT_PATH in {jdk_table} for name SDK")

        if not matched_any:
            logging.info("No matching SDKs found to modify associated_project.")

    def add_jdk(self, name: str, home: Path) -> None:
        changed_any = False
        for jdk_table in self.jdk_tables:
            tree = self.__load_jdk_table(jdk_table)
            root = tree.getroot()
            comp = self.__ensure_component(root)
            changed = False

            target = None
            project_dir = str(home.parents[2])
            project_dir = project_dir.replace(str(Path.home()), "$USER_HOME$")

            for jdk in comp.findall("jdk"):
                jdk_name = jdk.find("name")
                if jdk_name is not None and jdk_name.get("value") == name:
                    target = jdk
                    break
                if jdk.attrib.get("name") == name:
                    target = jdk
                    break

            if target is None:
                target = ET.SubElement(comp, "jdk", {"version": "2"})
                ET.SubElement(target, "name", {"value": name})
                ET.SubElement(target, "type", {"value": self.sdk_type})
                ET.SubElement(target, "homePath", {"value": str(home)})

                add_el = ET.SubElement(target, "additional", {"ASSOCIATED_PROJECT_PATH": project_dir,
                                                              "IS_UV": "true",
                                                              "UV_WORKING_DIR": project_dir})
                ET.SubElement(add_el, "setting", {"name": "FLAVOR_ID", "value": "UvSdkFlavor"})
                ET.SubElement(add_el, "setting", {"name": "FLAVOR_DATA", "value": "{}"})

                self.__ensure_roots(target)

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
                    home_el = ET.SubElement(target, "homePath", {"value": str(home)})
                if home_el.get("value") != str(home):
                    home_el.set("value",str(home))
                    changed = True

                add_el = target.find("additional")
                if add_el is None:
                    add_el = ET.SubElement(target, "additional", {"ASSOCIATED_PROJECT_PATH": project_dir,
                                                                  "IS_UV": "true",
                                                                  "UV_WORKING_DIR": project_dir})
                if add_el.get("ASSOCIATED_PROJECT_PATH") != project_dir:
                    add_el.set("ASSOCIATED_PROJECT_PATH", project_dir)
                    changed = True

                if add_el.get("UV_WORKING_DIR") != project_dir:
                    add_el.set("UV_WORKING_DIR", project_dir)
                    changed = True
                if add_el.get("IS_UV") != "true":
                    add_el.set("IS_UV", "true")
                    changed = True

                setting_els = add_el.findall("setting")
                if setting_els is None:
                    ET.SubElement(add_el, "setting", {"name": "FLAVOR_ID", "value": "UvSdkFlavor"})
                    ET.SubElement(add_el, "setting", {"name": "FLAVOR_DATA", "value": "{}"})
                else:
                    for el in setting_els:
                        if el.get("name") == "FLAVOR_ID" and el.get("value") != "UvSdkFlavor":
                            el.set("value", "UvSdkFlavor")
                        if el.get("name") == "FLAVOR_DATA" and el.get("value") != "{}":
                            el.set("value", "{}")

                self.__ensure_roots(target)

            if changed:
                write_xml(tree, jdk_table)
                changed_any = True
                logging.info(f"Updated {jdk_table} with sdk {name} at {home}")
            if not changed_any:
                logging.info("No changed applied to JetBrains jdk.table.xml.")
                changed_any = True

        if not changed_any:
            logging.info("No changed applied to JetBrains jdk.table.xml.")

    def prune_uv_names(self, keep_names: Iterable[str]) -> None:
        keep = set(keep_names)
        for table in self.jdk_tables:
            if not table.exists():
                continue
            try:
                tree = read_xml(table)
            except ET.ParseError:
                continue
            root = tree.getroot()
            comp = self.__ensure_component(root)
            removed = 0
            for jdk in list(comp.findall("jdk")):
                nm = (jdk.findtext("name") if jdk.find("name") is not None else jdk.attrib.get("name", ""))
                tp = (jdk.find("type").get("value") if jdk.find("type") is not None else jdk.attrib.get("type", ""))
                if tp == self.sdk_type and nm.startswith("uv (") and nm not in keep:
                    comp.remove(jdk)
                    removed += 1
            if removed:
                write_xml(tree, table)
                logging.info(f"Pruned SDKs in {table}, kept: {sorted(keep)}")


# ==================== Project Class ====================

class Project:
    EXCLUDE_FOLDERS = ("dist", "build", ".venv")

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _ensure_exclude_folders(self, content: ET.Element) -> bool:
        base_url = (content.get("url") or "").rstrip("/")
        if not base_url:
            return False
        existing = {node.get("url") for node in content.findall("excludeFolder")}
        changed = False
        for name in self.EXCLUDE_FOLDERS:
            url = f"{base_url}/{name}"
            if url not in existing:
                ET.SubElement(content, "excludeFolder", {"url": url})
                changed = True
        return changed

    def ensure_module_excludes(self, iml_path: Path, dir_path: Path) -> None:
        if not iml_path.exists():
            return

        tree = read_xml(iml_path)
        root = tree.getroot()

        comp = root.find("./component[@name='NewModuleRootManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})

        content = comp.find("content")
        if content is None:
            content = ET.SubElement(comp, "content", {"url": content_url_for(self.cfg, dir_path)})

        if self._ensure_exclude_folders(content):
            write_xml(tree, iml_path)
            logging.info(f"Updated exclude folders in {iml_path}")

    def write_module_minimal(self, module_name: str, dir_path: Path) -> Path:
        iml_path = self.cfg.MODULES_DIR / f"{module_name}.iml"
        m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
        comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
        content = ET.SubElement(comp, "content", {"url": content_url_for(self.cfg, dir_path)})
        self._ensure_exclude_folders(content)
        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
        write_xml(ET.ElementTree(m), iml_path)
        logging.info(f"IML created (minimal): {iml_path}")
        return iml_path

    def set_project_sdk(self, sdk_name: str):
        if self.cfg.MISC.exists():
            tree = read_xml(self.cfg.MISC)
            root = tree.getroot()
        else:
            root =  ET.Element("project", {"version": "4"})
            tree = ET.ElementTree(root)

        prm = root.find("./component[@name='Black']")
        if prm is None:
            prm = ET.SubElement(root, "component", {"name": "Black"})
        option = prm.find("./option[@name='sdkName']")
        if option is None:
            option = ET.SubElement(prm, "option", {"name": "sdkName"})
        option.set("value", sdk_name)
        write_xml(tree, self.cfg.MISC)
        logging.info(f"Project SDK set to {sdk_name} in {self.cfg.MISC}")

    def set_module_sdk(self, iml_path: Path, sdk_name: str):
        if not iml_path.exists():
            logging.error(f"Module file {iml_path} does not exist.")
            return

        tree = read_xml(iml_path)
        root = tree.getroot()

        comp = root.find("./component[@name='NewModuleRootManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
        for oe in list(comp.findall("orderEntry")):
            if oe.get("type") in {"inheritedJdk", "jdk"}:
                comp.remove(oe)
        ET.SubElement(comp, "orderEntry", {"type": "jdk", "jdkName": sdk_name, "jdkType": self.cfg.PROJECT_SDK_TYPE})

        write_xml(tree, iml_path)
        logging.info(f"Module SDK set to {sdk_name} in {iml_path}")

    def ensure_root_module_iml(self) -> Path:
        """Create/update the root module pointing to $PROJECT_DIR$."""
        path = self.cfg.MODULES_DIR / f"{self.cfg.PROJECT_NAME}.iml"
        if path.exists():
            try:
                tree = read_xml(path)
                root = tree.getroot()
                comp = root.find("./component[@name='NewModuleRootManager']")
                if comp is None:
                    comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})
                content = comp.find("content")
                if content is None:
                    content = ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})
                else:
                    content.set("url", "file://$PROJECT_DIR$")
                changed = self._ensure_exclude_folders(content)
                if changed:
                    write_xml(tree, path)
            except ET.ParseError:
                pass
            return path

        m = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
        comp = ET.SubElement(m, "component", {"name": "NewModuleRootManager"})
        content = ET.SubElement(comp, "content", {"url": "file://$MODULE_DIR$/../"})
        self._ensure_exclude_folders(content)
        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})
        write_xml(ET.ElementTree(m), path)
        logging.info(f"Root module IML created: {path}")
        return path

    def add_app_module_entry(self, module_name: str) -> Path | None:
        """Generate a module for the given app directory."""
        project_name = module_name[:-8]

        tree = read_xml(self.cfg.MODULES)
        root = tree.getroot()
        comp = root.find("./component[@name='ProjectModuleManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "ProjectModuleManager"})
        modules = comp.find("modules")
        if modules is None:
            modules = ET.SubElement(comp, "modules")

        entries = {}
        for m in modules.findall("module"):
            filepath = m.get("filepath")
            fileurl = m.get("fileurl")
            if filepath and fileurl:
                entries[(fileurl, filepath)] = m

        output = None
        for key in self.cfg.FILE_TEMPLATE.keys():
            fu = self.cfg.FILE_TEMPLATE[key][0].format(APP=project_name)
            fp = self.cfg.FILE_TEMPLATE[key][1].format(APP=project_name)

            resolved_fp = self.cfg.resolve_macros(fp or fu, project_name)
            is_within_repo = self.cfg.is_within_repo(resolved_fp)

            if not self.cfg.ALLOW_EXTERNAL_MODULES and not is_within_repo:
                continue

            if (fu, fp) in entries:
                logging.warning(f"Module entry for {module_name} already exists in modules.xml, skipping.")
                continue

            m = ET.Element("module")
            m.set("fileurl", fu)
            m.set("filepath", fp)
            modules.append(m)
            entries[(fu, fp)] = m

            if is_within_repo:
                output = resolved_fp

        if output:
            write_xml(tree, self.cfg.MODULES)
            logging.info(f"Module entry for {module_name} added to modules.xml")

    def add_module_entry(self, core_iml: Path) -> Path | None:
        tree = read_xml(self.cfg.MODULES)
        root = tree.getroot()
        comp = root.find("./component[@name='ProjectModuleManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "ProjectModuleManager"})
        modules = comp.find("modules")
        if modules is None:
            modules = ET.SubElement(comp, "modules")

        entries = {}
        for m in modules.findall("module"):
            filepath = m.get("filepath")
            fileurl = m.get("fileurl")
            if filepath and fileurl:
                entries[(fileurl, filepath)] = m

        fu = self.cfg.as_project_url(core_iml)
        fp = self.cfg.as_project_macro(core_iml)

        if (fu, fp) in entries:
            logging.warning(f"Module entry for {core_iml.name} already exists in modules.xml, skipping.")
            return None

        ET.SubElement(modules, "module", {"fileurl": fu, "filepath": fp})
        write_xml(tree, self.cfg.MODULES)
        logging.info(f"Module entry for {core_iml.name} added to modules.xml")
        return core_iml

    def generate_run_configs_for_apps(self, app_names: List[str]) -> None:
        if not self.cfg.GEN_SCRIPT.exists():
            logging.info(f"Missing {self.cfg.GEN_SCRIPT}; skipping run configuration generation.")
            return
        for name in app_names:
            logging.info(f"Generating run configs for '{name}' via {self.cfg.GEN_SCRIPT.name} …")
            subprocess.run([sys.executable, str(self.cfg.GEN_SCRIPT), name], check=True, cwd=str(self.cfg.ROOT))

    def python_terminal_settings(self):
        term_cfg = self.cfg.IDEA_DIR / "python-terminal.xml"
        if term_cfg.exists():
            tree = read_xml(term_cfg)
            root = tree.getroot()
        else:
            root =  ET.Element("project", {"version": "4"})
            tree = ET.ElementTree(root)

        comp = root.find("./component[@name='PyVirtualEnvTerminalCustomizer']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "PyVirtualEnvTerminalCustomizer"})
        option = comp.find("./option[@name='virtualEnvActivate']")
        if option is None:
            option = ET.SubElement(comp, "option", {"name": "virtualEnvActivate"})
        option.set("virtualEnvActivate", "false")

        write_xml(tree, term_cfg)

def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parents[1]
    cfg = Config(root=path)
    cfg.create_directories()

    if not cfg.MODULES.exists():
        project = ET.Element("project", {"version": "4"})
        ET.SubElement(ET.SubElement(project, "component", {"name": "ProjectModuleManager"}), "modules")
        tree = ET.ElementTree(project)
        write_xml(tree, cfg.MODULES)

    model = Project(cfg)
    jdk_table = JdkTable(cfg.PROJECT_SDK_TYPE)

    root_py = venv_python_for(cfg.ROOT)
    if root_py:
        jdk_table.add_jdk(cfg.PROJECT_SDK, root_py)
        model.set_project_sdk(cfg.PROJECT_SDK)
    else:
        logging.error(f"Project SDK {cfg.PROJECT_SDK} not found.")
        return 1

    root_iml = model.ensure_root_module_iml()
    model.set_module_sdk(root_iml, cfg.PROJECT_SDK)
    model.add_module_entry(root_iml)
    model.ensure_module_excludes(root_iml, cfg.ROOT)

    realized_apps = []
    for app in cfg.eligible_apps:
        app_py = venv_python_for(app)
        if not app_py:
            app_py = _bootstrap_project_venv(app)
        if not app_py:
            logging.warning(f"No virtual environment found for {app.name}, skipping.")
            continue

        added_project = model.add_app_module_entry(app.name)
        target = None
        if added_project:
            if added_project.name.endswith("_project.iml"):
                target = added_project
        if not target:
            target = cfg.MODULES_DIR / f"{app.name}.iml"
        if not target.exists():
            model.write_module_minimal(target.stem, app)
            # If the minimal wrote to a different path (modules/<name>.iml), move/rename if needed
            default_path = cfg.MODULES_DIR / f"{target.stem}.iml"
            if default_path != target and default_path.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                default_path.replace(target)
                logging.info(f"Moved IML to match template path: {target}")
        model.ensure_module_excludes(target, app)

        sdk_app = f"uv ({app.name})"
        jdk_table.add_jdk(sdk_app, app_py)
        model.set_module_sdk(target, sdk_app)

        project = app.name[:-8]
        worker_path = Path.home() / "wenv" / f"{project}_worker"
        worker_py = venv_python_for(worker_path)
        if not worker_py:
            logging.warning(f"No virtual environment found for {worker_path.name}, skipping.")
            continue
        sdk_worker = f"uv ({project}_worker)"
        jdk_table.add_jdk(sdk_worker, worker_py)
        jdk_table.set_associated_project(sdk_worker, worker_py)

        realized_apps.append(app.name)
        seed_example_scripts(cfg, project)
    
    realized_apps_pages = []
    for apps_page in cfg.eligible_apps_pages:
        apps_page_py = venv_python_for(apps_page)
        if not apps_page_py:
            apps_page_py = _bootstrap_project_venv(apps_page)

        iml = model.write_module_minimal(apps_page.name, apps_page)

        if apps_page_py:
            sdk_name = f"uv ({apps_page.name})"
            jdk_table.add_jdk(sdk_name, apps_page_py)
        else:
            logging.warning(
                "No virtual environment found for %s even after bootstrap; falling back to project SDK %s.",
                apps_page.name,
                cfg.PROJECT_SDK,
            )
            sdk_name = cfg.PROJECT_SDK

        model.set_module_sdk(iml, sdk_name)
        model.add_module_entry(iml)
        model.ensure_module_excludes(iml, apps_page)
        realized_apps_pages.append(apps_page.name)

    realized_core = []
    for core in cfg.eligible_core:
        core_py = venv_python_for(core)
        if not core_py:
            logging.warning(f"No virtual environment found for {core.name}, skipping.")
            continue

        iml = model.write_module_minimal(core.name, core)
        sdk_name = f"uv ({core.name})"
        jdk_table.add_jdk(sdk_name, core_py)
        model.set_module_sdk(iml, sdk_name)

        model.add_module_entry(iml)
        model.ensure_module_excludes(iml, core)

        realized_core.append(core.name)

    # jdk_table.prune_uv_names([sdk for _, sdk in realized_apps + realized_core])

    model.generate_run_configs_for_apps([p for p in realized_apps])

    logging.info("Project setup completed successfully.")
    logging.info(f"Realized apps: {', '.join([app for app in realized_apps])}")
    logging.info(f"Realized core: {', '.join([core for core in realized_core])}")
    logging.info(f"Realized apps-pages: {', '.join([apps_page for apps_page in realized_apps_pages])}")

    if cfg.AGISPACE.exists():
        logging.info("Realizing agi-space as a module.")
        agi_iml = model.write_module_minimal("agi-space", cfg.AGISPACE)
        agi_py = venv_python_for(cfg.AGISPACE)
        if agi_py:
            sdk_name = "uv (agi-space)"
            jdk_table.add_jdk(sdk_name, agi_py)
            model.set_module_sdk(agi_iml, sdk_name)
            model.add_module_entry(agi_iml)
            model.ensure_module_excludes(agi_iml, cfg.AGISPACE)
        else:
            logging.warning("No virtual environment found for agi-space, skipping SDK assignment.")
    else:
        logging.info("No agi-space directory found, skipping.")

    model.python_terminal_settings()

    return 0

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    raise SystemExit(main())
