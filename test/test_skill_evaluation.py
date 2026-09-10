from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

from agilab.agent_runtime.agent_run import trace_agent_run
from agilab.evidence import skill_evaluation as evaluation


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: synthetic-evaluation\ndescription: Test fixture\n---\n"
    )
    (skill / "reference.md").write_text("Frozen synthetic expectations.\n")
    fixtures = {
        "cases": [
            {"id": "in-scope", "checks": ["routing", "task", "persistence"]},
            {"id": "nearby", "checks": ["routing"]},
        ]
    }
    (tmp_path / "fixtures.json").write_text(json.dumps(fixtures))
    (tmp_path / "grader.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "plan = json.loads(Path(sys.argv[1]).read_text())\n"
        "result = {'schema': 'agilab.skill_evaluation_results.v1', 'plan_sha256': plan['sha256'], 'cases': []}\n"
        "for case in plan['cases']:\n"
        "    result['cases'].append({'id': case['id'], 'checks': {name: {'status': 'passed', 'evidence': 'Synthetic fixture observation.'} for name in case['checks']}})\n"
        "print(json.dumps(result))\n"
    )
    plan = evaluation.create_evaluation_plan(
        root=tmp_path,
        skill="skill",
        fixtures="fixtures.json",
        grader="grader.py",
        evaluator={
            "mode": "deterministic_fixture",
            "runtime": "python",
            "runtime_version": sys.version.split()[0],
            "model": "not_used",
        },
    )
    evaluation.persist_evaluation(tmp_path, "plan.json", plan)
    return tmp_path, plan


def run_fixture(frozen):
    root, plan = frozen
    result = trace_agent_run(
        [sys.executable, "grader.py", "plan.json"],
        cwd=root,
        output_dir=root / "run",
        run_id="synthetic-eval",
        agent="deterministic-fixture",
        permission_level="standard",
        metadata={"skill_evaluation_plan_sha256": plan["sha256"]},
    )
    assert result.returncode == 0, result.manifest
    return root / "run" / "agent_run_manifest.json"


def write_observations(manifest_path, update):
    """Model a different producer output, updating its native artifact fingerprint."""
    manifest = json.loads(manifest_path.read_text())
    stdout = Path(manifest["artifacts"]["stdout"]["path"])
    payload = json.loads(stdout.read_text())
    update(payload)
    data = json.dumps(payload).encode()
    stdout.write_bytes(data)
    manifest["artifacts"]["stdout"].update(
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
    )
    manifest_path.write_text(json.dumps(manifest))


def test_real_agent_run_round_trip_and_relative_receipt(frozen):
    root, _ = frozen
    manifest_path = run_fixture(frozen)
    manifest = json.loads(manifest_path.read_text())
    for name in ("stdout", "stderr", "claim"):
        descriptor = manifest["artifacts"][name]
        assert (
            descriptor["sha256"]
            == hashlib.sha256(Path(descriptor["path"]).read_bytes()).hexdigest()
        )
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=manifest_path
    )
    assert receipt["summary"] == {
        "status": "passed",
        "case_count": 2,
        "check_count": 4,
        "checks": {
            "passed": 4,
            "failed": 0,
            "not_checked": 0,
            "insufficient_evidence": 0,
        },
    }
    evaluation.persist_evaluation(root, "receipts/first.json", receipt)
    verified = evaluation.verify_evaluation_receipt(
        root=root, receipt_path="receipts/first.json"
    )
    assert verified["verification"] == "passed"
    assert verified["evaluation_status"] == "passed"
    assert str(root) not in json.dumps(receipt)
    assert "not independent attestation" in verified["claim_scope"]


@pytest.mark.parametrize(
    "change", ["skill", "reference", "new_file", "fixtures", "grader"]
)
def test_frozen_source_drift_is_rejected(frozen, change):
    root, _ = frozen
    manifest = run_fixture(frozen)
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=manifest
    )
    evaluation.persist_evaluation(root, "receipt.json", receipt)
    target = {
        "skill": "skill/SKILL.md",
        "reference": "skill/reference.md",
        "new_file": "skill/new.md",
        "fixtures": "fixtures.json",
        "grader": "grader.py",
    }[change]
    (root / target).write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        evaluation.verify_evaluation_receipt(root=root, receipt_path="receipt.json")


def test_same_size_output_tampering_is_rejected(frozen):
    root, _ = frozen
    manifest = run_fixture(frozen)
    stdout = root / "run/stdout.txt"
    data = stdout.read_bytes()
    stdout.write_bytes(data.replace(b"passed", b"failed"))
    assert len(stdout.read_bytes()) == len(data)
    with pytest.raises(ValueError, match="stdout bytes"):
        evaluation.create_evaluation_receipt(
            root=root, plan_path="plan.json", agent_run=manifest
        )


