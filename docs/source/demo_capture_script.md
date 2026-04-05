# AGILAB Demo Capture Script

Use this as a short capture plan for a GIF or MP4.

Concrete workflow:

```bash
tools/capture_demo_workflow.sh --name agilab-flight --duration 45 --trim 30
```

This wrapper:

- launches an interactive macOS screen recording with `screencapture`
- stores the raw `.mov` under `artifacts/demo_media/<name>/raw/`
- exports a shareable `.mp4` and `.gif` under `artifacts/demo_media/<name>/edited/`

Self-generated fallback when you do not want to rely on interactive capture:

```bash
uv --preview-features extra-build-dependencies run --with imageio --with imageio-ffmpeg \
  python tools/build_demo_explainer.py
```

This produces:

- `artifacts/demo_media/agilab_explainer.gif`
- `artifacts/demo_media/agilab_explainer.mp4`
- `artifacts/demo_media/agilab_explainer_poster.png`

If you already have a raw recording and only want the export step:

```bash
uv --preview-features extra-build-dependencies run --with imageio-ffmpeg \
  python tools/export_demo_media.py \
  --input artifacts/demo_media/agilab-flight/raw/example.mov \
  --mp4 artifacts/demo_media/agilab-flight/edited/agilab-flight.mp4 \
  --gif artifacts/demo_media/agilab-flight/edited/agilab-flight.gif \
  --duration 30
```

## Goal

Show, in under 60 seconds, that AGILAB removes orchestration work around an AI/ML workflow.

## Suggested sequence

1. Open the AGILAB home screen.
2. In `PROJECT`, select `src/agilab/apps/builtin/flight_project`.
3. Briefly show the app settings or source area.
4. Move to `ORCHESTRATE`.
5. Trigger the install/distribute/run flow.
6. Show that the workflow is packaged and executed without hand-written shell glue.
7. Move to `PIPELINE`.
8. Show the generated or replayable steps.
9. Move to `ANALYSIS`.
10. Open a built-in page over the produced artifacts.

## Narration line

`AGILAB gives the same app one control path from UI to workers to analysis, instead of making the team hand-wire environments, scripts, and validation every time.`

## Recording tips

- Record at 1440p or 1080p, then crop tightly.
- Keep the cursor slow and deliberate.
- Avoid typing during capture unless the command is central to the story.
- Use one app only. The point is clarity, not breadth.
- End on a visible result, not on logs.
- If the capture includes dead time at the beginning or end, trim it during export rather than re-recording immediately.
