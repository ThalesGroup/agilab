import xml.etree.ElementTree as ET
from pathlib import Path

WORKSPACE_FILE = "../../../.idea/workspace.xml"
PWD = Path.cwd()
DEFAULT_PROJECT = "agi-space"
INCLUDED_APPS = [
    "mycode_project",
    "flight_project",
    "sat_trajectory_project",
    "flight_trajectory_project",
    "link_sim_project",
    # "flight_legacy_project",
]

# Map included apps to their local interpreter path (relative like in install.sh)
def get_interpreter_path(project_name):
    if project_name in INCLUDED_APPS:
        return str(PWD / project_name / ".venv/bin/python3")
    else:
        # fallback for generic config: main space venv
        return str(PWD.parent / DEFAULT_PROJECT / ".venv/bin/python3")

def get_sdk_name(project_name):
    if project_name in INCLUDED_APPS:
        return f"uv ({project_name})"
    else:
        return f"uv ({DEFAULT_PROJECT})"

def infer_project_name(config):
    # Try <module name="..."/>
    module = config.find('module')
    if module is not None and module.get("name") in INCLUDED_APPS:
        return module.get("name")
    # Try folderName
    folder = config.get("folderName")
    if folder in INCLUDED_APPS:
        return folder
    # If config name matches, use it (rare)
    name = config.get("name", "")
    for app in INCLUDED_APPS:
        if app in name:
            return app
    # Default fallback
    return DEFAULT_PROJECT

tree = ET.parse(WORKSPACE_FILE)
root = tree.getroot()
changed = False

for component in root.findall('.//component[@name="RunManager"]'):
    for config in component.findall('configuration'):
        project_name = infer_project_name(config)
        sdk_home_path = get_interpreter_path(project_name)
        sdk_name = get_sdk_name(project_name)

        # Patch or add SDK_HOME
        sdk_home = config.find('option[@name="SDK_HOME"]')
        if sdk_home is not None:
            if not sdk_home.get("value"):
                print(f"Patching SDK_HOME for '{config.get('name')}' → {sdk_home_path}")
                sdk_home.set("value", sdk_home_path)
                changed = True
        else:
            print(f"Adding SDK_HOME to '{config.get('name')}' → {sdk_home_path}")
            ET.SubElement(config, "option", name="SDK_HOME", value=sdk_home_path)
            changed = True

        # Patch or add SDK_NAME
        sdk_name_opt = config.find('option[@name="SDK_NAME"]')
        if sdk_name_opt is not None:
            if not sdk_name_opt.get("value"):
                print(f"Patching SDK_NAME for '{config.get('name')}' → {sdk_name}")
                sdk_name_opt.set("value", sdk_name)
                changed = True
        else:
            print(f"Adding SDK_NAME to '{config.get('name')}' → {sdk_name}")
            ET.SubElement(config, "option", name="SDK_NAME", value=sdk_name)
            changed = True

if changed:
    tree.write(WORKSPACE_FILE, encoding="utf-8", xml_declaration=True)
    print("workspace.xml patched.")
else:
    print("Nothing to patch: all configs already have SDK_HOME and SDK_NAME set.")

