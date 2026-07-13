extends Node3D
# viz2_terrain_window.gd — STEWIE viz2 Phase B3: the LIVE moving-window terrain node
# (plan v4 §2b.4 patch manifests + §2b.5 render-geometry contract, NB-1/NB-2).
#
# Owns ONE PlaneMesh sized to the WorkSite streaming window's world footprint, textured with
# viz2_window.gdshader (a fine-scale copy of the far-field vertex-displace mechanism). On each
# physics generation it applies the runtime's patch manifest crops into the live field Images
# IN PLACE (Image.blit_rect + ImageTexture.update, no realloc), so the vertex shader displaces the
# newly carved geometry — the rover's rut/trench carves into the terrain live. This is the render
# consumer that mirrors, in GDScript, the runtime's Python apply_manifest() bbox/field/dtype contract.
#
# Coordinate contract (plan §2b.5, the base<->fine<->window<->mesh mapping):
#   * The runtime's manifest carries window_world_origin (ox, oy) [global metres of fine cell (0,0)],
#     fine_cell_m, bbox_rc [r0,c0,r1,c1], shape, and per-field {file,dtype,shape,digest}.
#   * Field arrays are ROW-MAJOR: Image pixel (x=col, y=row) = field[row][col] — the SAME convention
#     the frozen state_fields.gd loader bakes (Image.create_from_data + row-major .rf32/.r8), so this
#     window registers identically to the proven far-field context plane.
#   * The window mesh spans [window_world_origin, +side_m]^2 in the Godot world (X = global x,
#     Z = global y, Y = elevation); a recenter keyframe repositions it to the new origin.
#
# The frozen loader (state_fields.gd) is used read-only for context seeding by viz2_root; this node
# instantiates NO frozen seam.

const WindowShader := preload("res://viz2_window.gdshader")
const DiffShader := preload("res://viz2_diff.gdshader")   # E2: the signed cut/berm difference drape

# Hard cap on per-side mesh subdivisions (one vertex per fine cell up to this). 600^2 (2 cm window)
# = 360k verts is inside the RTX 3090 envelope (plan §2b.5.4); 240^2 (5 cm) is the B3 default.
const MAX_SUBDIV := 640

var _mi: MeshInstance3D
var _mat: ShaderMaterial
var _mat_diff: ShaderMaterial   # E2: swapped in for _mat when the diff drape is toggled on
var _diff_mode := false
var _img_height: Image      # FORMAT_RF, absolute elevation (m)
var _img_state: Image       # FORMAT_R8, label 0..4
var _img_disturbance: Image # FORMAT_RF, [0,1]
var _img_diff: Image        # FORMAT_RF, signed h_now - h_virgin (m) — E2
var _tex_height: ImageTexture
var _tex_state: ImageTexture
var _tex_disturbance: ImageTexture
var _tex_diff: ImageTexture

var _shape := Vector2i(0, 0)          # (W, H) in fine cells
var _fine_cell_m := 0.05
var _window_origin := Vector2.ZERO    # (ox, oy) global metres of fine cell (0,0)
var _initialized := false
var _aabb_set := false
var applied_generation := 0
var error_msg := ""


# Apply one generation manifest at ``manifest_path``. The first applied manifest MUST be a keyframe
# (full window) — it sizes the Images, builds the mesh, and positions it. Later manifests blit their
# bbox crop in place; a keyframe whose origin moved (recenter) repositions the mesh and reloads whole.
# Returns true on success. Mirrors the Python apply_manifest() contract (digest not re-checked here —
# the runtime writes manifest.json LAST as the atomic commit marker; a present manifest => complete).
func apply_manifest_file(manifest_path: String) -> bool:
	if not FileAccess.file_exists(manifest_path):
		error_msg = "manifest not found: %s" % manifest_path
		return false
	var txt := FileAccess.get_file_as_string(manifest_path)
	var json := JSON.new()
	if json.parse(txt) != OK:
		error_msg = "manifest JSON parse error: %s" % json.get_error_message()
		return false
	var m: Dictionary = json.data
	var gen := int(m.get("generation", 0))
	var keyframe := bool(m.get("keyframe", false))
	var bbox: Array = m.get("bbox_rc", [])
	if bbox.size() != 4:
		error_msg = "manifest missing bbox_rc"
		return false
	var gdir := manifest_path.get_base_dir()
	var wwo: Array = m.get("window_world_origin", [])
	var new_origin := _window_origin
	if wwo.size() == 2:
		new_origin = Vector2(float(wwo[0]), float(wwo[1]))

	if not _initialized:
		if not keyframe:
			# Pre-keyframe delta: cannot size the window yet. Skip (the client applies the connect
			# keyframe first); never fabricate a window from a partial crop.
			return false
		var shp: Array = m.get("shape", [])
		if shp.size() != 2:
			error_msg = "keyframe missing shape"
			return false
		_shape = Vector2i(int(shp[1]), int(shp[0]))   # (W, H)
		_fine_cell_m = float(m.get("fine_cell_m", 0.05))
		_window_origin = new_origin
		_build(new_origin)
		_initialized = true

	# Recenter: a keyframe whose origin moved => reposition the mesh (textures reload whole below).
	if keyframe and new_origin != _window_origin:
		_window_origin = new_origin
		_reposition(new_origin)

	var r0 := int(bbox[0]); var c0 := int(bbox[1]); var r1 := int(bbox[2]); var c1 := int(bbox[3])
	var fields: Dictionary = m.get("fields", {})
	_apply_field(fields, "height", gdir, _img_height, _tex_height, c0, r0, c1 - c0, r1 - r0, true)
	_apply_field(fields, "state_label", gdir, _img_state, _tex_state, c0, r0, c1 - c0, r1 - r0, false)
	_apply_field(fields, "disturbance", gdir, _img_disturbance, _tex_disturbance, c0, r0, c1 - c0, r1 - r0, true)
	_apply_field(fields, "diff", gdir, _img_diff, _tex_diff, c0, r0, c1 - c0, r1 - r0, true)   # E2
	# The heights are displaced in the VERTEX SHADER, which does NOT update the mesh AABB — Godot would
	# frustum-cull the (flat, Y=0) mesh while the real geometry sits at absolute elevation. Give the
	# MeshInstance a custom AABB that spans the live height range so it is never wrongly culled.
	if keyframe or not _aabb_set:
		_update_custom_aabb()
	applied_generation = gen
	return true


