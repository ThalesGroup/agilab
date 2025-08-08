# ======================
# Interpreter patching (apps-only, no CLI args; keeps your original functions)
# ======================
import time
import shutil
from pathlib import Path as _P
import xml.etree.ElementTree as _ET

def _write_xml(_tree: _ET.ElementTree, _target: _P) -> None:
    _tree.write(_target, encoding="utf-8", xml_declaration=True)

def _ensure_sdk_in_xml(_xml_path: _P, desired_name: str) -> bool:
    """
    Ensure .idea/misc.xml has ProjectRootManager with the desired Python SDK.
    Returns True if changes were written.
    """
    if _xml_path.exists():
        try:
            tree = _ET.parse(_xml_path)
            root = tree.getroot()
        except _ET.ParseError as e:
            print(f"[misc.xml] {_xml_path.parent.name}: XML parse error: {e}")
            return False
    else:
        root = _ET.Element("project", version="4")
        tree = _ET.ElementTree(root)

    prm = None
    for comp in root.findall("component"):
        if comp.get("name") == "ProjectRootManager":
            prm = comp
            break
    if prm is None:
        prm = _ET.SubElement(root, "component", {"name": "ProjectRootManager"})

    changed = False
    if prm.get("project-jdk-type") != "Python SDK":
        prm.set("project-jdk-type", "Python SDK")
        changed = True
    if prm.get("project-jdk-name") != desired_name:
        prm.set("project-jdk-name", desired_name)
        changed = True
    if prm.get("version") != "2":
        prm.set("version", "2")
        changed = True

    if changed:
        _write_xml(tree, _xml_path)
        print(f"[misc.xml] {_xml_path.parent.name}: set interpreter declaration -> '{desired_name}'")
    return changed

def _set_interpreter(project_root: _P) -> bool:
    """
    Patch .idea/workspace.xml AND .idea/misc.xml in project_root to set:
        project-jdk-type="Python SDK"
        project-jdk-name="uv (<folder-name>)"
    Only if .venv exists in project_root.
    Returns True if changes were written.
    """
    idea_dir = project_root / ".idea"
    workspace_xml = idea_dir / "workspace.xml"
    misc_xml = idea_dir / "misc.xml"
    venv_dir = project_root / ".venv"

    if not idea_dir.is_dir() or not workspace_xml.is_file() or not venv_dir.exists():
        return False

    folder = project_root.name
    desired_name = f"uv ({folder})"

    # workspace.xml
    try:
        tree_ws = _ET.parse(workspace_xml)
        root_ws = tree_ws.getroot()
    except _ET.ParseError as e:
        print(f"[workspace.xml] {folder}: XML parse error: {e}")
        return False

    prm_ws = None
    for comp in root_ws.findall("component"):
        if comp.get("name") == "ProjectRootManager":
            prm_ws = comp
            break
    if prm_ws is None:
        prm_ws = _ET.SubElement(root_ws, "component", {"name": "ProjectRootManager"})

    changed = False
    if prm_ws.get("project-jdk-type") != "Python SDK":
        prm_ws.set("project-jdk-type", "Python SDK")
        changed = True
    if prm_ws.get("project-jdk-name") != desired_name:
        prm_ws.set("project-jdk-name", desired_name)
        changed = True

    if changed:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_path = workspace_xml.with_suffix(f".xml.bak-{ts}")
        try:
            shutil.copy2(workspace_xml, backup_path)
        except Exception as e:
            print(f"[workspace.xml] {folder}: WARN backup failed: {e}")
        _write_xml(tree_ws, workspace_xml)
        print(f"[workspace.xml] {folder}: set interpreter -> '{desired_name}' (backup: {backup_path.name})")

    # misc.xml (declare the SDK so PyCharm finds it immediately)
    changed_misc = _ensure_sdk_in_xml(misc_xml, desired_name)

    return changed or changed_misc

def _apps_base_candidates(script_dir: _P) -> list[_P]:
    return [
        script_dir / "src" / "agilab" / "apps",
        script_dir.parent / "src" / "agilab" / "apps",
        script_dir.parent.parent / "src" / "agilab" / "apps",
    ]

# ----------------------
# AUTO-RUN (no args): scan apps/* ending with "_project" and patch interpreters
# ----------------------
try:
    _here = _P(__file__).resolve().parent
    updated = 0
    # Find the first existing apps directory from common locations
    for _apps in _apps_base_candidates(_here):
        if not _apps.is_dir():
            continue
        for sub in sorted(p for p in _apps.iterdir() if p.is_dir() and p.name.endswith("_project")):
            try:
                if _set_interpreter(sub):
                    updated += 1
                else:
                    print(f"[apps] {sub.name}: skipped (no .venv/.idea or no change)")
            except Exception as e:
                print(f"[apps] {sub.name}: ERROR {e}")
        # Stop after the first found apps dir to avoid duplicates
        break
    if updated:
        print(f"[apps] Done. Updated {updated} project(s).")
    else:
        print("[apps] No interpreters updated (no matching apps with .venv/.idea).")
except Exception as _e:
    print(f"[apps] ERROR during interpreter patching: {_e}")
