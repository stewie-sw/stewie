extends Node3D
# P6 OBSERVED-MAP producer, render half: a NADIR DEPTH capture of the conserved terrain.
#
# The passive front-stereo egress (sidecar.gd --cameras -> obs_map_producer SGBM) is the
# forward-looking perception tier: real, but sparse (~1-2% coverage/station) and occlusion-
# limited (a grazing 0.15 m eye cannot see the floor of a pit it dug in front of it). This
# scene is the complementary DENSE tier: a downward depth sensor (mast/inspection pass) over
# the worksite. For a 2.5-D heightfield a nadir view has NO self-occlusion, so it recovers the
# observed elevation of every cell it covers.
#
# It is a REAL render, not a heightfield read-back: the authoritative heightmap.rf32 is built
# into a displaced ArrayMesh (the SAME field->Godot mapping terrain.gd uses -- gx=x0+col*cell,
# gy=height, gz=z0+row*cell), and an orthographic camera measures the per-fragment DEPTH
# (camera-to-surface distance) of that geometry. The observed elevation is reconstructed from
# the measured depth: wy = cam_height - depth. The mesh is built from the MUTATED scene the
# authority wrote, so a dig the rover performed shows up in what the sensor observes -- that is
# the closed perception loop.
#
# Camera framing is chosen so image pixel [row,col] maps EXACTLY to authority cell [row,col]
# (viewport = field WxH, ortho extent = field extent, look straight down with +X->right,
# +Z->down). The depth is encoded to an 8-bit grayscale over a metadata-declared [d_lo,d_hi]
# range; Godot stores the framebuffer sRGB-encoded, so the numpy decoder inverts sRGB before
# mapping back to metric depth (dart/observed_map.py). A round-trip of the UNMUTATED scene
# (observed == truth within the 8-bit quantum) validates the whole chain.
#
# CLI (after '--'):  --scene <dir>  [--out <png>]  [--manifest <json>]  [--pad-m <f>]
#
# CC0-1.0 (see ../../LICENSE).

var _scene_dir := ""
var _out_path := "res://out/depth_nadir.png"
var _manifest_path := ""
var _pad_m := 0.05                 # depth-range padding beyond the terrain min/max (m)

var _W := 0
var _H := 0
var _cell := 0.0
var _x0 := 0.0
var _z0 := 0.0
var _cam_h := 0.0
var _d_lo := 0.0
var _d_hi := 0.0

const DEPTH_SHADER := "res://observed_depth.gdshader"


func _ready() -> void:
	_parse_args()
	if _scene_dir == "":
		push_error("depth_nadir: --scene <dir> is required")
		get_tree().quit(2); return
	var heights := _load_scene()
	if heights.is_empty():
		get_tree().quit(3); return
	_build_terrain_mesh(heights)
	_setup_env()
	_setup_nadir_camera()
	await _render_and_save()
	get_tree().quit(0)


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	var i := 0
	while i < args.size():
		match String(args[i]):
			"--scene":
				i += 1; _scene_dir = String(args[i])
			"--out":
				i += 1; _out_path = _abs_out(String(args[i]))
			"--manifest":
				i += 1; _manifest_path = _abs_out(String(args[i]))
			"--pad-m":
				i += 1; _pad_m = float(args[i])
		i += 1
	if _manifest_path == "":
		_manifest_path = _out_path.get_basename() + ".json"


func _abs_out(p: String) -> String:
	if p.is_absolute_path() or p.begins_with("res://") or p.begins_with("user://"):
		return p
	return "res://out/" + p


# Read metadata.json (grid + world bounds) and heightmap.rf32 (row-major C float32 LE).
func _load_scene() -> PackedFloat32Array:
	var meta_txt := FileAccess.get_file_as_string(_scene_dir + "/metadata.json")
	if meta_txt == "":
		push_error("depth_nadir: cannot read %s/metadata.json" % _scene_dir)
		return PackedFloat32Array()
	var meta = JSON.parse_string(meta_txt)
	if typeof(meta) != TYPE_DICTIONARY:
		push_error("depth_nadir: metadata.json did not parse")
		return PackedFloat32Array()
	var grid: Dictionary = meta.get("grid", {})
	_W = int(grid.get("width", 0))
	_H = int(grid.get("height", 0))
	_cell = float(grid.get("cell_m", 0.0))
	var wb: Dictionary = meta.get("world_bounds_m", {})
	_x0 = float(wb.get("x0", 0.0))
	_z0 = float(wb.get("y0", 0.0))
	if _W <= 0 or _H <= 0 or _cell <= 0.0:
		push_error("depth_nadir: bad grid %dx%d cell=%f" % [_W, _H, _cell])
		return PackedFloat32Array()
	var f := FileAccess.open(_scene_dir + "/heightmap.rf32", FileAccess.READ)
	if f == null:
		push_error("depth_nadir: cannot open heightmap.rf32")
		return PackedFloat32Array()
	var floats := f.get_buffer(f.get_length()).to_float32_array()
	if floats.size() != _W * _H:
		push_error("depth_nadir: heightmap %d floats != %dx%d" % [floats.size(), _W, _H])
		return PackedFloat32Array()
	return floats


