# _show_dependencies.py
import json
import sys
import argparse
import urllib.request
from urllib.error import HTTPError, URLError

REPOS = {
    "pypi": "https://pypi.org/pypi",
    "testpypi": "https://test.pypi.org/pypi",
}

def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "dep-check/1.0"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def get_requires(name: str, base: str, version: str | None = None):
    # Resolve version if not provided
    if not version:
        try:
            data = fetch_json(f"{base}/{name}/json")
        except HTTPError as e:
            if e.code == 404:
                raise SystemExit(f"[error] Package '{name}' not found at {base}")
            raise
        version = data["info"]["version"]

    # Fetch metadata for that version
    try:
        data = fetch_json(f"{base}/{name}/{version}/json")
    except HTTPError as e:
        if e.code == 404:
            # Try to help by listing available versions
            try:
                all_data = fetch_json(f"{base}/{name}/json")
                versions = sorted(all_data.get("releases", {}).keys(), reverse=True)
                hint = f" Available versions: {', '.join(versions[:15])}" if versions else ""
            except Exception:
                hint = ""
            raise SystemExit(f"[error] {name}=={version} not found at {base}.{hint}")
        raise
    return version, data["info"].get("requires_dist") or []

def main():
    parser = argparse.ArgumentParser(description="Show dependencies for packages on (Test)PyPI.")
    parser.add_argument("--repo", choices=REPOS.keys(), default="pypi",
                        help="Which index to query (default: pypi).")
    parser.add_argument("--version", default=None,
                        help="Specific version to inspect. If omitted, use latest.")
    parser.add_argument("packages", nargs="*", default=["agilab", "agi-core"],
                        help="Package names (default: agilab agi-core).")
    args = parser.parse_args()

    base = REPOS[args.repo]

    for pkg in args.packages:
        try:
            ver, reqs = get_requires(pkg, base, args.version)
        except (HTTPError, URLError) as e:
            raise SystemExit(f"[error] Failed fetching '{pkg}': {e}")
        print(f"\n{pkg} ({ver}) dependencies:")
        if reqs:
            print("\n".join(reqs))
        else:
            print("  None")

if __name__ == "__main__":
    main()
