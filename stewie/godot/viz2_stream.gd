extends RefCounted
# viz2_stream.gd — STEWIE viz2 pixel-stream: the Godot<->stream-server frame socket.
#
# A StreamPeerTCP CLIENT to 127.0.0.1:<stream_port> (the standalone FastAPI stream server's frame
# seam; the server accepts, Godot connects). Length-prefixed framing — a 4-byte BIG-ENDIAN unsigned
# length followed by that many payload bytes — matched byte-for-byte by stewie/stream/framing.py:
#   * OUTBOUND (Godot -> server): payload = raw JPEG bytes (one captured viewport frame).
#   * INBOUND  (server -> Godot): payload = UTF-8 JSON control {v, omega, dig, dump, sun_az, sun_el}.
#
# This is the SAME real-bytes-on-127.0.0.1 discipline as viz2_drive_client.gd's runtime seam; no mock.
# The viz2_root live-drive path (--live) still owns the conserved drive THROUGH the Viz2Runtime; this
# socket is only the browser<->render pixel/control relay layered on top (--stream).

var _peer: StreamPeerTCP
var _in := PackedByteArray()
var connected := false
var error_msg := ""


func connect_server(port: int, timeout_ms: int = 5000) -> bool:
	_peer = StreamPeerTCP.new()
	if _peer.connect_to_host("127.0.0.1", port) != OK:
		error_msg = "connect_to_host failed"
		return false
	var deadline := Time.get_ticks_msec() + timeout_ms
	while Time.get_ticks_msec() < deadline:
		_peer.poll()
		var st := _peer.get_status()
		if st == StreamPeerTCP.STATUS_CONNECTED:
			connected = true
			break
		if st == StreamPeerTCP.STATUS_ERROR:
			error_msg = "socket error during connect"
			return false
		OS.delay_msec(5)
	if not connected:
		error_msg = "connect timed out"
		return false
	_peer.set_no_delay(true)
	return true


# Send one length-prefixed frame (a captured JPEG). Returns false if the peer is gone (caller stops).
func send_frame(payload: PackedByteArray) -> bool:
	if _peer == null:
		return false
	_peer.poll()
	if _peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		connected = false
		return false
	var n := payload.size()
	var hdr := PackedByteArray()
	hdr.resize(4)
	hdr[0] = (n >> 24) & 0xff      # big-endian, explicit (no encode_u32 endian ambiguity)
	hdr[1] = (n >> 16) & 0xff
	hdr[2] = (n >> 8) & 0xff
	hdr[3] = n & 0xff
	if _peer.put_data(hdr) != OK:
		connected = false
		return false
	if _peer.put_data(payload) != OK:
		connected = false
		return false
	return true


# Drain every COMPLETE inbound control frame; returns an Array of parsed Dictionaries (may be empty).
func poll_input() -> Array:
	var out: Array = []
	if _peer == null:
		return out
	_peer.poll()
	if _peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		connected = false
		return out
	var avail := _peer.get_available_bytes()
	if avail > 0:
		var got := _peer.get_data(avail)
		if got[0] == OK:
			_in.append_array(got[1])
	while _in.size() >= 4:
		var n := (int(_in[0]) << 24) | (int(_in[1]) << 16) | (int(_in[2]) << 8) | int(_in[3])
		if _in.size() < 4 + n:
			break
		var payload := _in.slice(4, 4 + n)
		_in = _in.slice(4 + n)
		var j := JSON.new()
		if j.parse(payload.get_string_from_utf8()) == OK and typeof(j.data) == TYPE_DICTIONARY:
			out.append(j.data)
	return out


# Re-poll the link and refresh `connected` (named to avoid Object.is_connected). The stream loop
# reads the `connected` property directly; this is the explicit refresh helper.
func link_alive() -> bool:
	if _peer == null:
		return false
	_peer.poll()
	connected = _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED
	return connected


func close() -> void:
	if _peer != null:
		_peer.disconnect_from_host()
	connected = false
