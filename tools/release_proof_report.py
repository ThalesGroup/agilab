#!/usr/bin/env python3
"""Render and validate the AGILAB release proof documentation page."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
from string import Formatter
import subprocess
import textwrap
from typing import Any, Mapping, Sequence
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS_SOURCE = REPO_ROOT / "docs" / "source"
MANIFEST_RELATIVE_PATH = Path("data/release_proof.toml")
OUTPUT_RELATIVE_PATH = Path("release-proof.rst")
SCHEMA = "agilab.release_proof.v1"


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        raise KeyError(f"unknown release proof template key: {key}")


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_toml(path)
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"{path} must declare schema = {SCHEMA!r}")
    return manifest


def _format_toml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    raise TypeError(f"unsupported TOML scalar: {type(value).__name__}")


def _format_toml_list_item(value: Any) -> str:
    if isinstance(value, Mapping):
        raise TypeError("mapping values must be written as TOML tables")
    return _format_toml_scalar(value)


def _dump_toml_key_value(lines: list[str], key: str, value: Any) -> None:
    if isinstance(value, list):
        if all(not isinstance(item, Mapping) for item in value):
            if not value:
                lines.append(f"{key} = []")
                return
            lines.append(f"{key} = [")
            for item in value:
                lines.append(f"  {_format_toml_list_item(item)},")
            lines.append("]")
            return
        raise TypeError(f"{key} must be emitted as an array table")
    if isinstance(value, Mapping):
        raise TypeError(f"{key} must be emitted as a table")
    lines.append(f"{key} = {_format_toml_scalar(value)}")


def dump_manifest(manifest: Mapping[str, Any]) -> str:
    lines: list[str] = []
    first_block = True
    for key, value in manifest.items():
        if isinstance(value, Mapping):
            if not first_block:
                lines.append("")
            lines.append(f"[{key}]")
            for child_key, child_value in value.items():
                _dump_toml_key_value(lines, str(child_key), child_value)
            first_block = False
            continue
        if isinstance(value, list) and any(isinstance(item, Mapping) for item in value):
            for item in value:
                if not isinstance(item, Mapping):
                    raise TypeError(f"{key} mixes table and scalar values")
                if not first_block:
                    lines.append("")
                lines.append(f"[[{key}]]")
                for child_key, child_value in item.items():
                    _dump_toml_key_value(lines, str(child_key), child_value)
                first_block = False
            continue
        _dump_toml_key_value(lines, str(key), value)
        first_block = False
    lines.append("")
    return "\n".join(lines)


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_manifest(manifest), encoding="utf-8")


def _template_context(manifest: Mapping[str, Any]) -> dict[str, Any]:
    release = manifest.get("release", {})
    if not isinstance(release, Mapping):
        raise TypeError("[release] must be a table")
    package_name = str(release.get("package_name", ""))
    package_version = str(release.get("package_version", ""))
    return {
        **{str(key): value for key, value in release.items()},
        "package_spec": f"{package_name}=={package_version}",
    }


def _format_template(text: str, context: Mapping[str, Any]) -> str:
    # Validate field names explicitly so a release manifest typo fails clearly.
    for _, field_name, _, _ in Formatter().parse(text):
        if field_name and field_name not in context:
            raise KeyError(f"unknown release proof template key: {field_name}")
    return text.format_map(_SafeFormatDict(context))


def _format_templates(values: Sequence[Any], context: Mapping[str, Any]) -> list[str]:
    return [_format_template(str(value), context) for value in values]


def _append_wrapped(
    lines: list[str],
    text: str,
    *,
    initial_indent: str = "",
    subsequent_indent: str | None = None,
) -> None:
    subsequent = initial_indent if subsequent_indent is None else subsequent_indent
    wrapped = textwrap.wrap(
        text,
        width=79,
        initial_indent=initial_indent,
        subsequent_indent=subsequent,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if wrapped:
        lines.extend(wrapped)
    else:
        lines.append(initial_indent.rstrip())


def _append_paragraphs(lines: list[str], paragraphs: Sequence[Any], context: Mapping[str, Any]) -> None:
    for index, paragraph in enumerate(_format_templates(paragraphs, context)):
        if index:
            lines.append("")
        _append_wrapped(lines, paragraph)


def _append_code_block(
    lines: list[str],
    commands: Sequence[Any],
    context: Mapping[str, Any],
    *,
    indent: str = "",
) -> None:
    lines.append("")
    lines.append(f"{indent}.. code-block:: bash")
    lines.append("")
    for command in _format_templates(commands, context):
        lines.append(f"{indent}   {command}")


def _required_table(name: str, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    value = manifest.get(name)
    if not isinstance(value, Mapping):
        raise TypeError(f"[{name}] must be a table")
    return value


def _required_list(name: str, manifest: Mapping[str, Any]) -> list[Any]:
    value = manifest.get(name, [])
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


def render_release_proof(manifest: Mapping[str, Any]) -> str:
    context = _template_context(manifest)
    release = _required_table("release", manifest)
    proof_command = _required_table("proof_command", manifest)
    verification = _required_table("verification", manifest)
    scope = _required_table("scope", manifest)
    maintenance = manifest.get("maintenance", {})
    ci_runs = _required_list("ci_runs", manifest)
    proof_bullets = _required_list("proof_bullets", manifest)
    related_pages = _required_list("related_pages", manifest)

    title = str(manifest.get("title", "Release Proof"))
    lines: list[str] = [title, "=" * len(title), ""]
    lines.extend(
        [
            ".. This page is generated from docs/source/data/release_proof.toml by",
            "   tools/release_proof_report.py. Edit the TOML and rerender.",
            "",
        ]
    )
    _append_paragraphs(lines, _required_list("intro", manifest), context)

    lines.extend(
        [
            "",
            "Current public release",
            "----------------------",
            "",
            ".. list-table::",
            "   :header-rows: 1",
            "   :widths: 24 76",
            "",
            "   * - Item",
            "     - Public evidence",
            "   * - Package version",
            (
                f"     - ``{context['package_spec']}`` on "
                f"`PyPI <{release['pypi_url']}>`__"
            ),
            "   * - GitHub release",
            (
                f"     - `{release['github_release_tag']} "
                f"<{release['github_release_url']}>`__"
            ),
            "   * - Hosted demo",
            (
                f"     - `{release['hf_space_label']} <{release['hf_space_url']}>`__ "
                f"at Space commit ``{release['hf_space_commit']}``"
            ),
        ]
    )
    for run in ci_runs:
        if not isinstance(run, Mapping):
            raise TypeError("each [[ci_runs]] entry must be a table")
        label = str(run["label"])
        workflow = str(run["workflow"])
        run_id = str(run["run_id"])
        url = str(run["url"])
        summary = _format_template(str(run["summary"]), context)
        lines.extend(
            [
                f"   * - {label}",
                f"     - `{workflow} run {run_id} <{url}>`__ {summary}",
            ]
        )

    lines.extend(["", "What was proved", "---------------", ""])
    _append_wrapped(lines, _format_template(str(proof_command["summary"]), context), initial_indent="- ")
    _append_code_block(lines, proof_command.get("commands", []), context, indent="  ")
    lines.append("")
    for bullet in _format_templates(proof_bullets, context):
        _append_wrapped(lines, bullet, initial_indent="- ", subsequent_indent="  ")

    lines.extend(["", "How to verify it again", "----------------------", ""])
    _append_paragraphs(lines, [verification["intro"]], context)
    _append_code_block(lines, verification.get("commands", []), context)
    lines.append("")
    _append_paragraphs(lines, [verification["follow_up"]], context)

    if maintenance:
        if not isinstance(maintenance, Mapping):
            raise TypeError("[maintenance] must be a table")
        lines.extend(["", "Maintainer refresh", "------------------", ""])
        _append_paragraphs(lines, [maintenance["intro"]], context)
        _append_code_block(lines, maintenance.get("commands", []), context)
        follow_up = maintenance.get("follow_up")
        if follow_up:
            lines.append("")
            _append_paragraphs(lines, [follow_up], context)

    lines.extend(["", "Scope and limits", "----------------", ""])
    _append_paragraphs(lines, [scope["paragraph"]], context)

    lines.extend(["", "Related pages", "-------------", ""])
    for page in related_pages:
        lines.append(f"- :doc:`{page}`")
    lines.append("")
    return "\n".join(lines)


def _check_result(
    check_id: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": dict(details or {}),
    }


def _load_project_version(repo_root: Path) -> str | None:
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return None
    payload = _load_toml(pyproject)
    project = payload.get("project", {})
    if not isinstance(project, Mapping):
        return None
    version = project.get("version")
    return str(version) if version is not None else None


def _run_git(repo_root: Path, args: Sequence[str]) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _release_tag_prefix(package_version: str) -> str | None:
    match = re.match(r"^(\d{4}\.\d{2}\.\d{2})", package_version)
    return match.group(1) if match else None


def _latest_local_release_tag(repo_root: Path, package_version: str) -> str | None:
    prefix = _release_tag_prefix(package_version)
    if not prefix:
        return None
    output = _run_git(repo_root, ["tag", "--list", f"v{prefix}*", "--sort=-v:refname"])
    if not output:
        return None
    return output.splitlines()[0].strip() or None


def _github_repo_base_url(repo_root: Path) -> str | None:
    remote = _run_git(repo_root, ["remote", "get-url", "origin"])
    if not remote:
        return None
    remote = remote.strip()
    if remote.startswith("https://github.com/"):
        return remote.removesuffix(".git")
    ssh_match = re.match(r"git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$", remote)
    if ssh_match:
        return f"https://github.com/{ssh_match.group('repo')}"
    return None


def refresh_manifest_from_local(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    github_release_tag: str | None = None,
    github_release_url: str | None = None,
    hf_space_commit: str | None = None,
) -> dict[str, Any]:
    refreshed = copy.deepcopy(dict(manifest))
    release = refreshed.get("release")
    if not isinstance(release, dict):
        raise TypeError("[release] must be a table")

    package_version = _load_project_version(repo_root) or str(release.get("package_version", ""))
    if package_version:
        release["package_version"] = package_version

    tag = github_release_tag or _latest_local_release_tag(repo_root, package_version)
    if tag:
        release["github_release_tag"] = tag
        base_url = _github_repo_base_url(repo_root)
        release["github_release_url"] = github_release_url or (
            f"{base_url}/releases/tag/{tag}" if base_url else str(release.get("github_release_url", ""))
        )
    elif github_release_url:
        release["github_release_url"] = github_release_url

    if hf_space_commit:
        release["hf_space_commit"] = hf_space_commit

    return refreshed


def _text_contains(path: Path, expected: str) -> bool | None:
    if not path.exists():
        return None
    return expected in path.read_text(encoding="utf-8")


def _ci_run_urls_are_consistent(ci_runs: Sequence[Any]) -> bool:
    for run in ci_runs:
        if not isinstance(run, Mapping):
            return False
        run_id = str(run.get("run_id", ""))
        url = str(run.get("url", ""))
        if not run_id or not url.endswith(f"/actions/runs/{run_id}"):
            return False
    return True


def build_report(
    *,
    manifest_path: Path,
    output_path: Path,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    rendered = render_release_proof(manifest)
    release = _required_table("release", manifest)
    ci_runs = _required_list("ci_runs", manifest)
    package_version = str(release["package_version"])
    github_release_url = str(release["github_release_url"])
    github_release_tag = str(release["github_release_tag"])
    checks: list[dict[str, Any]] = []

    project_version = _load_project_version(repo_root)
    checks.append(
        _check_result(
            "pyproject_version",
            project_version in (None, package_version),
            (
                "manifest package version matches pyproject.toml"
                if project_version is not None
                else "pyproject.toml not present; skipped package version cross-check"
            ),
            evidence=["pyproject.toml", str(manifest_path)],
            details={"pyproject_version": project_version, "manifest_version": package_version},
        )
    )
    checks.append(
        _check_result(
            "github_release_url",
            github_release_tag in github_release_url,
            "manifest GitHub release URL contains the release tag",
            evidence=[str(manifest_path)],
            details={"tag": github_release_tag, "url": github_release_url},
        )
    )
    badge_path = repo_root / "badges" / "pypi-version-agilab.svg"
    badge_contains = _text_contains(badge_path, f"v{package_version}")
    checks.append(
        _check_result(
            "pypi_badge_version",
            badge_contains is not False,
            (
                "PyPI badge contains manifest package version"
                if badge_contains is not None
                else "PyPI badge not present; skipped badge cross-check"
            ),
            evidence=[str(badge_path.relative_to(repo_root)) if badge_path.exists() else str(badge_path)],
        )
    )
    changelog = repo_root / "CHANGELOG.md"
    changelog_text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
    checks.append(
        _check_result(
            "changelog_release",
            not changelog.exists()
            or (f"## [{package_version}]" in changelog_text and github_release_url in changelog_text),
            "CHANGELOG current release entry matches the manifest",
            evidence=["CHANGELOG.md", str(manifest_path)],
        )
    )
    readme = repo_root / "README.md"
    readme_contains = _text_contains(readme, "https://thalesgroup.github.io/agilab/release-proof.html")
    checks.append(
        _check_result(
            "readme_release_proof_link",
            readme_contains is not False,
            (
                "README links to the public release proof page"
                if readme_contains is not None
                else "README not present; skipped README link cross-check"
            ),
            evidence=["README.md"],
        )
    )
    checks.append(
        _check_result(
            "ci_run_urls",
            _ci_run_urls_are_consistent(ci_runs),
            "CI run URLs match their run IDs",
            evidence=[str(manifest_path)],
        )
    )
    output_matches = output_path.exists() and output_path.read_text(encoding="utf-8") == rendered
    checks.append(
        _check_result(
            "rendered_page",
            output_matches,
            "release-proof.rst matches the rendered manifest output",
            evidence=[str(manifest_path), str(output_path)],
        )
    )

    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "report": "AGILAB release proof report",
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "manifest": str(manifest_path),
        "output": str(output_path),
        "release": {
            "package_name": str(release["package_name"]),
            "package_version": package_version,
            "github_release_tag": github_release_tag,
            "github_release_url": github_release_url,
            "hf_space_url": str(release["hf_space_url"]),
            "hf_space_commit": str(release["hf_space_commit"]),
        },
        "summary": {
            "check_count": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs-source",
        type=Path,
        default=DEFAULT_DOCS_SOURCE,
        help="Docs source root containing data/release_proof.toml.",
    )
    parser.add_argument("--data", type=Path, default=None, help="Override manifest path.")
    parser.add_argument("--output", type=Path, default=None, help="Override RST output path.")
    parser.add_argument(
        "--refresh-from-local",
        action="store_true",
        help=(
            "Update the manifest from local release evidence: pyproject.toml, the matching "
            "local git release tag, and the GitHub origin URL."
        ),
    )
    parser.add_argument("--github-release-tag", default=None, help="Override refreshed GitHub release tag.")
    parser.add_argument("--github-release-url", default=None, help="Override refreshed GitHub release URL.")
    parser.add_argument("--hf-space-commit", default=None, help="Override refreshed Hugging Face Space commit.")
    parser.add_argument("--render", action="store_true", help="Write the rendered RST page.")
    parser.add_argument("--check", action="store_true", help="Fail if manifest checks or rendered page drift.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    parser.add_argument("--quiet", action="store_true", help="Suppress JSON output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    docs_source = args.docs_source
    manifest_path = args.data or docs_source / MANIFEST_RELATIVE_PATH
    output_path = args.output or docs_source / OUTPUT_RELATIVE_PATH

    manifest = load_manifest(manifest_path)
    if args.refresh_from_local:
        manifest = refresh_manifest_from_local(
            manifest,
            repo_root=REPO_ROOT,
            github_release_tag=args.github_release_tag,
            github_release_url=args.github_release_url,
            hf_space_commit=args.hf_space_commit,
        )
        write_manifest(manifest_path, manifest)

    rendered = render_release_proof(manifest)
    if args.render:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    report = build_report(
        manifest_path=manifest_path,
        output_path=output_path,
        repo_root=REPO_ROOT,
    )
    if not args.quiet:
        if args.compact:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if (not args.check or report["status"] == "pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
