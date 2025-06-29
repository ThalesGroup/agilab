import os
import asyncio
import subprocess
from pathlib import Path
from agi_env import AgiEnv
import logging

logger = logging.getLogger(__name__)

async def main():
    """
    Runs an SSH command and returns (stdout, stderr) decoded strings.
    Raises subprocess.CalledProcessError on failure.
    """
    host = "127.0.0.1"
    agipath = AgiEnv.locate_agi_installation(verbose=0)
    env = AgiEnv(active_app="flight", apps_dir=agipath / "apps", install_type=1, verbose=1)
    env.user = "jpm"
    cmd_prefix = 'export PATH="$HOME/.local/bin:$PATH";' # ""  if remote host is windows

    cmd = f'{cmd_prefix}uv run --project {env.wenv_rel} python {env.wenv_rel / "dummy_cmd.py"}'
    await env.send_file(host,  "dummy_cmd.py", env.wenv_rel)
    await env.exec_ssh(host, cmd)

if __name__ == '__main__':
    asyncio.run(main())