def test_complete_evidence_root_can_move_without_rewriting_native_manifest(frozen):
    root, _ = frozen
    manifest = run_fixture(frozen)
    original = manifest.read_bytes()
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=manifest
    )
    evaluation.persist_evaluation(root, "receipt.json", receipt)
    moved = root / "relocated"
    # Move only the bundle inputs; leave the test-owned HOME in place.
    moved.mkdir()
    for name in (
        "skill",
        "fixtures.json",
        "grader.py",
        "plan.json",
        "run",
        "receipt.json",
    ):
        shutil.move(str(root / name), str(moved / name))
    result = evaluation.verify_evaluation_receipt(
        root=moved, receipt_path="receipt.json"
    )
    assert result["verification"] == "passed"
    assert (moved / "run/agent_run_manifest.json").read_bytes() == original


@pytest.mark.parametrize("change", ["escape", "symlink", "extra", "wrong_hash"])
def test_receipt_artifact_mapping_is_confined_and_bound_to_native_hashes(
    frozen, change
):
    root, _ = frozen
    manifest = run_fixture(frozen)
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=manifest
    )
    if change == "escape":
        receipt["artifacts"]["stdout"]["path"] = "../outside.txt"
    elif change == "symlink":
        (root / "escape").symlink_to(root.parent)
        receipt["artifacts"]["stdout"]["path"] = "escape/outside.txt"
    elif change == "extra":
        receipt["artifacts"]["claim"] = receipt["artifacts"]["stdout"]
    else:
        (root / "other.txt").write_text("{}")
        receipt["artifacts"]["stdout"] = evaluation._file(root, "other.txt")
    receipt = evaluation._seal(
        {key: value for key, value in receipt.items() if key != "sha256"}
    )
    evaluation.persist_evaluation(root, "receipt.json", receipt)
    with pytest.raises(ValueError):
        evaluation.verify_evaluation_receipt(root=root, receipt_path="receipt.json")


def test_deeply_nested_native_output_is_preserved_as_failed_receipt(frozen):
    root, plan = frozen
    result = trace_agent_run(
        [sys.executable, "-c", "print('[' * 10000 + '0' + ']' * 10000)"],
        cwd=root,
        output_dir=root / "nested-run",
        run_id="nested-eval",
        agent="deterministic-fixture",
        permission_level="standard",
        metadata={"skill_evaluation_plan_sha256": plan["sha256"]},
    )
    assert result.returncode == 0
    receipt = evaluation.create_evaluation_receipt(
        root=root,
        plan_path="plan.json",
        agent_run="nested-run/agent_run_manifest.json",
    )
    assert receipt["summary"]["status"] == "failed"
    assert receipt["summary"]["checks"]["insufficient_evidence"] == 4
    assert "nesting" in receipt["observation_error"]
    evaluation.persist_evaluation(root, "receipt.json", receipt)
    assert (
        evaluation.verify_evaluation_receipt(root=root, receipt_path="receipt.json")[
            "verification"
        ]
        == "passed"
    )


@pytest.mark.parametrize("status", ["failed", "not_checked", "insufficient_evidence"])
def test_nonpassing_observations_are_persisted_and_verifiable(frozen, status):
    root, _ = frozen
    manifest = run_fixture(frozen)
    write_observations(
        manifest,
        lambda result: result["cases"][0]["checks"]["task"].update(status=status),
    )
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=manifest
    )
    assert receipt["summary"]["status"] == status
    evaluation.persist_evaluation(root, "receipt.json", receipt)
    result = evaluation.verify_evaluation_receipt(
        root=root, receipt_path="receipt.json"
    )
    assert result["verification"] == "passed"
    assert result["evaluation_status"] == status


def test_missing_cases_and_checks_keep_frozen_denominator(frozen):
    root, _ = frozen
    manifest = run_fixture(frozen)

    def omit(result):
        result["cases"].pop()
        del result["cases"][0]["checks"]["persistence"]

    write_observations(manifest, omit)
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=manifest
    )
    assert receipt["summary"]["case_count"] == 2
    assert receipt["summary"]["check_count"] == 4
    assert receipt["summary"]["checks"]["not_checked"] == 2
    assert receipt["summary"]["status"] == "not_checked"


@pytest.mark.parametrize(
    "change", ["duplicate", "unknown", "wrong_plan", "invalid_status"]
)
def test_invalid_observations_leave_failed_receipts(frozen, change):
    root, _ = frozen
    manifest = run_fixture(frozen)

    def corrupt(result):
        if change == "duplicate":
            result["cases"].append(result["cases"][0])
        elif change == "unknown":
            result["cases"][0]["id"] = "not-in-frozen-cohort"
        elif change == "wrong_plan":
            result["plan_sha256"] = "0" * 64
        else:
            result["cases"][0]["checks"]["task"]["status"] = "success"

    write_observations(manifest, corrupt)
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=manifest
    )
    assert receipt["summary"]["status"] == "failed"
    assert receipt["summary"]["checks"]["passed"] == 0
    assert receipt["observation_error"]
    evaluation.persist_evaluation(root, "receipt.json", receipt)
    assert (
        evaluation.verify_evaluation_receipt(root=root, receipt_path="receipt.json")[
            "verification"
        ]
        == "passed"
    )


