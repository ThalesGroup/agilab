import json
import urllib.request
import sys

def get_requires(name, version=None):
    # If version is not provided, fetch the latest
    if not version:
        with urllib.request.urlopen(f"https://test.pypi.org/pypi/{name}/json") as r:
            data = json.load(r)
        version = data["info"]["version"]

    # Fetch metadata for the chosen version
    with urllib.request.urlopen(f"https://test.pypi.org/pypi/{name}/{version}/json") as r:
        data = json.load(r)

    return version, data["info"].get("requires_dist") or []


if __name__ == "__main__":
    version = sys.argv[1] if len(sys.argv) > 1 else None

    for pkg in ["agilab", "agi-core"]:
        ver, reqs = get_requires(pkg, version)
        print(f"\n{pkg} ({ver}) dependencies:")
        if reqs:
            print("\n".join(reqs))
        else:
            print("  None")
