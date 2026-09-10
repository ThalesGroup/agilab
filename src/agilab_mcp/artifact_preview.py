"""Bounded PNG decoding for manifest-linked MCP previews (optional Pillow)."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any
import warnings

PREVIEW_SCHEMA = "agilab.mcp.artifact_preview.v1"
MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_SOURCE_PIXELS = 4_000_000
MAX_SOURCE_DIMENSION = 4096
MAX_PREVIEW_DIMENSION = 1280


@dataclass(frozen=True)
class ArtifactPreview:
    """An internal result type; manifest dictionaries cannot opt into images."""

    evidence: dict[str, Any]
    png: bytes


def render_png(source: bytes) -> tuple[bytes, tuple[int, int], tuple[int, int]]:
    """Decode a single PNG and return a thumbnail containing only pixel data."""
    try:
        from PIL import Image, ImageFile
    except ImportError as exc:
        raise ValueError(
            'Artifact previews require Pillow. Install "agilab[preview]" '
            "in the environment running agilab-mcp."
        ) from exc
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ValueError(
            "Pillow permits truncated images; disable LOAD_TRUNCATED_IMAGES in the MCP environment."
        )
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        return _render_png(source, Image)


def _render_png(
    source: bytes, Image: Any
) -> tuple[bytes, tuple[int, int], tuple[int, int]]:
    if len(source) > MAX_SOURCE_BYTES:
        raise ValueError("PNG artifact exceeds the 5 MiB source limit.")
    try:
        with Image.open(BytesIO(source), formats=("PNG",)) as image:
            width, height = image.size
            if (
                width < 1
                or height < 1
                or max(width, height) > MAX_SOURCE_DIMENSION
                or width * height > MAX_SOURCE_PIXELS
            ):
                raise ValueError(
                    "PNG artifact exceeds the 4096-side or 4-million-pixel limit."
                )
            if getattr(image, "n_frames", 1) != 1 or getattr(
                image, "is_animated", False
            ):
                raise ValueError(
                    "Animated PNG artifacts are not supported; export one frame."
                )
            image.verify()
        # verify() checks the container; load() must also decode the raster.
        with Image.open(BytesIO(source), formats=("PNG",)) as image:
            image.load()
            pixels = image.convert("RGBA")
        try:
            pixels.thumbnail((MAX_PREVIEW_DIMENSION, MAX_PREVIEW_DIMENSION))
            # Rebuild from pixels, so text, EXIF, profiles and trailing data are
            # never sent as part of the MCP image. No source file is rewritten.
            with Image.frombytes("RGBA", pixels.size, pixels.tobytes()) as clean:
                output = BytesIO()
                clean.save(output, format="PNG")
                preview = output.getvalue()
                if len(preview) > MAX_PREVIEW_BYTES:
                    raise ValueError(
                        "PNG preview exceeds 2 MiB; export a smaller source image."
                    )
                return preview, (width, height), clean.size
        finally:
            pixels.close()
    except (
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(
            "Artifact is not a valid, bounded PNG; export a fresh PNG."
        ) from exc