def test_agent_failure_cannot_be_promoted_by_passing_grader_output(frozen):
    root, _ = frozen
    path = run_fixture(frozen)
    run = json.loads(path.read_text())
    run.update(status="fail", returncode=1)
    path.write_text(json.dumps(run))
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=path
    )
    assert receipt["summary"]["checks"]["passed"] == 4
    assert receipt["summary"]["status"] == "failed"


@pytest.mark.parametrize("change", ["unbound", "older_run", "planned", "missing_hash"])
def test_receipt_requires_bound_terminal_run_with_digests(frozen, change):
    root, _ = frozen
    path = run_fixture(frozen)
    run = json.loads(path.read_text())
    if change == "unbound":
        run["context"]["metadata"] = {}
    elif change == "older_run":
        run["timing"]["started_at"] = "2000-01-01T00:00:00Z"
    elif change == "planned":
        run.update(status="planned", returncode=None)
    else:
        del run["artifacts"]["stdout"]["sha256"]
    path.write_text(json.dumps(run))
    with pytest.raises(ValueError):
        evaluation.create_evaluation_receipt(
            root=root, plan_path="plan.json", agent_run=path
        )


def test_rehashed_receipt_cannot_inflate_observations(frozen):
    root, _ = frozen
    manifest = run_fixture(frozen)
    receipt = evaluation.create_evaluation_receipt(
        root=root, plan_path="plan.json", agent_run=manifest
    )
    receipt["summary"]["check_count"] = 100
    receipt = evaluation._seal(
        {key: value for key, value in receipt.items() if key != "sha256"}
    )
    evaluation.persist_evaluation(root, "receipt.json", receipt)
    with pytest.raises(ValueError, match="does not match"):
        evaluation.verify_evaluation_receipt(root=root, receipt_path="receipt.json")


def test_receipt_checksum_failure_is_actionable(frozen):
    root, plan = frozen
    plan["evaluator"]["model"] = "changed"
    (root / "plan.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="checksum"):
        evaluation._load_plan(root, "plan.json")


def test_path_escape_symlink_and_polluted_workspace_are_rejected(frozen, tmp_path):
    root, _ = frozen
    with pytest.raises(ValueError, match="declared root"):
        evaluation._file(root, "../outside.txt")
    outside = root.parent / (root.name + "-outside.txt")
    outside.write_text("must not read")
    try:
        (root / "escape").symlink_to(outside)
        with pytest.raises(ValueError, match="declared root"):
            evaluation._file(root, "escape")
        (root / "skill/link").symlink_to(root / "fixtures.json")
        with pytest.raises(ValueError, match="symlinks"):
            evaluation._load_plan(root, "plan.json")
    finally:
        outside.unlink()


def test_exclusive_publication_keeps_previous_receipt(frozen):
    root, plan = frozen

    def publish():
        try:
            evaluation.persist_evaluation(root, "race.json", plan)
            return "published"
        except FileExistsError:
            return "exists"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: publish(), range(2)))
    assert sorted(outcomes) == ["exists", "published"]
    assert json.loads((root / "race.json").read_text()) == plan
    assert not list(root.glob(".skill-evaluation-*"))


def test_cli_records_nonpassing_evaluation_and_reports_verification_separately(
    frozen, capsys
):
    root, _ = frozen
    path = run_fixture(frozen)
    write_observations(path, lambda result: result.update(cases=[]))
    assert (
        evaluation.main(
            [
                "--root",
                str(root),
                "record",
                "--plan",
                "plan.json",
                "--agent-run",
                str(path),
                "--output",
                "receipt.json",
            ]
        )
        == 1
    )
    output = json.loads(capsys.readouterr().out)
    assert output["verification"] == "passed"
    assert output["evaluation_status"] == "not_checked"
    assert evaluation.main(["--root", str(root), "verify", "receipt.json"]) == 0
    capsys.readouterr()
    (root / "receipt.json").write_text("[]")
    assert evaluation.main(["--root", str(root), "verify", "receipt.json"]) == 2
    assert json.loads(capsys.readouterr().out)["verification"] == "failed"


@pytest.mark.parametrize("data", ['{"cases":[],"cases":[]}', '{"value":NaN}', "[]"])
def test_json_contract_rejects_ambiguous_or_nonfinite_data(tmp_path, data):
    path = tmp_path / "invalid.json"
    path.write_text(data)
    with pytest.raises(ValueError):
        evaluation._read_json(path)


def test_fixture_contract_rejects_duplicate_cases_and_checks(frozen):
    root, _ = frozen
    fixtures = json.loads((root / "fixtures.json").read_text())
    duplicate = deepcopy(fixtures)
    duplicate["cases"].append(duplicate["cases"][0])
    with pytest.raises(ValueError, match="unique"):
        evaluation._cases(duplicate)
    fixtures["cases"][0]["checks"].append("task")
    with pytest.raises(ValueError, match="unique"):
        evaluation._cases(fixtures)
