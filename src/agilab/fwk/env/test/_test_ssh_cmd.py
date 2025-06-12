import os
import subprocess
from pathlib import Path
from agi_env import AgiEnv

def run_ssh_command():
    """
    Runs an SSH command and returns (stdout, stderr) decoded strings.
    Raises subprocess.CalledProcessError on failure.
    """
    host = "192.168.20.222"
    user = "nsbl"
    agipath = AgiEnv.locate_agi_installation(verbose=0)
    env = AgiEnv(active_app="flight", apps_dir=agipath / "apps", install_type=1, verbose=1)
    cmd = f"ssh {user}@{host} "

    cwd = Path().home()
    os.chdir(cwd)
    module = 'flight'
    wenv = env.wenv_rel
    dist = wenv / "dist"
    cmd += (
        f"uv -q --project {wenv} run python -c "
        f"\"from pathlib import Path; "
        f"whl = list((Path().home() / '{dist}').glob('{module}*.whl')); "
        f"print(whl)\""
    )

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    print("Stdout: " + result.stdout.strip())
    print("Stderr: " + result.stderr.strip())

if __name__ == "__main__":
    run_ssh_command()