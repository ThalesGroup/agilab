"""Exercise the real CLI dispatch block with process/filesystem actions replaced."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_node.agi_dispatcher import cli


@pytest.fixture
def dispatch():
    # Keep production parsing and argument routing intact. Isolate its main block
    # so force-clean and kill commands cannot signal user processes or delete data.
    source = Path(cli.__file__)
    tree = ast.parse(source.read_text(), filename=str(source))
    blocks = [node for node in tree.body if isinstance(node, ast.If)
              and isinstance(node.test, ast.Compare)
              and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"]
    assert len(blocks) == 1
    code = compile(ast.Module(body=blocks, type_ignores=[]), str(source), "exec")
    operations = {name: Mock(return_value=True) for name in (
        "kill", "clean", "acquire_remote_target_lease", "release_remote_target_lease",
        "recover_remote_target_lease", "unzip", "test_python_threads", "python_version", "rapids_probe")}
    operations["rapids_probe"].return_value = {"rapids_capable": False}
    log = Mock()
    def invoke(arguments):
        def exit_process(code):
            raise SystemExit(code)
        namespace = {**vars(cli), **operations, "__name__": "__main__",
                     "sys": SimpleNamespace(argv=["worker-cli", *arguments], exit=exit_process), "logger": log}
        exec(code, namespace)
    return invoke, operations, log


@pytest.mark.parametrize("args", [[], ["unknown"], ["kill"], ["clean"], ["clean-force"], ["unzip"],
                                ["target-lease-acquire"], ["target-lease-acquire", "target"],
                                ["target-lease-release", "target"], ["target-lease-recover", "target", "token"]])
def test_cli_rejects_missing_or_unknown_arguments_without_actions(dispatch, capsys, args):
    invoke, operations, _ = dispatch
    with pytest.raises(SystemExit) as raised:
        invoke(args)
    assert raised.value.code == 1
    assert cli.USAGE in capsys.readouterr().out
    assert all(operation.call_count == 0 for operation in operations.values())


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("success", [False, True])
def test_kill_dispatch_retains_explicit_exclusions_and_failure_status(dispatch, force, success):
    invoke, operations, log = dispatch
    operations["kill"].return_value = success
    args = ["kill-force", "1,bad,2"] if force else ["kill", "worker-target", "1,bad,2"]
    if success:
        invoke(args)
    else:
        with pytest.raises(SystemExit) as raised:
            invoke(args)
        assert raised.value.code == 1
    kwargs = {"exclude_pids": {1, 2}, "force_scan": True} if force else {"target": "worker-target", "exclude_pids": {1, 2}}
    operations["kill"].assert_called_once_with(**kwargs)
    log.warning.assert_called_once_with("Invalid PID to exclude: bad")


@pytest.mark.parametrize("command", ["clean", "clean-force"])
@pytest.mark.parametrize("token", [None, "exact-token"])
def test_clean_dispatch_preserves_force_scope_and_lease_token(dispatch, command, token):
    invoke, operations, _ = dispatch
    invoke([command, "worker-target", *([token] if token else [])])
    operations["clean"].assert_called_once_with(wenv="worker-target", force_scratch=command == "clean-force", lease_token=token)


@pytest.mark.parametrize("command", ["clean", "clean-force", "unzip"])
def test_mutation_action_failure_is_nonzero(dispatch, command):
    invoke, operations, _ = dispatch
    operations["unzip" if command == "unzip" else "clean"].return_value = False
    with pytest.raises(SystemExit) as raised:
        invoke([command, "worker-target"])
    assert raised.value.code == 1


@pytest.mark.parametrize("command,operation,args,expected", [
    ("target-lease-acquire", "acquire_remote_target_lease", ["target", "token"], (Path("target"), "token", "unknown")),
    ("target-lease-acquire", "acquire_remote_target_lease", ["target", "token", "deploy"], (Path("target"), "token", "deploy")),
    ("target-lease-release", "release_remote_target_lease", ["target", "token"], (Path("target"), "token")),
    ("target-lease-recover", "recover_remote_target_lease", ["target", "token", "old,,older"], (Path("target"), "token", ["old", "older"], "unknown")),
    ("target-lease-recover", "recover_remote_target_lease", ["target", "token", "old", "deploy"], (Path("target"), "token", ["old"], "deploy")),
])
@pytest.mark.parametrize("success", [False, True])
def test_lease_dispatch_preserves_exact_tokens_and_failure_status(dispatch, command, operation, args, expected, success):
    invoke, operations, _ = dispatch
    operations[operation].return_value = success
    if success:
        invoke([command, *args])
    else:
        with pytest.raises(SystemExit) as raised:
            invoke([command, *args])
        assert raised.value.code == 1
    operations[operation].assert_called_once_with(*expected)


@pytest.mark.parametrize("command,operation", [("threaded", "test_python_threads"), ("platform", "python_version"), ("rapids-probe", "rapids_probe")])
def test_read_only_diagnostics_dispatch(dispatch, capsys, command, operation):
    invoke, operations, _ = dispatch
    invoke([command])
    operations[operation].assert_called_once_with()
    if command == "rapids-probe":
        assert json.loads(capsys.readouterr().out) == {"rapids_capable": False}


@pytest.mark.parametrize("output,expected", [
    ("\nGPU 0: NVIDIA Test (UUID: GPU-fixture)\n", ["NVIDIA Test"]),
    (" Test Model \n\nSecond Model\n", ["Test Model", "Second Model"]),
])
def test_gpu_probe_names_remove_transport_formatting(output, expected):
    assert cli._gpu_names_from_nvidia_smi(output) == expected


def test_gpu_probe_candidates_are_deduplicated(monkeypatch):
    monkeypatch.setattr(cli, "shutil", SimpleNamespace(which=lambda _: "/fixture/nvidia-smi"))
    monkeypatch.setattr(cli, "_NVIDIA_SMI_CANDIDATES", ("/fixture/nvidia-smi", "/fallback", "/fallback"))
    assert list(cli._nvidia_smi_candidates()) == ["/fixture/nvidia-smi", "/fallback"]
