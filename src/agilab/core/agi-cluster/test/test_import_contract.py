from __future__ import annotations

import subprocess
import sys
import textwrap


def test_distributor_import_does_not_require_sklearn() -> None:
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class BlockSklearn(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "sklearn" or fullname.startswith("sklearn."):
                    raise ModuleNotFoundError(fullname)
                return None

        sys.meta_path.insert(0, BlockSklearn())

        from agi_cluster.agi_distributor import AGI

        assert AGI is not None
        print("ok")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "ok"
