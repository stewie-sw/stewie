"""[REQ:] viz2 stream JPEG frame encode/decode round-trip (the browser/e2e decode path).

Gate on exit code: pytest stewie/stream/test_jpeg_roundtrip.py

Godot emits JPEG frames (Image.save_jpg_to_buffer); the browser and the e2e client decode them. This
gates the DECODE side against a REAL source image — the checked-in hillshade preview of the real 1 m
Haworth SfS bundle — proving a lunar-terrain frame survives a JPEG round-trip as a non-empty,
non-black raster. No synthetic image: the source is a real on-disk artifact.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_PREVIEW = _REPO / "samples" / "lunar_dem" / "haworth_sfs_2km_1m" / "preview_hillshade.png"


def _decode_jpeg(buf: bytes) -> np.ndarray:
    """Decode JPEG bytes to an HxWx3 uint8 array (the exact path the e2e client + browser use)."""
    img = Image.open(io.BytesIO(buf)).convert("RGB")
    return np.asarray(img)


def test_real_terrain_frame_survives_jpeg_round_trip():
    assert _PREVIEW.is_file(), f"missing real preview image {_PREVIEW}"
    src = Image.open(_PREVIEW).convert("RGB")
    src_arr = np.asarray(src)

    # encode to JPEG bytes in memory (mirrors Godot's save_jpg_to_buffer output)
    enc = io.BytesIO()
    src.save(enc, format="JPEG", quality=72)
    jpg = enc.getvalue()
    assert jpg[:2] == b"\xff\xd8", "JPEG SOI marker (FFD8) missing"

    dec = _decode_jpeg(jpg)
    assert dec.shape == src_arr.shape, "decoded frame shape differs from source"
    assert dec.size > 0, "decoded frame is empty"
    # a real hillshade is NOT a black frame (the e2e liveness check uses the same non-black assert)
    assert float(dec.mean()) > 5.0, "decoded terrain frame is (near) black"
    # lossy but faithful: mean brightness within a few levels of the source
    assert abs(float(dec.mean()) - float(src_arr.mean())) < 8.0


def test_two_distinct_frames_have_a_measurable_pixel_diff():
    """The e2e 'frames changed under drive' assertion in miniature: two different crops of the real
    preview produce a mean-abs pixel diff above the liveness threshold after a JPEG round-trip."""
    src = Image.open(_PREVIEW).convert("RGB")
    w, h = src.size
    a = np.asarray(src.crop((0, 0, w // 2, h)).resize((256, 256)))
    b = np.asarray(src.crop((w // 2, 0, w, h)).resize((256, 256)))

    def rt(arr: np.ndarray) -> np.ndarray:
        enc = io.BytesIO()
        Image.fromarray(arr).save(enc, format="JPEG", quality=72)
        return _decode_jpeg(enc.getvalue())

    diff = float(np.abs(rt(a).astype(np.int16) - rt(b).astype(np.int16)).mean())
    assert diff > 1.0, f"distinct terrain frames should differ, mean-abs diff={diff:.3f}"
