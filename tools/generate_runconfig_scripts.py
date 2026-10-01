#!/usr/bin/env python3
"""
Generate runnable shell scripts mirroring every PyCharm run configuration.

Each script lives under tools/run_configs/<config_name>.sh and invokes the same
command (workdir, env vars, interpreter) that the IDE would execute.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET


def sanitize_name(name: str) -> str:
    slug = []
    prev_sep = True
    for ch in name:
        if ch.isalnum():
            slug.append(ch.lower())
            prev_sep = False
        elif not prev_sep:
            slug.append("-")
            prev_sep = True
    cleaned = "".join(slug).strip("-")
    return cleaned or "run-config"


def expand_macros(text: str) -> str:
    replacements = {
        "$ProjectFileDir$": "$REPO_ROOT",
        "$PROJECT_DIR$": "$REPO_ROOT",
        "$USER_HOME$": "$HOME",
        "$MODULE_DIR$": "$REPO_ROOT/.idea/modules",
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text



# IDE fields contain argv values, not shell programs. Protect complete macros
# before splitting PARAMETERS so prompt labels and defaults stay in one token.
RUNCONFIG_MACRO_RE = re.compile(
    r"\$ProjectFileDir\$|\$PROJECT_DIR\$|\$USER_HOME\$|\$MODULE_DIR\$"
    r"|\$Prompt:[^$:]+(?::[^$]*)?\$|\$FilePrompt\$"
)
SHELL_PATH_MACROS = {
    "$ProjectFileDir$": '"${REPO_ROOT}"',
    "$PROJECT_DIR$": '"${REPO_ROOT}"',
    "$USER_HOME$": '"${HOME}"',
    "$MODULE_DIR$": '"${REPO_ROOT}"/.idea/modules',
}


def parameter_tokens(value: str) -> list[str]:
    protected_macros: dict[str, str] = {}

    def protect(match: re.Match[str]) -> str:
        # NUL cannot occur in XML; the placeholder cannot collide with input.
        marker = f"\0AGILAB_RUNCONFIG_MACRO_{len(protected_macros)}\0"
        protected_macros[marker] = match.group(0)
        return marker

    protected = RUNCONFIG_MACRO_RE.sub(protect, value)
    tokens = shlex.split(protected)
    for marker, macro in protected_macros.items():
        tokens = [token.replace(marker, macro) for token in tokens]
    return tokens


def shell_argument(
    value: str, inputs: dict[str, tuple[str, str, str, bool]]
) -> str:
    pieces: list[str] = []
    offset = 0
    for match in RUNCONFIG_MACRO_RE.finditer(value):
        if match.start() > offset:
            pieces.append(shlex.quote(value[offset:match.start()]))
        macro = match.group(0)
        if macro in SHELL_PATH_MACROS:
            pieces.append(SHELL_PATH_MACROS[macro])
        else:
            if macro not in inputs:
                is_file = macro == "$FilePrompt$"
                label, _, default = (
                    ("file_prompt", "", "") if is_file
                    else macro[len("$Prompt:"):-1].partition(":")
                )
                identifier = re.sub(r"[^A-Z0-9_]+", "_", label.upper()).strip("_")
                environment_name = f"AGILAB_RUNCONFIG_INPUT_{identifier or 'PROMPT'}"
                if any(
                    existing[1] == environment_name for existing in inputs.values()
                ):
                    raise ValueError(
                        "Ambiguous PyCharm input labels normalize to "
                        f"{environment_name}; rename one prompt label."
                    )
                variable = f"AGILAB_RUNCONFIG_VALUE_{len(inputs)}"
                inputs[macro] = (variable, environment_name, default, is_file)
            pieces.append('"${' + inputs[macro][0] + '}"')
        offset = match.end()
    if offset < len(value):
        pieces.append(shlex.quote(value[offset:]))
    return "".join(pieces) or "''"


def prompt_setup_lines(inputs: dict[str, tuple[str, str, str, bool]]) -> list[str]:
    lines: list[str] = []
    for variable, environment_name, default, is_file in inputs.values():
        lines.extend([
            f"# Set {environment_name} to override this PyCharm input.",
            f"if [[ ${{{environment_name}+x}} ]]; then",
            f'    {variable}="${{{environment_name}}}"',
            "else",
            f"    {variable}={shlex.quote(default)}",
            "fi",
        ])
        if is_file:
            lines.extend([
                f'if [[ -z "${{{variable}}}" ]]; then',
                "    printf '%s\\n' " + shlex.quote(
                    f"Set {environment_name} before running this wrapper."
                ) + " >&2",
                "    exit 2",
                "fi",
            ])
    return lines

def option_is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def looks_like_module_name(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    if any(sep in value for sep in ("/", "\\", " ")):
        return False
    return "." in value


def classify_group(name: str, script: str, params: str, workdir: str) -> str:
    combined = " ".join(filter(None, [name.lower(), script.lower(), params.lower(), workdir.lower()]))
    if "apps/" in combined or "examples/" in combined or "apps-pages" in combined or "_project" in combined:
        return "apps"
    if "_worker" in combined or "wenv/" in combined or "build_ext" in combined or "bdist_egg" in combined:
        return "components"
    if "view_" in combined:
        return "views"
    return "agilab"


def tracked_runconfigs(repo_root: Path, runconfig_dir: Path) -> list[Path]:
    """Return versioned or newly added run configuration XML files.

    This prevents local, ignored `_*.xml` configs from leaking into generated scripts
    while still allowing wrappers to be regenerated before a renamed config is committed.
    """
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
        return sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name)
    paths = sorted(
        {
            line.strip()
            for output in (tracked_proc.stdout, untracked_proc.stdout)
            for line in output.splitlines()
            if line.strip()
        }
    )
    if not paths:
        return sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name)
    existing = [
        repo_root / p
        for p in paths
        if (repo_root / p).exists() and not Path(p).name.startswith("_")
    ]
    if existing:
        return existing
    return sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name)


def generate_scripts(runconfig_dir: Path, out_dir: Path, project_root: Path) -> None:
    rendered_scripts: list[tuple[Path, str]] = []

    for xml_path in tracked_runconfigs(project_root, runconfig_dir):
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError:
            continue

        cfg = tree.find(".//configuration")
        if cfg is None:
            continue

        cfg_name = cfg.get("name", xml_path.stem)
        options = {opt.get("name"): opt.get("value", "") for opt in cfg.findall("option")}
        envs = [
            (env.get("name"), env.get("value", ""))
            for env in cfg.findall("./envs/env")
        ]

        module_mode = option_is_truthy(options.get("MODULE_MODE", "false"))
        module_name = options.get("MODULE_NAME", "")
        script = options.get("SCRIPT_NAME", "")
        params = options.get("PARAMETERS", "")
        workdir = options.get("WORKING_DIRECTORY", "")

        if module_mode:
            module_target = module_name
            if not module_target and looks_like_module_name(script):
                module_target = script
            if module_target:
                command_tokens = ["uv", "run", "python", "-m", module_target]
            else:
                command_tokens = ["uv", "run"]
                if script:
                    command_tokens.append(script)
        else:
            command_tokens = ["uv", "run", "python"]
            if script:
                command_tokens.append(script)

        try:
            command_tokens.extend(parameter_tokens(params))
        except ValueError as exc:
            raise ValueError(f"{cfg_name}: invalid PARAMETERS: {exc}") from exc
        inputs: dict[str, tuple[str, str, str, bool]] = {}
        cmd = " ".join(shell_argument(token, inputs) for token in command_tokens)
        workdir_expanded = expand_macros(workdir)

        group = classify_group(cfg_name, script, params, workdir)
        script_lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"',
            "",
        ]
        script_lines.append(f"# Generated from PyCharm run configuration: {cfg_name}")
        if workdir_expanded:
            script_lines.append(f'cd "{workdir_expanded}"')
        if envs:
            for key, value in envs:
                if key == "VIRTUAL_ENV":
                    continue
                value_expanded = expand_macros(value)
                script_lines.append(f'export {key}="{value_expanded}"')
        script_lines.extend(
            [
                "# Let uv select the run-config project .venv instead of a stale activated shell.",
                "unset VIRTUAL_ENV",
            ]
        )
        script_lines.extend(prompt_setup_lines(inputs))
        script_lines.append(cmd)
        script_lines.append("")

        rendered_scripts.append(
            (Path(group) / f"{sanitize_name(cfg_name)}.sh", "\n".join(script_lines))
        )

    # Finish validation before replacing a previously usable wrapper tree.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in rendered_scripts:
        out_path = out_dir / relative_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        out_path.chmod(0o755)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runconfig_dir = repo_root / ".idea" / "runConfigurations"
    out_dir = repo_root / "tools" / "run_configs"
    generate_scripts(runconfig_dir, out_dir, repo_root)


if __name__ == "__main__":
    main()
