import logging
import os
import shutil
import sys
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Iterable, Dict, List


class Config:
    def __init__(self, root: Path, sdk_type: str = "Python SDK", allow_external_modules: bool = False):
        self.ALLOW_EXTERNAL_MODULES = allow_external_modules
        self.ROOT = root.resolve()
        self.IDEA_DIR = self.ROOT / ".idea"
        self.MODULES_DIR = self.IDEA_DIR / "modules"
        self.RUN_CONFIGS_DIR = self.IDEA_DIR / "runConfigurations"
        self.MISC = self.IDEA_DIR / "misc.xml"
        self.MODULES = self.IDEA_DIR / "modules.xml"
        self.AGISPACE = self.ROOT / ".." / "agi-space"
        self.AGI_ENV_DIR = Path.home() / ".agilab"
        self.AGI_ENV_FILE = self.AGI_ENV_DIR / ".env"

        self.PROJECT_NAME = self.IDEA_DIR.parent.name
        self.PROJECT_SDK = f"uv ({self.PROJECT_NAME})"
        self.PROJECT_SDK_TYPE = sdk_type

        self.APPS_PATH = self.ROOT / "src" / self.PROJECT_NAME / "apps"
        self.APPS_PATH_SET = [self.APPS_PATH, self.APPS_PATH / "builtin"]
        self.APPS_PAGES_DIR = self.ROOT / "src" / self.PROJECT_NAME / "apps-pages"
        self.CORE_DIR = self.ROOT / "src" / self.PROJECT_NAME / "core"

        self.FILE_TEMPLATE = {
            "app": (
                "file://$PROJECT_DIR$/.idea/modules/{APP}_project.iml",
                "$PROJECT_DIR$/.idea/modules/{APP}_project.iml",
            ),
            "worker": (
                "file://$USER_HOME$/wenv/{APP}_worker/.idea/{APP}_worker.iml",
                "$USER_HOME$/wenv/{APP}_worker/.idea/{APP}_worker.iml",
            ),
        }

        self.GEN_SCRIPT = (
            self.ROOT / "pycharm" / "gen_app_script.py"
            if (self.ROOT / "pycharm" / "gen_app_script.py").exists()
            else self.ROOT / "gen_app_script.py"
        )

        self._env_file_values = self._load_env_file(self.AGI_ENV_FILE)
        self.eligible_apps = self.__eligible_apps()
        self.eligible_core = self.__eligible_core()
        self.eligible_apps_pages = self.__eligible_apps_pages()

    def create_directories(self) -> None:
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

                if key:
                    data[key.strip()] = value.strip().strip("\"'")
        except OSError as exc:
            logging.warning("Failed to read %s: %s", env_path, exc)

        return data

    def __eligible_apps(self) -> List[Path]:
        out: List[Path] = []

        for apps_dir in self.APPS_PATH_SET:
            if not apps_dir.exists():
                continue

            for p in sorted(apps_dir.iterdir()):
                if p.is_dir() and p.name.endswith("_project"):
                    out.append(p)

        return out

    def __eligible_apps_pages(self) -> List[Path]:
        out: List[Path] = []

        if not self.APPS_PAGES_DIR.exists():
            return out

        for p in sorted(self.APPS_PAGES_DIR.iterdir()):
            if p.is_dir() and not p.name.startswith((".", "__")):
                out.append(p)

        return out

    def __eligible_core(self) -> List[Path]:
        out: List[Path] = []

        if not self.CORE_DIR.exists():
            return out

        for p in sorted(self.CORE_DIR.iterdir()):
            if p.is_dir() and not p.name.startswith((".", "__")):
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

def read_xml(file_path: Path) -> ET.ElementTree:
    return ET.parse(file_path)


def _indent(tree: ET.ElementTree) -> None:
    try:
        ET.indent(tree, space="    ")
    except Exception:
        pass


def write_xml(tree: ET.ElementTree, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _indent(tree)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)


# ================= Helper Functions =================

def venv_python_for(project_dir: Path) -> Optional[Path]:
    for candidate in (
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "bin" / "python3",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ):
        if candidate.exists():
            return candidate.absolute()

    return None


