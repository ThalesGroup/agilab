from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = next(
    parent / "tools" / "security" / "git_secret_scan_guard.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "tools" / "security" / "git_secret_scan_guard.py").is_file()
)


def load_guard():
    spec = importlib.util.spec_from_file_location("git_secret_scan_guard_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def scanner(tmp_path_factory):
    module = load_guard()
    # Tests install only the pinned upstream artifact when no verified cache exists.
    try:
        source = module.verified_binary()
    except module.GuardError:
        source = module.install()
    cache = tmp_path_factory.mktemp("verified-scanner-cache")
    target = cache / module.VERSION / module.platform_key() / source.name
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)
    return cache


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    path = tmp_path / "repository"
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Secret Guard Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    # This fixture has no project hook; hook enforcement is tested separately.
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "config",
            "core.hooksPath",
            str(tmp_path / "empty-hooks"),
        ],
        check=True,
    )
    return path


def stage(repo, name, text):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "--", name], check=True)
    return path


def baseline(repo):
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "Prepare isolated fixture"],
        check=True,
    )


def prototype():
    # Generated syntax test data; never an issued credential or a source literal.
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    def part():
        return "".join(secrets.choice(alphabet) for _ in range(20))

    return "sk-" + part() + "T3BlbkFJ" + part()


def configured(monkeypatch, scanner):
    monkeypatch.setenv("AGILAB_GITLEAKS_CACHE", str(scanner))
    return load_guard()


def test_explicit_dummy_password_and_api_key_are_accepted(repo, scanner, monkeypatch):
    module = configured(monkeypatch, scanner)
    stage(
        repo,
        ".idea/runConfigurations/example.xml",
        '<option name="PASSWORD" value="EXAMPLE_ONLY"/>',
    )
    stage(repo, "test/fixture.env", "OPENAI_API_KEY=EXAMPLE_ONLY_NOT_A_REAL_KEY\n")
    stage(
        repo,
        "test/phase_events.py",
        'events = ["login", "totp-wait", "mfa", "reauth"]\n',
    )
    result = module.scan_staged(repo)
    assert result == {"status": "pass", "files_scanned": 3, "findings": []}


@pytest.mark.parametrize(
    "name",
    [
        ".idea/runConfigurations/install.xml",
        ".env",
        "scripts/install.sh",
        "test/fixture.py",
    ],
)
def test_credential_syntax_blocks_even_in_a_test_file(repo, scanner, monkeypatch, name):
    module = configured(monkeypatch, scanner)
    value = prototype()
    stage(repo, name, "OPENAI_API_KEY=" + value + "\n")
    result = module.scan_staged(repo)
    assert result["status"] == "fail"
    assert result["findings"]
    assert all(item["file"] == name for item in result["findings"])
    assert value not in json.dumps(result)


def test_staged_secret_is_found_when_working_copy_is_clean(repo, scanner, monkeypatch):
    module = configured(monkeypatch, scanner)
    stage(repo, "config.env", "OPENAI_API_KEY=" + prototype()).write_text(
        "OPENAI_API_KEY=EXAMPLE_ONLY"
    )
    assert module.scan_staged(repo)["status"] == "fail"


def test_subdirectory_invocation_still_scans_the_whole_repository(
    repo, scanner, monkeypatch
):
    module = configured(monkeypatch, scanner)
    nested = repo / "nested"
    nested.mkdir()
    stage(repo, "config.env", "OPENAI_API_KEY=" + prototype())
    assert module.scan_staged(nested)["status"] == "fail"