# One vertex per authority cell CENTER, displaced to (x0+(col+.5)*cell, height, z0+(row+.5)*cell).
func _build_terrain_mesh(heights: PackedFloat32Array) -> void:
	var verts := PackedVector3Array(); verts.resize(_W * _H)
	var hmin := INF
	var hmax := -INF
	for r in range(_H):
		for c in range(_W):
			var h := heights[r * _W + c]
			verts[r * _W + c] = Vector3(_x0 + (c + 0.5) * _cell, h, _z0 + (r + 0.5) * _cell)
			hmin = minf(hmin, h); hmax = maxf(hmax, h)
	var idx := PackedInt32Array()
	for r in range(_H - 1):
		for c in range(_W - 1):
			var a := r * _W + c
			var b := r * _W + c + 1
			var cc := (r + 1) * _W + c
			var d := (r + 1) * _W + c + 1
			idx.append_array([a, cc, b, b, cc, d])
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_INDEX] = idx
	var am := ArrayMesh.new()
	am.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var mi := MeshInstance3D.new()
	mi.mesh = am

	# Camera sits above the highest point; depth = cam_h - world_y spans the terrain relief.
	_cam_h = hmax + maxf(_pad_m, 0.5)
	_d_lo = _cam_h - (hmax + _pad_m)     # smallest depth (nearest surface = highest terrain)
	_d_hi = _cam_h - (hmin - _pad_m)     # largest depth  (farthest surface = lowest terrain)

	var sm := ShaderMaterial.new()
	sm.shader = load(DEPTH_SHADER)
	sm.set_shader_parameter("cam_height", _cam_h)
	sm.set_shader_parameter("d_lo", _d_lo)
	sm.set_shader_parameter("d_hi", _d_hi)
	mi.material_override = sm
	add_child(mi)


func _setup_env() -> void:
	var we := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0, 0, 0)              # depth==d_hi sentinel (decoded as "no surface")
	e.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	e.ambient_light_energy = 0.0
	e.ssil_enabled = false
	e.sdfgi_enabled = false
	e.glow_enabled = false
	e.ssao_enabled = false
	e.tonemap_mode = Environment.TONE_MAPPER_LINEAR  # identity in [0,1]; no filmic curve on the encoded depth
	e.tonemap_exposure = 1.0
	we.environment = e
	add_child(we)


# Nadir ORTHOGRAPHIC camera framed so pixel[row,col] == cell[row,col] (see header + dart/observed_map.py).
func _setup_nadir_camera() -> void:
	get_window().size = Vector2i(_W, _H)
	var cam := Camera3D.new()
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	cam.keep_aspect = Camera3D.KEEP_HEIGHT
	cam.size = _H * _cell                            # vertical extent = z-span; aspect W/H -> horiz = W*cell
	cam.near = 0.001
	cam.far = _cam_h + 1.0
	var cx := _x0 + _W * _cell * 0.5
	var cz := _z0 + _H * _cell * 0.5
	# Basis: +X_cam = world +X, +Y_cam = world -Z, -Z_cam (look dir) = world -Y (straight down).
	var basis := Basis(Vector3(1, 0, 0), Vector3(0, 0, -1), Vector3(0, 1, 0))
	cam.transform = Transform3D(basis, Vector3(cx, _cam_h, cz))
	cam.current = true
	add_child(cam)


func _render_and_save() -> void:
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(_out_path)
	if err != OK:
		push_error("depth_nadir: save_png failed %d for %s" % [err, _out_path])
		return
	var man := {
		"scene": _scene_dir,
		"width": _W, "height": _H, "cell_m": _cell, "x0": _x0, "y0": _z0,
		"cam_height_m": _cam_h, "d_lo_m": _d_lo, "d_hi_m": _d_hi,
		"encoding": "grayscale 8-bit, sRGB-stored; t=(depth-d_lo)/(d_hi-d_lo); depth=cam_height-world_y",
		"note": "REAL nadir ortho render of the displaced terrain mesh; pixel[row,col]==cell[row,col].",
	}
	var mf := FileAccess.open(_manifest_path, FileAccess.WRITE)
	mf.store_string(JSON.stringify(man, "  "))
	mf.close()
	print("depth_nadir: wrote ", ProjectSettings.globalize_path(_out_path),
		" (%dx%d) cam_h=%.3f d=[%.3f,%.3f] manifest=%s" % [
			_W, _H, _cam_h, _d_lo, _d_hi, ProjectSettings.globalize_path(_manifest_path)])