def content_url_for(cfg: Config, dir_path: Path) -> str:
    try:
        rel = dir_path.relative_to(cfg.ROOT)
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
    logging.info("No virtual environment found for %s; attempting uv sync.", project_dir.name)

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


# ================= JdkTable Class =================

class JdkTable:
    """
    Idempotent JetBrains jdk.table.xml manager.

    Important behavior:
    - matches SDKs by name OR interpreter homePath
    - prevents growth on repeated calls
    - removes duplicate SDK entries for the same logical interpreter
    - rewrites one canonical SDK entry
    """

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
                    path = candidate / "options" / "jdk.table.xml"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    out.append(path)

        return sorted(set(out))

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
                logging.warning("Invalid XML in %s; recreating minimal jdk table.", path)

        root = ET.Element("application")
        self.__ensure_component(root)
        return ET.ElementTree(root)

    def __project_dir_for_home(self, home: Path) -> str:
        home = Path(home)

        parts = home.parts
        if ".venv" in parts:
            idx = parts.index(".venv")
            project_dir = Path(*parts[:idx])
        else:
            project_dir = home.parents[2]

        value = str(project_dir)
        return value.replace(str(Path.home()), "$USER_HOME$")

    def __jdk_name(self, jdk: ET.Element) -> str:
        name_el = jdk.find("name")
        if name_el is not None:
            return name_el.get("value", "")
        return jdk.get("name", "")

    def __jdk_type(self, jdk: ET.Element) -> str:
        type_el = jdk.find("type")
        if type_el is not None:
            return type_el.get("value", "")
        return jdk.get("type", "")

    def __jdk_home(self, jdk: ET.Element) -> str:
        home_el = jdk.find("homePath")
        if home_el is not None:
            return home_el.get("value", "")
        return jdk.get("homePath", "")

    def __normalize_path(self, path: str) -> str:
        try:
            return str(Path(path).expanduser().resolve())
        except Exception:
            return str(path)

    def __ensure_child_value(self, parent: ET.Element, tag: str, value: str) -> bool:
        el = parent.find(tag)

        if el is None:
            ET.SubElement(parent, tag, {"value": value})
            return True

        if el.get("value") != value:
            el.set("value", value)
            return True

        return False

    def __ensure_setting(self, additional: ET.Element, name: str, value: str) -> bool:
        for setting in additional.findall("setting"):
            if setting.get("name") == name:
                if setting.get("value") != value:
                    setting.set("value", value)
                    return True
                return False

        ET.SubElement(additional, "setting", {"name": name, "value": value})
        return True

    def __ensure_roots(self, jdk: ET.Element) -> bool:
        if jdk.find("roots") is None:
            ET.SubElement(jdk, "roots")
            return True
        return False

    def __is_same_sdk(self, jdk: ET.Element, name: str, home: Path) -> bool:
        jdk_name = self.__jdk_name(jdk)
        jdk_home = self.__normalize_path(self.__jdk_home(jdk))
        target_home = self.__normalize_path(str(home))

        return jdk_name == name or jdk_home == target_home

    def __upsert_jdk_element(self, jdk: ET.Element, name: str, home: Path) -> bool:
        changed = False
        project_dir = self.__project_dir_for_home(home)

        if jdk.get("version") != "2":
            jdk.set("version", "2")
            changed = True

        changed |= self.__ensure_child_value(jdk, "name", name)
        changed |= self.__ensure_child_value(jdk, "type", self.sdk_type)
        changed |= self.__ensure_child_value(jdk, "homePath", str(home))

        additional = jdk.find("additional")
        if additional is None:
            additional = ET.SubElement(jdk, "additional")
            changed = True

        expected_attrs = {
            "ASSOCIATED_PROJECT_PATH": project_dir,
            "IS_UV": "true",
            "UV_WORKING_DIR": project_dir,
        }

        for key, value in expected_attrs.items():
            if additional.get(key) != value:
                additional.set(key, value)
                changed = True

        changed |= self.__ensure_setting(additional, "FLAVOR_ID", "UvSdkFlavor")
        changed |= self.__ensure_setting(additional, "FLAVOR_DATA", "{}")
        changed |= self.__ensure_roots(jdk)

        return changed

    def add_jdk(self, name: str, home: Path) -> None:
        home = Path(home).absolute()
        changed_any = False

        for jdk_table in self.jdk_tables:
            tree = self.__load_jdk_table(jdk_table)
            root = tree.getroot()
            comp = self.__ensure_component(root)

            matches = [
                jdk
                for jdk in comp.findall("jdk")
                if self.__is_same_sdk(jdk, name, home)
            ]

            changed = False

            if matches:
                target = matches[0]

                for duplicate in matches[1:]:
                    logging.info(
                        "Removed duplicate SDK from %s: name=%s home=%s",
                        jdk_table,
                        self.__jdk_name(duplicate),
                        self.__jdk_home(duplicate),
                    )
                    comp.remove(duplicate)
                    changed = True
            else:
                target = ET.SubElement(comp, "jdk", {"version": "2"})
                changed = True

            changed |= self.__upsert_jdk_element(target, name, home)

            if changed:
                write_xml(tree, jdk_table)
                changed_any = True
                logging.info("Updated %s with SDK %s at %s", jdk_table, name, home)

        if not changed_any:
            logging.info("No changes applied to JetBrains jdk.table.xml.")

    def set_associated_project(self, name: str, home: Path) -> None:
        project_dir = self.__project_dir_for_home(home)
        matched_any = False
        changed_any = False

        for jdk_table in self.jdk_tables:
            tree = self.__load_jdk_table(jdk_table)
            root = tree.getroot()
            comp = self.__ensure_component(root)
            changed = False

            for jdk in comp.findall("jdk"):
                if self.__jdk_name(jdk) != name:
                    continue

                matched_any = True

                additional = jdk.find("additional")
                if additional is None:
                    additional = ET.SubElement(jdk, "additional")
                    changed = True

                for key in ("ASSOCIATED_PROJECT_PATH", "UV_WORKING_DIR"):
                    if additional.get(key) != project_dir:
                        additional.set(key, project_dir)
                        changed = True

                if additional.get("IS_UV") != "true":
                    additional.set("IS_UV", "true")
                    changed = True

                changed |= self.__ensure_setting(additional, "FLAVOR_ID", "UvSdkFlavor")
                changed |= self.__ensure_setting(additional, "FLAVOR_DATA", "{}")

            if changed:
                write_xml(tree, jdk_table)
                changed_any = True
                logging.info("Updated associated project in %s for SDK %s", jdk_table, name)

        if not matched_any:
            logging.info("No matching SDK found for associated project update: %s", name)
        elif not changed_any:
            logging.info("Associated project already up to date for SDK %s", name)

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
                name = self.__jdk_name(jdk)
                sdk_type = self.__jdk_type(jdk)

                if sdk_type == self.sdk_type and name.startswith("uv (") and name not in keep:
                    comp.remove(jdk)
                    removed += 1

            if removed:
                write_xml(tree, table)
                logging.info("Pruned %d SDK(s) in %s, kept: %s", removed, table, sorted(keep))


