# ======================
# Apps-only auto run: install.sh "$apps_dir" "1" + generate configs + set interpreter
# ======================
import time, shutil, subprocess, os
from pathlib import Path as _P
import xml.etree.ElementTree as _ET

def _xml_write(_tree: _ET.ElementTree, _target: _P):
    _tree.write(_target, encoding="utf-8", xml_declaration=True)

def _ensure_sdk_in_misc(_misc_path: _P, desired_name: str) -> bool:
    if _misc_path.exists():
        try:
            t = _ET.parse(_misc_path)
            r = t.getroot()
        except _ET.ParseError as e:
            print(f"[misc.xml] {_misc_path.parent.name}: XML parse error: {e}")
            return False
    else:
        r = _ET.Element("project", version="4")
        t = _ET.ElementTree(r)

    comp = None
    for c in r.findall("component"):
        if c.get("name") == "ProjectRootManager":
            comp = c; break
    if comp is None:
        comp = _ET.SubElement(r, "component", {"name": "ProjectRootManager"})

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

def _set_interpreter_for_project(proj_root: _P) -> bool:
    idea = proj_root / ".idea"
    ws = idea / "workspace.xml"
    misc = idea / "misc.xml"
    if not idea.is_dir() or not ws.is_file() or not (proj_root / ".venv").exists():
        return False

    desired = f"uv ({proj_root.name})"
    try:
        tws = _ET.parse(ws)
        rws = tws.getroot()
    except _ET.ParseError as e:
        print(f"[workspace.xml] {proj_root.name}: XML parse error: {e}")
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
            print(f"[workspace.xml] {proj_root.name}: WARN backup failed: {e}")
        _xml_write(tws, ws)
        print(f"[workspace.xml] {proj_root.name}: set interpreter -> '{desired}' (backup: {bak.name})")

    changed_misc = _ensure_sdk_in_misc(misc, desired)
    return changed or changed_misc

def _apps_base_candidates(script_dir: _P) -> list[_P]:
    return [
        script_dir / "src" / "agilab" / "apps",
        script_dir.parent / "src" / "agilab" / "apps",
        script_dir.parent.parent / "src" / "agilab" / "apps",
    ]

# ----------------------
# AUTO-RUN (no args): for each apps/*_project
#   1) run ./install.sh "$apps_dir" "1"
#   2) call your existing update_workspace_xml(CONFIG_NAME, CONFIG_TYPE, FOLDER_NAME)
#   3) patch interpreter (workspace.xml + misc.xml)
# ----------------------
try:
    _here = _P(__file__).resolve().parent
    install_sh = (_here / "install.sh").resolve()
    total = 0

    for _apps in _apps_base_candidates(_here):
        if not _apps.is_dir():
            continue

        for app_dir in sorted(p for p in _apps.iterdir() if p.is_dir() and p.name.endswith("_project")):
            FOLDER_NAME = app_dir.name
            CONFIG_NAME = FOLDER_NAME.replace("_project", "")
            CONFIG_TYPE = "PythonConfigurationType"

            try:
                # 1) Ensure env/files via your installer with the 2 args
                if install_sh.exists():
                    subprocess.run([str(install_sh), str(app_dir), "1"], cwd=_here, check=True)
                else:
                    print(f"[install.sh] Not found at {_here}. Skipping installer for {FOLDER_NAME}.")

                # 2) Generate/update run configs using your existing function
                cwd_before = os.getcwd()
                os.chdir(app_dir)
                try:
                    update_workspace_xml(CONFIG_NAME, CONFIG_TYPE, FOLDER_NAME)
                finally:
                    os.chdir(cwd_before)

                # 3) Patch interpreter
                if _set_interpreter_for_project(app_dir):
                    total += 1
                else:
                    print(f"[apps] {FOLDER_NAME}: no interpreter change (no .venv/.idea or already correct).")

            except subprocess.CalledProcessError as e:
                print(f"[install.sh] {FOLDER_NAME}: ERROR (exit {e.returncode})")
            except Exception as e:
                print(f"[apps] {FOLDER_NAME}: ERROR {e}")

        break  # stop after first found apps dir (avoid duplicates)

    if total:
        print(f"[apps] Done. Interpreters updated for {total} project(s).")
    else:
        print("[apps] No interpreter updates were needed.")
except Exception as _e:
    print(f"[apps] ERROR during apps-only pass: {_e}")
