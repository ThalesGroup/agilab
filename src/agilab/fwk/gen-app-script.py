import os
import sys
import xml.etree.ElementTree as ET
from tkinter import simpledialog, Tk


if len(sys.argv) < 2:
    print("Usage: script.py <replacement_name>")
    sys.exit(1)

app = sys.argv[1]

if not app:
    print("No name entered. Exiting.")
    exit(1)

print(f"Replacement name: {app}")

template_paths = [
    'pycharm/_template_app_lib.xml',
    'pycharm/_template_app_egg.xml',
    'pycharm/_template_app_run.xml',
    'pycharm/_template_app_test.xml'
]

output_dir = os.path.join(os.getcwd(), '.idea', 'runConfigurations')
os.makedirs(output_dir, exist_ok=True)

for template_path in template_paths:
    tree = ET.parse(template_path)
    xml_root = tree.getroot()

    for elem in xml_root.iter():
        for attr in elem.attrib:
            if '{APP}' in elem.attrib[attr]:
                elem.attrib[attr] = elem.attrib[attr].replace('{APP}', app)
        if elem.text and '{APP}' in elem.text:
            elem.text = elem.text.replace('{APP}', app)

    base_name = os.path.basename(template_path).replace('TEMPLATE', app)
    output_file = os.path.join(output_dir, base_name)

    tree.write(output_file.replace("_template_app", app))
    print(f"Generated config: {output_file}")

print(f"All {app} configurations generated successfully.")
