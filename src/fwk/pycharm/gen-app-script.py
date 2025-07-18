import os
import sys
import xml.etree.ElementTree as ET
import filecmp
import tempfile

def update_workspace_xml(config_name, config_type, folder_name):
    workspace_path = os.path.join(os.getcwd(), '.idea', 'workspace.xml')
    # If file does not exist, create minimal skeleton
    if not os.path.exists(workspace_path):
        root = ET.Element('project', version="4")
        ET.SubElement(root, 'component', {'name': 'RunManager'})
        tree = ET.ElementTree(root)
        tree.write(workspace_path)
    tree = ET.parse(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    if runmanager is None:
        runmanager = ET.SubElement(root, 'component', {'name': 'RunManager'})
    # Check for existing configuration
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
            'factoryName': config_type.replace('ConfigurationType', ''),  # not always correct but safe
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

    # Check if folder already exists
    existing = root.find(f"./folder[@name='{folder_name}']")
    if existing is None:
        ET.SubElement(root, 'folder', attrib={'name': folder_name})
        tree.write(folders_xml_path, encoding='utf-8', xml_declaration=True)
        print(f"Added folder '{folder_name}' to folders.xml")
    else:
        print(f"Folder '{folder_name}' already exists in folders.xml")


def add_folder_name_to_config(tree, folder_name):
    config_elem = next(tree.getroot().iter('configuration'), None)
    if config_elem is not None:
        config_elem.attrib['folderName'] = folder_name


if len(sys.argv) < 2:
    print("Usage: script.py <replacement_name>")
    sys.exit(1)

app = sys.argv[1]
if not app:
    print("No name entered. Exiting.")
    sys.exit(1)

print(f"Replacement name: {app}")

template_paths = [
    'pycharm/_template_app_egg_manager.xml',
    'pycharm/_template_app_lib_worker.xml',
    'pycharm/_template_app_preinstall_manager.xml',
    'pycharm/_template_app_postinstall_worker.xml',
    'pycharm/_template_app_run.xml',
    'pycharm/_template_app_test_manager.xml',
    'pycharm/_template_app_test_worker.xml',
    'pycharm/_template_app_test.xml',
]

output_dir = os.path.join(os.getcwd(), '.idea', 'runConfigurations')
os.makedirs(output_dir, exist_ok=True)

FOLDER_NAME = f"{app}"

for tpl in template_paths:
    tree = ET.parse(tpl)
    root = tree.getroot()

    # replace {APP} placeholders
    for el in root.iter():
        for k, v in el.attrib.items():
            if '{APP}' in v:
                el.attrib[k] = v.replace('{APP}', app)
        if el.text and '{APP}' in el.text:
            el.text = el.text.replace('{APP}', app)

    # Add folderName attribute to configuration element
    add_folder_name_to_config(tree, FOLDER_NAME)

    # derive output filename
    base = os.path.basename(tpl).replace('_template_app', f'_{app}')
    out_path = os.path.join(output_dir, base)

    # Get config name/type for workspace.xml
    config_elem = next(root.iter('configuration'))
    config_name = config_elem.attrib.get('name', base.rsplit('.', 1)[0])
    config_type = config_elem.attrib.get('type', 'PythonConfigurationType')

    # --- idempotency check ----------------
    if os.path.exists(out_path):
        fd, tmp_path = tempfile.mkstemp(suffix='.xml')
        os.close(fd)
        tree.write(tmp_path)
        if filecmp.cmp(tmp_path, out_path, shallow=False):
            print(f"Skipped (unchanged): {out_path}")
            os.remove(tmp_path)
        else:
            os.replace(tmp_path, out_path)
            print(f"Updated config (changed): {out_path}")
            update_workspace_xml(config_name, config_type, FOLDER_NAME)
        continue

    # first time write
    tree.write(out_path)
    print(f"Generated config: {out_path}")
    update_workspace_xml(config_name, config_type, FOLDER_NAME)

# Update folders.xml once after processing all templates
update_folders_xml(FOLDER_NAME)

print(f"All {app} configurations processed.")
