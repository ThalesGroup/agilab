import os
import sys
import xml.etree.ElementTree as ET
import filecmp
import tempfile
from pathlib import Path


def update_workspace_xml(config_name, config_type, folder_name: str) -> None:
    """
    Ensure that workspace.xml has a RunManager configuration entry
    with the given name/type and folderName.
    """
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
    """
    Ensure that .idea/runConfigurations/folders.xml has a folder entry
    for the given folder_name.
    """
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
    """
    Replace {APP} with the given app string everywhere in the template.
    """
    root = tree.getroot()
    for el in root.iter():
        # attributes
        for k, v in list(el.attrib.items()):
            if "{APP}" in v:
                el.attrib[k] = v.replace("{APP}", app)
        # text
        if el.text and "{APP}" in el.text:
            el.text = el.text.replace("{APP}", app)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: gen_app_script.py <app_name_or_path>")
        sys.exit(1)

    # examples:
    #   "example_app_project"
    #   "builtin/flight_project"
    app_arg = sys.argv[1]

    if not app_arg:
        print("No name entered. Exiting.")
        sys.exit(1)

    # app_dir is the directory-like value used for {APP}:
    #   "example_app_project"   -> "example_app"
    #   "builtin/flight_project" -> "builtin/flight"
    if app_arg.endswith("_project"):
        app_dir = app_arg[:-8]
    else:
        app_dir = app_arg

    # leaf app name (no "builtin/"):
    #   "example_app"
    #   "flight"
    app_name = Path(app_dir).name

    # folder name in workspace/folders is the full project name
    #   "example_app_project"
    #   "builtin/flight_project"
    folder_name = app_arg

    # setup_pycharm creates SDKs like: uv (flight_project), uv (mycode_project), ...
    sdk_name_for_app = f"uv ({Path(app_arg).name})"

    print(f"CLI arg      : {app_arg}")
    print(f"App dir      : {app_dir}")
    print(f"App name     : {app_name}")
    print(f"Folder name  : {folder_name}")
    print(f"SDK name     : {sdk_name_for_app}")

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

        # First pass: replace {APP} with directory-like value (may include "builtin/")
        _replace_placeholders(tree, app_dir)

        base = tpl_path.name.replace("_template_app", f"_{app_name}")
        out_path = os.path.join(output_dir, base)

        root = tree.getroot()
        first_cfg = next(root.iter("configuration"), None)
        if first_cfg is None:
            print(f"Skip {tpl_path}: no <configuration> element.")
            continue

        config_name = first_cfg.attrib.get("name", os.path.splitext(base)[0])
        config_type = first_cfg.attrib.get("type", "PythonConfigurationType")

        # ---- Adjust SCRIPT_NAME + SDK_NAME for this app ----
        for opt in first_cfg.findall("option"):
            name = opt.attrib.get("name")

            if name == "SCRIPT_NAME":
                val = opt.attrib.get("value", "")
                marker = "log/execute/"
                idx = val.find(marker)
                if idx == -1:
                    continue

                base_prefix = val[: idx + len(marker)]

                agi_idx = val.find("AGI_", idx)
                if agi_idx == -1:
                    continue
                after_agi = val[agi_idx + len("AGI_") :]
                underscore_idx = after_agi.find("_")
                if underscore_idx == -1:
                    continue

                action = after_agi[:underscore_idx]  # install, run, get_distrib, ...

                # e.g. $USER_HOME$/log/execute/flight/AGI_install_flight.py
                opt.attrib["value"] = f"{base_prefix}{app_name}/AGI_{action}_{app_name}.py"

            elif name == "IS_MODULE_SDK":
                # Force using the module's SDK (which is uv (flight_project) for module flight_project)
                opt.attrib["value"] = "true"

            elif name == "SDK_NAME":
                # When using module SDK, we don't need an explicit SDK_NAME here.
                # You can either clear it:
                opt.attrib["value"] = ""
                # Or, if you prefer, delete the option entirely:
                # first_cfg.remove(opt)


        # ---- Write / update file on disk ----
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
