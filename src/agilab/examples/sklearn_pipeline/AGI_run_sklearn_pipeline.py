import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI, RunRequest
from agi_env import AgiEnv


APP = "sklearn_pipeline_project"
PYTHON_ONLY_MODE = AGI.PYTHON_MODE


def agilab_apps_path() -> Path:
    marker = Path.home() / ".local/share/agilab/.agilab-path"
    if not marker.is_file():
        raise SystemExit(
            "AGILAB is not initialized. Run the AGILAB installer or "
            "`agilab first-proof --json` before this example."
        )
    return Path(marker.read_text(encoding="utf-8").strip()) / "apps" / "builtin"


async def main():
    app_env = AgiEnv(apps_path=agilab_apps_path(), app=APP, verbose=1)
    request = RunRequest(
        params={
            "data_out": "sklearn_pipeline/evidence",
            "sample_count": 240,
            "test_size": 0.25,
            "regularization_c": 1.0,
            "seed": 2026,
            "reset_target": True,
        },
        data_out="sklearn_pipeline/evidence",
        mode=PYTHON_ONLY_MODE,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
    )
    res = await AGI.run(app_env, request=request)
    print(res)
    return res


if __name__ == "__main__":
    asyncio.run(main())
