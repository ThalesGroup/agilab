from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "agilab" / "kubernetes_job.py"
SPEC = importlib.util.spec_from_file_location("agilab.kubernetes_job", MODULE_PATH)
assert SPEC and SPEC.loader
kubernetes_job = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = kubernetes_job
SPEC.loader.exec_module(kubernetes_job)


def test_kubernetes_job_manifest_includes_runner_contract_and_artifact_pvc() -> None:
    manifest = kubernetes_job.build_kubernetes_job_manifest(
        kubernetes_job.KubernetesJobConfig(
            app="flight_telemetry_project",
            image="ghcr.io/thalesgroup/agilab:2026.05.25",
            namespace="agilab",
            command=("python", "-m", "agilab.lab_run", "first-proof", "--json"),
            env=(("OPENAI_MODEL", "gpt-4.1-mini"),),
            pvc_name="agilab-artifacts",
            service_account="agilab-runner",
        )
    )

    assert manifest["apiVersion"] == "batch/v1"
    assert manifest["kind"] == "Job"
    assert manifest["metadata"]["name"] == "agilab-flight-telemetry-project"
    assert manifest["metadata"]["namespace"] == "agilab"
    assert manifest["metadata"]["labels"]["agilab.thalesgroup.com/app"] == "flight_telemetry_project"
    assert manifest["metadata"]["annotations"]["agilab.thalesgroup.com/schema"] == kubernetes_job.SCHEMA

    pod_spec = manifest["spec"]["template"]["spec"]
    assert pod_spec["restartPolicy"] == "Never"
    assert pod_spec["serviceAccountName"] == "agilab-runner"
    assert pod_spec["volumes"] == [
        {
            "name": "agilab-artifacts",
            "persistentVolumeClaim": {"claimName": "agilab-artifacts"},
        }
    ]
    container = pod_spec["containers"][0]
    assert container["image"] == "ghcr.io/thalesgroup/agilab:2026.05.25"
    assert container["command"] == ["python"]
    assert container["args"] == ["-m", "agilab.lab_run", "first-proof", "--json"]
    assert container["volumeMounts"] == [{"name": "agilab-artifacts", "mountPath": "/agilab/export"}]
    env = {entry["name"]: entry["value"] for entry in container["env"]}
    assert env["AGILAB_ACTIVE_APP"] == "flight_telemetry_project"
    assert env["AGILAB_EXECUTION_BACKEND"] == "kubernetes-job"
    assert env["OPENAI_MODEL"] == "gpt-4.1-mini"


def test_kubernetes_job_names_and_labels_are_kubernetes_safe() -> None:
    name = kubernetes_job.kubernetes_name("My Demo_Project With VERY long " * 5)
    label = kubernetes_job.kubernetes_label_value("My Demo_Project With VERY long " * 5)

    assert len(name) <= 63
    assert name.startswith("agilab-my-demo-project")
    assert name[-1].isalnum()
    assert len(label) <= 63
    assert label[-1].isalnum()
    assert kubernetes_job.kubernetes_name("!!!") == "agilab-job"
    assert kubernetes_job.kubernetes_label_value("!!!") == "unknown"


def test_kubernetes_job_renderers_are_deterministic() -> None:
    manifest = kubernetes_job.build_kubernetes_job_manifest(
        kubernetes_job.KubernetesJobConfig(app="demo_project", image="agilab:local")
    )

    yaml_text = kubernetes_job.render_manifest(manifest, output_format="yaml")
    json_text = kubernetes_job.render_manifest(manifest, output_format="json")

    assert 'apiVersion: "batch/v1"' in yaml_text
    assert 'kind: "Job"' in yaml_text
    assert '- name: "AGILAB_ACTIVE_APP"' in yaml_text
    assert json.loads(json_text)["metadata"]["name"] == "agilab-demo-project"
    assert kubernetes_job.kubectl_apply_command("/tmp/job.yaml") == "kubectl apply -f /tmp/job.yaml"


def test_kubernetes_job_cli_writes_manifest_and_accepts_command_after_separator(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "job.yaml"

    assert (
        kubernetes_job.main(
            [
                "--app",
                "demo_project",
                "--image",
                "agilab:local",
                "--env",
                "OPENAI_MODEL=gpt-4.1-mini",
                "--output",
                str(output),
                "--",
                "python",
                "-m",
                "agilab.lab_run",
                "first-proof",
                "--json",
            ]
        )
        == 0
    )

    assert capsys.readouterr().out.strip() == str(output)
    text = output.read_text(encoding="utf-8")
    assert 'name: "agilab-demo-project"' in text
    assert 'value: "gpt-4.1-mini"' in text
    assert '- "first-proof"' in text


def test_kubernetes_job_cli_reports_bad_environment_assignment() -> None:
    with pytest.raises(SystemExit) as exc_info:
        kubernetes_job.main(["--app", "demo", "--image", "agilab:local", "--env", "bad"])

    assert exc_info.value.code == 2


def test_kubernetes_job_module_entrypoint_reads_process_argv(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "python -m agilab.kubernetes_job",
            "--app",
            "demo_project",
            "--image",
            "agilab:local",
            "--format",
            "json",
        ],
    )

    assert kubernetes_job.main() == 0

    manifest = json.loads(capsys.readouterr().out)
    assert manifest["metadata"]["name"] == "agilab-demo-project"
