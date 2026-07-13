"""Length-prefixed framing for the viz2 stream localhost seam (server <-> Godot).

Both directions of the Godot<->server TCP seam carry the SAME 4-byte big-endian unsigned
length prefix followed by that many payload bytes:

  * Godot -> server : payload = raw JPEG bytes (one captured viewport frame).
  * server -> Godot : payload = UTF-8 JSON input command ({v, omega, dig, dump, sun_az, sun_el}).

Big-endian (network order) is used explicitly on BOTH ends (Python ``struct.pack(">I", n)`` and
the manual byte pack in ``viz2_stream.gd``) so there is no endianness ambiguity across the seam.

``FrameDecoder`` is the pure, sans-I/O parser (feed bytes, get complete frames) used by the unit
tests and by any polling consumer; ``read_frame`` is the asyncio-stream reader the server relay
uses. No mock: the same bytes flow on 127.0.0.1 in the live path.
"""
from __future__ import annotations

import asyncio
import struct

HEADER_LEN = 4
#: hard ceiling on a single frame payload (defensive; a 1280x720 JPEG is well under 1 MB).
MAX_FRAME_BYTES = 16 * 1024 * 1024


def pack_frame(payload: bytes) -> bytes:
    """Prefix ``payload`` with its 4-byte big-endian length. Raises on an over-ceiling payload."""
    n = len(payload)
    if n > MAX_FRAME_BYTES:
        raise ValueError(f"frame payload {n} bytes exceeds MAX_FRAME_BYTES {MAX_FRAME_BYTES}")
    return struct.pack(">I", n) + payload


class FrameDecoder:
    """Incremental, sans-I/O length-prefixed frame parser.

    Feed it arbitrary byte chunks (as they arrive off a socket); it returns the list of COMPLETE
    frame payloads unwrapped so far, retaining any partial tail for the next ``feed``.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf.extend(data)
        out: list[bytes] = []
        while len(self._buf) >= HEADER_LEN:
            n = struct.unpack(">I", self._buf[:HEADER_LEN])[0]
            if n > MAX_FRAME_BYTES:
                raise ValueError(f"declared frame length {n} exceeds MAX_FRAME_BYTES")
            if len(self._buf) < HEADER_LEN + n:
                break
            out.append(bytes(self._buf[HEADER_LEN:HEADER_LEN + n]))
            del self._buf[:HEADER_LEN + n]
        return out

    @property
    def pending(self) -> int:
        """Bytes buffered but not yet a complete frame (for introspection/tests)."""
        return len(self._buf)


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    """Read exactly one length-prefixed frame from an asyncio stream.

    Raises ``asyncio.IncompleteReadError`` on EOF (the caller treats that as a closed peer).
    """
    hdr = await reader.readexactly(HEADER_LEN)
    n = struct.unpack(">I", hdr)[0]
    if n > MAX_FRAME_BYTES:
        raise ValueError(f"declared frame length {n} exceeds MAX_FRAME_BYTES")
    return await reader.readexactly(n)
