"""[REQ:] Guarded REAL end-to-end pixel-stream test (opt-in; needs the host GPU + Godot + xvfb).

SKIPPED by default so it never hangs the fast suite. Enable with STEWIE_STREAM_E2E=1:

    STEWIE_STREAM_E2E=1 .venv/bin/python -m pytest stewie/stream/test_e2e_stream.py -q

It drives the full loop (browser WS -> server -> Godot --live --stream on the RTX 3090 -> Viz2Runtime
-> JPEG frames back) and asserts >=5 non-black terrain frames that CHANGE under a forward drive. The
same check is runnable standalone (timeout-wrapped) via ``python -m stewie.stream.e2e_check``.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("STEWIE_STREAM_E2E") != "1",
    reason="real GPU/Godot end-to-end; set STEWIE_STREAM_E2E=1 to run")


def test_stream_e2e_real_haworth():
    from stewie.stream.e2e_check import main
    assert main() == 0, "viz2 stream end-to-end FAILED (see printed server log path)"
