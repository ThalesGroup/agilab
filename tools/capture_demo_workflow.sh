#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  tools/capture_demo_workflow.sh [--name demo-name] [--duration 45] [--start 0] [--trim 35] [--crop x:y:w:h]

What it does:
  1. Opens an interactive macOS screen recording using screencapture.
  2. Saves a raw .mov under artifacts/demo_media/<name>/raw/.
  3. Exports a shareable MP4 and GIF using tools/export_demo_media.py through uv.

Examples:
  tools/capture_demo_workflow.sh --name agilab-flight --duration 45
  tools/capture_demo_workflow.sh --name agilab-flight --duration 45 --trim 30 --crop 140:120:1600:900
EOF
  exit 0
fi

NAME="agilab-demo"
DURATION="45"
START="0"
TRIM=""
CROP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      NAME="$2"
      shift 2
      ;;
    --duration)
      DURATION="$2"
      shift 2
      ;;
    --start)
      START="$2"
      shift 2
      ;;
    --trim)
      TRIM="$2"
      shift 2
      ;;
    --crop)
      CROP="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$ROOT/artifacts/demo_media/$NAME"
RAW_DIR="$OUT_DIR/raw"
EDIT_DIR="$OUT_DIR/edited"
mkdir -p "$RAW_DIR" "$EDIT_DIR"

RAW_FILE="$RAW_DIR/${STAMP}.mov"
MP4_FILE="$EDIT_DIR/${NAME}.mp4"
GIF_FILE="$EDIT_DIR/${NAME}.gif"

echo "Interactive capture is starting."
echo "Select the AGILAB window or region, then record the flow."
echo "Raw recording: $RAW_FILE"

screencapture -i -U -Jvideo -k -v -V "$DURATION" "$RAW_FILE"

if [[ ! -f "$RAW_FILE" ]]; then
  echo "No recording was created." >&2
  exit 1
fi

CMD=(
  uv --preview-features extra-build-dependencies run --with imageio-ffmpeg
  python "$ROOT/tools/export_demo_media.py"
  --input "$RAW_FILE"
  --mp4 "$MP4_FILE"
  --gif "$GIF_FILE"
  --start "$START"
)

if [[ -n "$TRIM" ]]; then
  CMD+=(--duration "$TRIM")
fi

if [[ -n "$CROP" ]]; then
  CMD+=(--crop "$CROP")
fi

echo "Exporting MP4 and GIF..."
"${CMD[@]}"

echo "Done."
echo "MP4: $MP4_FILE"
echo "GIF: $GIF_FILE"
