#!/usr/bin/env python3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# ---- paths ----
SCRIPT_DIR = Path(__file__).resolve().parent      # .../pycharm
ROOT = SCRIPT_DIR.parent                           # repo root
APPS_DIR = ROOT / "src" / "agilab" / "apps"
IDEA = ROOT / ".idea"
RUNCFG_DIR = IDEA / "runConfigurations"

# Discover all app templates placed next to this script
TEMPLATES = sorted([p for p in SCRIPT_DIR.glob("_template_app_*.xml")])

# ---- tiny utils ----
def debug(msg: str) -> None:
    print(f"[gen-app] {msg}")

def ensure_dirs() -> None:
    IDEA.mkdir(exist_ok=True)
    RUNCFG_DIR.mkdir(parents=True, exist_ok=True)

def venv_python_for(project_dir: Path) -> Optional[Path]:
    for p in [
        project_dir / ".venv" / "bin" / "python3",        # unix/mac
        project_dir / ".venv" / "bin" / "python",         # unix/mac alt
        project_dir / ".venv" / "Scripts" / "python.exe", # windows
    ]:
        if p.exists():
            return p.resolve()
    return None

def parse_template(path: Path) -> ET.ElementTree:
    return ET.parse(str(path))

def ensure_option(config_elem: ET.Element, name: str, value: str) -> None:
    for o in config_elem.findall("option"):
        if o.get("name") == name:
            o.set("value", value)
            return
    ET.SubElement(config_elem, "option", {"name": name, "value": value})

def replace_placeholders(root: ET.Element, app: str) -> None:
    """Replace {APP} in attributes and text."""
    for el in root.iter():
        for k, v in list(el.attrib.items()):
            el.set(k, v.replace("{APP}", app))
        if el.text:
            el.text = el.text.replace("{APP}", app)

def set_folder(config_elem: ET.Element, folder: str) -> None:
    # support both attributes used by different IDE versions
    if "folder" in config_elem.attrib:
        config_elem.set("folder", folder)
    else:
        config_elem.set("folderName", folder)

def patch_sdk_home(tree: ET.ElementTree, py: Path) -> None:
    cfg = tree.getroot().find(".//configuration")
    if cfg is None:
        return
    ensure_option(cfg, "SDK_HOME", str(py))
    # Keep SDK_NAME from template (cosmetic)

def safe_filename_from_conf_name(name: str) -> str:
    import re
    base = name.strip().lower().replace(" ", "_")
    base = re.sub(r"[^a-z0-9_\-]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    return f"{base}.xml" if base else "config.xml"

def write_run_config(tree: ET.ElementTree, out_name: str) -> None:
    out_path = RUNCFG_DIR / out_name
    tree.write(str(out_path), encoding="UTF-8", xml_declaration=True)
    debug(f"wrote {out_path.relative_to(ROOT)}")

# ---- main ----
def main() -> int:
    ensure_dirs()

    # Accept positional <module_name> or --module-name <module_name>
    module_name: Optional[str] = None
    args = [a for a in sys.argv[1:] if a != "--"]
    if not args:
        print("Usage: gen-app-script.py <module_name>  (or --module-name <module_name>)")
        return 2
    if args[0] == "--module-name":
        if len(args) < 2:
            print("error: --module-name requires a value")
            return 2
        module_name = args[1]
    else:
        module_name = args[0]

    app = module_name  # {APP} placeholder (without '_project')
    app_dir = APPS_DIR / f"{app}_project"
    if not app_dir.exists():
        debug(f"warning: {app_dir} not found; falling back to project root for interpreter.")
        app_dir = ROOT

    py = venv_python_for(app_dir)
    if py is None:
        debug(f"warning: no .venv interpreter found for {app_dir}; SDK_HOME will be empty.")
    else:
        debug(f"interpreter for {app}: {py}")

    if not TEMPLATES:
        debug(f"no templates found in {SCRIPT_DIR}")
        return 0

    for tpl in TEMPLATES:
        try:
            tree = parse_template(tpl)
        except Exception as e:
            debug(f"skip template {tpl.name}: {e}")
            continue

        root = tree.getroot()
        replace_placeholders(root, app)

        if py is not None:
            patch_sdk_home(tree, py)

        cfg = root.find(".//configuration")
        conf_name = cfg.get("name", f"{app}_config") if cfg is not None else f"{app}_config"
        if cfg is not None:
            set_folder(cfg, app)

        out_name = safe_filename_from_conf_name(conf_name)
        write_run_config(tree, out_name)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
