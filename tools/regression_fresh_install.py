#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "tools" / "install_enduser.sh"


def _run(cmd: list[str], *, env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    printable = " ".join(cmd)
    print(f"$ {printable}")
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )


def _installed_python(agi_space: Path) -> Path:
    posix_python = agi_space / ".venv" / "bin" / "python"
    if posix_python.exists():
        return posix_python
    windows_python = agi_space / ".venv" / "Scripts" / "python.exe"
    if windows_python.exists():
        return windows_python
    raise FileNotFoundError(f"Could not locate installed Python under {agi_space / '.venv'}")


def _site_packages_root(agi_space: Path) -> Path:
    lib_root = agi_space / ".venv" / "lib"
    if lib_root.exists():
        for candidate in sorted(lib_root.glob("python*/site-packages")):
            if (candidate / "agilab").exists():
                return candidate
    windows_root = agi_space / ".venv" / "Lib" / "site-packages"
    if (windows_root / "agilab").exists():
        return windows_root
    raise FileNotFoundError(f"Could not locate site-packages under {agi_space / '.venv'}")


def _streamlit_smoke(python_bin: Path, site_packages: Path, *, env: dict[str, str]) -> None:
    smoke_code = textwrap.dedent(
        f"""
        import os
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        from agi_env import AgiEnv

        site_packages = Path({str(site_packages)!r})
        about_page = site_packages / "agilab" / "main_page.py"
        orchestrate_page = site_packages / "agilab" / "pages" / "2_ORCHESTRATE.py"
        apps_path = Path.home() / "agi-space" / "apps"

        def assert_clean(page_name, app_test):
            exceptions = list(app_test.exception)
            if exceptions:
                raise AssertionError(f"{{page_name}} exceptions: {{exceptions}}")

        about = AppTest.from_file(str(about_page), default_timeout=90)
        about.run(timeout=90)
        assert_clean("About", about)

        if not apps_path.exists():
            raise AssertionError(f"Installed apps path was not created: {{apps_path}}")

        env = about.session_state["env"] if "env" in about.session_state else None
        if env is None:
            env = AgiEnv(apps_path=apps_path, app="flight_telemetry_project", verbose=0)

        orchestrate = AppTest.from_file(str(orchestrate_page), default_timeout=45)
        orchestrate.session_state["env"] = env
        orchestrate.session_state["app_settings"] = {{"args": {{}}, "cluster": {{}}}}
        orchestrate.run(timeout=45)
        assert_clean("ORCHESTRATE", orchestrate)

        print("fresh-install-streamlit-smoke: OK")
        """
    )
    result = subprocess.run(
        [str(python_bin), "-u", "-c", smoke_code],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(
            "Fresh-install Streamlit smoke failed "
            f"(exit={result.returncode}). See output above."
        )


def main() -> int:
    scratch_root = Path(tempfile.mkdtemp(prefix="agilab-fresh-install-"))
    home_dir = scratch_root / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    share_dir = home_dir / "agi-share"
    share_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("CONDA_PREFIX", None)
    env.update(
        {
            "HOME": str(home_dir),
            "AGI_CLUSTER_SHARE": str(share_dir),
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "OPENAI_API_KEY": "sk-test-fresh-install-000000000000",
            "CLUSTER_CREDENTIALS": "user:password",
            "FORCE_REBUILD": "1",
            "SKIP_OFFLINE": "1",
        }
    )

    try:
        result = _run([str(INSTALL_SCRIPT), "--source", "local", "--skip-offline"], env=env, cwd=REPO_ROOT)
        print(result.stdout)

        agi_space = home_dir / "agi-space"
        python_bin = _installed_python(agi_space)
        site_packages = _site_packages_root(agi_space)

        import_check = _run(
            [
                str(python_bin),
                "-c",
                "import agilab, agi_env, agi_cluster, agi_node; print('fresh-install-imports: OK')",
            ],
            env=env,
            cwd=REPO_ROOT,
        )
        print(import_check.stdout)

        _streamlit_smoke(python_bin, site_packages, env=env)
        print(f"Fresh install regression passed. Scratch home: {home_dir}")
        return 0
    finally:
        if os.environ.get("AGILAB_KEEP_FRESH_INSTALL_TMP") == "1":
            print(f"Preserved scratch directory: {scratch_root}")
        else:
            shutil.rmtree(scratch_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
