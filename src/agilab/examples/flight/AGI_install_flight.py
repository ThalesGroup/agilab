import asyncio
import textwrap
from pathlib import Path

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

SSH_HOST = "192.168.20.111"
REMOTE_REPO_CWD = "~/PycharmProjects/agilab"


def _local_apps_dir() -> str:
    repo_root = Path(__file__).resolve().parents[4]
    return str((repo_root / "src/agilab/apps").resolve())


REMOTE_SCRIPT = textwrap.dedent(
    f"""\
    import asyncio
    from pathlib import Path
    from agi_cluster.agi_distributor import AGI
    from agi_env import AgiEnv

    def _resolve_repo(path_str: str) -> Path:
        path = Path(path_str)
        if path_str.startswith("~"):
            return path.expanduser()
        if not path.is_absolute():
            return Path.home() / path
        return path.resolve()

    REPO_ROOT = _resolve_repo("{REMOTE_REPO_CWD}")
    APPS_DIR = str((REPO_ROOT / "src/agilab/apps").resolve())
    APP = "flight_project"

    async def main():
        app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
        res = await AGI.install(
            app_env,
            modes_enabled=15,
            scheduler="192.168.20.111",
            workers={{"192.168.20.130": 1, "192.168.20.111": 1}},
        )
        print(res)
        return res

    if __name__ == "__main__":
        asyncio.run(main())
    """
)


async def main():
    app_env = AgiEnv(
        apps_dir=_local_apps_dir(),
        app="flight_project",
        verbose=1,
    )
    AGI.env = app_env

    cmd_prefix = app_env.envars.get(
        f"{SSH_HOST}_CMD_PREFIX", 'export PATH="$HOME/.local/bin:$PATH";'
    )
    script_lines = [
        cmd_prefix.strip(),
        f"{app_env.uv} run python - <<'PY'",
        REMOTE_SCRIPT.strip(),
        "PY",
    ]
    ssh_cmd = "\n".join(line for line in script_lines if line)

    result = await AGI.exec_ssh(SSH_HOST, ssh_cmd)
    print(result)
    return result


if __name__ == "__main__":
    asyncio.run(main())