func _apply_field(fields: Dictionary, name: String, gdir: String, dst: Image, tex: ImageTexture,
		c0: int, r0: int, w: int, h: int, is_float: bool) -> void:
	if not fields.has(name) or dst == null or w <= 0 or h <= 0:
		return
	var fmeta: Dictionary = fields[name]
	var fpath := gdir.path_join(String(fmeta.get("file", "")))
	if not FileAccess.file_exists(fpath):
		return
	var raw := FileAccess.get_file_as_bytes(fpath)
	var fmt := Image.FORMAT_RF if is_float else Image.FORMAT_R8
	var need := w * h * (4 if is_float else 1)
	if raw.size() < need:
		return
	# avoid a full PackedByteArray copy in the common exact-size case (council/Lena: crop file is exactly need)
	var crop := Image.create_from_data(w, h, false, fmt, raw if raw.size() == need else raw.slice(0, need))
	dst.blit_rect(crop, Rect2i(0, 0, w, h), Vector2i(c0, r0))   # absolute-value crop, idempotent
	tex.update(dst)                                             # in-place GPU update, no realloc


func _build(origin: Vector2) -> void:
	var W := _shape.x
	var H := _shape.y
	# Live field Images sized to the whole window (blitted per generation). RF = 32-bit float R
	# (matches the .rf32 LE float bytes on x86); R8 = the raw label byte (sampled as byte/255).
	_img_height = Image.create(W, H, false, Image.FORMAT_RF)
	_img_state = Image.create(W, H, false, Image.FORMAT_R8)
	_img_disturbance = Image.create(W, H, false, Image.FORMAT_RF)
	_img_diff = Image.create(W, H, false, Image.FORMAT_RF)       # E2: signed diff drape field
	_tex_height = ImageTexture.create_from_image(_img_height)
	_tex_state = ImageTexture.create_from_image(_img_state)
	_tex_disturbance = ImageTexture.create_from_image(_img_disturbance)
	_tex_diff = ImageTexture.create_from_image(_img_diff)

	var side_m := float(W) * _fine_cell_m
	var pm := PlaneMesh.new()
	pm.size = Vector2(side_m, float(H) * _fine_cell_m)
	pm.subdivide_width = mini(W - 1, MAX_SUBDIV)      # one vertex per fine cell up to the cap
	pm.subdivide_depth = mini(H - 1, MAX_SUBDIV)

	_mat = ShaderMaterial.new()
	_mat.shader = WindowShader
	_mat.set_shader_parameter("height_tex", _tex_height)
	_mat.set_shader_parameter("state_tex", _tex_state)
	_mat.set_shader_parameter("disturbance_tex", _tex_disturbance)
	_mat.set_shader_parameter("lod_step_m", _fine_cell_m)

	# E2: the diff-drape material — same vertex displacement from height_tex, diverging falsecolor of
	# diff_tex. Swapped in by set_diff_mode(); binds the SAME live textures so toggling is instant.
	_mat_diff = ShaderMaterial.new()
	_mat_diff.shader = DiffShader
	_mat_diff.set_shader_parameter("height_tex", _tex_height)
	_mat_diff.set_shader_parameter("diff_tex", _tex_diff)
	_mat_diff.set_shader_parameter("lod_step_m", _fine_cell_m)

	_mi = MeshInstance3D.new()
	_mi.name = "Viz2Window"
	_mi.mesh = pm
	_mi.material_override = _mat_diff if _diff_mode else _mat
	_reposition(origin)
	add_child(_mi)


