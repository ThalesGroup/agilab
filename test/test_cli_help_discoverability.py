"""Every shipped subcommand must be discoverable from `agilab --help`.

lab_run.main dispatches on raw_argv[:1] before building the argparse parser, so
argparse cannot advertise those verbs on its own. lab_run._SUBCOMMAND_GROUPS
supplies them as a help epilog; these tests keep that table honest as the
dispatch ladder changes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES = ROOT / "agilab-capabilities.json"
LAB_RUN = ROOT / "src" / "agilab" / "lab_run.py"

# `agilab agilab ...` is never a verb; guards against a malformed manifest entry.
_NOT_A_SUBCOMMAND = {"agilab"}


def _documented_subcommands() -> set[str]:
    manifest = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    verbs: set[str] = set()
    for entry in manifest["cli_commands"]:
        for invocation in [entry["command"], *entry.get("aliases", [])]:
            parts = invocation.split()
            if parts[:1] != ["agilab"] or len(parts) < 2:
                continue
            # Some manifest entries pipe-join sibling verbs: "agilab prove|verify|sign".
            for verb in parts[1].split("|"):
                if verb.startswith("-") or verb in _NOT_A_SUBCOMMAND:
                    continue
                verbs.add(verb)
    return verbs


def _dispatched_subcommands() -> set[str]:
    """Literal verbs matched in lab_run.main's raw_argv dispatch ladder."""
    source = LAB_RUN.read_text(encoding="utf-8")
    body = source[source.index("def main("):]
    verbs: set[str] = set()
    # `raw_argv[:1] == ["doctor"]`, `raw_argv[:1] in (["prove"], ["verify"], ...)`,
    # and `raw_argv[:2] == ["reuse", "suggest"]` — take only the leading verb of
    # each bracketed form, and allow the `in (...)` tuples to span lines.
    for match in re.finditer(r"raw_argv\[:([12])\]\s*(?:==|in)\s*(\(.*?\)|\[.*?\])", body, re.S):
        for form in re.findall(r'\[\s*"([a-z][a-z0-9_-]*)"', match.group(2)):
            verbs.add(form)
    return {v.replace("_", "-") for v in verbs}


def _help_text(capsys, argv: list[str]) -> str:
    from agilab import lab_run

    with pytest.raises(SystemExit):
        lab_run.main(argv)
    return capsys.readouterr().out


def test_capability_manifest_only_lists_dispatched_commands() -> None:
    """Guards the other direction: no manifest entry for a verb that is gone."""
    undispatched = _documented_subcommands() - _dispatched_subcommands()
    assert not undispatched, f"manifest advertises non-dispatched verbs: {sorted(undispatched)}"


def test_top_level_help_lists_every_shipped_subcommand(capsys) -> None:
    from agilab import lab_run

    help_text = _help_text(capsys, ["--help"])
    aliases = lab_run._SUBCOMMAND_ALIASES
    missing = sorted(
        verb
        for verb in _dispatched_subcommands()
        # An alias is covered by the help line of the verb it resolves to.
        if aliases.get(verb, verb) not in help_text
    )
    assert not missing, (
        "`agilab --help` does not advertise these dispatched subcommands: "
        f"{missing}. Add them to the parser epilog or a subparser group in "
        "lab_run.main so docs are not the only discovery path."
    )


def test_app_help_lists_surface_backend_launcher(capsys) -> None:
    """`agilab app surface` is owned by lab_run but registered on the app parser."""
    help_text = _help_text(capsys, ["app", "--help"])
    assert "surface" in help_text, (
        "`agilab app --help` omits `surface`, which quick-start.rst, features.rst, "
        "pytorch-playground.rst, demos.rst, public-app-catalog.rst and index.rst all document."
    )
