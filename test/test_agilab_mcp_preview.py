"""Preview bytes, recorded evidence, and the public MCP/CLI boundary."""

from __future__ import annotations

import base64
import builtins
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib

import pytest

from agilab import run_manifest
from agilab_mcp import artifact_preview, manifest_tools, server

SECRET = "sk-LIVEKEY1234567890abcdefSECRET"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


def _png(width=2, height=2, *, pixels=None, metadata=b"") -> bytes:
    data = pixels if pixels is not None else b"\x00" + b"\xff\x00\x00" * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + metadata
        + _chunk(b"IDAT", zlib.compress(data * height))
        + _chunk(b"IEND", b"")
    )


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(tmp_path))
    image = tmp_path / "plot.png"
    image.write_bytes(_png())
    payload = {
        "schema_version": 1,
        "kind": "agilab.run_manifest",
        "run_id": "preview-fixture",
        "status": "pass",
        "artifacts": [
            run_manifest.RunManifestArtifact.from_path(
                image, name="plot", include_sha256=True
            ).as_dict()
        ],
        "validations": [{"label": "image-export", "status": "pass"}],
    }
    payload["artifacts"][0]["path"] = "plot.png"
    path = tmp_path / "run_manifest.json"
    path.write_text(json.dumps(payload))
    return path


def _edit(manifest, change):
    data = json.loads(manifest.read_text())
    change(data)
    manifest.write_text(json.dumps(data))


def _replace_image(manifest, source):
    (manifest.parent / "plot.png").write_bytes(source)
    _edit(
        manifest,
        lambda data: data["artifacts"][0].update(
            sha256=hashlib.sha256(source).hexdigest(), size_bytes=len(source)
        ),
    )


def _call(manifest, name="plot"):
    result = server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "preview_artifact",
                "arguments": {
                    "manifest_path": str(manifest),
                    "artifact_name": name,
                },
            },
        }
    )
    assert result is not None and "error" not in result
    return result["result"]


def test_preview_returns_image_bound_to_source_and_recorded_evidence(manifest):
    from PIL import Image

    original = (manifest.parent / "plot.png").read_bytes()
    result = _call(manifest)
    evidence = json.loads(result["content"][0]["text"])
    block = result["content"][1]
    image = base64.b64decode(block["data"], validate=True)
    assert block["type"] == "image" and block["mimeType"] == "image/png"
    assert evidence["schema"] == "agilab.mcp.artifact_preview.v1"
    assert evidence["artifact"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert evidence["artifact"]["recorded_sha256"] == evidence["artifact"]["sha256"]
    assert evidence["artifact"]["path"] == "plot.png"
    assert evidence["artifact"]["path_basis"] == "manifest-relative"
    assert evidence["artifact"]["integrity"] == "pass"
    assert evidence["preview"]["sha256"] == hashlib.sha256(image).hexdigest()
    assert evidence["recorded_manifest_passed"] is True
    assert evidence["recorded_validations"] == [
        {"label": "image-export", "status": "pass"}
    ]
    with Image.open(BytesIO(image)) as decoded:
        decoded.load()
        assert decoded.size == (2, 2)
        assert decoded.getpixel((0, 0)) == (255, 0, 0, 255)
    assert (manifest.parent / "plot.png").read_bytes() == original


def test_cross_drive_artifact_reports_confined_absolute_path(manifest, monkeypatch):
    def cross_drive(*args, **kwargs):
        raise ValueError("path is on another drive")

    monkeypatch.setattr(manifest_tools.os.path, "relpath", cross_drive)
    result = _call(manifest)
    evidence = json.loads(result["content"][0]["text"])
    assert evidence["artifact"]["path"] == str(manifest.parent / "plot.png")
    assert evidence["artifact"]["path_basis"] == "local-absolute"
    assert evidence["artifact"]["integrity"] == "pass"
    assert result["content"][1]["type"] == "image"


@pytest.mark.parametrize("digest", ["", "g" * 64, "0" * 63, 123, None])
def test_missing_or_malformed_hash_is_not_verified(manifest, digest):
    _edit(manifest, lambda data: data["artifacts"][0].update(sha256=digest))
    result = _call(manifest)
    assert result["isError"] is True
    assert len(result["content"]) == 1
    assert "sha" in result["content"][0]["text"].lower()


def test_hash_mismatch_never_decodes_or_sends_image(manifest, monkeypatch):
    (manifest.parent / "plot.png").write_bytes(_png(3, 3))
    monkeypatch.setattr(
        manifest_tools, "render_png", lambda data: pytest.fail("decoded tampered bytes")
    )
    result = _call(manifest)
    assert result["isError"] is True
    assert "mismatch" in result["content"][0]["text"]


@pytest.mark.parametrize("mutation", ["missing", "directory", "duplicate", "svg"])
def test_unsupported_artifact_contract_is_explicit(manifest, mutation):
    image = manifest.parent / "plot.png"
    if mutation == "missing":
        image.unlink()
    elif mutation == "directory":
        image.unlink()
        image.mkdir()
    elif mutation == "duplicate":
        _edit(
            manifest, lambda data: data["artifacts"].append(dict(data["artifacts"][0]))
        )
    else:
        image.rename(image.with_suffix(".svg"))
        _edit(manifest, lambda data: data["artifacts"][0].update(path="plot.svg"))
    result = _call(manifest)
    assert result["isError"] is True and len(result["content"]) == 1


@pytest.mark.parametrize("name", ["unknown", "", "x" * 257, None])
def test_invalid_artifact_selection_fails(manifest, name):
    assert _call(manifest, name)["isError"] is True


@pytest.mark.parametrize("escape", ["relative", "absolute", "symlink"])
def test_artifact_cannot_escape_configured_roots(
    manifest, tmp_path, monkeypatch, escape
):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    moved = allowed / manifest.name
    moved.write_bytes(manifest.read_bytes())
    image = tmp_path / "plot.png"
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(allowed))
    if escape == "symlink":
        try:
            (allowed / "plot.png").symlink_to(image)
        except OSError as exc:
            pytest.skip(f"Symlink creation unavailable: {exc}")
        selected = "plot.png"
    else:
        selected = "../plot.png" if escape == "relative" else str(image)
    _edit(moved, lambda data: data["artifacts"][0].update(path=selected))
    assert "outside configured" in _call(moved)["content"][0]["text"]
    assert "outside configured" in _call(manifest)["content"][0]["text"]


