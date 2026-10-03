"""Generate or verify the standalone host's canonical public-bind policy copy."""

from __future__ import annotations

import argparse
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/agilab/lib/agi-web"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the packaged copy differs from its canonical source.")
    args = parser.parse_args()
    metadata = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    source = metadata["tool"]["agilab"]["generated-sources"]["public-bind-guard"]
    canonical, destination = (PACKAGE / source["canonical"]).resolve(), PACKAGE / source["destination"]
    payload = canonical.read_bytes()
    if args.check:
        if not destination.is_file() or destination.read_bytes() != payload:
            parser.exit(1, "The portable public-bind policy is stale; run this generator without --check.\n")
    else:
        destination.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