def test_windows_style_project_interpreter_is_selected(repo):
    root = SCRIPT.parents[2]
    executable = repo / ".venv/Scripts/python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nprintf 'selected-windows-layout\\n'\n")
    executable.chmod(0o755)
    command = 'ROOT_DIR="$1"; . "$2"; run_guard_python unused.py'
    result = subprocess.run(
        [
            "bash",
            "-c",
            command,
            "guard-test",
            str(repo),
            str(root / ".githooks/guard_python.sh"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "selected-windows-layout"


def test_unstaged_secret_is_not_committed_or_scanned(repo, scanner, monkeypatch):
    module = configured(monkeypatch, scanner)
    stage(repo, "config.env", "OPENAI_API_KEY=EXAMPLE_ONLY").write_text(
        "OPENAI_API_KEY=" + prototype()
    )
    assert module.scan_staged(repo)["status"] == "pass"


def test_full_staged_blob_catches_a_secret_outside_the_changed_line(
    repo, scanner, monkeypatch
):
    module = configured(monkeypatch, scanner)
    text = "OPENAI_API_KEY=" + prototype() + "\nFLAG=before\n"
    stage(repo, "config.env", text)
    baseline(repo)
    stage(repo, "config.env", text.replace("FLAG=before", "FLAG=after"))
    assert module.scan_staged(repo)["status"] == "fail"


def test_inline_allow_comment_cannot_hide_a_credential(repo, scanner, monkeypatch):
    module = configured(monkeypatch, scanner)
    stage(repo, "config.env", "OPENAI_API_KEY=" + prototype() + " # gitleaks:allow\n")
    assert module.scan_staged(repo)["status"] == "fail"


def test_environment_and_staged_policy_cannot_disable_detection(
    repo, scanner, monkeypatch
):
    module = configured(monkeypatch, scanner)
    monkeypatch.setenv("GITLEAKS_CONFIG_TOML", "[allowlist]\npaths = ['.*']\n")
    stage(repo, ".gitleaks.toml", "[allowlist]\npaths = ['.*']\n")
    stage(repo, ".gitleaksignore", "*\n")
    stage(repo, "config.env", "OPENAI_API_KEY=" + prototype() + "\n")
    assert module.scan_staged(repo)["status"] == "fail"


def test_missing_scanner_blocks_a_nonempty_commit(repo, tmp_path, monkeypatch):
    module = load_guard()
    monkeypatch.setenv("AGILAB_GITLEAKS_CACHE", str(tmp_path / "missing-scanner"))
    stage(repo, "safe.txt", "safe content\n")
    with pytest.raises(module.GuardError, match="not installed"):
        module.scan_staged(repo)


def test_tampered_scanner_is_rejected_before_execution(repo, tmp_path, monkeypatch):
    module = load_guard()
    monkeypatch.setenv("AGILAB_GITLEAKS_CACHE", str(tmp_path / "tampered-scanner"))
    binary = module.binary_path()
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"untrusted executable")
    stage(repo, "safe.txt", "safe content\n")
    with pytest.raises(module.GuardError, match="checksum mismatch"):
        module.scan_staged(repo)


def test_index_change_during_scan_blocks_commit(repo, scanner, monkeypatch):
    module = configured(monkeypatch, scanner)
    stage(repo, "safe.txt", "before\n")
    original = module.git
    calls = 0

    def changed_index(root, *args):
        nonlocal calls
        if args[:2] == ("ls-files", "--stage"):
            calls += 1
            if calls == 2:
                stage(repo, "safe.txt", "after\n")
        return original(root, *args)

    monkeypatch.setattr(module, "git", changed_index)
    with pytest.raises(module.GuardError, match="index changed"):
        module.scan_staged(repo)


def test_no_staged_files_does_not_require_installation(repo, tmp_path, monkeypatch):
    module = load_guard()
    monkeypatch.setenv("AGILAB_GITLEAKS_CACHE", str(tmp_path / "missing"))
    assert module.scan_staged(repo)["files_scanned"] == 0


@pytest.mark.skipif(
    os.name == "nt",
    reason="Git on Windows does not expose native Unix symlink creation.",
)
def test_symlink_target_is_not_read_from_outside_the_index(
    repo, scanner, monkeypatch, tmp_path
):
    module = configured(monkeypatch, scanner)
    outside = tmp_path / "outside.env"
    outside.write_text("OPENAI_API_KEY=" + prototype())
    (repo / "link.env").symlink_to(outside)
    subprocess.run(["git", "-C", str(repo), "add", "link.env"], check=True)
    assert module.scan_staged(repo)["status"] == "pass"


def test_cli_never_echoes_secret_content(repo, scanner, monkeypatch):
    configured(monkeypatch, scanner)
    value = prototype()
    stage(repo, "config.env", "OPENAI_API_KEY=" + value)
    result = subprocess.run(
        [os.sys.executable, str(SCRIPT), "staged", "--root", str(repo)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert value not in result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "fail"


def test_git_hook_blocks_secret_even_when_other_local_guards_are_skipped(
    repo, scanner, monkeypatch
):
    configured(monkeypatch, scanner)
    project = SCRIPT.parents[2]
    tools = repo / "tools" / "security"
    hooks = repo / ".githooks"
    tools.mkdir(parents=True)
    hooks.mkdir()
    shutil.copy2(SCRIPT, tools / SCRIPT.name)
    for name in ("pre-commit", "guard_python.sh"):
        original = project / ".githooks" / name
        if original.exists():
            shutil.copy2(original, hooks / name)
    (hooks / "pre-commit").chmod(0o755)
    subprocess.run(
        ["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True
    )
    monkeypatch.setenv("AGILAB_SKIP_LOCAL_GUARDS", "1")
    value = prototype()
    stage(repo, "config.env", "OPENAI_API_KEY=" + value)
    blocked = subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Must reject secret syntax"],
        capture_output=True,
        text=True,
    )
    assert blocked.returncode != 0
    assert value not in blocked.stdout + blocked.stderr
    assert '"status": "fail"' in blocked.stdout + blocked.stderr
    stage(repo, "config.env", "OPENAI_API_KEY=EXAMPLE_ONLY_NOT_A_REAL_KEY\n")
    accepted = subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Accept explicit placeholder"],
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_bom_encoded_windows_configuration_cannot_hide_a_secret(
    repo, scanner, monkeypatch, encoding
):
    module = configured(monkeypatch, scanner)
    path = repo / "config.xml"
    path.write_bytes(("OPENAI_API_KEY=" + prototype() + "\n").encode(encoding))
    subprocess.run(["git", "-C", str(repo), "add", "config.xml"], check=True)
    assert module.scan_staged(repo)["status"] == "fail"
