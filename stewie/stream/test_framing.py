"""[REQ:] viz2 stream framing — length-prefixed encode/decode round-trip + relay-boundary parsing.

Gate on exit code: pytest stewie/stream/test_framing.py

Covers the WS<->socket relay framing the server and Godot both speak (big-endian 4-byte length +
payload): a single round-trip, multi-frame in one chunk, a frame split across chunk boundaries, and
the empty-payload edge. Real bytes only; no mock transport.
"""
from __future__ import annotations

import struct

import pytest

from stewie.stream.framing import FrameDecoder, MAX_FRAME_BYTES, pack_frame


def test_pack_frame_header_is_big_endian_length():
    payload = b"hello-stewie"
    framed = pack_frame(payload)
    assert framed[:4] == struct.pack(">I", len(payload))
    assert framed[4:] == payload


def test_round_trip_single_frame():
    payload = b'{"v": 1.0, "omega": 0.1}'
    dec = FrameDecoder()
    out = dec.feed(pack_frame(payload))
    assert out == [payload]
    assert dec.pending == 0


def test_multiple_frames_in_one_chunk():
    a, b, c = b"a", b"bb", b"ccc"
    chunk = pack_frame(a) + pack_frame(b) + pack_frame(c)
    dec = FrameDecoder()
    assert dec.feed(chunk) == [a, b, c]


def test_frame_split_across_chunk_boundaries():
    payload = b"\xff\xd8\xff\xe0jpeg-bytes-\x00\x01\x02"  # JPEG-magic-lookalike binary
    framed = pack_frame(payload)
    dec = FrameDecoder()
    # split mid-header and mid-payload
    assert dec.feed(framed[:2]) == []          # partial header
    assert dec.feed(framed[2:6]) == []          # rest of header + a little payload
    out = dec.feed(framed[6:])                  # remainder completes the frame
    assert out == [payload]
    assert dec.pending == 0


def test_empty_payload_round_trips():
    dec = FrameDecoder()
    assert dec.feed(pack_frame(b"")) == [b""]


def test_pack_frame_rejects_oversized_payload():
    with pytest.raises(ValueError):
        pack_frame(b"x" * (MAX_FRAME_BYTES + 1))


def test_decoder_rejects_oversized_declared_length():
    bogus = struct.pack(">I", MAX_FRAME_BYTES + 1) + b"partial"
    dec = FrameDecoder()
    with pytest.raises(ValueError):
        dec.feed(bogus)
