import os
import sys
import xml.etree.ElementTree as ET
import filecmp
import tempfile
from pathlib import Path


def update_workspace_xml(config_name, config_type, folder_name: str) -> None:
    workspace_path = os.path.join(os.getcwd(), ".idea", "workspace.xml")
    if not os.path.exists(workspace_path):
        root = ET.Element("project", version="4")
        ET.SubElement(root, "component", {"name": "RunManager"})
        ET.ElementTree(root).write(workspace_path, encoding="utf-8", xml_declaration=True)

    tree = ET.parse(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    if runmanager is None:
        runmanager = ET.SubElement(root, "component", {"name": "RunManager"})

    config_el = None
    for conf in runmanager.findall("configuration"):
        if conf.attrib.get("name") == config_name and conf.attrib.get("type") == config_type:
            config_el = conf
            break

    if config_el is None:
        ET.SubElement(
            runmanager,
            "configuration",
            {
                "name": config_name,
                "type": config_type,
                "folderName": folder_name,
                "factoryName": config_type.replace("ConfigurationType", ""),
            },
        )
    else:
        config_el.attrib["folderName"] = folder_name

    tree.write(workspace_path, encoding="utf-8", xml_declaration=True)
    print(f"Updated workspace.xml for config '{config_name}' in folder '{folder_name}'.")


def update_folders_xml(folder_name: str) -> None:
    output_dir = os.path.join(os.getcwd(), ".idea", "runConfigurations")
    folders_xml_path = os.path.join(output_dir, "folders.xml")

    if os.path.exists(folders_xml_path):
        tree = ET.parse(folders_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element("component", attrib={"name": "RunManager"})
        tree = ET.ElementTree(root)

    existing = root.find(f"./folder[@name='{folder_name}']")
    if existing is None:
        ET.SubElement(root, "folder", attrib={"name": folder_name})
        tree.write(folders_xml_path, encoding="utf-8", xml_declaration=True)
        print(f"Added folder '{folder_name}' to folders.xml")
    else:
        print(f"Folder '{folder_name}' already exists in folders.xml")


def _replace_placeholders(tree: ET.ElementTree, app: str) -> None:
    """Replace {APP} with the given app string everywhere in the template."""
    for el in tree.getroot().iter():
        # attributes
        for k, v in list(el.attrib.items()):
            if "{APP}" in v:
                el.attrib[k] = v.replace("{APP}", app)
        # text nodes
        if el.text and "{APP}" in el.text:
            el.text = el.text.replace("{APP}", app)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: gen_app_script.py <replacement_name>")
        sys.exit(1)

    app_arg = sys.argv[1]  # e.g. "builtin/flight_project" or "example_app_project"
    if not app_arg:
        print("No name entered. Exiting.")
        sys.exit(1)

    # app_dir: used as {APP} in templates
    #   "builtin/flight_project" -> "builtin/flight"
    #   "example_app_project"   -> "example_app"
    if app_arg.endswith("_project"):
        app_dir = app_arg[:-8]
    else:
        app_dir = app_arg

    # app_name: leaf part only ("flight", "example_app")
    app_name = Path(app_dir).name.replace("builtin/","")

    # For workspace/folders we want the full project name, e.g. "builtin/flight_project"
    folder_name = app_arg

    print(f"CLI arg      : {app_arg}")
    print(f"App dir      : {app_dir}")
    print(f"App name     : {app_name}")
    print(f"Folder name  : {folder_name}")

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

    output_dir = os.path.join(os.getcwd(), ".idea", "runConfigurations")
    os.makedirs(output_dir, exist_ok=True)

    for filename in template_names:
        tpl_path = templates_root / filename
        if not tpl_path.exists():
            print(f"Warning: skipped template '{filename}' (file not found in {templates_root}).")
            continue

        tree = ET.parse(tpl_path)

        # First pass: {APP} -> app_dir ("builtin/flight", "example_app", etc.)
        _replace_placeholders(tree, app_dir)

        # File name uses leaf name only (so: _flight_*.xml, not _builtin/flight_*.xml)
        base = tpl_path.name.replace("_template_app", f"_{app_name}")
        out_path = os.path.join(output_dir, base)

        root = tree.getroot()
        first_cfg = next(root.iter("configuration"), None)
        if first_cfg is None:
            print(f"Skip {tpl_path}: no <configuration> element.")
            continue

        # At this point, for builtin/flight_project templates we have:
        #   name="builtin/flight install"
        #   folderName="builtin/flight_project"
        #   SCRIPT_NAME="$USER_HOME$/log/execute/builtin/flight/AGI_install_builtin/flight.py"
        # We want to ONLY adjust the directory part of SCRIPT_NAME:
        #   SCRIPT_NAME="$USER_HOME$/log/execute/flight/AGI_install_builtin/flight.py"

        for opt in first_cfg.findall("option"):
            if opt.attrib.get("name") == "SCRIPT_NAME":
                val = opt.attrib.get("value", "")
                marker = "log/execute/"
                idx = val.find(marker)
                if idx != -1:
                    prefix = val[: idx + len(marker)]  # "$USER_HOME$/log/execute/"
                    # Force directory and filename to use the leaf app_name (e.g. "flight")
                    opt.attrib["value"] = prefix + f"{app_name}/AGI_install_{app_name}.py"

        config_name = first_cfg.attrib.get("name", os.path.splitext(base)[0])
        config_type = first_cfg.attrib.get("type", "PythonConfigurationType")

        if os.path.exists(out_path):
            fd, tmp_path = tempfile.mkstemp(suffix=".xml")
            os.close(fd)
            tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
            if filecmp.cmp(tmp_path, out_path, shallow=False):
                print(f"Skipped (unchanged): {out_path}")
                os.remove(tmp_path)
            else:
                os.replace(tmp_path, out_path)
                print(f"Updated config (changed): {out_path}")
            update_workspace_xml(config_name, config_type, folder_name)
            continue

        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        print(f"Generated config: {out_path}")
        update_workspace_xml(config_name, config_type, folder_name)

    update_folders_xml(folder_name)
    print(f"All {app_arg} configurations processed.")
