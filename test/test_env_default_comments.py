from __future__ import annotations

from pathlib import Path

from agilab.cluster import cluster_flight_validation as cfv
from agilab.environment.env_default_comments import (
    CLUSTER_ENV_DEFAULT_COMMENT_LINES,
    USER_ENV_DEFAULT_COMMENT_LINES,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ENV = REPO_ROOT / "src/agilab/core/agi-env/src/agi_env/resources/.agilab/.env"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _missing_lines(text: str, lines: tuple[str, ...]) -> list[str]:
    return [line for line in lines if line not in text]


def test_packaged_env_template_lists_user_default_comments() -> None:
    template = _text(TEMPLATE_ENV)

    assert _missing_lines(template, USER_ENV_DEFAULT_COMMENT_LINES) == []
    assert "# OPENAI_API_KEY=\"\"" in template
    assert "OPENAI_API_KEY=sk-" not in template


def test_main_installers_append_same_default_comments() -> None:
    for installer in (REPO_ROOT / "install.sh", REPO_ROOT / "install.ps1"):
        text = _text(installer)

        assert _missing_lines(text, USER_ENV_DEFAULT_COMMENT_LINES) == []

    assert "append_default_env_comments \"$HOME/.agilab/.env\"" in _text(REPO_ROOT / "install.sh")
    assert "Add-DefaultEnvComments -EnvFile" in _text(REPO_ROOT / "install.ps1")


def test_enduser_installers_append_defaults_from_template() -> None:
    shell_text = _text(REPO_ROOT / "tools/install_enduser.sh")
    ps_text = _text(REPO_ROOT / "tools/install_enduser.ps1")

    assert "append_default_env_comments \"${ENV_FILE}\"" in shell_text
    assert "src/agilab/core/agi-env/src/agi_env/resources/.agilab/.env" in shell_text
    assert "Add-DefaultEnvComments -EnvFile $EnvFile -TemplateFile $TemplateEnvFile" in ps_text
    assert "agi_env/resources/.agilab/.env" in ps_text


def test_cluster_remote_env_writer_appends_missing_cluster_comment_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    env_file = tmp_path / ".agilab/.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        'AGI_CLUSTER_ENABLED=0\nAGILAB_CLUSTER_SHARE_BACKEND="nfs"\n',
        encoding="utf-8",
    )
    plan = cfv.ValidationPlan(
        app=cfv.DEFAULT_APP,
        apps_path=tmp_path / "apps",
        scheduler="192.168.1.10",
        workers={"192.168.1.11": 1},
        worker_specs=(cfv.WorkerSpec(host="192.168.1.11"),),
        remote_user="agi",
        scheduler_ssh_port=22,
        cluster_share_backend="sshfs",
        remote_cluster_share_premounted=False,
        local_share_setting="localshare",
        local_cluster_share_setting="clustershare/user",
        remote_cluster_share_setting="clustershare",
        local_dataset_dir=tmp_path / "localshare/flight_cluster_validation/dataset/csv",
        dataset_rel_to_home=Path("localshare/flight_cluster_validation/dataset/csv"),
        output_rel=Path("flight_cluster_validation/dataframe_cluster_validation"),
        aircraft=(60,),
        rows_per_aircraft=1,
        modes_enabled=15,
    )

    exec(compile(cfv._remote_env_update_script(plan), "<remote-env-update>", "exec"), {})

    written = env_file.read_text(encoding="utf-8")
    assert "AGI_CLUSTER_ENABLED='1'" in written
    assert "AGI_CLUSTER_ENABLED=0" not in written
    assert 'AGILAB_CLUSTER_SHARE_BACKEND="nfs"' in written
    assert written.count("AGILAB_CLUSTER_SHARE_BACKEND") == 1
    assert '# AGILAB_SCHEDULER_SSH_PORT="22"' in written
    assert '# AGILAB_CLUSTER_SSH_HOST_KEY_POLICY="strict"' in written
    assert '# AGI_CLUSTER_SHARE="clustershare/<user>"' not in written

    for line in CLUSTER_ENV_DEFAULT_COMMENT_LINES:
        key = line.lstrip("#").split("=", 1)[0].strip()
        if key in {"IS_SOURCE_ENV", "IS_WORKER_ENV", "AGI_CLUSTER_ENABLED", "AGI_CLUSTER_SHARE"}:
            continue
        if key == "AGILAB_CLUSTER_SHARE_BACKEND":
            continue
        assert line in written
