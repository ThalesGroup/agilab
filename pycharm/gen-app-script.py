#!/usr/bin/env python3
"""
gen-apps.py — Generate PyCharm run configurations per app, grouped by folder.

Usage:
  # scan current ./apps dir for *_project
  ./gen-apps.py

  # specify apps dir
  ./gen-apps.py --apps-dir /path/to/apps

  # explicit app names
  ./gen-apps.py flight_trajectory_project sat_trajectory_project
"""
from __future__ import annotations
import argparse
import filecmp
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, List

# ---- Templates to expand (must contain {APP} placeholders) -------------------
TEMPLATE_PATHS = [
    'pycharm/_template_app_egg_manager.xml',
    'pycharm/_template_app_lib_worker.xml',
    'pycharm/_template_app_preinstall_manager.xml',
    'pycharm/_template_app_postinstall_worker.xml',
    'pycharm/_template_app_run.xml',
    'pycharm/_template_app_test_manager.xml',
    'pycharm/_template_app_test_worker.xml',
    'pycharm/_template_app_test.xml',
]

# ---- Helpers -----------------------------------------------------------------
def ensure_workspace_has_runmanager(workspace_path: Path) -> ET.ElementTree:
    if not workspace_path.exists():
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        root = ET.Element('project', version="4")
        ET.SubElement(root, 'component', {'name': 'RunManager'})
        tree = ET.ElementTree(root)
        tree.write(workspace_path, encoding="utf-8", xml_declaration=True)
        return tree
    tree = ET.parse(workspace_path)
    root = tree.getroot()
    if root.find("./component[@name='RunManager']") is None:
        ET.SubElement(root, 'component', {'name': 'RunManager'})
    return tree

def update_workspace_xml(workspace_path: Path, config_name: str, config_type: str, folder_name: str) -> None:
    tree = ensure_workspace_has_runmanager(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    assert runmanager is not None

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

def update_folders_xml(runconfigs_dir: Path, folder_name: str) -> None:
    runconfigs_dir.mkdir(parents=True, exist_ok=True)
    folders_xml_path = runconfigs_dir / 'folders.xml'
    if folders_xml_path.exists():
        tree = ET.parse(folders_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element('component', attrib={'name': 'RunManager'})
        tree = ET.ElementTree(root)

    if root.find(f"./folder[@name='{folder_name}']") is None:
        ET.SubElement(root, 'folder', attrib={'name': folder_name})
        tree.write(folders_xml_path, encoding='utf-8', xml_declaration=True)

def add_folder_name_to_config(tree: ET.ElementTree, folder_name: str) -> None:
    config_elem = next(tree.getroot().iter('configuration'), None)
    if config_elem is not None:
        config_elem.attrib['folderName'] = folder_name

def iter_apps(apps_dir: Path) -> Iterable[str]:
    for p in sorted(apps_dir.glob("*_project")):
        if p.is_dir():
            yield p.name

def load_and_replace(tpl_path: Path, app: str) -> ET.ElementTree:
    tree = ET.parse(tpl_path)
    root = tree.getroot()
    for el in root.iter():
        for k, v in list(el.attrib.items()):
            if '{APP}' in v:
                el.attrib[k] = v.replace('{APP}', app)
        if el.text and '{APP}' in el.text:
            el.text = el.text.replace('{APP}', app)
    return tree

def write_if_changed(tree: ET.ElementTree, out_path: Path) -> str:
    # returns action string for logging
    if out_path.exists():
        fd, tmp_path = tempfile.mkstemp(suffix='.xml')
        os.close(fd)
        tmp_path_p = Path(tmp_path)
        tree.write(tmp_path_p, encoding="utf-8", xml_declaration=True)
        if filecmp.cmp(tmp_path_p, out_path, shallow=False):
            tmp_path_p.unlink()
            return f"Skipped (unchanged): {out_path.name}"
        else:
            os.replace(tmp_path_p, out_path)
            return f"Updated (changed): {out_path.name}"
    else:
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        return f"Generated: {out_path.name}"

def process_app(app: str, project_root: Path) -> None:
    # Paths
    idea_dir = project_root / ".idea"
    runconfigs_dir = idea_dir / "runConfigurations"
    workspace_path = idea_dir / "workspace.xml"

    # One folder per app
    folder_name = app

    # Ensure the folder exists in folders.xml (once per app)
    update_folders_xml(runconfigs_dir, folder_name)

    # Generate every template for this app
    for tpl in TEMPLATE_PATHS:
        tpl_path = project_root / tpl
        if not tpl_path.exists():
            print(f"[warn] Missing template: {tpl}")
            continue

        tree = load_and_replace(tpl_path, app)
        add_folder_name_to_config(tree, folder_name)

        base = tpl_path.name.replace('_template_app', f'_{app}')
        out_path = runconfigs_dir / base

        # Determine config name/type for workspace.xml
        cfg = next(tree.getroot().iter('configuration'))
        config_name = cfg.attrib.get('name', base.rsplit('.', 1)[0])
        config_type = cfg.attrib.get('type', 'PythonConfigurationType')

        action = write_if_changed(tree, out_path)
        print(action)

        # Keep workspace.xml in sync
        update_workspace_xml(workspace_path, config_name, config_type, folder_name)

    print(f"[ok] All '{app}' configurations grouped under '{folder_name}'")

# ---- CLI --------------------------------------------------------------------
def parse_args(argv: List[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Generate grouped PyCharm run configs per app.")
    ap.add_argument("apps", nargs="*", help="App names (e.g., flight_trajectory_project). If empty, scan --apps-dir.")
    ap.add_argument("--apps-dir", default=str((Path.cwd() / "apps").resolve()),
                    help="Directory to scan for *_project when no apps are passed (default: ./apps).")
    ap.add_argument("--project-root", default=str(Path.cwd().resolve()),
                    help="Project root containing .idea/ and pycharm/ (default: CWD).")
    return ap.parse_args(argv)

def main(argv: List[str]) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).resolve()
    apps: List[str] = args.apps

    if not apps:
        apps_dir = Path(args.apps_dir).resolve()
        if not apps_dir.exists():
            print(f"[error] apps dir not found: {apps_dir}")
            return 2
        apps = list(iter_apps(apps_dir))
        if not apps:
            print(f"[warn] no *_project found in {apps_dir}")
            return 0

    for app in apps:
        process_app(app, project_root)

    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
