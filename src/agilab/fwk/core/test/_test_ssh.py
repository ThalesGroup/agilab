import os
import pytest
import paramiko
from dotenv import load_dotenv

# Load the .env file from your home directory
env_path = os.path.expanduser("~/agilab/.env")
load_dotenv(env_path)


@pytest.fixture(scope="module")
def ssh_client():
    """
    Spins up an SSHClient, connects once for all tests in this module,
    then closes it at the end.
    """
    host = os.getenv("SSH_HOST", "192.168.20.222")

    # Read the combined credentials and split into user / password
    creds = os.getenv("CLUSTER_CREDENTIALS")
    if not creds or ":" not in creds:
        pytest.skip("Please set CLUSTER_CREDENTIALS in ~/agilab/.env as USER:PASS")
    user, pwd = creds.split(":", 1)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=user,
        password=pwd,
        look_for_keys=True,
        allow_agent=True
    )
    yield client
    client.close()


def test_hostname(ssh_client):
    """
    Verify that `hostname` returns something non-empty.
    """
    stdin, stdout, stderr = ssh_client.exec_command("hostname")
    out = stdout.read().decode().strip()
    stdout.close()
    stderr.close()
    assert out, "Expected a hostname string, got empty"


def test_system_version(ssh_client):
    """
    Verify OS type: use uname for Unix, ver for Windows.
    """
    stdin, stdout, stderr = ssh_client.exec_command("uname -a")
    out = stdout.read().decode().strip()
    stdout.close()
    stderr.close()

    if out:
        assert any(tok in out for tok in ("Linux", "Darwin", "BSD")), \
            f"Unexpected uname output: {out}"
    else:
        stdin, stdout, stderr = ssh_client.exec_command("ver")
        out2 = stdout.read().decode().strip()
        stdout.close()
        stderr.close()
        assert any(tok in out2 for tok in ("Windows", "Microsoft")), \
            f"Unexpected ver output: {out2}"