# ================= Project Class =================

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

    def _ensure_source_folders(
        self,
        content: ET.Element,
        dir_path: Path,
        source_roots: Iterable[str],
    ) -> bool:
        existing = {
            (node.get("url"), node.get("isTestSource", "false"))
            for node in content.findall("sourceFolder")
        }

        changed = False

        for root_name in source_roots:
            root_path = dir_path / root_name

            if not root_path.exists():
                continue

            url = content_url_for(self.cfg, root_path)
            key = (url, "false")

            if key in existing:
                continue

            ET.SubElement(content, "sourceFolder", {"url": url, "isTestSource": "false"})
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
            logging.info("Updated exclude folders in %s", iml_path)

    def ensure_module_source_folders(
        self,
        iml_path: Path,
        dir_path: Path,
        source_roots: Iterable[str] = ("src",),
    ) -> None:
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

        if self._ensure_source_folders(content, dir_path, source_roots):
            write_xml(tree, iml_path)
            logging.info("Updated source folders in %s", iml_path)

    def write_module_minimal(
        self,
        module_name: str,
        dir_path: Path,
        source_roots: Iterable[str] = (),
    ) -> Path:
        iml_path = self.cfg.MODULES_DIR / f"{module_name}.iml"

        module = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
        comp = ET.SubElement(module, "component", {"name": "NewModuleRootManager"})
        content = ET.SubElement(comp, "content", {"url": content_url_for(self.cfg, dir_path)})

        self._ensure_source_folders(content, dir_path, source_roots)
        self._ensure_exclude_folders(content)

        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})

        write_xml(ET.ElementTree(module), iml_path)
        logging.info("IML created or overwritten: %s", iml_path)

        return iml_path

    def set_project_sdk(self, sdk_name: str) -> None:
        if self.cfg.MISC.exists():
            tree = read_xml(self.cfg.MISC)
            root = tree.getroot()
        else:
            root = ET.Element("project", {"version": "4"})
            tree = ET.ElementTree(root)

        project_root_manager = root.find("./component[@name='ProjectRootManager']")
        if project_root_manager is None:
            project_root_manager = ET.SubElement(root, "component", {"name": "ProjectRootManager"})

        project_root_manager.set("project-jdk-name", sdk_name)
        project_root_manager.set("project-jdk-type", self.cfg.PROJECT_SDK_TYPE)

        black_component = root.find("./component[@name='Black']")
        if black_component is None:
            black_component = ET.SubElement(root, "component", {"name": "Black"})

        option = black_component.find("./option[@name='sdkName']")
        if option is None:
            option = ET.SubElement(black_component, "option", {"name": "sdkName"})

        option.set("value", sdk_name)

        write_xml(tree, self.cfg.MISC)
        logging.info("Project SDK set to %s in %s", sdk_name, self.cfg.MISC)

    def set_module_sdk(self, iml_path: Path, sdk_name: str) -> None:
        if not iml_path.exists():
            logging.error("Module file %s does not exist.", iml_path)
            return

        tree = read_xml(iml_path)
        root = tree.getroot()

        comp = root.find("./component[@name='NewModuleRootManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "NewModuleRootManager"})

        for order_entry in list(comp.findall("orderEntry")):
            if order_entry.get("type") in {"inheritedJdk", "jdk"}:
                comp.remove(order_entry)

        ET.SubElement(
            comp,
            "orderEntry",
            {
                "type": "jdk",
                "jdkName": sdk_name,
                "jdkType": self.cfg.PROJECT_SDK_TYPE,
            },
        )

        write_xml(tree, iml_path)
        logging.info("Module SDK set to %s in %s", sdk_name, iml_path)

    def ensure_root_module_iml(self) -> Path:
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

                return path
            except ET.ParseError:
                logging.warning("Invalid root IML %s; recreating it.", path)

        module = ET.Element("module", {"type": "PYTHON_MODULE", "version": "4"})
        comp = ET.SubElement(module, "component", {"name": "NewModuleRootManager"})
        content = ET.SubElement(comp, "content", {"url": "file://$PROJECT_DIR$"})

        self._ensure_exclude_folders(content)

        ET.SubElement(comp, "orderEntry", {"type": "inheritedJdk"})
        ET.SubElement(comp, "orderEntry", {"type": "sourceFolder", "forTests": "false"})

        write_xml(ET.ElementTree(module), path)
        logging.info("Root module IML created: %s", path)

        return path

    def add_app_module_entry(self, module_name: str) -> Optional[Path]:
        project_name = module_name[:-8]

        tree = read_xml(self.cfg.MODULES)
        root = tree.getroot()

        comp = root.find("./component[@name='ProjectModuleManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "ProjectModuleManager"})

        modules = comp.find("modules")
        if modules is None:
            modules = ET.SubElement(comp, "modules")

        existing = {
            (m.get("fileurl"), m.get("filepath"))
            for m in modules.findall("module")
        }

        output = None
        changed = False

        for key in self.cfg.FILE_TEMPLATE.keys():
            fileurl = self.cfg.FILE_TEMPLATE[key][0].format(APP=project_name)
            filepath = self.cfg.FILE_TEMPLATE[key][1].format(APP=project_name)

            resolved_fp = self.cfg.resolve_macros(filepath or fileurl, project_name)
            is_within_repo = self.cfg.is_within_repo(resolved_fp)

            if not self.cfg.ALLOW_EXTERNAL_MODULES and not is_within_repo:
                continue

            if (fileurl, filepath) in existing:
                continue

            ET.SubElement(modules, "module", {"fileurl": fileurl, "filepath": filepath})
            existing.add((fileurl, filepath))
            changed = True

            if is_within_repo:
                output = resolved_fp

        if changed:
            write_xml(tree, self.cfg.MODULES)
            logging.info("Module entry for %s added to modules.xml", module_name)

        return output

    def add_module_entry(self, core_iml: Path) -> Optional[Path]:
        tree = read_xml(self.cfg.MODULES)
        root = tree.getroot()

        comp = root.find("./component[@name='ProjectModuleManager']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "ProjectModuleManager"})

        modules = comp.find("modules")
        if modules is None:
            modules = ET.SubElement(comp, "modules")

        fileurl = self.cfg.as_project_url(core_iml)
        filepath = self.cfg.as_project_macro(core_iml)

        for module in modules.findall("module"):
            if module.get("fileurl") == fileurl and module.get("filepath") == filepath:
                return None

        ET.SubElement(modules, "module", {"fileurl": fileurl, "filepath": filepath})
        write_xml(tree, self.cfg.MODULES)

        logging.info("Module entry for %s added to modules.xml", core_iml.name)

        return core_iml

    def generate_run_configs_for_apps(self, app_names: List[Path]) -> None:
        if not self.cfg.GEN_SCRIPT.exists():
            logging.info("Missing %s; skipping run configuration generation.", self.cfg.GEN_SCRIPT)
            return

        for rel in app_names:
            rel_path = rel if isinstance(rel, Path) else Path(rel)
            app_dir = (self.cfg.APPS_PATH / rel_path).resolve()

            app_python = venv_python_for(app_dir)
            if not app_python:
                logging.warning(
                    "No virtual environment found for %s; falling back to current Python: %s",
                    app_dir,
                    sys.executable,
                )
                app_python = Path(sys.executable)

            logging.info(
                "Generating run configs for %s using %s",
                rel_path.as_posix(),
                app_python,
            )

            subprocess.run(
                [str(app_python), str(self.cfg.GEN_SCRIPT), rel_path.as_posix()],
                check=True,
                cwd=str(self.cfg.ROOT),
            )

    def python_terminal_settings(self) -> None:
        term_cfg = self.cfg.IDEA_DIR / "python-terminal.xml"

        if term_cfg.exists():
            tree = read_xml(term_cfg)
            root = tree.getroot()
        else:
            root = ET.Element("project", {"version": "4"})
            tree = ET.ElementTree(root)

        comp = root.find("./component[@name='PyVirtualEnvTerminalCustomizer']")
        if comp is None:
            comp = ET.SubElement(root, "component", {"name": "PyVirtualEnvTerminalCustomizer"})

        option = comp.find("./option[@name='virtualEnvActivate']")
        if option is None:
            option = ET.SubElement(comp, "option", {"name": "virtualEnvActivate"})

        option.set("virtualEnvActivate", "false")

        write_xml(tree, term_cfg)


def ensure_modules_xml(cfg: Config) -> None:
    if cfg.MODULES.exists():
        return

    project = ET.Element("project", {"version": "4"})
    component = ET.SubElement(project, "component", {"name": "ProjectModuleManager"})
    ET.SubElement(component, "modules")

    write_xml(ET.ElementTree(project), cfg.MODULES)


def build_keep_sdks(cfg: Config) -> List[str]:
    keep_sdks = [cfg.PROJECT_SDK]

    keep_sdks += [f"uv ({app.name})" for app in cfg.eligible_apps]
    keep_sdks += [f"uv ({app.name[:-8]}_worker)" for app in cfg.eligible_apps]
    keep_sdks += [f"uv ({core.name})" for core in cfg.eligible_core]
    keep_sdks += [f"uv ({page.name})" for page in cfg.eligible_apps_pages]

    if cfg.AGISPACE.exists():
        keep_sdks.append("uv (agi-space)")

    return sorted(set(keep_sdks))


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parents[1]

    cfg = Config(root=path)
    cfg.create_directories()
    ensure_modules_xml(cfg)

    model = Project(cfg)
    jdk_table = JdkTable(cfg.PROJECT_SDK_TYPE)

    root_py = venv_python_for(cfg.ROOT)
    if root_py:
        jdk_table.add_jdk(cfg.PROJECT_SDK, root_py)
        model.set_project_sdk(cfg.PROJECT_SDK)
    else:
        logging.error("Project SDK %s not found.", cfg.PROJECT_SDK)
        return 1

    root_iml = model.ensure_root_module_iml()
    model.set_module_sdk(root_iml, cfg.PROJECT_SDK)
    model.add_module_entry(root_iml)
    model.ensure_module_excludes(root_iml, cfg.ROOT)

    realized_apps: List[Path] = []
    realized_apps_pages: List[str] = []
    realized_core: List[str] = []

    for app in cfg.eligible_apps:
        app_py = venv_python_for(app)

        if not app_py:
            app_py = _bootstrap_project_venv(app)

        if not app_py:
            logging.warning("No virtual environment found for %s, skipping.", app.name)
            continue

        added_project = model.add_app_module_entry(app.name)

        target = None
        if added_project and added_project.name.endswith("_project.iml"):
            target = added_project

        if not target:
            target = cfg.MODULES_DIR / f"{app.name}.iml"

        if not target.exists():
            model.write_module_minimal(target.stem, app)

            default_path = cfg.MODULES_DIR / f"{target.stem}.iml"
            if default_path != target and default_path.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                default_path.replace(target)
                logging.info("Moved IML to match template path: %s", target)

        model.ensure_module_excludes(target, app)

        sdk_app = f"uv ({app.name})"
        jdk_table.add_jdk(sdk_app, app_py)
        model.set_module_sdk(target, sdk_app)

        project = app.name[:-8]
        seed_example_scripts(cfg, project)

        worker_path = Path.home() / "wenv" / f"{project}_worker"
        worker_py = venv_python_for(worker_path)

        if worker_py:
            sdk_worker = f"uv ({project}_worker)"
            jdk_table.add_jdk(sdk_worker, worker_py)
            jdk_table.set_associated_project(sdk_worker, worker_py)
        else:
            logging.warning("No virtual environment found for %s, skipping worker SDK.", worker_path.name)

        try:
            realized_apps.append(app.relative_to(cfg.APPS_PATH))
        except ValueError:
            realized_apps.append(Path("builtin") / app.name)

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
                "No virtual environment found for %s after bootstrap; falling back to project SDK %s.",
                apps_page.name,
                cfg.PROJECT_SDK,
            )
            sdk_name = cfg.PROJECT_SDK

        model.set_module_sdk(iml, sdk_name)
        model.add_module_entry(iml)
        model.ensure_module_excludes(iml, apps_page)

        realized_apps_pages.append(apps_page.name)

    for core in cfg.eligible_core:
        core_py = venv_python_for(core)

        if not core_py:
            logging.warning("No virtual environment found for %s, skipping.", core.name)
            continue

        iml = model.write_module_minimal(core.name, core, source_roots=("src",))

        sdk_name = f"uv ({core.name})"
        jdk_table.add_jdk(sdk_name, core_py)
        model.set_module_sdk(iml, sdk_name)

        model.add_module_entry(iml)
        model.ensure_module_excludes(iml, core)
        model.ensure_module_source_folders(iml, core, source_roots=("src",))

        realized_core.append(core.name)

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

    keep_sdks = build_keep_sdks(cfg)
    jdk_table.prune_uv_names(keep_sdks)

    model.generate_run_configs_for_apps(realized_apps)
    model.python_terminal_settings()

    logging.info("Project setup completed successfully.")
    logging.info("Realized apps: %s", ", ".join(str(app) for app in realized_apps))
    logging.info("Realized core: %s", ", ".join(realized_core))
    logging.info("Realized apps-pages: %s", ", ".join(realized_apps_pages))

    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    raise SystemExit(main())