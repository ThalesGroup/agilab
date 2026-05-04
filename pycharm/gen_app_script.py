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


def _normalize_module_name(raw_module: str, app_dir: str, module_name: str) -> str:
    """Keep app modules slash-free while preserving non-app template modules."""
    if raw_module == module_name or raw_module == f"{app_dir}_project":
        return module_name
    if raw_module.endswith(f"/{module_name}"):
        return module_name
    return raw_module


def _normalize_sdk_name(raw_sdk_name: str, module_name: str, app_name: str) -> str:
    """Map SDK names back to the venv names created by setup_pycharm.py."""
    if not raw_sdk_name.startswith("uv (") or not raw_sdk_name.endswith(")"):
        return raw_sdk_name
    if raw_sdk_name.endswith("_project)"):
        return f"uv ({module_name})"
    if raw_sdk_name.endswith("_worker)"):
        return f"uv ({app_name}_worker)"
    return raw_sdk_name


def _normalize_builtin_worker_references(raw_value: str, app_dir: str, app_name: str) -> str:
    """Built-in apps live under apps/builtin, but worker venvs do not."""
    if app_dir != app_name:
        return raw_value.replace(f"{app_dir}_worker", f"{app_name}_worker")
    return raw_value


def _normalize_test_script_name(raw_value: str, app_dir: str, app_name: str) -> str:
    if app_dir == app_name:
        return raw_value
    return raw_value.replace(f"/test/test_{app_dir}_", f"/test/test_{app_name}_")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: gen_app_script.py <app>")
        sys.exit(1)

    # Example values:
    #   raw_arg = "example_app_project"
    #   raw_arg = "builtin/flight_project"
    raw_arg = sys.argv[1]
    app_path = Path(raw_arg)

    # module name is always last segment, e.g. "flight_project"
    module_name = app_path.name

    # app name without "_project" suffix, e.g. "flight"
    if module_name.endswith("_project"):
        app_name = module_name[:-8]
    else:
        app_name = module_name

    # app_dir = what we substitute into {APP} in the templates:
    #   for "example_app_project"          -> "example_app"
    #   for "builtin/flight_project"       -> "builtin/flight"
    if app_path.parent == Path("."):
        app_dir = app_name
    else:
        app_dir = f"{app_path.parent.as_posix()}/{app_name}"

    # folder name in workspace/folders is the full project name:
    #   "example_app_project"
    #   "builtin/flight_project"
    folder_name = raw_arg

    # setup_pycharm creates SDKs like: uv (flight_project), uv (mycode_project), ...
    sdk_name_for_app = f"uv ({module_name})"

    print(f"CLI arg      : {raw_arg}")
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
        # IMPORTANT: pass a STRING, not a Path
        _replace_placeholders(tree, app_dir)

        base = tpl_path.name.replace("_template_app", f"_{app_name}")
        out_path = os.path.join(output_dir, base)

        root = tree.getroot()
        first_cfg = next(root.iter("configuration"), None)
        if first_cfg is None:
            print(f"Skip {tpl_path}: no <configuration> element.")
            continue

        # Needed later for workspace.xml
        config_name = first_cfg.attrib.get("name", os.path.splitext(base)[0])
        config_type = first_cfg.attrib.get("type", "PythonConfigurationType")

        # --- 1) normalize app modules, but preserve explicit core modules like agi-cluster ---
        module_el = first_cfg.find("module")
        if module_el is None:
            ET.SubElement(first_cfg, "module", {"name": module_name})
        else:
            module_el.set("name", _normalize_module_name(module_el.get("name", ""), app_dir, module_name))

        # ---- Adjust SCRIPT_NAME for this app ----
        for opt in first_cfg.findall("option"):
            name = opt.attrib.get("name")
            if "value" in opt.attrib:
                opt.attrib["value"] = _normalize_builtin_worker_references(
                    opt.attrib["value"],
                    app_dir,
                    app_name,
                )

            if name == "SCRIPT_NAME":
                val = opt.attrib.get("value", "")
                marker = "log/execute/"
                idx = val.find(marker)

                if idx != -1:
                    base_prefix = val[: idx + len(marker)]

                    agi_idx = val.find("AGI_", idx)
                    if agi_idx != -1:
                        after_agi = val[agi_idx + len("AGI_") :]
                        underscore_idx = after_agi.find("_")
                        if underscore_idx != -1:
                            action = after_agi[:underscore_idx]  # install, run, get_distrib, ...

                            # e.g. $USER_HOME$/log/execute/flight/AGI_install_flight.py
                            opt.attrib["value"] = f"{base_prefix}{app_name}/AGI_{action}_{app_name}.py"

                opt.attrib["value"] = _normalize_test_script_name(opt.attrib["value"], app_dir, app_name)

            elif name == "SDK_NAME":
                opt.attrib["value"] = _normalize_sdk_name(opt.attrib.get("value", ""), module_name, app_name)

            elif name == "IS_MODULE_SDK":
                opt.attrib["value"] = "false"

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
    print(f"All {raw_arg} configurations processed.")
