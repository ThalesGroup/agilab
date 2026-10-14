from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "codex_skills.py"
SKILLS_ROOT = Path(".codex") / "skills"
GENERATED_JSON = ROOT / ".codex" / "skills" / ".generated" / "skills_index.json"
GENERATED_MD = ROOT / ".codex" / "skills" / ".generated" / "skills_index.md"


def _load_module():
    module_name = "codex_skills_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_generated_skill_indexes_are_in_sync(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.chdir(ROOT)

    skills, issues = module.collect_skills(SKILLS_ROOT)
    assert not issues, f"Skill validation issues must be fixed before regenerating indexes: {issues}"

    tmp_json = tmp_path / "skills_index.json"
    tmp_md = tmp_path / "skills_index.md"
    shutil.copy2(GENERATED_JSON, tmp_json)
    shutil.copy2(GENERATED_MD, tmp_md)

    changed = module.generate_outputs(skills=skills, json_out=tmp_json, md_out=tmp_md)

    assert changed == [], (
        "Generated skills index is stale. Run "
        "`python3 tools/codex_skills.py --root .codex/skills generate` and commit the updated "
        "`.codex/skills/.generated/skills_index.json` and `.codex/skills/.generated/skills_index.md`."
    )
    assert tmp_json.read_text(encoding="utf-8") == GENERATED_JSON.read_text(encoding="utf-8")
    assert tmp_md.read_text(encoding="utf-8") == GENERATED_MD.read_text(encoding="utf-8")


def _skill_fixture(skills_root, invalid=None):
    skill_dir = skills_root / "alpha"
    skill_dir.mkdir(parents=True)
    if invalid == "missing-entrypoint":
        return skill_dir
    content = (
        "---\nname: alpha\ndescription: Fixture skill\nlicense: BSD-3-Clause\n"
        "---\n\n# Alpha\n\nUse the fixture.\n"
    )
    if invalid == "name-mismatch":
        content = content.replace("name: alpha", "name: another-name")
    elif invalid == "missing-frontmatter":
        content = "# Alpha\n\nUse the fixture.\n"
    entrypoint = skill_dir / "SKILL.md"
    entrypoint.write_text(content, encoding="utf-8")
    return entrypoint


@pytest.mark.parametrize("invalid", ["missing-entrypoint", "name-mismatch", "missing-frontmatter"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("custom_outputs", [False, True])
def test_generate_rejects_invalid_skills_before_writing(tmp_path, invalid, existing, custom_outputs):
    skills_root = tmp_path / "skills"
    invalid_path = _skill_fixture(skills_root, invalid)
    output_dir = tmp_path / "exports" if custom_outputs else skills_root / ".generated"
    json_out = output_dir / "skills_index.json"
    md_out = output_dir / "skills_index.md"
    command = [sys.executable, str(MODULE_PATH), "--root", str(skills_root), "generate"]
    if custom_outputs:
        command += ["--json-output", str(json_out), "--md-output", str(md_out)]
    before = {}
    if existing:
        output_dir.mkdir()
        for output in (json_out, md_out):
            output.write_bytes(b"existing index must remain unchanged\n")
            output.chmod(0o640)
            before[output] = (output.read_bytes(), output.stat().st_mode, output.stat().st_mtime_ns)

    result = subprocess.run(command, capture_output=True, text=True, check=False)

    assert result.returncode == 2
    if existing:
        assert {
            output: (output.read_bytes(), output.stat().st_mode, output.stat().st_mtime_ns)
            for output in (json_out, md_out)
        } == before
    else:
        assert not output_dir.exists()
    assert "ERROR:" in result.stderr
    assert str(invalid_path) in result.stderr
    assert "Generated:" not in result.stdout


@pytest.mark.parametrize("custom_outputs", [False, True])
def test_generate_valid_skills_remains_idempotent(tmp_path, custom_outputs):
    skills_root = tmp_path / "skills"
    _skill_fixture(skills_root)
    output_dir = tmp_path / "exports" if custom_outputs else skills_root / ".generated"
    json_out = output_dir / "skills_index.json"
    md_out = output_dir / "skills_index.md"
    command = [sys.executable, str(MODULE_PATH), "--root", str(skills_root), "generate"]
    if custom_outputs:
        command += ["--json-output", str(json_out), "--md-output", str(md_out)]

    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert "Generated:" in first.stdout
    assert json.loads(json_out.read_text(encoding="utf-8"))["skills"][0]["name"] == "alpha"
    assert "alpha" in md_out.read_text(encoding="utf-8")
    before = [(output.read_bytes(), output.stat().st_mtime_ns) for output in (json_out, md_out)]

    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr
    assert "No changes in generated outputs" in second.stdout
    assert [(output.read_bytes(), output.stat().st_mtime_ns) for output in (json_out, md_out)] == before


def test_non_strict_validate_preserves_warning_contract(tmp_path):
    skills_root = tmp_path / "skills"
    _skill_fixture(skills_root, "name-mismatch")
    result = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--root", str(skills_root), "validate"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "WARN:" in result.stderr
    assert "warning(s)" in result.stdout
    assert not (skills_root / ".generated").exists()
