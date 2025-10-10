import os
import sys
import xml.etree.ElementTree as ET
import filecmp
import tempfile
from pathlib import Path

def update_workspace_xml(config_name, config_type, folder_name):
    workspace_path = os.path.join(os.getcwd(), '.idea', 'workspace.xml')
    if not os.path.exists(workspace_path):
        root = ET.Element('project', version="4")
        ET.SubElement(root, 'component', {'name': 'RunManager'})
        ET.ElementTree(root).write(workspace_path, encoding="utf-8", xml_declaration=True)
    tree = ET.parse(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    if runmanager is None:
        runmanager = ET.SubElement(root, 'component', {'name': 'RunManager'})
    config_el = None
    for conf in runmanager.findall('configuration'):
        if conf.attrib.get('name') == config_name and conf.attrib.get('type') == config_type:
            config_el = conf
            break
    if config_el is None:
        ET.SubElement(runmanager, 'configuration', {
            'name': config_name,
            'type': config_type,
            'folderName': folder_name,
            'factoryName': config_type.replace('ConfigurationType', ''),
        })
    else:
        config_el.attrib['folderName'] = folder_name
    tree.write(workspace_path, encoding="utf-8", xml_declaration=True)
    print(f"Updated workspace.xml for config '{config_name}' in folder '{folder_name}'.")

def update_folders_xml(folder_name):
    output_dir = os.path.join(os.getcwd(), '.idea', 'runConfigurations')
    folders_xml_path = os.path.join(output_dir, 'folders.xml')
    if os.path.exists(folders_xml_path):
        tree = ET.parse(folders_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element('component', attrib={'name': 'RunManager'})
        tree = ET.ElementTree(root)
    existing = root.find(f"./folder[@name='{folder_name}']")
    if existing is None:
        ET.SubElement(root, 'folder', attrib={'name': folder_name})
        tree.write(folders_xml_path, encoding='utf-8', xml_declaration=True)
        print(f"Added folder '{folder_name}' to folders.xml")
    else:
        print(f"Folder '{folder_name}' already exists in folders.xml")

def _replace_placeholders(tree, app: str):
    for el in tree.getroot().iter():
        for k, v in list(el.attrib.items()):
            if '{APP}' in v:
                el.attrib[k] = v.replace('{APP}', app)
        if el.text and '{APP}' in el.text:
            el.text = el.text.replace('{APP}', app)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: script.py <replacement_name>")
        sys.exit(1)

    app = sys.argv[1]
    if not app:
        print("No name entered. Exiting.")
        sys.exit(1)

    if app.endswith('_project'):
        app_name = app[:-8]  # Remove '_project' suffix if present
    else:
        app_name = app

    print(f"Replacement name: {app}")

    script_root = Path(__file__).resolve().parent
    templates_root = script_root / "app-scripts"

    template_names = [
        "_template_app_egg_manager.xml",
        "_template_app_lib_worker.xml",
        "_template_app_preinstall_manager.xml",
        "_template_app_postinstall_worker.xml",
        "_template_app_run.xml",
        "_template_app_install.xml",
        "_template_app_get_distrib.xml",
        "_template_app_test_manager.xml",
        "_template_app_test_worker.xml",
        "_template_app_call_worker.xml",
        "_template_app_test.xml",
    ]

    output_dir = os.path.join(os.getcwd(), '.idea', 'runConfigurations')
    os.makedirs(output_dir, exist_ok=True)

    for filename in template_names:
        tpl_path = templates_root / filename
        if not tpl_path.exists():
            print(f"Warning: skipped template '{filename}' (file not found in {templates_root}).")
            continue

        tree = ET.parse(tpl_path)
        _replace_placeholders(tree, app_name)

        # Run configuration display names now use a space (AGI run, AGI install, AGI get distrib)

        base = tpl_path.name.replace('_template_app', f'_{app_name}')
        out_path = os.path.join(output_dir, base)

        first_cfg = next(tree.getroot().iter("configuration"), None)
        if first_cfg is None:
            print(f"Skip {tpl}: no <configuration> element.")
            continue
        config_name = first_cfg.attrib.get("name", os.path.splitext(base)[0])
        config_type = first_cfg.attrib.get("type", "PythonConfigurationType")

        if os.path.exists(out_path):
            fd, tmp_path = tempfile.mkstemp(suffix='.xml')
            os.close(fd)
            tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
            if filecmp.cmp(tmp_path, out_path, shallow=False):
                print(f"Skipped (unchanged): {out_path}")
                os.remove(tmp_path)
            else:
                os.replace(tmp_path, out_path)
                print(f"Updated config (changed): {out_path}")
            update_workspace_xml(config_name, config_type, app)
            continue

        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        print(f"Generated config: {out_path}")
        update_workspace_xml(config_name, config_type, app)

    update_folders_xml(app)
    print(f"All {app} configurations processed.")
