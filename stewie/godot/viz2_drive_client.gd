extends RefCounted
# viz2_drive_client.gd — STEWIE viz2 Phase B3: the Godot->Viz2Runtime drive client
# (plan v4 §2b.3 transport + liveness).
#
# A StreamPeerTCP client that drives the rover THROUGH the runtime's conserved physics:
#   1. read the runtime's 0600 token file {port, token} (S-09 owner boundary);
#   2. connect to 127.0.0.1:<port> and present the token (the first frame is the handshake);
#   3. the server assigns the "drive" role (a client-supplied role is ignored);
#   4. send viz2_forward/back/left/right twist at ~15 Hz + a dig command;
#   5. read telemetry (pose / yaw / slip / entrapped + the generation counter), and cumulatively
#      ACK each generation AFTER its manifest has been applied (union-coverage discipline, §2b.4) so
#      the link heartbeat never trips the deadman while the render stays in coverage.
#
# This mirrors, in GDScript, the exact JSON-line wire protocol the Python test Client speaks against
# the same real socket (stewie/runtime/test_viz2_runtime.py) — no mock, real bytes on 127.0.0.1.

var _peer: StreamPeerTCP
var _buf := PackedByteArray()
var connected := false
var handshake_ok := false
var epoch := 0
var error_msg := ""

# latest telemetry (global metres; yaw rad)
var latest_pose := Vector2.ZERO
var latest_yaw := 0.0
var latest_generation := 0
var latest_keyframe := false
var latest_seq := -1
var slip := 0.0
var entrapped := false
var safe_stopped := false
var _have_pose := false


func connect_runtime(session_dir: String, connect_timeout_ms: int = 5000) -> bool:
	var token_path := session_dir.path_join("viz2_session.json")
	if not FileAccess.file_exists(token_path):
		error_msg = "token file absent: %s" % token_path
		return false
	var json := JSON.new()
	if json.parse(FileAccess.get_file_as_string(token_path)) != OK:
		error_msg = "token file not JSON: %s" % token_path
		return false
	var tok: Dictionary = json.data
	var port := int(tok.get("port", 0))
	var token := String(tok.get("token", ""))
	if port <= 0 or token == "":
		error_msg = "token file missing port/token"
		return false

	_peer = StreamPeerTCP.new()
	if _peer.connect_to_host("127.0.0.1", port) != OK:
		error_msg = "connect_to_host failed"
		return false
	var deadline := Time.get_ticks_msec() + connect_timeout_ms
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

	# handshake: present the token; the server assigns the role.
	_send({"token": token})
	var reply = _recv_line(connect_timeout_ms)   # Variant (Dictionary or null)
	if reply == null or not bool(reply.get("ok", false)):
		error_msg = "handshake refused: %s" % (str(reply) if reply != null else "no reply")
		return false
	handshake_ok = true
	epoch = int(reply.get("epoch", 0))
	return true


func send_twist(v: float, omega: float) -> void:
	_send({"cmd": "twist", "v": v, "omega": omega})


func send_dig() -> void:
	_send({"cmd": "dig"})


func send_dump() -> void:
	_send({"cmd": "dump"})


func ack(seq: int) -> void:
	if seq >= 0:
		_send({"cmd": "ack", "seq": seq})


# Read every available frame, updating the latest telemetry. Returns how many telemetry frames were
# seen. Does NOT ack — the caller acks AFTER applying the newest generation's manifest (§2b.4).
func poll_frames() -> int:
	if _peer == null:
		return 0
	_peer.poll()
	var avail := _peer.get_available_bytes()
	if avail > 0:
		var got := _peer.get_data(avail)
		if got[0] == OK:
			_buf.append_array(got[1])
	var count := 0
	while true:
		var nl := _buf.find(10)   # '\n'
		if nl < 0:
			break
		var line := _buf.slice(0, nl)
		_buf = _buf.slice(nl + 1)
		if line.size() == 0:
			continue
		var j := JSON.new()
		if j.parse(line.get_string_from_utf8()) != OK:
			continue
		var f = j.data
		if typeof(f) != TYPE_DICTIONARY:
			continue
		if f.has("seq"):
			latest_seq = int(f["seq"])
		var payload = f.get("payload", null)
		if typeof(payload) == TYPE_DICTIONARY and String(payload.get("type", "")) == "telemetry":
			count += 1
			latest_generation = int(payload.get("generation", latest_generation))
			latest_keyframe = bool(payload.get("keyframe", false))
			safe_stopped = bool(payload.get("safe_stop", false))
			var telem = payload.get("telem", {})
			if typeof(telem) == TYPE_DICTIONARY:
				if telem.has("pose_xy"):
					var p: Array = telem["pose_xy"]
					if p.size() == 2:
						latest_pose = Vector2(float(p[0]), float(p[1]))
						_have_pose = true
				latest_yaw = float(telem.get("yaw", latest_yaw))
				slip = float(telem.get("slip", slip))
				entrapped = bool(telem.get("entrapped", entrapped))
	return count


func have_pose() -> bool: return _have_pose


func close() -> void:
	if _peer != null:
		_peer.disconnect_from_host()
	connected = false


func _send(obj: Dictionary) -> void:
	if _peer == null:
		return
	_peer.poll()
	_peer.put_data((JSON.stringify(obj) + "\n").to_utf8_buffer())


func _recv_line(timeout_ms: int) -> Variant:
	var deadline := Time.get_ticks_msec() + timeout_ms
	while Time.get_ticks_msec() < deadline:
		_peer.poll()
		var avail := _peer.get_available_bytes()
		if avail > 0:
			var got := _peer.get_data(avail)
			if got[0] == OK:
				_buf.append_array(got[1])
		var nl := _buf.find(10)
		if nl >= 0:
			var line := _buf.slice(0, nl)
			_buf = _buf.slice(nl + 1)
			var j := JSON.new()
			if j.parse(line.get_string_from_utf8()) == OK:
				return j.data
			return null
		OS.delay_msec(5)
	return null