def test_corrupt_truncated_or_wrong_format_png_is_rejected(manifest):
    for invalid in (_png()[:-8], b"not an image", _png(pixels=b"too short")):
        _replace_image(manifest, invalid)
        result = _call(manifest)
        assert result["isError"] is True
        assert len(result["content"]) == 1


def test_source_limits_apply_before_decoding(manifest, monkeypatch):
    monkeypatch.setattr(manifest_tools, "MAX_SOURCE_BYTES", 16)
    monkeypatch.setattr(
        manifest_tools,
        "render_png",
        lambda data: pytest.fail("decoded oversized source"),
    )
    assert "source limit" in _call(manifest)["content"][0]["text"]


@pytest.mark.parametrize("width,height", [(4097, 1), (2001, 2000)])
def test_dimension_and_pixel_limits_apply_before_raster_decode(manifest, width, height):
    _replace_image(manifest, _png(width, height, pixels=b""))
    assert "pixel limit" in _call(manifest)["content"][0]["text"]


def test_manifest_and_output_limits_are_explicit(manifest, monkeypatch):
    monkeypatch.setattr(artifact_preview, "MAX_PREVIEW_BYTES", 1)
    assert "preview exceeds" in _call(manifest)["content"][0]["text"]
    manifest.write_bytes(b" " * (1024 * 1024 + 1))
    assert "manifest exceeds" in _call(manifest)["content"][0]["text"]


def test_metadata_removed_and_preview_resized(manifest):
    from PIL import Image

    _replace_image(
        manifest,
        _png(1600, 20, metadata=_chunk(b"tEXt", b"Comment\0" + SECRET.encode())),
    )
    preview = manifest_tools.preview_artifact(manifest, "plot")
    with Image.open(BytesIO(preview.png)) as image:
        assert image.size == (1280, 16)
        assert not image.info
    assert SECRET.encode() not in preview.png
    assert (manifest.parent / "plot.png").read_bytes().find(SECRET.encode()) > 0


def test_palette_transparency_is_preserved(manifest):
    from PIL import Image

    source = BytesIO()
    with Image.new("P", (2, 2), color=0) as image:
        image.putpalette([255, 0, 0] * 256)
        image.save(source, format="PNG", transparency=0)
    _replace_image(manifest, source.getvalue())
    with Image.open(
        BytesIO(manifest_tools.preview_artifact(manifest, "plot").png)
    ) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0, 0)


