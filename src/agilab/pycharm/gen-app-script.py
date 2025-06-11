import os
import sys
import xml.etree.ElementTree as ET
from tkinter import simpledialog, Tk
import filecmp
import tempfile

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
    'pycharm/_template_app_test.xml',
]

output_dir = os.path.join(os.getcwd(), '.idea', 'runConfigurations')
os.makedirs(output_dir, exist_ok=True)

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

    # derive output filename
    base = os.path.basename(tpl).replace('_template_app', f'_{app}')
    out_path = os.path.join(output_dir, base)

    # --- idempotency check ----------------
    if os.path.exists(out_path):
        # optional: compare contents to avoid silent mismatches
        # write to a temp file and compare
        fd, tmp_path = tempfile.mkstemp(suffix='.xml')
        os.close(fd)
        tree.write(tmp_path)
        if filecmp.cmp(tmp_path, out_path, shallow=False):
            print(f"Skipped (unchanged): {out_path}")
            os.remove(tmp_path)
            continue
        else:
            os.replace(tmp_path, out_path)
            print(f"Updated config (changed): {out_path}")
            continue
    # ---------------------------------------

    # first time write
    tree.write(out_path)
    print(f"Generated config: {out_path}")

print(f"All {app} configurations processed.")
