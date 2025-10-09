#!/usr/bin/env python3
"""
Generate runnable shell scripts mirroring every PyCharm run configuration.

Each script lives under tools/run_configs/<config_name>.sh and invokes the same
command (workdir, env vars, interpreter) that the IDE would execute.
"""

from __future__ import annotations

import shutil
import shlex
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


def expand_macros(text: str, project_root: Path, home: Path) -> str:
    replacements = {
        "$ProjectFileDir$": str(project_root),
        "$PROJECT_DIR$": str(project_root),
        "$USER_HOME$": str(home),
        "$MODULE_DIR$": str(project_root / ".idea" / "modules"),
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def classify_group(name: str, script: str, params: str, workdir: str) -> str:
    combined = " ".join(filter(None, [name.lower(), script.lower(), params.lower(), workdir.lower()]))
    if "apps/" in combined or "examples/" in combined or "apps-pages" in combined or "_project" in combined:
        return "apps"
    if "_worker" in combined or "wenv/" in combined or "build_ext" in combined or "bdist_egg" in combined:
        return "components"
    if "view_" in combined:
        return "views"
    return "agilab"


def generate_scripts(runconfig_dir: Path, out_dir: Path, project_root: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    home = Path.home()

    for xml_path in sorted(runconfig_dir.glob("*.xml"), key=lambda p: p.name):
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

        module_mode = options.get("MODULE_MODE", "false") == "true"
        module_name = options.get("MODULE_NAME", "")
        script = options.get("SCRIPT_NAME", "")
        params = options.get("PARAMETERS", "")
        workdir = options.get("WORKING_DIRECTORY", "")

        if module_mode:
            if module_name:
                cmd = f"uv run {module_name}"
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

        cmd = expand_macros(cmd, project_root, home)
        workdir_expanded = expand_macros(workdir, project_root, home)

        group = classify_group(cfg_name, script, params, workdir)
        group_dir = out_dir / group
        group_dir.mkdir(parents=True, exist_ok=True)

        script_lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
        script_lines.append(f"# Generated from PyCharm run configuration: {cfg_name}")
        if workdir_expanded:
            script_lines.append(f"cd {shlex.quote(workdir_expanded)}")
        if envs:
            for key, value in envs:
                value_expanded = expand_macros(value, project_root, home)
                script_lines.append(f'export {key}={shlex.quote(value_expanded)}')
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