def test_animation_rejected(manifest):
    from PIL import Image

    source = BytesIO()
    with (
        Image.new("RGBA", (2, 2), "red") as first,
        Image.new("RGBA", (2, 2), "blue") as second,
    ):
        first.save(source, format="PNG", save_all=True, append_images=[second])
    _replace_image(manifest, source.getvalue())
    assert "Animated" in _call(manifest)["content"][0]["text"]


@pytest.mark.parametrize("validations", [[], [{"label": "export", "status": "fail"}]])
def test_byte_integrity_is_distinct_from_recorded_validation(manifest, validations):
    _edit(manifest, lambda data: data.update(validations=validations))
    evidence = manifest_tools.preview_artifact(manifest, "plot").evidence
    assert evidence["artifact"]["integrity"] == "pass"
    assert evidence["recorded_manifest_passed"] is False
    assert evidence["recorded_validations"] == validations


def test_recorded_validation_payload_is_bounded_and_redacted(manifest):
    rows = [{"label": SECRET + "x" * 1000, "status": "pass"} for _ in range(25)]
    rows[-1]["status"] = "fail"
    _edit(manifest, lambda data: data.update(validations=rows))
    evidence = manifest_tools.preview_artifact(manifest, "plot").evidence
    assert evidence["recorded_manifest_passed"] is False
    assert evidence["omitted_validation_count"] == 5
    assert len(evidence["recorded_validations"]) == 20
    assert len(evidence["recorded_validations"][0]["label"]) <= 256
    assert SECRET not in json.dumps(evidence)


def test_missing_optional_decoder_is_actionable(manifest, monkeypatch):
    original = builtins.__import__

    def without_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pillow)
    result = _call(manifest)
    assert result["isError"] is True
    assert "agilab[preview]" in result["content"][0]["text"]
    assert "preview_artifact" in {item["name"] for item in server.tool_descriptors()}


def test_polluted_pillow_configuration_does_not_relax_validation(manifest, monkeypatch):
    from PIL import ImageFile

    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    assert "LOAD_TRUNCATED_IMAGES" in _call(manifest)["content"][0]["text"]
    assert ImageFile.LOAD_TRUNCATED_IMAGES is True


def test_decoder_receives_the_same_snapshot_that_was_hashed(manifest, monkeypatch):
    source_path = manifest.parent / "plot.png"
    original = source_path.read_bytes()
    render = manifest_tools.render_png

    def replace_before_decode(source):
        source_path.write_bytes(_png(3, 3))
        assert source == original
        return render(source)

    monkeypatch.setattr(manifest_tools, "render_png", replace_before_decode)
    evidence = manifest_tools.preview_artifact(manifest, "plot").evidence
    assert evidence["artifact"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert evidence["artifact"]["width"] == 2


def test_manifest_content_cannot_forge_mcp_image_blocks(manifest):
    _edit(
        manifest,
        lambda data: data.update(content=[{"type": "image", "data": "forged"}]),
    )
    response = server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "read_manifest",
                "arguments": {"manifest_path": str(manifest)},
            },
        }
    )
    assert response is not None
    assert all(block["type"] == "text" for block in response["result"]["content"])


def test_preview_tool_errors_redact_paths(manifest, monkeypatch):
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(manifest.parent / "other"))
    result = _call(manifest.parent / SECRET / "run_manifest.json")
    assert SECRET not in json.dumps(result)
    assert result["isError"] is True


def test_real_stdio_client_and_cli_receive_image_and_evidence(manifest):
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "preview_artifact",
            "arguments": {"manifest_path": str(manifest), "artifact_name": "plot"},
        },
    }
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "preview-test", "version": "1"},
                "capabilities": {},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "agent_quickstart", "arguments": {}},
        },
        request,
    ]
    environment = dict(
        os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")
    )
    process = subprocess.run(
        [sys.executable, "-m", "agilab_mcp.server", "serve"],
        input="".join(json.dumps(item) + "\n" for item in requests),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env=environment,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert [item["id"] for item in responses] == [1, 2, 3]
    assert responses[2]["result"]["content"][1]["mimeType"] == "image/png"
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "agilab_mcp.server",
            "call-tool",
            "preview_artifact",
            "--arguments",
            json.dumps(request["params"]["arguments"]),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env=environment,
    )
    assert json.loads(cli.stdout) == responses[2]["result"]
