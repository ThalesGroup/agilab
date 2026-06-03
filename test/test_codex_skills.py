from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import sys


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
