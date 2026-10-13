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


def git_fixture(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def commit_objects(repo):
    objects = git_fixture(
        repo, "cat-file", "--batch-all-objects", "--batch-check"
    ).stdout.splitlines()
    return {line.split()[0] for line in objects if line.split()[1] == "commit"}


def incoming_operation(repo, operation, text):
    """Prepare an isolated incoming commit before installing the tested hooks."""
    stage(repo, "baseline.txt", "ordinary baseline\n")
    baseline(repo)
    initial = git_fixture(repo, "rev-parse", "HEAD").stdout.strip()
    git_fixture(repo, "switch", "-c", "incoming")
    stage(repo, "scan-me.txt", text)
    baseline(repo)
    incoming = git_fixture(repo, "rev-parse", "HEAD").stdout.strip()
    git_fixture(repo, "switch", "-c", "receiver", initial)
    stage(repo, "receiver.txt", "ordinary independent change\n")
    baseline(repo)
    if operation == "commit":
        stage(repo, "scan-me.txt", text)
        return ["commit", "-m", "Check staged scan completion"]
    if operation == "merge":
        return ["merge", "--no-ff", "--no-edit", incoming]
    if operation == "cherry-pick":
        return ["cherry-pick", incoming]
    if operation == "am":
        patch = repo.parent / "staged-scan-incoming.patch"
        patch.write_text(
            git_fixture(repo, "format-patch", "--stdout", "-1", incoming).stdout,
            encoding="utf-8",
        )
        return ["am", str(patch)]
    git_fixture(repo, "switch", "incoming")
    return ["rebase", "--" + operation.removeprefix("rebase-"), "receiver"]


def install_project_hooks(repo, rejecting_sentinel=False):
    project = SCRIPT.parents[2]
    tools = repo / "tools" / "security"
    hooks = repo / ".githooks"
    tools.mkdir(parents=True)
    hooks.mkdir()
    if rejecting_sentinel:
        (tools / SCRIPT.name).write_text(
            "import json, sys\n"
            "assert sys.argv[1:3] == ['staged', '--root']\n"
            "print(json.dumps({'status': 'error', "
            "'message': 'isolated-staged-scan-sentinel'}))\n"
            "raise SystemExit(42)\n",
            encoding="utf-8",
        )
    else:
        shutil.copy2(SCRIPT, tools / SCRIPT.name)
    for name in (
        "pre-commit",
        "prepare-commit-msg",
        "pre-applypatch",
        "guard_python.sh",
    ):
        shutil.copy2(project / ".githooks" / name, hooks / name)
        if name != "guard_python.sh":
            (hooks / name).chmod(0o755)
    git_fixture(repo, "config", "core.hooksPath", ".githooks")


def prototype():
    # Generated syntax test data; never an issued credential or a source literal.
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    def part():
        return "".join(secrets.choice(alphabet) for _ in range(20))

    return "sk-" + part() + "T3BlbkFJ" + part()


def configured(monkeypatch, scanner):
    monkeypatch.setenv("AGILAB_GITLEAKS_CACHE", str(scanner))
    return load_guard()


@pytest.fixture
def synthetic_scanner(tmp_path, monkeypatch):
    """Keep Git real while reporting a generated credential from selected blobs."""
    module = load_guard()
    executable = tmp_path / "synthetic-staged-scanner"
    value = prototype()
    calls = []
    original = subprocess.run

    def scan(command, **kwargs):
        if command[0] != str(executable):
            return original(command, **kwargs)
        payload = Path(command[command.index("dir") + 1])
        files = sorted(path for path in payload.rglob("*") if path.is_file())
        calls.append([path.relative_to(payload).as_posix() for path in files])
        findings = [
            {"RuleID": "synthetic-credential", "StartLine": 1, "File": str(path)}
            for path in files
            if value.encode() in path.read_bytes()
        ]
        report = Path(command[command.index("--report-path") + 1])
        report.write_text(json.dumps(findings), encoding="utf-8")
        return subprocess.CompletedProcess(command, int(bool(findings)), b"", b"")

    monkeypatch.setattr(module, "verified_binary", lambda: executable)
    monkeypatch.setattr(module.subprocess, "run", scan)
    return module, calls, value


def test_staged_symlink_to_regular_file_type_change_is_scanned(
    repo, synthetic_scanner, capsys
):
    module, calls, value = synthetic_scanner
    stage(repo, "config.env", "ordinary-link-target")
    original_blob = git_fixture(repo, "rev-parse", ":config.env").stdout.strip()
    # Index modes exercise the same Git type change without OS symlink privileges.
    git_fixture(repo, "update-index", "--cacheinfo", "120000", original_blob, "config.env")
    baseline(repo)
    stage(repo, "config.env", "OPENAI_API_KEY=" + value + "\n")
    staged_blob = git_fixture(repo, "rev-parse", ":config.env").stdout.strip()
    git_fixture(repo, "update-index", "--cacheinfo", "100644", staged_blob, "config.env")
    assert git_fixture(repo, "diff", "--cached", "--name-status").stdout == "T\tconfig.env\n"

    assert module.main(["staged", "--root", str(repo)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "fail"
    assert result["files_scanned"] == 1
    assert result["findings"] == [
        {"file": "config.env", "line": 1, "rule": "synthetic-credential"}
    ]
    assert calls == [["config.env"]]


@pytest.mark.parametrize("change", ["delete", "gitlink", "rename"])
def test_changed_path_selection_preserves_existing_file_boundaries(
    repo, synthetic_scanner, capsys, change
):
    module, calls, value = synthetic_scanner
    stage(repo, "config.env", "OPENAI_API_KEY=" + value + "\n")
    baseline(repo)
    if change == "delete":
        git_fixture(repo, "rm", "--", "config.env")
    elif change == "gitlink":
        commit = git_fixture(repo, "rev-parse", "HEAD").stdout.strip()
        git_fixture(repo, "update-index", "--add", "--cacheinfo", "160000", commit, "worker")
    else:
        git_fixture(repo, "mv", "config.env", "renamed.env")

    assert module.main(["staged", "--root", str(repo)]) == int(change == "rename")
    result = json.loads(capsys.readouterr().out)
    assert result["files_scanned"] == int(change == "rename")
    if change == "rename":
        assert result["status"] == "fail"
        assert result["findings"][0]["file"] == "renamed.env"
        assert calls == [["renamed.env"]]
    else:
        assert result["status"] == "pass"
        assert result["findings"] == []
        assert calls == ([] if change == "delete" else [[]])


@pytest.mark.parametrize("suffix", ["", " ", "\t", "\n", " \n"])
def test_repository_root_whitespace_keeps_the_selected_index(
    repo, synthetic_scanner, capsys, suffix
):
    if os.name == "nt" and suffix:
        pytest.skip("Windows directory names do not support these trailing characters.")
    module, calls, value = synthetic_scanner
    selected = repo
    if suffix:
        selected = repo.rename(repo.with_name(repo.name + suffix))
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    filename = "config.env"
    stage(selected, filename, "OPENAI_API_KEY=" + value + "\n")

    assert module.main(["staged", "--root", str(selected)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "fail"
    assert result["files_scanned"] == 1
    assert result["findings"][0]["file"] == filename
    assert calls == [[filename]]


@pytest.mark.parametrize(
    "output", [b"", b"\n", b"relative\n", b"/invalid\0root\n", b"/truncated"]
)
def test_malformed_git_repository_root_cannot_pass_the_scan(
    repo, synthetic_scanner, monkeypatch, output
):
    module, calls, value = synthetic_scanner
    stage(repo, "config.env", "OPENAI_API_KEY=" + value + "\n")
    original = module.git

    def malformed_root(root, *args):
        if args == ("rev-parse", "--show-toplevel"):
            return output
        return original(root, *args)

    monkeypatch.setattr(module, "git", malformed_root)
    with pytest.raises(module.GuardError, match="repository root"):
        module.scan_staged(repo)
    assert calls == []


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
    install_project_hooks(repo)
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


@pytest.mark.parametrize(
    "operation",
    ["commit", "merge", "cherry-pick", "am", "rebase-merge", "rebase-apply"],
)
def test_git_commit_paths_require_the_staged_scan(repo, monkeypatch, operation):
    command = incoming_operation(repo, operation, "ordinary sentinel input\n")
    install_project_hooks(repo, rejecting_sentinel=True)
    monkeypatch.setenv("AGILAB_SKIP_LOCAL_GUARDS", "1")
    before = commit_objects(repo)
    result = subprocess.run(
        ["git", "-C", str(repo), *command], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "isolated-staged-scan-sentinel" in result.stdout + result.stderr
    assert commit_objects(repo) == before


@pytest.mark.parametrize(
    "operation",
    ["commit", "merge", "cherry-pick", "am", "rebase-merge", "rebase-apply"],
)
@pytest.mark.parametrize("credential_shaped", [False, True])
def test_git_commit_paths_scan_real_staged_blobs(
    repo, scanner, monkeypatch, operation, credential_shaped
):
    configured(monkeypatch, scanner)
    value = prototype() if credential_shaped else "EXAMPLE_ONLY_NOT_A_REAL_KEY"
    command = incoming_operation(repo, operation, "OPENAI_API_KEY=" + value + "\n")
    install_project_hooks(repo)
    monkeypatch.setenv("AGILAB_SKIP_LOCAL_GUARDS", "1")
    before = commit_objects(repo)
    result = subprocess.run(
        ["git", "-C", str(repo), *command], capture_output=True, text=True
    )
    if credential_shaped:
        assert result.returncode != 0
        assert '"status": "fail"' in result.stdout + result.stderr
        assert value not in result.stdout + result.stderr
        assert commit_objects(repo) == before
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(commit_objects(repo) - before) == 1


def test_native_timer_cannot_turn_an_incomplete_scan_into_success(
    repo, monkeypatch, capsys
):
    module = load_guard()
    stage(repo, "safe.txt", "ordinary staged content\n")
    executable = repo.parent / "fake-scanner"
    monkeypatch.setattr(module, "verified_binary", lambda: executable)
    original = subprocess.run
    calls = []

    def incomplete_scanner(command, **kwargs):
        if command[0] != str(executable):
            return original(command, **kwargs)
        calls.append((command, kwargs))
        report = Path(command[command.index("--report-path") + 1])
        report.write_text("[]", encoding="utf-8")
        if any(arg.startswith("--timeout") for arg in command):
            # Model Gitleaks' silent native-timer cancellation: a false clean report.
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise subprocess.TimeoutExpired(
            command,
            kwargs["timeout"],
            output=b"partial-private-output",
            stderr=b"partial-private-diagnostic",
        )

    monkeypatch.setattr(module.subprocess, "run", incomplete_scanner)
    assert module.main(["staged", "--root", str(repo)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {
        "status": "error",
        "message": "Secret scan could not complete; commit is blocked.",
    }
    assert len(calls) == 1
    command, options = calls[0]
    assert not any(arg.startswith("--timeout") for arg in command)
    assert options["timeout"] == 130
    assert options["capture_output"] is True
