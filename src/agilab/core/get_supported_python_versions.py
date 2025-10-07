import toml
import sys
from packaging.specifiers import SpecifierSet
from packaging.version import Version
import json

CANDIDATE_VERSIONS = [f"3.{i}" for i in range(6, 14)]  # 3.6 to 3.13

def extract_requires_python(path):
    data = toml.load(path)
    req_python = None
    if 'project' in data and 'requires-python' in data['project']:
        req_python = data['project']['requires-python']
    elif 'tool' in data and 'poetry' in data['tool'] and 'dependencies' in data['tool']['poetry']:
        deps = data['tool']['poetry']['dependencies']
        if 'python' in deps:
            req_python = deps['python']
    print(f"Parsed requires-python from {path}: {req_python}", file=sys.stderr)
    return req_python

def main(pyproject_paths):
    versions = set()
    for path in pyproject_paths:
        try:
            req_python = extract_requires_python(path)
            if not req_python:
                print(f"No python requirement found in {path}", file=sys.stderr)
                continue
            spec = SpecifierSet(req_python)
            for v in CANDIDATE_VERSIONS:
                if Version(v) in spec:
                    versions.add(v)
        except Exception as e:
            print(f"Error parsing {path}: {e}", file=sys.stderr)

    output = json.dumps(sorted(versions))
    print(output)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_supported_python_versions.py path1/pyproject.toml [path2 ...]", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1:])
