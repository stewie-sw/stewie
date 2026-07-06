#!/usr/bin/env python3
"""STEWIE read-only ROS2 -> browser telemetry collector (RT-04 engine pane backend).

WHY THIS EXISTS (not the stock rosbridge_server): the ros2 stack runs `network_mode: host`, so a
stock rosbridge listens on the *host* namespace. artemis-web nginx is on the `stewie_default`
bridge, and this host DROPS container->host (INPUT) traffic, so nginx cannot reach a host-net
rosbridge; plain DDS also does not cross bridge<->host-net. This collector sits ON the bridge (nginx
reaches it container->container) and is fed real ROS2 messages by a host-net rclpy `feeder` that
PUSHES over a 127.0.0.1-published ingest port (host->published-port always works). No rover reconfig,
no firewall change. Stdlib-only WebSocket (this host also blocks container egress, so no pip).

READ-ONLY BY CONSTRUCTION: the collector never holds a ROS publisher and speaks only the *subscribe*
half of the rosbridge v2 protocol. Browser advertise / publish / advertise_service / call_service
(to anything but rosapi introspection) ops are refused -> a browser CANNOT command /cmd_vel,
/cmd/nav_goal, /cmd/safe or call any acting service. There is no code path from a WS client to the
ROS graph. Sole-egress / no-command-authority preserved.

Two listeners in one asyncio process:
  * WS  :9090  browser clients (via nginx /rosbridge). rosbridge v2 protocol (subscribe only).
  * TCP :9091  ingest from the host-net feeder (newline-delimited JSON), published to 127.0.0.1:9091.
"""
import asyncio
import base64
import hashlib
import json
import struct
import time

WS_PORT = 9090
INGEST_PORT = 9091
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_subs: dict[str, set] = {}          # topic -> set[Client]
_latest: dict[str, dict] = {}       # topic -> last msg dict (replayed on subscribe)
_types: dict[str, str] = {}         # topic -> ROS type string
_last_seen: dict[str, float] = {}
_clients: set = set()


# ---------- minimal RFC6455 WebSocket over asyncio streams ----------
def _encode_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    b0 = 0x80 | opcode                       # FIN + opcode (0x1 text, 0x8 close, 0xA pong)
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", b0, n)
    elif n < 65536:
        head = struct.pack("!BBH", b0, 126, n)
    else:
        head = struct.pack("!BBQ", b0, 127, n)
    return head + payload                    # server frames are NOT masked


class Client:
    def __init__(self, writer: asyncio.StreamWriter):
        self._w = writer
        self._lock = asyncio.Lock()
        self.topics: set[str] = set()

    async def send_text(self, text: str) -> None:
        async with self._lock:
            self._w.write(_encode_frame(text.encode("utf-8"), 0x1))
            await self._w.drain()

    async def send_close(self) -> None:
        try:
            self._w.write(_encode_frame(b"", 0x8))
            await self._w.drain()
        except Exception:
            pass


async def _read_http_handshake(reader: asyncio.StreamReader) -> dict:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(1024)
        if not chunk:
            raise ConnectionError("closed during handshake")
        data += chunk
        if len(data) > 16384:
            raise ConnectionError("handshake too large")
    headers = {}
    for line in data.split(b"\r\n")[1:]:
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.strip().lower().decode()] = v.strip().decode()
    return headers


async def _read_frame(reader: asyncio.StreamReader):
    """Return (opcode, payload_bytes). Reassembles fragments. Client frames are masked."""
    payload = b""
    opcode_final = None
    while True:
        b0, b1 = struct.unpack("!BB", await reader.readexactly(2))
        fin = b0 & 0x80
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", await reader.readexactly(2))
        elif length == 127:
            (length,) = struct.unpack("!Q", await reader.readexactly(8))
        mask = await reader.readexactly(4) if masked else b"\x00\x00\x00\x00"
        raw = await reader.readexactly(length)
        if masked:
            raw = bytes(raw[i] ^ mask[i % 4] for i in range(length))
        if opcode != 0x0:
            opcode_final = opcode
        payload += raw
        if fin:
            return opcode_final, payload


