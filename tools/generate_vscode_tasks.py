#!/usr/bin/env python3
"""
Generate local VS Code tasks and launch configs from tracked PyCharm run configs.

The generated `.vscode/tasks.json` and `.vscode/launch.json` are intentionally
local-only because `.vscode/` is ignored in this repository. The source of truth
remains `.idea/runConfigurations/`.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


PROMPT_RE = re.compile(r"\$Prompt:([^:$]+)(?::([^$]*))?\$")
FILE_PROMPT_RE = re.compile(r"\$FilePrompt\$")


@dataclass(frozen=True)
class RunConfiguration:
    name: str
    config_type: str
    factory_name: str
    options: dict[str, str]
    env_map: dict[str, str]
    workdir: str
    group: str


def sanitize_name(name: str) -> str:
    slug = []
    prev_sep = True
    for ch in name:
        if ch.isalnum():
            slug.append(ch.lower())
            prev_sep = False
        elif not prev_sep:
            slug.append("_")
            prev_sep = True
    cleaned = "".join(slug).strip("_")
    return cleaned or "value"


def tracked_runconfigs(repo_root: Path, runconfig_dir: Path) -> list[Path]:
    rel_pattern = str(runconfig_dir.relative_to(repo_root) / "*.xml")
    try:
        tracked_proc = subprocess.run(
            ["git", "ls-files", "--", rel_pattern],
            cwd=repo_root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        untracked_proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", rel_pattern],
            cwd=repo_root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name.lower())
    paths = sorted(
        {
            line.strip()
            for output in (tracked_proc.stdout, untracked_proc.stdout)
            for line in output.splitlines()
            if line.strip()
        }
    )
    if not paths:
        return sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name.lower())
    existing = [
        repo_root / p
        for p in paths
        if (repo_root / p).exists() and not Path(p).name.startswith("_")
    ]
    return existing or sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name.lower())


def expand_repo_macros(text: str) -> str:
    replacements = {
        "$ProjectFileDir$": "${workspaceFolder}",
        "$PROJECT_DIR$": "${workspaceFolder}",
        "$USER_HOME$": "${env:HOME}",
        "$MODULE_DIR$": "${workspaceFolder}/.idea/modules",
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def option_is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def classify_group(name: str, script: str, params: str, workdir: str) -> str:
    combined = " ".join(filter(None, [name.lower(), script.lower(), params.lower(), workdir.lower()]))
    if "apps/" in combined or "examples/" in combined or "apps-pages" in combined or "_project" in combined:
        return "apps"
    if "_worker" in combined or "wenv/" in combined or "build_ext" in combined or "bdist_egg" in combined:
        return "components"
    if "view_" in combined:
        return "views"
    return "agilab"


def convert_prompt_macros(text: str, inputs: dict[str, dict[str, str]]) -> str:
    def _prompt_repl(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        default = (match.group(2) or "").strip()
        input_id = f"prompt_{sanitize_name(label)}"
        inputs.setdefault(
            input_id,
            {
                "id": input_id,
                "type": "promptString",
                "description": label,
                "default": default,
            },
        )
        return f"${{input:{input_id}}}"

    text = PROMPT_RE.sub(_prompt_repl, text)

    def _file_repl(_match: re.Match[str]) -> str:
        input_id = "file_prompt"
        inputs.setdefault(
            input_id,
            {
                "id": input_id,
                "type": "promptString",
                "description": "File or directory path",
                "default": "${workspaceFolder}",
            },
        )
        return f"${{input:{input_id}}}"

    return FILE_PROMPT_RE.sub(_file_repl, text)


def expand_for_vscode(text: str, inputs: dict[str, dict[str, str]]) -> str:
    return convert_prompt_macros(expand_repo_macros(text), inputs)


def strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def split_cli_args(text: str) -> list[str]:
    if not text.strip():
        return []
    return shlex.split(text, posix=True)


def render_task_tokens(tokens: list[str]) -> str:
    rendered: list[str] = []
    for token in tokens:
        if not token:
            rendered.append('""')
        elif token.startswith("${input:") and token.endswith("}"):
            rendered.append(token)
        elif any(ch.isspace() for ch in token) or any(ch in token for ch in "\"'"):
            rendered.append(shlex.quote(token))
        else:
            rendered.append(token)
    return " ".join(rendered)


def load_runconfig(xml_path: Path) -> RunConfiguration | None:
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return None
    cfg = tree.find(".//configuration")
    if cfg is None:
        return None

    cfg_name = cfg.get("name", xml_path.stem)
    options = {opt.get("name"): opt.get("value", "") for opt in cfg.findall("option")}
    env_map = {
        env.get("name"): env.get("value", "")
        for env in cfg.findall("./envs/env")
        if env.get("name")
    }
    return RunConfiguration(
        name=cfg_name,
        config_type=cfg.get("type", ""),
        factory_name=cfg.get("factoryName", ""),
        options=options,
        env_map=env_map,
        workdir=options.get("WORKING_DIRECTORY", ""),
        group=classify_group(
            cfg_name,
            options.get("SCRIPT_NAME", ""),
            options.get("PARAMETERS", ""),
            options.get("WORKING_DIRECTORY", ""),
        ),
    )


def resolve_debug_module(config: RunConfiguration) -> str | None:
    if not option_is_truthy(config.options.get("MODULE_MODE", "false")):
        return None
    module_name = config.options.get("MODULE_NAME", "").strip()
    if module_name:
        return module_name
    script = config.options.get("SCRIPT_NAME", "").strip()
    if script and not any(sep in script for sep in ("/", "\\", " ")):
        return script
    return None


def build_python_task_command(config: RunConfiguration, inputs: dict[str, dict[str, str]]) -> str | None:
    module_mode = option_is_truthy(config.options.get("MODULE_MODE", "false"))
    module_name = config.options.get("MODULE_NAME", "")
    script = config.options.get("SCRIPT_NAME", "")
    params = config.options.get("PARAMETERS", "")

    if module_mode:
        cmd = ["uv", "run"]
        if module_name:
            cmd.extend(["python", "-m", expand_for_vscode(module_name, inputs)])
        elif script:
            cmd.append(expand_for_vscode(script, inputs))
        else:
            return None
        if params:
            cmd.extend(split_cli_args(expand_for_vscode(params, inputs)))
        return render_task_tokens(cmd)

    if not script:
        return None
    cmd = ["uv", "run", "python", expand_for_vscode(script, inputs)]
    if params:
        cmd.extend(split_cli_args(expand_for_vscode(params, inputs)))
    return render_task_tokens(cmd)


def pytest_target(config: RunConfiguration, inputs: dict[str, dict[str, str]]) -> str | None:
    new_target = strip_wrapping_quotes(config.options.get("_new_target", ""))
    new_target_type = strip_wrapping_quotes(config.options.get("_new_targetType", ""))
    if new_target and new_target_type == "PATH":
        return expand_for_vscode(new_target, inputs)

    script = config.options.get("SCRIPT_NAME", "")
    if not script:
        return None
    target = expand_for_vscode(script, inputs)
    class_name = config.options.get("CLASS_NAME", "").strip()
    method_name = config.options.get("METHOD_NAME", "").strip()
    if class_name:
        target += f"::{class_name}"
    if method_name:
        target += f"::{method_name}"
    return target


def pytest_arguments(config: RunConfiguration, inputs: dict[str, dict[str, str]]) -> list[str]:
    args: list[str] = []

    pattern = config.options.get("PATTERN", "")
    if option_is_truthy(config.options.get("USE_PATTERN", "false")) and pattern:
        args.extend(["-k", expand_for_vscode(pattern, inputs)])

    keywords = strip_wrapping_quotes(config.options.get("_new_keywords", ""))
    if keywords:
        args.extend(["-k", expand_for_vscode(keywords, inputs)])

    params = config.options.get("PARAMS", "") or strip_wrapping_quotes(config.options.get("_new_parameters", ""))
    if params:
        args.extend(split_cli_args(expand_for_vscode(params, inputs)))

    additional = config.options.get("ADDITIONAL_ARGS", "") or strip_wrapping_quotes(
        config.options.get("_new_additionalArguments", "")
    )
    if additional:
        args.extend(split_cli_args(expand_for_vscode(additional, inputs)))

    target = pytest_target(config, inputs)
    if target:
        args.append(target)
    return args


def build_pytest_task_command(config: RunConfiguration, inputs: dict[str, dict[str, str]]) -> str:
    return render_task_tokens(["uv", "run", "pytest", *pytest_arguments(config, inputs)])


def build_task_entry(config: RunConfiguration, inputs: dict[str, dict[str, str]]) -> dict[str, object] | None:
    if config.config_type == "tests" and config.factory_name == "py.test":
        command = build_pytest_task_command(config, inputs)
    elif config.config_type == "PythonConfigurationType":
        command = build_python_task_command(config, inputs)
    else:
        return None

    if not command:
        return None

    workdir = expand_for_vscode(config.workdir, inputs) or "${workspaceFolder}"
    env_map = {
        key: expand_for_vscode(value, inputs)
        for key, value in config.env_map.items()
    }
    env_map["VIRTUAL_ENV"] = ""
    return {
        "label": config.name,
        "type": "shell",
        "command": command,
        "options": {
            "cwd": workdir,
            "env": env_map,
        },
        "presentation": {
            "reveal": "always",
            "panel": "dedicated",
            "clear": False,
        },
        "problemMatcher": [],
        "detail": f"Generated from PyCharm run configuration ({config.group})",
    }


def build_launch_entry(config: RunConfiguration, inputs: dict[str, dict[str, str]]) -> dict[str, object] | None:
    workdir = expand_for_vscode(config.workdir, inputs) or "${workspaceFolder}"
    env_map = {
        key: expand_for_vscode(value, inputs)
        for key, value in config.env_map.items()
    }
    entry: dict[str, object] = {
        "name": config.name,
        "type": "debugpy",
        "request": "launch",
        "cwd": workdir,
        "env": env_map,
        "console": "integratedTerminal",
    }

    interpreter_options = config.options.get("INTERPRETER_OPTIONS", "")
    python_args = split_cli_args(expand_for_vscode(interpreter_options, inputs))
    if python_args:
        entry["pythonArgs"] = python_args

    if config.config_type == "tests" and config.factory_name == "py.test":
        entry["module"] = "pytest"
        entry["args"] = pytest_arguments(config, inputs)
        return entry

    if config.config_type != "PythonConfigurationType":
        return None

    module_target = resolve_debug_module(config)
    params = config.options.get("PARAMETERS", "")
    entry["args"] = split_cli_args(expand_for_vscode(params, inputs))
    if module_target:
        entry["module"] = expand_for_vscode(module_target, inputs)
        return entry

    script = config.options.get("SCRIPT_NAME", "")
    if not script:
        return None
    entry["program"] = expand_for_vscode(script, inputs)
    return entry


def collect_runconfigs(repo_root: Path, runconfig_dir: Path) -> list[RunConfiguration]:
    configs: list[RunConfiguration] = []
    for xml_path in tracked_runconfigs(repo_root, runconfig_dir):
        config = load_runconfig(xml_path)
        if config is not None:
            configs.append(config)
    return configs


def build_tasks_payload(runconfigs: list[RunConfiguration]) -> dict[str, object]:
    inputs: dict[str, dict[str, str]] = {}
    tasks = []
    for config in runconfigs:
        entry = build_task_entry(config, inputs)
        if entry is not None:
            tasks.append(entry)
    payload: dict[str, object] = {
        "version": "2.0.0",
        "tasks": tasks,
    }
    if inputs:
        payload["inputs"] = sorted(inputs.values(), key=lambda item: item["id"])
    return payload


def build_launch_payload(runconfigs: list[RunConfiguration]) -> dict[str, object]:
    inputs: dict[str, dict[str, str]] = {}
    configurations = []
    for config in runconfigs:
        entry = build_launch_entry(config, inputs)
        if entry is not None:
            configurations.append(entry)
    payload: dict[str, object] = {
        "version": "0.2.0",
        "configurations": configurations,
    }
    if inputs:
        payload["inputs"] = sorted(inputs.values(), key=lambda item: item["id"])
    return payload


def build_tasks(repo_root: Path, runconfig_dir: Path) -> dict[str, object]:
    return build_tasks_payload(collect_runconfigs(repo_root, runconfig_dir))


def build_launch(repo_root: Path, runconfig_dir: Path) -> dict[str, object]:
    return build_launch_payload(collect_runconfigs(repo_root, runconfig_dir))


def write_json(payload: dict[str, object], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        "--tasks-out",
        dest="tasks_out",
        default=".vscode/tasks.json",
        help="Output path for generated VS Code tasks.json",
    )
    parser.add_argument(
        "--launch-out",
        default=".vscode/launch.json",
        help="Output path for generated VS Code launch.json",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    runconfig_dir = repo_root / ".idea" / "runConfigurations"
    if not runconfig_dir.exists():
        raise SystemExit(f"No runConfigurations directory found at {runconfig_dir}")

    tasks_out = (repo_root / args.tasks_out).resolve() if not Path(args.tasks_out).is_absolute() else Path(args.tasks_out)
    launch_out = (
        (repo_root / args.launch_out).resolve() if not Path(args.launch_out).is_absolute() else Path(args.launch_out)
    )

    runconfigs = collect_runconfigs(repo_root, runconfig_dir)
    tasks_payload = build_tasks_payload(runconfigs)
    launch_payload = build_launch_payload(runconfigs)
    write_json(tasks_payload, tasks_out)
    write_json(launch_payload, launch_out)
    print(
        f"Generated {len(tasks_payload['tasks'])} VS Code tasks -> {tasks_out}\n"
        f"Generated {len(launch_payload['configurations'])} VS Code launches -> {launch_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
