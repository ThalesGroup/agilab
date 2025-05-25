import os
import pytest
import subprocess
from dotenv import load_dotenv

# Load .env
env_path = os.path.expanduser("~/agilab/.env")
load_dotenv(env_path)

@pytest.fixture(scope="module")
def ssh_base_command():
    """
    Returns the base SSH command list to run remote commands.
    Assumes key-based authentication or ssh-agent.
    """
    host = os.getenv("SSH_HOST", "192.168.20.222")

    creds = os.getenv("CLUSTER_CREDENTIALS")
    if creds and ":" in creds:
        user, _ = creds.split(":", 1)
    else:
        pytest.skip("Please set CLUSTER_CREDENTIALS in ~/agilab/.env as USER:PASS")
    # Use user@host for SSH
    return ["ssh", f"{user}@{host}"]

def run_ssh_command(ssh_base_command, command):
    """
    Runs an SSH command and returns (stdout, stderr) decoded strings.
    Raises subprocess.CalledProcessError on failure.
    """
    full_cmd = ssh_base_command + [command]
    result = subprocess.run(full_cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip(), result.stderr.strip()

def test_hostname(ssh_base_command):
    out, err = run_ssh_command(ssh_base_command, "hostname")
    assert out, "Expected a hostname string, got empty"

def test_system_version(ssh_base_command):
    out, err = run_ssh_command(ssh_base_command, "uname -a")
    if out:
        assert any(tok in out for tok in ("Linux", "Darwin", "BSD")), f"Unexpected uname output: {out}"
    else:
        out2, err2 = run_ssh_command(ssh_base_command, "ver")
        assert any(tok in out2 for tok in ("Windows", "Microsoft")), f"Unexpected ver output: {out2}"