async def ws_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        headers = await _read_http_handshake(reader)
    except Exception:
        writer.close()
        return
    key = headers.get("sec-websocket-key")
    if not key or "websocket" not in headers.get("upgrade", "").lower():
        writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        return
    accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
    writer.write(("HTTP/1.1 101 Switching Protocols\r\n"
                  "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
    await writer.drain()

    client = Client(writer)
    _clients.add(client)
    try:
        while True:
            opcode, payload = await _read_frame(reader)
            if opcode == 0x8:                       # close
                break
            if opcode == 0x9:                       # ping -> pong
                writer.write(_encode_frame(payload, 0xA))
                await writer.drain()
                continue
            if opcode != 0x1:                       # only text ops carry rosbridge JSON
                continue
            try:
                m = json.loads(payload.decode("utf-8"))
            except Exception:
                continue
            await _handle_op(client, m)
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        _clients.discard(client)
        for t in list(client.topics):
            _subs.get(t, set()).discard(client)
        try:
            writer.close()
        except Exception:
            pass


async def _handle_op(client: "Client", m: dict) -> None:
    op = m.get("op")
    if op == "subscribe":
        topic = m.get("topic")
        if not topic:
            return
        _subs.setdefault(topic, set()).add(client)
        client.topics.add(topic)
        if topic in _latest:                        # immediate replay so the pane is not blank
            await client.send_text(json.dumps({"op": "publish", "topic": topic, "msg": _latest[topic]}))
    elif op == "unsubscribe":
        topic = m.get("topic")
        if topic:
            _subs.get(topic, set()).discard(client)
            client.topics.discard(topic)
    elif op == "call_service" and m.get("service") == "/rosapi/topics":
        names = sorted(_types.keys())
        await client.send_text(json.dumps({
            "op": "service_response", "service": "/rosapi/topics", "id": m.get("id"),
            "result": True, "values": {"topics": names, "types": [_types[n] for n in names]},
        }))
    elif op in ("advertise", "publish", "advertise_service", "call_service",
                "send_action_goal", "advertise_action"):
        # READ-ONLY: refuse every write / command / acting op.
        await client.send_text(json.dumps(
            {"op": "status", "level": "error", "id": m.get("id"),
             "msg": f"collector is read-only: {op} refused"}))
    # any other op (status, set_level, ...) is ignored


# ---------- ingest from the host-net feeder ----------
async def _broadcast(topic: str, msg: dict) -> None:
    frame = json.dumps({"op": "publish", "topic": topic, "msg": msg})
    for client in list(_subs.get(topic, ())):
        try:
            await client.send_text(frame)
        except Exception:
            _subs.get(topic, set()).discard(client)


async def ingest_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    print(f"[ingest] feeder connected: {peer}", flush=True)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                rec = json.loads(line)
            except Exception:
                continue
            topic = rec.get("topic")
            if not topic:
                continue
            msg = rec.get("msg", {})
            _latest[topic] = msg
            _types[topic] = rec.get("type", _types.get(topic, ""))
            _last_seen[topic] = time.time()
            await _broadcast(topic, msg)
    except Exception as e:
        print(f"[ingest] error: {e}", flush=True)
    finally:
        print("[ingest] feeder disconnected", flush=True)
        try:
            writer.close()
        except Exception:
            pass


async def main() -> None:
    ingest = await asyncio.start_server(ingest_handler, "0.0.0.0", INGEST_PORT)
    print(f"[collector] ingest TCP on :{INGEST_PORT}", flush=True)
    ws = await asyncio.start_server(ws_handler, "0.0.0.0", WS_PORT)
    print(f"[collector] rosbridge-protocol WS on :{WS_PORT} (READ-ONLY)", flush=True)
    async with ws, ingest:
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
