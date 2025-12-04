import os
from contextlib import suppress
from pathlib import Path
import pandas as pd
from agi_env import AgiEnv


def _share_base() -> Path:
    """Return the manager's share base, preferring AgiEnv when available."""

    env = None
    try:
        env = AgiEnv.current()
    except Exception:
        env = None

    if env is None:
        with suppress(Exception):
            env = AgiEnv(app="sb3_trainer")

    if env is not None:
        base = getattr(env, "agi_share_dir_abs", None) or getattr(env, "agi_share_dir", None)
        if base:
            base_path = Path(str(base)).expanduser()
            if base_path.is_absolute():
                return base_path
            return (Path(getattr(env, "home_abs", Path.home())).expanduser() / base_path).expanduser()

    raw = os.environ.get("AGI_SHARE_DIR") or os.environ.get("AGI_CLUSTER_SHARE")
    if raw:
        base_path = Path(raw).expanduser()
        if base_path.is_absolute():
            return base_path
        return (Path.home() / base_path).expanduser()

    return (Path.home() / "clustershare").expanduser()

# Source directory produced by network_sim
DATA_ROOT = _share_base() / "network_sim" / "pipeline"
SUMMARY_PARQUET = DATA_ROOT / "link_level_summary.parquet"
SUMMARY_CSV = DATA_ROOT / "link_level_summary.csv"

files = sorted(DATA_ROOT.glob("*.parquet"))
frames = []
for f in files:
    try:
        df = pd.read_parquet(f)
        df["source_file"] = f.name
        frames.append(df)
    except Exception:
        continue

if frames:
    df_all = pd.concat(frames, ignore_index=True)
else:
    df_all = pd.DataFrame()

# Ensure required columns
if "bearer_type" not in df_all.columns:
    df_all["bearer_type"] = "unknown"
if "make_before_break" not in df_all.columns:
    df_all["make_before_break"] = True

SUMMARY_PARQUET.parent.mkdir(parents=True, exist_ok=True)
df_all.to_parquet(SUMMARY_PARQUET, index=False)
df_all.to_csv(SUMMARY_CSV, index=False)
print(f"Wrote summary to {SUMMARY_PARQUET} and {SUMMARY_CSV}")