# Give the shader-displaced mesh a custom AABB spanning its live absolute-height range (+ margin),
# so Godot's frustum culler keeps it when the camera views the elevated geometry (the mesh's own AABB
# stays flat at Y=0 because the displacement is vertex-shader-only).
func _update_custom_aabb() -> void:
	if _mi == null or _img_height == null:
		return
	var hmin := INF
	var hmax := -INF
	var stepx := maxi(1, _shape.x / 48)
	var stepy := maxi(1, _shape.y / 48)
	for r in range(0, _shape.y, stepy):
		for c in range(0, _shape.x, stepx):
			var h := _img_height.get_pixel(c, r).r
			hmin = minf(hmin, h)
			hmax = maxf(hmax, h)
	if not is_finite(hmin) or not is_finite(hmax):
		return
	var side_x := float(_shape.x) * _fine_cell_m
	var side_z := float(_shape.y) * _fine_cell_m
	var m := 1.0   # height margin (m) — covers the coarse-sample miss + window_lift + a dug trench
	# Local frame: PlaneMesh centered at origin (X,Z in [-side/2, side/2]); vertices displaced to
	# absolute Y in the shader, so the local AABB Y spans [hmin, hmax].
	_mi.custom_aabb = AABB(Vector3(-0.5 * side_x, hmin - m, -0.5 * side_z),
		Vector3(side_x, (hmax - hmin) + 2.0 * m, side_z))
	_aabb_set = true


func _reposition(origin: Vector2) -> void:
	if _mi == null:
		return
	# PlaneMesh is centered at its origin; place the center at the window's mid-point so local
	# UV (0..1) maps linearly to fine cell (0..W/H) — the base<->fine<->window<->mesh contract.
	var side_x := float(_shape.x) * _fine_cell_m
	var side_z := float(_shape.y) * _fine_cell_m
	_mi.position = Vector3(origin.x + 0.5 * side_x, 0.0, origin.y + 0.5 * side_z)


# The live window height at a global (x, z) — used by viz2_root to seat the rover on the carved
# surface. Bilinear over the fine window; falls back to NAN outside the window footprint.
func height_at_world(x: float, z: float) -> float:
	if not _initialized or _img_height == null:
		return NAN
	var fc := (x - _window_origin.x) / _fine_cell_m
	var fr := (z - _window_origin.y) / _fine_cell_m
	if fc < 0.0 or fr < 0.0 or fc > float(_shape.x - 1) or fr > float(_shape.y - 1):
		return NAN
	var c0 := int(floor(fc)); var r0 := int(floor(fr))
	var c1 := mini(c0 + 1, _shape.x - 1); var r1 := mini(r0 + 1, _shape.y - 1)
	var tx := fc - c0; var ty := fr - r0
	var h00 := _img_height.get_pixel(c0, r0).r; var h10 := _img_height.get_pixel(c1, r0).r
	var h01 := _img_height.get_pixel(c0, r1).r; var h11 := _img_height.get_pixel(c1, r1).r
	return lerp(lerp(h00, h10, tx), lerp(h01, h11, tx), ty)


# E2: toggle the signed cut/berm difference drape on the live window mesh. When ON, the diverging
# falsecolor viz2_diff.gdshader replaces the lit window shader (same displaced geometry, recolored by
# diff = h_now - h_virgin). Safe to call before the window is built — the choice is honored in _build.
func set_diff_mode(enabled: bool) -> void:
	_diff_mode = enabled
	if _mi != null and _mat != null and _mat_diff != null:
		_mi.material_override = _mat_diff if enabled else _mat

func diff_mode() -> bool: return _diff_mode

# Analysis overlay on the fine window (mirror of the far-context): 0 = off, 1 = slope heatmap, 2 = topo.
func set_analysis_mode(mode: int) -> void:
	if _mat != null:
		_mat.set_shader_parameter("analysis_mode", mode)

# The live window's ShaderMaterial, so viz2_root can set the MONOLITH topo uniforms on it too (C1b:
# the topo overlay is continuous across the fine window + the far context). Null before _build.
func topo_material() -> ShaderMaterial:
	return _mat

# Diagnostic: global AABB of the displaced window mesh + the live height/diff texture ranges.
func debug_stats() -> String:
	if _mi == null or _img_height == null:
		return "window not built"
	var aabb := _mi.get_aabb()
	var gpos := _mi.global_position
	var hmin := INF; var hmax := -INF; var dmin := INF; var dmax := -INF
	for r in range(0, _shape.y, maxi(1, _shape.y / 32)):
		for c in range(0, _shape.x, maxi(1, _shape.x / 32)):
			var h := _img_height.get_pixel(c, r).r
			hmin = minf(hmin, h); hmax = maxf(hmax, h)
			var d := _img_diff.get_pixel(c, r).r
			dmin = minf(dmin, d); dmax = maxf(dmax, d)
	return "mesh gpos=%s local_aabb.pos.y=%.2f size=%s | height_tex=[%.2f,%.2f] diff_tex=[%.4f,%.4f] diff_mode=%s" % [
		str(gpos), aabb.position.y, str(aabb.size), hmin, hmax, dmin, dmax, str(_diff_mode)]

func window_origin() -> Vector2: return _window_origin
func fine_cell_m() -> float: return _fine_cell_m
func window_side_m() -> Vector2: return Vector2(float(_shape.x) * _fine_cell_m, float(_shape.y) * _fine_cell_m)
func is_ready() -> bool: return _initialized
