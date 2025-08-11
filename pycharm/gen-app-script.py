from pathlib import Path as _P
import xml.etree.ElementTree as _ET
import time, shutil, os, subprocess

def _set_interpreter_for_project(_apps_link_dir: _P) -> bool:
    """
    Follow symlink from apps/<name> to the real project root for file ops,
    but keep interpreter name based on the link name.
    """
    link_name = _apps_link_dir.name                            # name shown in PyCharm, and used in "uv (name)"
    proj_root = _apps_link_dir.resolve(strict=False)           # follow symlink if any; else same path

    idea = proj_root / ".idea"
    ws = idea / "workspace.xml"
    misc = idea / "misc.xml"
    venv = proj_root / ".venv"                                 # .venv may be a dir or a symlink; exists() is fine

    if not idea.is_dir() or not ws.is_file() or not venv.exists():
        return False

    desired = f"uv ({link_name})"                              # keep name from apps/* link, not target basename

    try:
        tws = _ET.parse(ws)
        rws = tws.getroot()
    except _ET.ParseError as e:
        print(f"[workspace.xml] {link_name}: XML parse error: {e}")
        return False

    prm = None
    for c in rws.findall("component"):
        if c.get("name") == "ProjectRootManager":
            prm = c; break
    if prm is None:
        prm = _ET.SubElement(rws, "component", {"name": "ProjectRootManager"})

    changed = False
    if prm.get("project-jdk-type") != "Python SDK":
        prm.set("project-jdk-type", "Python SDK"); changed = True
    if prm.get("project-jdk-name") != desired:
        prm.set("project-jdk-name", desired); changed = True

    if changed:
        bak = ws.with_suffix(f".xml.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            shutil.copy2(ws, bak)
        except Exception as e:
            print(f"[workspace.xml] {link_name}: WARN backup failed: {e}")
        tws.write(ws, encoding="utf-8", xml_declaration=True)
        print(f"[workspace.xml] {link_name}: set interpreter -> '{desired}' (backup: {bak.name})")

    # misc.xml SDK declaration (also on the resolved target)
    _ensure_sdk_in_misc(misc, desired)
    return changed

# In your apps loop, change just this part:
for app_dir in sorted(p for p in _apps.iterdir() if p.is_dir() and p.name.endswith("_project")):
    FOLDER_NAME = app_dir.name
    CONFIG_NAME = FOLDER_NAME.replace("_project", "")
    CONFIG_TYPE = "PythonConfigurationType"

    try:
        # 1) Run installer against the LINK PATH (your install.sh knows how to handle it)
        if install_sh.exists():
            subprocess.run([str(install_sh), str(app_dir), "1"], cwd=_here, check=True)
        else:
            print(f"[install.sh] Not found at {_here}. Skipping installer for {FOLDER_NAME}.")

        # 2) Generate/update run configs in the LINK PATH (cwd = link; PyCharm will read from target)
        cwd_before = os.getcwd()
        os.chdir(app_dir)  # link path
        try:
            update_workspace_xml(CONFIG_NAME, CONFIG_TYPE, FOLDER_NAME)
        finally:
            os.chdir(cwd_before)

        # 3) Patch interpreter by FOLLOWING the symlink to real project root,
        #    but keep the interpreter name based on the LINK name
        if _set_interpreter_for_project(app_dir):
            total += 1
        else:
            print(f"[apps] {FOLDER_NAME}: no interpreter change (no .venv/.idea or already correct).")

    except subprocess.CalledProcessError as e:
        print(f"[install.sh] {FOLDER_NAME}: ERROR (exit {e.returncode})")
    except Exception as e:
        print(f"[apps] {FOLDER_NAME}: ERROR {e}")
