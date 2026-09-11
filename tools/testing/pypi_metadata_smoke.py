"""Exercise Twine's metadata validation using the installed publishing lock.

Import-only checks missed Twine 6.2.0's parser override, which rejects valid
Metadata 2.5 even with a compatible packaging version. Keep this smoke in the
same environment as the publishing tools, without resolving extra dependencies.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def main() -> int:
    with TemporaryDirectory(prefix="agilab-publish-metadata-") as directory:
        wheel = Path(directory) / "agilab_metadata_smoke-1.0-py3-none-any.whl"
        dist_info = "agilab_metadata_smoke-1.0.dist-info"
        for metadata_version in ("2.4", "2.5"):
            metadata = (
                f"Metadata-Version: {metadata_version}\n"
                "Name: agilab-metadata-smoke\n"
                "Version: 1.0\n"
                "Summary: Publishing tool metadata compatibility check\n"
                "License-Expression: BSD-3-Clause\n"
                "Description-Content-Type: text/plain\n"
            )
            if metadata_version == "2.5":
                metadata += "Import-Name: agilab_metadata_smoke\n"
            with ZipFile(wheel, "w") as archive:
                archive.writestr(
                    f"{dist_info}/METADATA", metadata + "\nSmoke fixture.\n"
                )
                archive.writestr(
                    f"{dist_info}/WHEEL",
                    "Wheel-Version: 1.0\nGenerator: agilab-metadata-smoke\n"
                    "Root-Is-Purelib: true\nTag: py3-none-any\n",
                )
                archive.writestr(
                    f"{dist_info}/RECORD",
                    "".join(
                        f"{dist_info}/{name},,\n"
                        for name in ("METADATA", "WHEEL", "RECORD")
                    ),
                )
            print(f"Validating Core Metadata {metadata_version}", flush=True)
            result = subprocess.run(
                [sys.executable, "-m", "twine", "check", "--strict", str(wheel)],
                check=False,
            )
            if result.returncode:
                print(
                    f"Publishing tools rejected valid Core Metadata {metadata_version}; "
                    "check the Twine and packaging pins in ci-publish.in.",
                    file=sys.stderr,
                )
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
