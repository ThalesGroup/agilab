import os
import sys
import xml.etree.ElementTree as ET
from tkinter import simpledialog, Tk
import filecmp
import tempfile

app = sys.argv[1]

template_paths = [
    'pycharm/_template_app_lib_worker.xml',
    'pycharm/_template_app_egg_manager.xml',
    'pycharm/_template_app_run.xml',
    'pycharm/_template_app_test_manager.xml'
]

output_dir = os.path.join(os.getcwd(), '.idea', 'runConfigurations')
