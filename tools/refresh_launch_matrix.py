#!/usr/bin/env python3
"""
Regenerate the Launch Matrix from .idea/runConfigurations/*.xml.

Usage:
  - Print table to stdout:
      python tools/refresh_launch_matrix.py
  - Update AGENTS.md in-place (replace the table inside the <details> section):
      python tools/refresh_launch_matrix.py --inplace
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


def parse_run_configs(rc_dir: Path) -> list[tuple[str, str, str, str, str, str, str, str]]:
    rows_map: dict[str, tuple[str, str, str, str, str, str, str, str]] = {}
    files = sorted(rc_dir.glob("*.xml"), key=lambda p: (p.name.startswith("_"), p.name.lower()))
    for f in files:
        try:
            tree = ET.parse(f)
        except ET.ParseError:
            continue
        root = tree.getroot()
        cfg = root.find('.//configuration')
        if cfg is None:
            continue

        name = cfg.get('name', '')
        sdk = ''
        opts = {opt.get('name'): opt.get('value', '') for opt in cfg.findall('option')}
        for opt in cfg.findall('option'):
            if opt.get('name') == 'SDK_NAME':
                sdk = opt.get('value', '')

        envs_el = cfg.find('envs')
        envs: list[str] = []
        if envs_el is not None:
            for env in envs_el.findall('env'):
                envs.append(f"{env.get('name')}={env.get('value')}")
        env_str = ';'.join(envs)

        script = opts.get('SCRIPT_NAME', '')
        params = opts.get('PARAMETERS', '')
        workdir = opts.get('WORKING_DIRECTORY', '')
        module_mode = opts.get('MODULE_MODE', 'false') == 'true'
        module_name = opts.get('MODULE_NAME', '')

        # Group heuristics
        group = 'agilab'
        path_parts = (workdir + ' ' + script).lower()
        if any(k in path_parts for k in ['apps/', 'examples/', 'apps-pages', 'templates']):
            group = 'apps'
        if any(k in path_parts for k in ['agi_node', 'wenv/', '_worker', 'bdist_egg', 'build_ext']):
            group = 'components'
        if any(k in name.lower() for k in ['view_', 'view ']):
            group = 'views'
        if 'pypi' in name.lower() or 'publish' in name.lower():
            group = 'agilab'

        # How to run
        if module_mode:
            if module_name:
                launcher = f'uv run {module_name}'
            else:
                launcher = 'uv run'
                if script:
                    launcher += f' {script}'
            cmd = launcher + (f' {params}' if params else '')
        else:
            launcher = 'uv run python'
            cmd = launcher + (f" {script}" if script else '') + (f" {params}" if params else '')
        if workdir:
            cmd = f"cd {workdir} && {cmd}"

        if name in rows_map:
            continue
        rows_map[name] = (group, name, script, params, workdir, env_str, cmd, sdk)

    rows = list(rows_map.values())
    rows.sort(key=lambda r: (r[0], r[1].lower()))
    return rows


def render_table(rows: list[tuple[str, str, str, str, str, str, str, str]]) -> str:
    out = ["| Group | Config name | Entry | Args | Workdir | Env | How to run | Interpreter |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append('| ' + ' | '.join(x.replace('|', '\\|') for x in r) + ' |')
    return '\n'.join(out) + '\n'


def update_agents_md(table_md: str, repo_root: Path) -> bool:
    agents = repo_root / 'AGENTS.md'
    text = agents.read_text(encoding='utf-8')
    start_marker = "| Group | Config name | Entry | Args | Workdir | Env | How to run | Interpreter |"
    end_marker = "</details>"
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker, start_idx)
    if start_idx == -1 or end_idx == -1:
        return False
    before = text[:start_idx]
    after = text[end_idx:]
    new_text = before + table_md + after
    agents.write_text(new_text, encoding='utf-8')
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--inplace', action='store_true', help='Update AGENTS.md in-place')
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[1]
    rc_dir = repo / '.idea' / 'runConfigurations'
    if not rc_dir.exists():
        print(f"No runConfigurations directory found at {rc_dir}", file=sys.stderr)
        return 2

    rows = parse_run_configs(rc_dir)
    table = render_table(rows)
    if args.inplace:
        ok = update_agents_md(table, repo)
        if not ok:
            print("Could not locate matrix section in AGENTS.md; printing to stdout instead:\n", file=sys.stderr)
            sys.stdout.write(table)
    else:
        sys.stdout.write(table)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
