from pathlib import Path
import pandas as pd

# Source directory produced by network_sim
DATA_ROOT = Path("~/clustershare/network_sim/pipeline").expanduser()
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