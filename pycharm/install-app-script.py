# ======================
# Apps-only auto run: install.sh + generate configs + set interpreter
# - follows symlinks for .venv/.idea checks
# - interpreter name comes from the *link* folder (apps/<name>_project)
# - handles legacy vs new install.sh interface
# ======================
import os, time, shutil, subprocess
from pathlib import Path as _P
import xml.etree.ElementTree as ET

def _xml_write(_tree: ET.ElementTree, _target: _P):
    _tree.write(_target, encoding="utf-8", xml_declaration=True)

def _ensure_sdk_in_misc(_misc_path: _P, desired_name: str) -> bool:
    if _misc_path.exists():
        try:
            t = ET.parse(_misc_path); r = t.getroot()
        except ET.ParseError as e:
            print(f"[misc.xml] {_misc_path.parent.name}: XML parse error: {e}")
            return False
    else:
        r = ET.Element("project", version="4"); t = ET.ElementTree(r)

    comp = None
    for c in r.findall("component"):
        if c.get("name") == "ProjectRootManager":
            comp = c; break
    if comp is None:
        comp = ET.SubElement(r, "component", {"name": "ProjectRootManager"})

    changed = False
    if comp.get("project-jdk-type") != "Python SDK":
        comp.set("project-jdk-type", "Python SDK"); changed = True
    if comp.get("project-jdk-name") != desired_name:
        comp.set("project-jdk-name", desired_name); changed = True
    if comp.get("version") != "2":
        comp.set("version", "2"); changed = True

    if changed:
        _xml_write(t, _misc_path)
        print(f"[misc.xml] {_misc_path.parent.name}: set interpreter declaration -> '{desired_name}'")
    return changed

def _set_interpreter_for_project(_apps_link_dir: _P) -> bool:
    """Follow symlink to target; keep interpreter name from link folder."""
    link_name = _apps_link_dir.name
    proj_root = _apps_link_dir.resolve(strict=False)

    idea = proj_root / ".idea"
    ws   = idea / "workspace.xml"
    misc = idea / "misc.xml"
    venv = proj_root / ".venv"

    if not idea.is_dir() or not ws.is_file() or not venv.exists():
        return False

    desired = f"uv ({link_name})"
    try:
        tws = ET.parse(ws); rws = tws.getroot()
    except ET.ParseError as e:
        print(f"[workspace.xml] {link_name}: XML parse error: {e}")
        return False

    prm = None
    for c in rws.findall("component"):
        if c.get("name") == "ProjectRootManager":
            prm = c; break
    if prm is None:
        prm = ET.SubElement(rws, "component", {"name": "ProjectRootManager"})

    changed = False
    if prm.get("project-jdk-type") != "Python SDK":
        prm.set("project-jdk-type", "Python SDK"); changed = True
    if prm.get("project-jdk-name") != desired:
        prm.set("project-jdk-name", desired); changed = True

    if changed:
        bak = ws.with_suffix(f".xml.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        try: shutil.copy2(ws, bak)
        except Exception as e: print(f"[workspace.xml] {link_name}: WARN backup failed: {e}")
        _xml_write(tws, ws)
        print(f"[workspace.xml] {link_name}: set interpreter -> '{desired}' (backup: {bak.name})")

    _ensure_sdk_in_misc(misc, desired)
    return changed

def _apps_base_candidates(script_dir: _P) -> list[_P]:
    return [
        script_dir / "src" / "agilab" / "apps",
        script_dir.parent / "src" / "agilab" / "apps",
        script_dir.parent.parent / "src" / "agilab" / "apps",
    ]

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

# ---------- AUTO-RUN ----------
try:
    _here = _P(__file__).resolve().parent.parent
    install_sh = (_here / "install.sh").resolve()
    total = 0

    for apps_root in _apps_base_candidates(_here):
        if not apps_root.is_dir():
            continue

        for app_dir in sorted(
            [d for d in apps_root.iterdir() if d.is_dir() and d.name.endswith("_project")],
            key=lambda p: p.name
        ):
            FOLDER_NAME = app_dir.name
            CONFIG_NAME = FOLDER_NAME.replace("_project", "")
            CONFIG_TYPE = "PythonConfigurationType"

            try:
                # 1) your existing run-config generation (via link path)
                cwd_before = os.getcwd()
                os.chdir(app_dir)
                try:
                    update_workspace_xml(CONFIG_NAME, CONFIG_TYPE, FOLDER_NAME)
                finally:
                    os.chdir(cwd_before)

                # 2) interpreter patch (follow symlink, keep link name)
                if _set_interpreter_for_project(app_dir):
                    total += 1
                else:
                    print(f"[apps] {FOLDER_NAME}: no interpreter change (no .venv/.idea or already correct).")

            except Exception as e:
                print(f"[apps] {FOLDER_NAME}: ERROR {e}")

        break  # stop after first detected apps_root

    if total:
        print(f"[apps] Done. Interpreters updated for {total} project(s).")
    else:
        print("[apps] No interpreter updates were needed.")
except Exception as _e:
    print(f"[apps] ERROR during apps-only pass: {_e}")
