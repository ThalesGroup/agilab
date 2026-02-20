#!/usr/bin/env python3
"""
Generate runnable shell scripts mirroring every PyCharm run configuration.

Each script lives under tools/run_configs/<config_name>.sh and invokes the same
command (workdir, env vars, interpreter) that the IDE would execute.
"""

from __future__ import annotations

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
    """Return git-tracked run configuration XML files.

    This prevents local, ignored `_*.xml` configs from leaking into generated scripts.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--", str(runconfig_dir.relative_to(repo_root) / "*.xml")],
            cwd=repo_root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name)
    paths = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not paths:
        return sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name)
    return [repo_root / p for p in sorted(paths)]


def generate_scripts(runconfig_dir: Path, out_dir: Path, project_root: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

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
                cmd = f"uv run python -m {module_target}"
                if params:
                    cmd += f" {params}"
            else:
                cmd = "uv run"
                if script:
                    cmd += f" {script}"
                if params:
                    cmd += f" {params}"
        else:
            cmd = "uv run python"
            if script:
                cmd += f" {script}"
            if params:
                cmd += f" {params}"

        cmd = expand_macros(cmd)
        workdir_expanded = expand_macros(workdir)

        group = classify_group(cfg_name, script, params, workdir)
        group_dir = out_dir / group
        group_dir.mkdir(parents=True, exist_ok=True)

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
                value_expanded = expand_macros(value)
                script_lines.append(f'export {key}="{value_expanded}"')
        script_lines.append(cmd)
        script_lines.append("")

        out_path = group_dir / f"{sanitize_name(cfg_name)}.sh"
        out_path.write_text("\n".join(script_lines), encoding="utf-8")
        out_path.chmod(0o755)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runconfig_dir = repo_root / ".idea" / "runConfigurations"
    out_dir = repo_root / "tools" / "run_configs"
    generate_scripts(runconfig_dir, out_dir, repo_root)


if __name__ == "__main__":
    main()
