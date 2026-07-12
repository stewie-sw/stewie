extends Node3D
# viz2_root.gd — STEWIE viz2 Phase A: the driveable Godot scene FOUNDATION.
#
# Loads the REAL 1 m Haworth Shape-from-Shading site
# (samples/lunar_dem/haworth_sfs_2km_1m, 2000² @ 1.0 m) through the FROZEN state-field
# loader (state_fields.gd), builds the terrain with the FROZEN TerrainNode (terrain.gd,
# LIT_PBR / Hapke), assembles the EZ-RASSOR rig from the MIT-licensed glb meshes and seats
# it on the real heightfield, mounts the 8-camera sensor rig (camera_rig.gd), and wires
# WASD + gamepad drive input through the project InputMap (viz2_* actions — read via
# Input.get_action_strength / is_action_pressed, NEVER raw key polling).
#
# This is a SEPARATE scene/script family from the frozen sidecar.gd and from the OLD
# no-physics intern prototype drive_controller.gd (which is NOT extended). Phase A is the
# scene + rig + input ONLY. The conserved-terramechanics drive loop is Phase B and is NOT
# built here: the pose below is a plain kinematic unicycle re-seated on the surface each
# tick (a viewing prototype, honestly labelled — not a physics integrator).
#
# The frozen seams (state_fields.gd / terrain.gd / terrain.gdshader) are used READ-ONLY,
# as libraries; none are edited.
#
# ── MIT NOTICE (docs/ezrassor_assets.md §1; THIRD_PARTY.md) ─────────────────────────────
# The rover meshes assets/{rover_body,wheel,drum,drum_arm}.glb are converted from
# FlaSpaceInst/EZ-RASSOR, licensed MIT, Copyright (c) 2019 [10 named UCF students], The
# Florida Space Institute, and The National Aeronautics and Space Administration. The MIT
# copyright + permission notice rides along with any shipped/converted mesh (THIRD_PARTY.md).

const StateFieldsScript := preload("res://state_fields.gd")
const TerrainScript := preload("res://terrain.gd")
const CameraRigScript := preload("res://camera_rig.gd")
# Phase B3 (live): the runtime drive client + the live moving-window terrain node.
const Viz2DriveClientScript := preload("res://viz2_drive_client.gd")
const Viz2WindowScript := preload("res://viz2_terrain_window.gd")
# Pixel-stream (--stream): the Godot<->stream-server frame socket (JPEG out / control in).
const Viz2StreamScript := preload("res://viz2_stream.gd")
# Phase C: the interactive sun az/el HUD. Preloaded (not reached by class_name) so it compiles
# with THIS script, mirroring how sun_sweep.gd reaches boulder_manifest.gd.
const Viz2SunHudScript := preload("res://viz2_hud.gd")
# Phase F (F2): the planned mission-route polyline overlay (mission_planner.plan() detour display).
const Viz2PathScript := preload("res://viz2_path.gd")

# ── EZ-RASSOR rig geometry (SOURCED from the URDF via ezrassor_assets.md §3; the SAME
# constants sidecar.gd::_build_rover uses — Y-up, unscaled metres; only the meshes carry
# the URDF 0.35 scale, baked into the glbs). Joint origins are absolute. ──────────────────
const ROVER_ASSETS := "res://assets"
const ROVER_JOINT_AXIS := Vector3(0, 0, -1)          # URDF (0,1,0)_zup -> (0,0,-1)_yup
const WHEEL_ORIGINS := {
	"LF": Vector3(0.20, 0.0, -0.285), "RF": Vector3(0.20, 0.0, 0.285),
	"LB": Vector3(-0.20, 0.0, -0.285), "RB": Vector3(-0.20, 0.0, 0.285),
}
const ARM_FRONT_ORIGIN := Vector3(0.20, 0.0, 0.0)
const ARM_BACK_ORIGIN := Vector3(-0.20, 0.0, 0.0)
const DRUM_FRONT_REL := Vector3(0.388245, 0.0, 0.0)
const DRUM_BACK_REL := Vector3(-0.388245, 0.0, 0.0)
const ARM_FRONT_PITCH := 0.20                        # front arm lowered (digging approach)
const ARM_BACK_PITCH := 0.65                         # back arm raised clear (transport)
const DRUM_FRONT_SPIN := 0.5                         # counter-rotation convention (control-layer)
const DRUM_BACK_SPIN := -0.5

# ── Drive kinematics (Phase-A prototype — NOT physics) ───────────────────────────────────
const LIN_SPEED := 0.6      # m/s at full forward action
const ANG_SPEED := 0.7      # rad/s at full turn action
# LIVE-mode twist ceilings: the Viz2Runtime REFUSES a twist above the IPEx envelope
# (v_max = ipex_specs.DRIVE_SPEED_MS = 0.30 m/s; omega_max ~ 1.05 rad/s), so the live drive is
# scaled to sit just inside those bounds (a Phase-A 0.6 m/s command would be rejected, M-04).
const LIVE_LIN := 0.29     # m/s at full forward action (< runtime v_max 0.30)
const LIVE_ANG := 0.90     # rad/s at full turn action (< runtime omega_max ~1.05)

# ── Chase camera framing (frames the rover in the foreground with the real relief behind) ─
const CHASE_BACK := 11.0    # m behind the rover along -forward
const CHASE_UP := 5.5       # m above
const CAM_FOV := 55.0

# ── Sun / environment (§8: single hard sun, no atmosphere). Phase-A inspection defaults use
# a mid-low elevation so the whole 2 km reads; overridable via --sun-elev / --sun-azim. ───
const SUN_ENERGY := 3.0
const SHADOW_MAX_DIST_M := 300.0   # overview scale (sidecar's 16 m is tuned for a 5 m patch)
# Drive-view ambient fill: the calibrated zero-ambient PSR look is for the frozen sensor sidecar; the
# interactive drive is a VIEWING surface, so lift the shadow side enough that a human can see the
# terrain + drive (0.06 rendered near-black on the polar grazing sun). A future --psr toggle can drop it.
const AMBIENT_FILL := 0.45

# ── parsed CLI (OS.get_cmdline_user_args(), everything after '--') ────────────────────────
var _site_dir := ""
var _out_dir := "res://out/viz2"
var _auto_frames := 0
var _rover_rc := Vector2i(-1, -1)     # (row,col); default -> field center
var _sun_elev_deg := 22.0
var _sun_azim_deg := 135.0
var _view_size := Vector2i(1280, 720)
var _region_cx := 0.0        # mission-region centre X (world m)
var _region_cz := 0.0        # mission-region centre Z (world m)
var _region_size := 0.0      # mission size (m); 0 = render the whole tile (legacy)
var _hud_selfcheck := false           # Phase C: headless proof the HUD slider drives the sun
var _clasts_path := ""                # Phase D: JSON rock field (spatial-k Golombek) to display
var _path_path := ""                  # Phase F: JSON planned-route polyline (mission_planner.plan detour)

# ── Phase B3 live mode (--live): drive THROUGH the Viz2Runtime over TCP ───────────────────
var _live := false
var _session_dir := ""
var _drive_client                       # Viz2DriveClient instance
var _window                             # Viz2TerrainWindow instance (live moving-window mesh)
var _applied_gen := 0
var _far_context: MeshInstance3D

# ── Pixel-stream mode (--stream): drive live from a browser over the FastAPI stream server ────
var _stream := false
var _stream_port := 0
var _stream_fps := 24
var _stream_quality := 0.72
var _stream_io                          # Viz2Stream frame-socket helper (RefCounted)
var _stream_v := 0.0                     # scaled twist held between browser commands (m/s)
var _stream_omega := 0.0                 # scaled twist held between browser commands (rad/s)
var _stream_max_seconds := 900.0         # hard wall-clock cap on the stream loop (safety)
var _next_reconnect_ms := 0              # throttle for the deadman-recovery reconnect (#7)

# ── browser-toggleable camera modes (the "rover view <-> 3rd person" ask) ──────────────────────
const CAM_CHASE := 0        # 3rd-person chase: behind + above, rover in the foreground
const CAM_POV := 1          # rover POV: forward-facing cam on the rover body, near the ground
const CAM_ORBIT := 2        # free orbit: pointer-drag swings az/el around the rover
const CAM_TOPDOWN := 3      # top-down tactical: straight down (tracks / dig / waypoints from above)
const CAM_MODE_COUNT := 4
var _cam_mode := CAM_CHASE
var _orbit_yaw := -2.3       # orbit azimuth (rad), pointer-driven
var _orbit_pitch := 0.55     # orbit elevation (rad), pointer-driven, clamped
var _orbit_radius := 9.0     # orbit / topdown distance (m)
var _cam_zoom := 1.0         # zoom multiplier for chase/POV (orbit/topdown use _orbit_radius)

# ── rover articulation (the URDF joints animate: wheels roll, drums counter-rotate, arms dig) ──
# Grounded in ipex_specs: wheel ⌀0.305 m, drum rated 18 RPM (108 deg/s), counter-rotating bucket
# drums (KSC-TOPS-7), front arm DOWN to dig + back arm UP to transport ("COBRA" posture).
const WHEEL_RADIUS_M := 0.1524
const DRUM_IDLE_DPS := 42.0        # cinematic idle drum spin (deg/s)
const DRUM_DIG_DPS := 108.0        # 18 RPM rated dig spin (ipex_specs.DRUM_SPEED_RATED_RPM)
const ARM_DIG_DOWN := -0.55        # extra front-arm pitch (rad): LOWER the drum to dig (+ raises, so -)
const ARM_TRANSPORT_UP := 0.35     # extra back-arm pitch (rad): RAISE for transport
const DIG_ANIM_S := 2.2            # dig / dump gesture duration
var _joints := {}                  # joint name -> {node, rest:Basis, origin:Vector3, base:float}
var _wheel_angle := 0.0
var _drum_angle := 0.0
var _dig_anim_t := 0.0
var _dump_anim_t := 0.0
# manual articulation (browser-driven, independent of the auto dig/dump gesture)
var _manual_drum := 0.0            # drum spin command (-1..1), 0 = hold
var _arm_front_offset := 0.0       # manual front-arm angle offset (rad), added to the gesture
var _arm_back_offset := 0.0        # manual back-arm angle offset (rad)
# planning: click-plotted waypoints + autonomous traverse
var _waypoints: Array = []         # Array[Vector3] world positions
var _wp_index := 0
var _auto_traverse := false
var _wp_root: Node3D               # holds the waypoint marker meshes

# ── runtime state ────────────────────────────────────────────────────────────────────────
var sf                                 # StateFields instance (read-only library)
var _terrain: Node3D                   # TerrainNode (class_name not relied on in headless ad-hoc load)
var _rover_root: Node3D
var _sun: DirectionalLight3D           # the single hard sun (Phase C HUD + --sun-az/--sun-el drive it)
var _hud                               # Viz2SunHud instance (interactive az/el sliders)
var _clast_mmi: MultiMeshInstance3D    # Phase D: the rendered spatial-k rock field
var _clast_center := Vector3.ZERO      # rock-field bbox center (for the display capture framing)
var _clast_span := 0.0                 # rock-field bbox horizontal span (m)
var _path_node: Node3D                 # Phase F: the Viz2Path route-polyline overlay
var _cam: Camera3D                      # main viewport (chase) camera
var _rig_cams: Array = []              # camera_rig.gd 8-cam sensor rig (mounted on the rover)
var _root_lift := 0.0                  # wheel-bottom -> surface ground-snap offset (yaw-invariant)
var _pose_x := 0.0
var _pose_z := 0.0
var _pose_yaw := 0.0
# pose interpolation: the RENDERED pose glides toward the newest 15 Hz telemetry TARGET so motion is
# smooth at 20-60 fps instead of snapping 15x/s (council #15).
const POSE_SMOOTH := 14.0
var _target_x := 0.0
var _target_z := 0.0
var _target_yaw := 0.0
var _pose_init := false
var _field_center := Vector3.ZERO


func _ready() -> void:
	_parse_args()
	get_window().size = _view_size

	if _site_dir == "":
		# Default: the merged 1 m Haworth SfS bundle at the repo-root samples/ (res:// is
		# stewie/godot, so ../../samples resolves to code/samples).
		_site_dir = ProjectSettings.globalize_path(
			"res://../../samples/lunar_dem/haworth_sfs_2km_1m")

	sf = StateFieldsScript.new()
	if not sf.load_scene(_site_dir):
		push_error("viz2: failed to load site '%s': %s" % [_site_dir, sf.error_msg])
		get_tree().quit(3)
		return
	print("viz2: loaded site '%s' (%dx%d @ %.3f m, height_range=[%.1f, %.1f])" % [
		sf.scene_name, sf.width, sf.height, sf.cell_m, sf.height_range.x, sf.height_range.y])

	var ext: Vector2 = sf.extent_m()
	_field_center = Vector3(sf.world_min.x + ext.x * 0.5, sf.height_range.x,
							sf.world_min.y + ext.y * 0.5)

	_setup_environment()

	# Phase C: a headless proof the HUD slider actually drives the sun (real Godot runtime, no fake).
	# Runs right after the sun exists — no terrain/rover/capture needed — and quits with a status code.
	if _hud_selfcheck:
		_run_hud_selfcheck()
		return

	if _live:
		_build_far_context()   # viz2-owned context (the frozen terrain.gd is NOT instantiated in live mode)
	else:
		_build_terrain()
	_build_rover()
	# The 8-SubViewport sensor rig is unused by the stream (it reads only the main viewport), so skip
	# its permanent per-session VRAM/driver cost on a GPU capped at 2 concurrent sessions. (council #12)
	if not _stream:
		_build_camera_rig()
	# Phase D: display the spatial-k Golombek rock field over the real terrain (if --clasts given).
	if _clasts_path != "":
		_build_clasts_display()
	# Phase F: overlay the planned mission-route polyline (mission_planner.plan detour) if --path given.
	if _path_path != "":
		_build_path_display()
	_setup_chase_camera()
	# Phase G / G4: the "About this DEM" provenance pane — reads THIS bundle's
	# metadata.json dem_provenance.citation VERBATIM (Barker/Mazarico for a LOLA tile,
	# Alexandrov & Beyer for the SfS tile). Built for every mode so it rides the capture.
	_build_provenance_pane()

	if _live:
		if not _setup_live():
			get_tree().quit(5)
			return
		if _stream:
			_apply_stream_render_profile()   # real-time AA/shadow profile (not the offline-still stack)
			_run_stream()      # coroutine: continuous browser-driven live loop + JPEG frame stream
		elif _auto_frames > 0:
			_run_live_auto()   # coroutine: drive THROUGH the Viz2Runtime, carve, capture
		else:
			_build_sun_hud()   # Phase C: interactive az/el sliders
			set_process(true)
			print("viz2: LIVE interactive drive — WASD/gamepad THROUGH the Viz2Runtime")
	elif _auto_frames > 0:
		if _path_path != "" and _path_node != null:
			# Phase F verification: frame the planned route so the DETOUR around the rock cluster reads
			# (a near-nadir plan + a low oblique), rocks + route both in view.
			_run_path_capture()   # coroutine
		elif _clasts_path != "" and _clast_mmi != null:
			# Phase D verification: frame the rendered spatial-k rock field so the density gradient
			# (rockier near the rim, sparse on the flat) reads under a grazing sun.
			_run_clast_capture()   # coroutine
		else:
			# Headless verification: scripted drive THROUGH the InputMap (Input.action_press ->
			# the SAME _read_twist() path interactive mode uses -> proves the A5 action wiring),
			# capturing N frames + a wide overview to out/viz2/.
			_run_auto()   # coroutine
	else:
		# Interactive: WASD / gamepad drive via the project InputMap.
		_build_sun_hud()   # Phase C: interactive az/el sliders (grazing-band annotation)
		set_process(true)
		print("viz2: interactive drive — WASD or gamepad (viz2_forward/back/left/right/brake/dig/dump)")


# ── CLI ─────────────────────────────────────────────────────────────────────────────────
func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()   # everything after '--'
	var i := 0
	while i < args.size():
		match args[i]:
			"--site":
				i += 1; _site_dir = String(args[i])
			"--out":
				i += 1; _out_dir = _abs_out(String(args[i]))
			"--auto":
				i += 1; _auto_frames = maxi(1, int(args[i]))
			"--rover-rc":
				i += 1
				var rc := String(args[i]).split(",")
				if rc.size() == 2:
					_rover_rc = Vector2i(int(rc[0]), int(rc[1]))
			"--sun-elev", "--sun-el":
				i += 1; _sun_elev_deg = float(args[i])
			"--sun-azim", "--sun-az":
				i += 1; _sun_azim_deg = float(args[i])
			"--hud-selfcheck":
				_hud_selfcheck = true
			"--clasts":
				i += 1; _clasts_path = String(args[i])
			"--path":
				i += 1; _path_path = String(args[i])
			"--size":
				i += 1
				var wh := String(args[i]).split("x")
				if wh.size() == 2:
					_view_size = Vector2i(int(wh[0]), int(wh[1]))
			"--live":
				_live = true
			"--session-dir":
				i += 1; _session_dir = String(args[i])
			"--stream":
				_stream = true; _live = true      # streaming implies the live conserved drive
			"--stream-port":
				i += 1; _stream_port = int(args[i])
			"--stream-fps":
				i += 1; _stream_fps = maxi(1, int(args[i]))
			"--stream-quality":
				i += 1; _stream_quality = clampf(float(args[i]), 0.1, 1.0)
			"--region-cx":
				i += 1; _region_cx = float(args[i])
			"--region-cz":
				i += 1; _region_cz = float(args[i])
			"--region-size":
				i += 1; _region_size = float(args[i])
		i += 1


func _abs_out(p: String) -> String:
	if p.begins_with("res://") or p.begins_with("/"):
		return p
	return "res://out/" + p


# ── environment ───────────────────────────────────────────────────────────────────────────
func _setup_environment() -> void:
	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	sun.rotation_degrees = Vector3(-_sun_elev_deg, _sun_azim_deg, 0.0)
	sun.light_energy = SUN_ENERGY
	sun.light_angular_distance = 0.5          # ~0.5° solar disc -> PCSS penumbra
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_ORTHOGONAL
	sun.directional_shadow_max_distance = SHADOW_MAX_DIST_M
	add_child(sun)
	_sun = sun          # Phase C: the HUD sliders + --sun-az/--sun-el drive THIS light

	var we := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.01, 0.01, 0.015)   # near-black vacuum sky
	# A faint ambient fill — inspection-only (Phase A is a viewing prototype). The calibrated
	# zero-ambient sensor look lives in the frozen sidecar; here we just guarantee the rover
	# and shadow-side relief stay legible in the verification capture.
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.55, 0.55, 0.6)
	e.ambient_light_energy = AMBIENT_FILL
	e.ssil_enabled = false
	e.sdfgi_enabled = false
	e.glow_enabled = false
	e.ssao_enabled = false
	e.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	we.environment = e
	add_child(we)


# Real-time render profile for the LIVE stream. project.godot's AA/shadow stack is authored for
# one-shot offline SENSOR STILLS (2.25x SSAA via scaling_3d=1.5, 4x MSAA, SMAA, TAA off, 8192px Ultra
# PCSS) -- ~4-9x wasted shading on every ~24 fps streamed frame that is then downscaled to 960x540 and
# JPEG'd. Override the main viewport for continuous rendering: TAA (correct for a moving scene, and it
# suppresses the PCSS shadow shimmer), no SSAA/SMAA, light MSAA, and a distance-matched PSSM shadow that
# concentrates texel density on the live chase/POV view instead of one 300 m ortho split. (council #2)
func _apply_stream_render_profile() -> void:
	var vp := get_viewport()
	if vp == null:
		return
	vp.scaling_3d_mode = Viewport.SCALING_3D_MODE_BILINEAR
	vp.scaling_3d_scale = 1.0
	vp.msaa_3d = Viewport.MSAA_2X
	vp.screen_space_aa = Viewport.SCREEN_SPACE_AA_DISABLED
	vp.use_taa = true
	if _sun != null:
		_sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
		_sun.directional_shadow_max_distance = 140.0
	print("viz2: STREAM render profile — TAA on, SSAA/SMAA off, MSAA 2x, PSSM-4 shadow 140 m")


# ── Phase C: interactive sun az/el HUD (viz2_hud.gd) ──────────────────────────────────────
# Built ONLY in the interactive paths — the headless capture paths drive the same _sun through
# --sun-az/--sun-el so a capture is reproducible and HUD-free. The HUD owns the light's rotation.
func _build_sun_hud() -> void:
	if _sun == null:
		return
	_hud = Viz2SunHudScript.new()
	_hud.build(self, _sun, _sun_azim_deg, _sun_elev_deg)
	print("viz2: sun HUD ready — azimuth 0-360 / elevation -5..+90 sliders drive the ",
		"DirectionalLight (Vector3(-el, az, 0)); grazing polar band <= 7 deg annotated")


# Phase C headless proof: build the HUD, move the az/el sliders (which re-fire the SAME handlers a
# human drag uses), and assert the sun's rotation follows the Vector3(-el, az, 0) convention. Uses
# the (215,5)->(35,5) pair so it also proves the shadow-flip sun poses the capture verify uses. Real
# Godot runtime; nothing faked. Quits 0 on PASS, 1 on FAIL.
func _run_hud_selfcheck() -> void:
	_build_sun_hud()
	if _hud == null:
		push_error("viz2: HUD selfcheck — no sun/HUD built")
		get_tree().quit(1)
		return
	var ok := true
	_hud.set_azimuth(215.0)
	_hud.set_elevation(5.0)
	var r: Vector3 = _sun.rotation_degrees
	if absf(r.x - (-5.0)) > 1e-3 or absf(r.y - 215.0) > 1e-3 or absf(r.z) > 1e-3:
		ok = false
	# a second az proves the slider drives the sun LIVE (not a one-shot); this is the flip target
	_hud.set_azimuth(35.0)
	var r2: Vector3 = _sun.rotation_degrees
	if absf(r2.y - 35.0) > 1e-3 or absf(r2.x - (-5.0)) > 1e-3:
		ok = false
	print("viz2: HUD selfcheck %s — set(az=215,el=5)->sun(%.2f,%.2f,%.2f); set(az=35)->sun(%.2f,%.2f,%.2f)" % [
		"PASS" if ok else "FAIL", -5.0, 215.0, 0.0, r2.x, r2.y, r2.z])
	get_tree().quit(0 if ok else 1)


# ── Phase D: spatial-k Golombek rock-field DISPLAY (clasts as a lit sphere MultiMesh) ─────
# Loads a --clasts JSON (produced by scripts/viz2_rockfield_clasts.py from stewie.terrain.rockfield
# over the REAL DEM) whose clasts carry center_m in the SCENE WORLD frame [x, height, z], radius_m,
# buried_frac, stratum. Renders them with the SAME clast.gdshader / triaxial-shape path the frozen
# sidecar._build_clasts uses (INTERFACE.md §5 clasts schema), so the rocks read as lit angular rock,
# not CG spheres, and the spatial-k density (rockier near rims, sparse on the flat) is visible.
func _build_clasts_display() -> void:
	var f := FileAccess.open(_clasts_path, FileAccess.READ)
	if f == null:
		push_error("viz2: --clasts file not readable: %s" % _clasts_path)
		return
	var parsed = JSON.parse_string(f.get_as_text())
	f.close()
	if typeof(parsed) != TYPE_DICTIONARY or not parsed.has("clasts"):
		push_error("viz2: --clasts JSON missing a 'clasts' array")
		return
	var clasts: Array = parsed["clasts"]
	if clasts.is_empty():
		print("viz2: rock field carries 0 clasts")
		return

	var sphere := SphereMesh.new()
	sphere.radius = 1.0
	sphere.height = 2.0
	sphere.radial_segments = 20
	sphere.rings = 12
	var mat := ShaderMaterial.new()
	mat.shader = load("res://clast.gdshader")
	mat.set_shader_parameter("hapke_enabled", sf.hapke_enabled)
	mat.set_shader_parameter("hapke_b", sf.hapke_b)
	mat.set_shader_parameter("hapke_c", sf.hapke_c)
	mat.set_shader_parameter("hapke_B0", sf.hapke_B0)
	mat.set_shader_parameter("hapke_h", sf.hapke_h)
	mat.set_shader_parameter("hapke_gain", sf.hapke_gain)
	mat.set_shader_parameter("surf_amp", 0.34)
	mat.set_shader_parameter("surf_freq", 1.9)
	mat.set_shader_parameter("facet_levels", 3.0)
	mat.set_shader_parameter("ridge_mix", 0.95)
	mat.set_shader_parameter("detail_amp", 1.1)
	mat.set_shader_parameter("detail_freq", 16.0)
	sphere.material = mat

	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_custom_data = true
	mm.mesh = sphere
	mm.instance_count = clasts.size()
	var lo := Vector3(INF, INF, INF)
	var hi := Vector3(-INF, -INF, -INF)
	for i in range(clasts.size()):
		var c: Dictionary = clasts[i]
		var ctr = c.get("center_m", [0.0, 0.0, 0.0])
		var rad := float(c.get("radius_m", 0.05))
		var pos := Vector3(float(ctr[0]), float(ctr[1]), float(ctr[2]))
		lo = Vector3(minf(lo.x, pos.x), minf(lo.y, pos.y), minf(lo.z, pos.z))
		hi = Vector3(maxf(hi.x, pos.x), maxf(hi.y, pos.y), maxf(hi.z, pos.z))
		var cid: int = int(c.get("id", i))
		var rng := RandomNumberGenerator.new()
		rng.seed = hash(cid)
		# Triaxial lunar-fragment axial ratios (Tsuchiyama 2022), renormalized to geo-mean 1 so the
		# Golombek radius is preserved (identical to sidecar.gd:1090-1097).
		var b_ratio := rng.randf_range(0.65, 0.90)
		var c_ratio := rng.randf_range(0.50, 0.75)
		var gmean := pow(1.0 * b_ratio * c_ratio, 1.0 / 3.0)
		var sa := 1.0 / gmean
		var sb := b_ratio / gmean
		var sc := c_ratio / gmean
		var yaw := rng.randf_range(0.0, TAU)
		var tilt := rng.randf_range(-0.20, 0.20)
		var tilt_dir := rng.randf_range(0.0, TAU)
		var rot := Basis(Vector3.UP, yaw)
		rot = Basis(Vector3(cos(tilt_dir), 0.0, sin(tilt_dir)), tilt) * rot
		var basis := rot.scaled(Vector3(rad * sa, rad * sc, rad * sb))
		mm.set_instance_transform(i, Transform3D(basis, pos))
		var seed_f := float(absi(hash(cid)) % 100000) / 100000.0
		var elong := clampf(sa / maxf(sc, 1e-3), 1.0, 4.0)
		var void_gate := 1.0 if rng.randf() < 0.35 else 0.0
		mm.set_instance_custom_data(i, Color(seed_f, elong, void_gate, 0.0))

	_clast_mmi = MultiMeshInstance3D.new()
	_clast_mmi.name = "RockField"
	_clast_mmi.multimesh = mm
	add_child(_clast_mmi)
	_clast_center = (lo + hi) * 0.5
	_clast_span = maxf(hi.x - lo.x, hi.z - lo.z)
	var tag := "?"
	if parsed.has("manifest") and typeof(parsed["manifest"]) == TYPE_DICTIONARY:
		var man: Dictionary = parsed["manifest"]
		tag = String(man.get("honesty_tags", {}).get("spatial_abundance_k", "?"))
	print("viz2: displayed %d spatial-k Golombek clasts over the real DEM (abundance %s)" % [
		clasts.size(), tag])


# ── Phase F: planned mission-route polyline overlay (mission_planner.plan detour display) ──
# Instantiates viz2_path.gd on a --path JSON whose waypoints are the REAL planner route (over the
# real DEM, bending around the rock-hazard keep-outs) in the SAME scene world frame the clasts use.
func _build_path_display() -> void:
	_path_node = Viz2PathScript.new()
	_path_node.name = "RoutePath"
	add_child(_path_node)
	if not _path_node.build_from_file(_path_path):
		push_error("viz2: --path route overlay failed to build from %s" % _path_path)
		remove_child(_path_node)
		_path_node = null


# ── terrain (frozen TerrainNode, LIT_PBR) ─────────────────────────────────────────────────
func _build_terrain() -> void:
	_terrain = TerrainScript.new()
	_terrain.name = "Terrain"
	add_child(_terrain)
	_terrain.build(sf, 0)   # 0 == TerrainNode.Mode.LIT_PBR (active fine mesh + far-field LOD plane)


# ── EZ-RASSOR rig (assembled from the MIT glbs; mirrors sidecar.gd::_build_rover faithfully) ─
func _build_rover() -> void:
	var have_parts := FileAccess.file_exists(ROVER_ASSETS + "/rover_body.glb") \
		and FileAccess.file_exists(ROVER_ASSETS + "/wheel.glb") \
		and FileAccess.file_exists(ROVER_ASSETS + "/drum.glb") \
		and FileAccess.file_exists(ROVER_ASSETS + "/drum_arm.glb")
	if not have_parts:
		push_error("viz2: EZ-RASSOR glbs missing under %s" % ROVER_ASSETS)
		get_tree().quit(4)
		return

	var root := Node3D.new()
	root.name = "RASSOR"

	var body := _load_glb(ROVER_ASSETS + "/rover_body.glb")
	if body == null:
		push_error("viz2: rover_body.glb failed to load")
		get_tree().quit(4)
		return
	body.name = "body"
	root.add_child(body)

	for key in WHEEL_ORIGINS.keys():
		var w := _make_joint("wheel_" + String(key), ROVER_ASSETS + "/wheel.glb",
			WHEEL_ORIGINS[key], Basis.IDENTITY, 0.0, Basis.IDENTITY)
		if w != null:
			root.add_child(w)

	# Arms: URDF origin rpy bakes into the pivot REST basis; the link visual rpy bakes into
	# the mesh-child basis (mirrors sidecar.gd exactly so the arms/drums read correctly).
	var arm_front := _make_joint("arm_front", ROVER_ASSETS + "/drum_arm.glb",
		ARM_FRONT_ORIGIN, Basis(Vector3.RIGHT, PI), ARM_FRONT_PITCH, Basis.IDENTITY)
	var arm_back := _make_joint("arm_back", ROVER_ASSETS + "/drum_arm.glb",
		ARM_BACK_ORIGIN, Basis.IDENTITY, ARM_BACK_PITCH,
		Basis(Vector3(0, 0, 1), PI) * Basis(Vector3.RIGHT, PI))
	if arm_front != null:
		var drum_front := _make_joint("drum_front", ROVER_ASSETS + "/drum.glb",
			DRUM_FRONT_REL, Basis(Vector3.RIGHT, PI), DRUM_FRONT_SPIN, Basis.IDENTITY)
		if drum_front != null:
			arm_front.add_child(drum_front)
		root.add_child(arm_front)
	if arm_back != null:
		var drum_back := _make_joint("drum_back", ROVER_ASSETS + "/drum.glb",
			DRUM_BACK_REL, Basis(Vector3.RIGHT, PI), DRUM_BACK_SPIN,
			Basis(Vector3(0, 0, 1), PI) * Basis(Vector3.RIGHT, PI))
		if drum_back != null:
			arm_back.add_child(drum_back)
		root.add_child(arm_back)

	_apply_material_recursive(root, _rover_material())

	# Placement: a valid pose on the real surface. Default = field center (interior of the
	# Haworth crop, gentle relief); --rover-rc overrides. Ground-snap ONCE at the root: seat
	# the lowest point (wheel bottoms) at the sampled surface height.
	var place_rc := _rover_rc
	if place_rc.x < 0:
		place_rc = Vector2i(int(sf.height / 2), int(sf.width / 2))
	place_rc.x = clampi(place_rc.x, 0, sf.height - 1)
	place_rc.y = clampi(place_rc.y, 0, sf.width - 1)

	_pose_x = sf.world_min.x + place_rc.y * sf.cell_m   # col -> +X
	_pose_z = sf.world_min.y + place_rc.x * sf.cell_m   # row -> +Z
	_pose_yaw = deg_to_rad(35.0)                        # 3/4 view heading

	var u: float = clampf(float(place_rc.y) / float(sf.width - 1), 0.0, 1.0)
	var v: float = clampf(float(place_rc.x) / float(sf.height - 1), 0.0, 1.0)
	var surf_y: float = sf.height_uv(u, v)

	root.transform = Transform3D(Basis(Vector3.UP, _pose_yaw), Vector3(_pose_x, surf_y, _pose_z))
	add_child(root)
	var aabb := _node_world_aabb(root)
	_root_lift = surf_y - aabb.position.y            # yaw-invariant (rotation about +Y)
	root.position.y += _root_lift
	_rover_root = root
	print("viz2: seated EZ-RASSOR (MIT) at rc=(%d,%d) world=(%.1f, %.3f, %.1f); " % [
			place_rc.x, place_rc.y, _pose_x, root.position.y, _pose_z],
		"AABB size=(%.2f,%.2f,%.2f) lift=%.3f surf=%.3f" % [
			aabb.size.x, aabb.size.y, aabb.size.z, _root_lift, surf_y])


func _make_joint(node_name: String, glb_res: String, origin: Vector3,
		rest_basis: Basis, angle: float, mesh_basis: Basis) -> Node3D:
	var mesh := _load_glb(glb_res)
	if mesh == null:
		return null
	var pivot := Node3D.new()
	pivot.name = node_name
	pivot.transform = Transform3D(rest_basis * Basis(ROVER_JOINT_AXIS, angle), origin)
	mesh.transform = Transform3D(mesh_basis, Vector3.ZERO)
	pivot.add_child(mesh)
	# register for live articulation (re-drive the pivot about ROVER_JOINT_AXIS from its rest pose)
	_joints[node_name] = {"node": pivot, "rest": rest_basis, "origin": origin, "base": angle}
	return pivot


func _set_joint(jname: String, extra: float) -> void:
	var j = _joints.get(jname)
	if j == null:
		return
	j["node"].transform = Transform3D(j["rest"] * Basis(ROVER_JOINT_AXIS, float(j["base"]) + extra), j["origin"])


# Live articulation, called every stream frame: wheels roll with forward speed, the bucket drums
# counter-rotate (front +, back -; a dig/dump gesture speeds them to the rated 18 RPM and dump
# reverses the scoops), and the front arm lowers to dig while the back arm raises for transport.
func _animate_rover(dt: float) -> void:
	if _joints.is_empty():
		return
	if absf(_stream_v) > 1e-4:
		_wheel_angle += (_stream_v / WHEEL_RADIUS_M) * dt
		for k in ["LF", "RF", "LB", "RB"]:
			_set_joint("wheel_" + k, _wheel_angle)
	# bucket drums: auto-spin while digging/dumping (dump reverses), else the browser's MANUAL command
	var active := _dig_anim_t > 0.0 or _dump_anim_t > 0.0
	var spin_dps := 0.0
	if active:
		spin_dps = (-1.0 if _dump_anim_t > 0.0 else 1.0) * DRUM_DIG_DPS
	elif absf(_manual_drum) > 1e-3:
		spin_dps = _manual_drum * DRUM_DIG_DPS
	_drum_angle += deg_to_rad(spin_dps) * dt
	_set_joint("drum_front", _drum_angle)
	_set_joint("drum_back", -_drum_angle)
	# arms: the auto dig gesture PLUS whatever manual offset the browser dialed in (full URDF control)
	var g := clampf(maxf(_dig_anim_t, _dump_anim_t) / DIG_ANIM_S, 0.0, 1.0)
	_set_joint("arm_front", ARM_DIG_DOWN * g + _arm_front_offset)
	_set_joint("arm_back", ARM_TRANSPORT_UP * g + _arm_back_offset)
	if _dig_anim_t > 0.0:
		_dig_anim_t -= dt
	if _dump_anim_t > 0.0:
		_dump_anim_t -= dt


func _load_glb(res_path: String) -> Node3D:
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	var err := doc.append_from_file(ProjectSettings.globalize_path(res_path), state)
	if err != OK:
		push_warning("viz2: glTF load failed for %s (%d)" % [res_path, err])
		return null
	var scene := doc.generate_scene(state)
	return scene as Node3D


func _rover_material() -> ShaderMaterial:
	var m := ShaderMaterial.new()
	m.shader = load("res://rover.gdshader")   # worn-metal PBR (default PBR, not Hapke)
	return m


func _apply_material_recursive(node: Node, mat: Material) -> void:
	if node is MeshInstance3D:
		(node as MeshInstance3D).material_override = mat
	for ch in node.get_children():
		_apply_material_recursive(ch, mat)


func _node_world_aabb(node: Node) -> AABB:
	var acc := AABB()
	var first := true
	for mi in _collect_mesh_instances(node):
		if mi.mesh == null:
			continue
		var local: AABB = mi.mesh.get_aabb()
		var gx: Transform3D = mi.global_transform
		for ci in range(8):
			var corner := local.position + Vector3(
				local.size.x if (ci & 1) else 0.0,
				local.size.y if (ci & 2) else 0.0,
				local.size.z if (ci & 4) else 0.0)
			var wc: Vector3 = gx * corner
			if first:
				acc = AABB(wc, Vector3.ZERO); first = false
			else:
				acc = acc.expand(wc)
	return acc


func _collect_mesh_instances(node: Node) -> Array:
	var out: Array = []
	if node is MeshInstance3D:
		out.append(node)
	for ch in node.get_children():
		out.append_array(_collect_mesh_instances(ch))
	return out


# ── 8-camera sensor rig (camera_rig.gd) mounted on the rover ──────────────────────────────
func _build_camera_rig() -> void:
	if _rover_root == null:
		return
	# Small offscreen SubViewports (the sensor egress rig); UPDATE_ONCE keeps the Phase-A
	# overview render cheap — the rig is WIRED (rides the rover) but is not the capture path.
	_rig_cams = CameraRigScript.build(self, _rover_root, get_viewport().world_3d,
		Vector2i(320, 240), 0.0)
	for e in _rig_cams:
		e["sv"].render_target_update_mode = SubViewport.UPDATE_ONCE
	print("viz2: mounted %d-camera sensor rig on the rover (camera_rig.gd)" % _rig_cams.size())


# ── main chase camera ─────────────────────────────────────────────────────────────────────
func _setup_chase_camera() -> void:
	_cam = Camera3D.new()
	_cam.name = "ChaseCam"
	_cam.fov = CAM_FOV
	_cam.near = 0.05
	_cam.far = 6000.0
	add_child(_cam)
	_cam.current = true
	_update_chase_cam()


func _update_chase_cam() -> void:
	if _cam == null or _rover_root == null:
		return
	var fwd := (Basis(Vector3.UP, _pose_yaw) * Vector3(1, 0, 0)).normalized()
	var rover_pos: Vector3 = _rover_root.global_transform.origin
	var eye := rover_pos - fwd * CHASE_BACK + Vector3.UP * CHASE_UP
	_cam.global_transform = _look_at_xf(eye, rover_pos + Vector3.UP * 0.4, Vector3.UP)


# Mode-aware camera for the live/stream drive: the browser cycles CAM_CHASE/POV/ORBIT/TOPDOWN and
# drags to orbit. Framed tight on the ~1.8 m rover so it reads at any DEM cell size (per-surface scale
# is Phase 2; this keeps the rover legible now). Called every stream frame + on a camera command.
func _update_stream_cam() -> void:
	if _cam == null or _rover_root == null:
		return
	var rp: Vector3 = _rover_root.global_transform.origin
	var fwd := (Basis(Vector3.UP, _pose_yaw) * Vector3(1, 0, 0)).normalized()
	var eye: Vector3
	var target: Vector3
	var up := Vector3.UP
	var clamp_eye := true
	match _cam_mode:
		CAM_POV:                                  # forward-facing cam on the rover body, near the ground
			eye = rp + fwd * 0.95 + Vector3.UP * 1.05
			target = rp + fwd * 14.0 + Vector3.UP * 0.35
		CAM_ORBIT:                                # free orbit: az/el from pointer drag, fixed radius
			var cp := cos(_orbit_pitch)
			var dir := Vector3(cos(_orbit_yaw) * cp, sin(_orbit_pitch), sin(_orbit_yaw) * cp)
			eye = rp + dir * _orbit_radius
			target = rp + Vector3.UP * 0.4
		CAM_TOPDOWN:                              # straight down — tracks / dig / waypoints as a plan/map
			eye = rp + Vector3(0.001, _orbit_radius * 1.7, 0.001)
			target = rp
			up = Vector3(0.0, 0.0, -1.0)
			clamp_eye = false
		_:                                        # CAM_CHASE: behind + above, rover in the foreground (zoomable)
			eye = rp - fwd * (8.0 * _cam_zoom) + Vector3.UP * (4.0 * _cam_zoom)
			target = rp + fwd * 2.0 + Vector3.UP * 0.6
	# keep the eye above the terrain (+clearance) so chase/POV/orbit don't clip into >16deg slopes (council #11)
	if clamp_eye:
		eye.y = maxf(eye.y, _ground_h(eye.x, eye.z) + 0.8)
	_cam.global_transform = _look_at_xf(eye, target, up)


# Terrain height at world (x,z): the live carved window where it covers, else the static DEM.
func _ground_h(x: float, z: float) -> float:
	if _window != null:
		var h: float = _window.height_at_world(x, z)
		if not is_nan(h):
			return h
	if sf != null:
		var u: float = clampf((x - sf.world_min.x) / sf.extent_m().x, 0.0, 1.0)
		var v: float = clampf((z - sf.world_min.y) / sf.extent_m().y, 0.0, 1.0)
		return sf.height_uv(u, v)
	return 0.0


# ── planning: click-to-plot waypoints + autonomous traverse ───────────────────────────────
# The browser sends a canvas-pixel click; the main-viewport camera unprojects a ray and intersects a
# ground plane at the rover's height to get a world waypoint, dropped as a bright marker.
func _add_waypoint_from_click(px: float, py: float) -> void:
	if _cam == null:
		return
	var sp := Vector2(px, py)
	var origin := _cam.project_ray_origin(sp)
	var dir := _cam.project_ray_normal(sp)
	if absf(dir.y) < 1e-5:
		return
	var ground_y := _ground_h(_pose_x, _pose_z)
	var t := (ground_y - origin.y) / dir.y
	if t <= 0.0:
		return
	var hit := origin + dir * t
	hit.y = _ground_h(hit.x, hit.z)                  # snap the marker to the terrain there
	_waypoints.append(hit)
	_add_wp_marker(hit)


func _add_wp_marker(pos: Vector3) -> void:
	if _wp_root == null:
		_wp_root = Node3D.new()
		_wp_root.name = "Waypoints"
		add_child(_wp_root)
	var m := MeshInstance3D.new()
	var cyl := CylinderMesh.new()
	cyl.top_radius = 0.25
	cyl.bottom_radius = 0.25
	cyl.height = 1.2
	m.mesh = cyl
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(1.0, 0.85, 0.2)         # bright plotting-marker yellow
	mat.emission_enabled = true
	mat.emission = Color(0.9, 0.7, 0.1)
	m.material_override = mat
	m.position = pos + Vector3(0.0, 0.6, 0.0)
	_wp_root.add_child(m)


func _clear_waypoints() -> void:
	_waypoints.clear()
	_wp_index = 0
	_auto_traverse = false
	if _wp_root != null:
		for c in _wp_root.get_children():
			c.queue_free()


# Autonomous waypoint follower: steer the runtime twist toward the current waypoint, advance when
# reached, stop at the end. Returns the SCALED (v, omega) for the runtime (computed in the runtime's
# heading convention, bypassing the browser's A=left omega flip).
func _traverse_step() -> Vector2:
	if _wp_index >= _waypoints.size():
		_auto_traverse = false
		return Vector2.ZERO
	var wp: Vector3 = _waypoints[_wp_index]
	var dx := wp.x - _pose_x
	var dz := wp.z - _pose_z
	if sqrt(dx * dx + dz * dz) < 1.0:                # reached this waypoint
		_wp_index += 1
		if _wp_index >= _waypoints.size():
			_auto_traverse = false
		return Vector2.ZERO
	var bearing := atan2(dz, dx)                     # runtime heading convention (0=+x, +90=+z)
	var yaw: float = _drive_client.latest_yaw if _drive_client != null else 0.0
	var err := wrapf(bearing - yaw, -PI, PI)
	var omega := clampf(err * 2.0, -1.0, 1.0)
	var v := clampf(1.0 - absf(err) / 1.5, 0.2, 1.0)  # ease the throttle on a hard turn
	return Vector2(v * LIVE_LIN, omega * LIVE_ANG)


func _look_at_xf(eye: Vector3, target: Vector3, up_hint: Vector3) -> Transform3D:
	var dir := (target - eye)
	if dir.length() < 1e-6:
		dir = Vector3(0, 0, -1)
	dir = dir.normalized()
	var u := up_hint
	if absf(dir.dot(u.normalized())) > 0.999:
		u = Vector3(0, 0, 1)
	var z_axis := -dir
	var x_axis := u.cross(z_axis).normalized()
	var y_axis := z_axis.cross(x_axis).normalized()
	return Transform3D(Basis(x_axis, y_axis, z_axis), eye)


# ── drive input (project InputMap; NO raw key polling) ────────────────────────────────────
# v (m/s), omega (rad/s) from the viz2_* actions. Gamepad axes are analog (get_action_strength
# in [0,1]); keys read as full strength. Brake zeroes the twist.
func _read_twist() -> Vector2:
	var v := Input.get_action_strength("viz2_forward") - Input.get_action_strength("viz2_back")
	var om := Input.get_action_strength("viz2_left") - Input.get_action_strength("viz2_right")
	if Input.is_action_pressed("viz2_brake"):
		return Vector2.ZERO
	return Vector2(clampf(v, -1.0, 1.0) * LIN_SPEED, clampf(om, -1.0, 1.0) * ANG_SPEED)


func _integrate(v: float, omega: float, dt: float) -> void:
	_pose_yaw += omega * dt
	var fwd := Basis(Vector3.UP, _pose_yaw) * Vector3(1, 0, 0)
	_pose_x += v * fwd.x * dt
	_pose_z += v * fwd.z * dt
	_pose_x = clampf(_pose_x, sf.world_min.x, sf.world_max.x)
	_pose_z = clampf(_pose_z, sf.world_min.y, sf.world_max.y)


func _apply_pose() -> void:
	if _rover_root == null:
		return
	var u: float = clampf((_pose_x - sf.world_min.x) / sf.extent_m().x, 0.0, 1.0)
	var v: float = clampf((_pose_z - sf.world_min.y) / sf.extent_m().y, 0.0, 1.0)
	var surf_y: float = sf.height_uv(u, v)
	_rover_root.transform = Transform3D(Basis(Vector3.UP, _pose_yaw),
		Vector3(_pose_x, surf_y + _root_lift, _pose_z))


func _process(delta: float) -> void:
	if _live:
		# LIVE interactive: drive THROUGH the runtime (bounded twist), dig on viz2_dig, dump on
		# viz2_dump, toggle the signed cut/berm diff drape on viz2_diff (E2).
		var lt := _read_twist_live()
		_live_tick(lt.x, lt.y)
		if Input.is_action_just_pressed("viz2_dig"):
			_drive_client.send_dig()
		if Input.is_action_just_pressed("viz2_dump"):
			_drive_client.send_dump()
		if _window != null and Input.is_action_just_pressed("viz2_diff"):
			_window.set_diff_mode(not _window.diff_mode())
		return
	var tw := _read_twist()
	if tw != Vector2.ZERO:
		_integrate(tw.x, tw.y, delta)
		_apply_pose()
		_update_chase_cam()
	# Dig / dump are recognized here so the full command surface (viz2_dig / viz2_dump) is
	# wired end-to-end. The conserved excavation/deposition physics is Phase B and is
	# deliberately NOT built in Phase A, so a press is acknowledged on the log — it is NEVER
	# faked as a terrain edit.
	if Input.is_action_just_pressed("viz2_dig"):
		print("viz2: dig (viz2_dig) — conserved excavation is Phase B (not wired in Phase A)")
	if Input.is_action_just_pressed("viz2_dump"):
		print("viz2: dump (viz2_dump) — conserved deposition is Phase B (not wired in Phase A)")


# Coerce a metadata value to a String, mapping null/absent to "" (JSON null would crash String()).
func _meta_str(v) -> String:
	if v == null:
		return ""
	return String(v)


# ── Phase G / G4: "About this DEM" provenance pane ────────────────────────────────────────
# Reads the loaded bundle's metadata.json dem_provenance block and shows the source + citation
# VERBATIM in a bottom-left overlay (rides the headless capture). The citation is echoed, never
# composed — a LOLA Product-78 tile shows Barker/Mazarico; the SfS tile shows Alexandrov & Beyer.
# A SYNTHETIC procedural bundle (citation=null) instead shows the red guardrail banner.
func _build_provenance_pane() -> void:
	var meta_path := _site_dir + "/metadata.json"
	var f := FileAccess.open(meta_path, FileAccess.READ)
	if f == null:
		return
	var parsed = JSON.parse_string(f.get_as_text())
	f.close()
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	var region := _meta_str(parsed.get("region", ""))
	var source := ""
	var citation := ""
	var frame := ""
	var prov = parsed.get("dem_provenance", {})
	if typeof(prov) == TYPE_DICTIONARY:
		# NULL-SAFE: a procedural bundle sets citation=null (JSON null) — String(null) throws, so
		# coerce a missing/null field to "" (a real DEM's fields are strings and pass through).
		source = _meta_str(prov.get("source", ""))
		citation = _meta_str(prov.get("citation", ""))
		frame = _meta_str(prov.get("frame", ""))
	# SYNTHETIC guardrail: a procedural bundle carries synthetic=true (top-level and/or in
	# dem_provenance) with a null citation. Render it UNMISTAKABLY so a synthetic frame can never
	# be mistaken for a real DEM (segregation guardrail; matches procedural_bundle metadata).
	var is_synth := bool(parsed.get("synthetic", false))
	if typeof(prov) == TYPE_DICTIONARY:
		is_synth = is_synth or bool(prov.get("synthetic", false))

	var layer := CanvasLayer.new()
	layer.name = "AboutThisDEM"
	add_child(layer)
	var panel := PanelContainer.new()
	panel.position = Vector2(12, maxf(0.0, float(_view_size.y) - 150.0))
	layer.add_child(panel)
	var col := VBoxContainer.new()
	col.custom_minimum_size = Vector2(minf(760.0, float(_view_size.x) - 24.0), 0)
	panel.add_child(col)

	# A red SYNTHETIC banner at the TOP of the pane for procedural terrain (only). Real DEMs get
	# none, so the two are visually unmistakable in the capture.
	if is_synth:
		var banner := Label.new()
		banner.text = "⚠ SYNTHETIC — PROCEDURAL TERRAIN (fbm_global; NO real citation)"
		banner.modulate = Color(1.0, 0.35, 0.30)
		col.add_child(banner)
		# Also stamp a large top-center watermark so a cropped screenshot still reads SYNTHETIC.
		var top := Label.new()
		top.name = "SyntheticWatermark"
		top.text = "SYNTHETIC PROCEDURAL TERRAIN"
		top.modulate = Color(1.0, 0.35, 0.30, 0.85)
		top.position = Vector2(maxf(0.0, float(_view_size.x) * 0.5 - 170.0), 14.0)
		layer.add_child(top)
		print("viz2: SYNTHETIC bundle — rendered with the procedural-terrain guardrail banner")

	var title := Label.new()
	title.text = ("SYNTHETIC terrain — %s" % region) if is_synth else ("About this DEM — %s" % region)
	col.add_child(title)
	var src := Label.new()
	src.text = "source: %s" % source
	src.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	col.add_child(src)
	var cite := Label.new()
	if is_synth and citation == "":
		cite.text = "citation: (none — SYNTHETIC procedural terrain, no real source)"
	else:
		cite.text = "citation: %s" % citation
	cite.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	col.add_child(cite)
	if frame != "":
		var fr := Label.new()
		fr.text = "frame: %s" % frame
		fr.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		fr.modulate = Color(0.72, 0.74, 0.80)
		col.add_child(fr)
	print("viz2: About-this-DEM pane — region='%s' citation='%s'" % [region, citation])


# ── headless auto-drive + capture ─────────────────────────────────────────────────────────
func _run_auto() -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_out_dir))
	# Drive forward with a gentle left turn — pressed on the InputMap so _read_twist() (the
	# interactive path) is what actually moves the rover (A5 verification).
	Input.action_press("viz2_forward", 0.85)
	Input.action_press("viz2_left", 0.30)
	var dt := 0.2   # scripted step: ~0.10 m/frame forward so motion is visible across N frames
	for i in range(_auto_frames):
		var tw := _read_twist()
		_integrate(tw.x, tw.y, dt)
		_apply_pose()
		_update_chase_cam()
		await RenderingServer.frame_post_draw
		await RenderingServer.frame_post_draw     # first buffer can be stale (render_test.gd)
		_save_main("viz2_frame_%03d.png" % i)
	Input.action_release("viz2_forward")
	Input.action_release("viz2_left")

	# A wide oblique OVERVIEW of the whole 2 km site (relief, unambiguous), rover still in it.
	var ext: Vector2 = sf.extent_m()
	var span := maxf(ext.x, ext.y)
	var eye := _field_center + Vector3(0.0, span * 0.55, span * 0.62)
	var look_target := _field_center + Vector3(0, sf.height_range.y - sf.height_range.x, 0)
	_cam.global_transform = _look_at_xf(eye, look_target, Vector3.UP)
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	_save_main("viz2_overview.png")

	print("viz2: auto — wrote %d drive frames + overview to %s; final pose=(%.1f, %.1f) yaw=%.0f°" % [
		_auto_frames, ProjectSettings.globalize_path(_out_dir), _pose_x, _pose_z, rad_to_deg(_pose_yaw)])
	get_tree().quit(0)


# ── Phase D: frame the rendered spatial-k rock field so the density gradient reads ────────
# Three framings of the rock window over the REAL terrain: an oblique aerial + a low oblique
# (grazing-sun shadows resolve individual rocks + the rover for scale) + a near-nadir plan (the
# density MAP — dense near the rim, sparse on the flat: the spatial-k, not a uniform sprinkle).
func _run_clast_capture() -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_out_dir))
	var center := _clast_center
	var span: float = maxf(_clast_span, 20.0)

	var eye1 := center + Vector3(-span * 0.14, span * 0.60, span * 0.60)
	_cam.global_transform = _look_at_xf(eye1, center, Vector3.UP)
	await _settle_and_capture("viz2_rockfield_aerial.png")

	var eye2 := center + Vector3(-span * 0.06, span * 0.16, span * 0.34)
	_cam.global_transform = _look_at_xf(eye2, center, Vector3.UP)
	await _settle_and_capture("viz2_rockfield_closeup.png")

	var eye3 := center + Vector3(0.001, span * 0.92, 0.001)
	_cam.global_transform = _look_at_xf(eye3, center, Vector3(0.0, 0.0, -1.0))
	await _settle_and_capture("viz2_rockfield_plan.png")

	print("viz2: rock-field capture — %d clasts, center=(%.1f,%.1f,%.1f) span=%.1f m, sun(az=%.0f,el=%.0f) -> %s" % [
		_clast_mmi.multimesh.instance_count, center.x, center.y, center.z, span,
		_sun_azim_deg, _sun_elev_deg, ProjectSettings.globalize_path(_out_dir)])
	get_tree().quit(0)


# ── Phase F: frame the planned route so its DETOUR around the rock cluster reads ──────────
# A near-nadir PLAN view (the detour is unambiguous from above: the bright route bends around the
# rock clump) + a low oblique (the boulders cast grazing shadows, the route threads past them). The
# framing spans BOTH the route bbox and the rock field so start, goal, cluster, and detour are in view.
func _run_path_capture() -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_out_dir))
	var center: Vector3 = _path_node.center
	if _clast_mmi != null:
		center = (_path_node.center + _clast_center) * 0.5   # frame route + rocks together
	var span: float = maxf(_path_node.span, _clast_span)
	span = maxf(span, 24.0)

	# near-nadir plan: the detour is clearest looking straight down.
	var eye_plan := center + Vector3(0.001, span * 1.05, 0.001)
	_cam.global_transform = _look_at_xf(eye_plan, center, Vector3(0.0, 0.0, -1.0))
	await _settle_and_capture("viz2_path_plan.png")

	# low oblique: grazing-sun shadows resolve the boulders; the route threads past them.
	var eye_obl := center + Vector3(-span * 0.10, span * 0.42, span * 0.62)
	_cam.global_transform = _look_at_xf(eye_obl, center, Vector3.UP)
	await _settle_and_capture("viz2_path_oblique.png")

	var n_rocks := 0 if _clast_mmi == null else _clast_mmi.multimesh.instance_count
	print("viz2: path capture — route %d wp / %.1f m detouring %d clasts, center=(%.1f,%.1f,%.1f) span=%.1f m -> %s" % [
		_path_node.n_waypoints, _path_node.route_length_m, n_rocks,
		center.x, center.y, center.z, span, ProjectSettings.globalize_path(_out_dir)])
	get_tree().quit(0)


func _save_main(fname: String) -> void:
	var path := _out_dir + "/" + fname
	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(path)
	if err != OK:
		push_error("viz2: save_png failed (%d) for %s" % [err, path])
	else:
		print("viz2: wrote %s (%dx%d)" % [
			ProjectSettings.globalize_path(path), img.get_width(), img.get_height()])


# ══════════════════════════════════════════════════════════════════════════════════════════
# Phase B3 — LIVE drive THROUGH the Viz2Runtime (conserved terramechanics + live rutting)
# ══════════════════════════════════════════════════════════════════════════════════════════

# Twist from the InputMap, scaled to the runtime's IPEx envelope (a Phase-A 0.6 m/s command would
# be M-04-refused). Same actions as _read_twist(), different ceilings.
func _read_twist_live() -> Vector2:
	var v := Input.get_action_strength("viz2_forward") - Input.get_action_strength("viz2_back")
	var om := Input.get_action_strength("viz2_left") - Input.get_action_strength("viz2_right")
	if Input.is_action_pressed("viz2_brake"):
		return Vector2.ZERO
	return Vector2(clampf(v, -1.0, 1.0) * LIVE_LIN, clampf(om, -1.0, 1.0) * LIVE_ANG)


# viz2-owned far CONTEXT plane (the frozen terrain.gd is NOT instantiated in live mode). Mirrors
# terrain.gd::_build_far_field: one low-poly PlaneMesh displaced in terrain_farfield.gdshader from a
# decimated height texture read through the FROZEN loader (read-only). The live window overdraws it.
func _build_far_context() -> void:
	var ext: Vector2 = sf.extent_m()
	# MISSION REGION: cover only a sub-area around the spawn (big rover ratio + fine terrain) instead of
	# the whole tile. _region_size==0 -> legacy full-tile render. 256 subdivisions over a ~100 m mission
	# = ~0.4 m/vertex (finer than the DEM), and the small plane is cheap.
	var use_region := _region_size > 0.0
	var rsize := clampf(_region_size, 60.0, minf(ext.x, ext.y))
	var rcenter := Vector2(_region_cx, _region_cz)
	if use_region:
		rcenter.x = clampf(rcenter.x, sf.world_min.x + rsize * 0.5, sf.world_max.x - rsize * 0.5)
		rcenter.y = clampf(rcenter.y, sf.world_min.y + rsize * 0.5, sf.world_max.y - rsize * 0.5)
	var pm := PlaneMesh.new()
	pm.size = Vector2(rsize, rsize) if use_region else ext
	pm.subdivide_width = 256
	pm.subdivide_depth = 256
	_far_context = MeshInstance3D.new()
	_far_context.name = "FarContext"
	_far_context.mesh = pm
	if use_region:
		_far_context.position = Vector3(rcenter.x, 0.0, rcenter.y)
	else:
		_far_context.position = Vector3(sf.world_min.x + ext.x * 0.5, 0.0, sf.world_min.y + ext.y * 0.5)
	var sm := ShaderMaterial.new()
	sm.shader = load("res://terrain_farfield.gdshader")
	sm.set_shader_parameter("height_lowres", sf.tex_height_lowres(2))   # was /4 -> 2x finer far height
	var lw := int(ceil(float(sf.width) / 2.0))
	sm.set_shader_parameter("lod_step_m", ext.x / float(maxi(lw, 1)))
	# region UV: map the plane's [0,1] UV to the mission region's slice of the full height/state textures
	if use_region:
		sm.set_shader_parameter("region_uv_offset", (rcenter - Vector2(rsize, rsize) * 0.5 - sf.world_min) / ext)
		sm.set_shader_parameter("region_uv_scale", Vector2(rsize / ext.x, rsize / ext.y))
	else:
		sm.set_shader_parameter("region_uv_offset", Vector2.ZERO)
		sm.set_shader_parameter("region_uv_scale", Vector2.ONE)
	sm.set_shader_parameter("state_tex", sf.tex_state())
	sm.set_shader_parameter("disturbance_tex", sf.tex_disturbance())
	sm.set_shader_parameter("mass_areal_tex", sf.tex_mass_areal())
	sm.set_shader_parameter("cut_depth_enabled", sf.has_uniform_mantle)
	sm.set_shader_parameter("mantle_areal_m0", sf.mantle_areal_m0)
	sm.set_shader_parameter("surface_density_cd", sf.mantle_surface_density)
	sm.set_shader_parameter("cut_depth_full_m", sf.cut_depth_full_m)
	sm.set_shader_parameter("fresh_albedo_gain", sf.maturity_albedo_ratio)
	sm.set_shader_parameter("hapke_enabled", sf.hapke_enabled)
	sm.set_shader_parameter("hapke_b", sf.hapke_b)
	sm.set_shader_parameter("hapke_c", sf.hapke_c)
	sm.set_shader_parameter("hapke_B0", sf.hapke_B0)
	sm.set_shader_parameter("hapke_h", sf.hapke_h)
	sm.set_shader_parameter("hapke_gain", sf.hapke_gain)
	_far_context.material_override = sm
	add_child(_far_context)


# Connect the drive client to the running Viz2Runtime (token handshake) + create the live window node.
func _setup_live() -> bool:
	if _session_dir == "":
		push_error("viz2: --live requires --session-dir <runtime session dir>")
		return false
	_window = Viz2WindowScript.new()
	_window.name = "Viz2TerrainWindow"
	add_child(_window)
	_drive_client = Viz2DriveClientScript.new()
	if not _drive_client.connect_runtime(_session_dir):
		push_error("viz2: live connect failed: %s" % _drive_client.error_msg)
		return false
	print("viz2: LIVE connected to Viz2Runtime (epoch %d) session=%s" % [_drive_client.epoch, _session_dir])
	return true


func _manifest_path(gen: int) -> String:
	return _session_dir.path_join("generations").path_join("gen_%08d" % gen).path_join("manifest.json")


# One live step: send the twist, drain telemetry, apply the NEWEST generation's manifest to the
# window (union coverage), THEN ack that generation (§2b.4 discipline), then seat the rover.
func _live_tick(v: float, omega: float) -> void:
	if _drive_client == null or not _drive_client.connected:
		return
	_drive_client.send_twist(v, omega)
	var n: int = _drive_client.poll_frames()
	if n > 0:
		# ACK a generation ONLY after its manifest is actually applied (or there was nothing new to
		# apply). Acking unconditionally advanced the runtime's union-coverage floor past regions the
		# window never rendered, dropping them from every future bbox until the next keyframe. (council #3)
		var applied_ok := true
		if _drive_client.latest_generation > _applied_gen:
			# origin-aware resync: if we coalesced PAST a recenter KEYFRAME, apply that keyframe FIRST so
			# the window repositions before the newest delta blits into it -- else the crop lands in the
			# old-origin texture and corrupts / mis-seats the rover on drive-away. (council #9)
			var kf: int = _drive_client.latest_keyframe_gen
			if kf > _applied_gen and kf < _drive_client.latest_generation:
				_window.apply_manifest_file(_manifest_path(kf))
			if _window.apply_manifest_file(_manifest_path(_drive_client.latest_generation)):
				_applied_gen = _drive_client.latest_generation
			else:
				applied_ok = false            # apply failed -> retry next tick, do NOT ack past it
		if applied_ok:
			_drive_client.ack(_drive_client.latest_seq)
		_place_rover_live()
		if not _stream:
			_seat_rover(1.0)          # non-stream (auto / interactive): seat immediately at the target


# Seat the rover at the runtime's REPORTED pose (the pose-tracking gate: rendered == telemetry),
# on the LIVE carved window surface where it covers the pose, else the static DEM.
func _place_rover_live() -> void:
	if not _drive_client.have_pose():
		return
	_target_x = _drive_client.latest_pose.x
	_target_z = _drive_client.latest_pose.y
	# runtime heading is math-convention (0=+x,+90=+z, CCW); Godot Basis(UP,yaw) rotates the OPPOSITE
	# sense in x-z, so negate so the mesh nose + camera track the ACTUAL travel direction (steering fix).
	_target_yaw = -_drive_client.latest_yaw
	if not _pose_init:                       # snap on the first pose (no glide from origin)
		_pose_x = _target_x
		_pose_z = _target_z
		_pose_yaw = _target_yaw
		_pose_init = true


# Glide the rendered pose toward the telemetry TARGET (dt-scaled; dt>=~0.07 s snaps), seat the rover on
# the live/DEM surface, and update the camera. Called every render frame in the stream for smooth motion
# between 15 Hz telemetry; called with dt=1.0 off-stream to snap immediately. (council #15)
func _seat_rover(dt: float) -> void:
	if _rover_root == null or not _pose_init:
		return
	var k := clampf(POSE_SMOOTH * dt, 0.0, 1.0)
	_pose_x = lerpf(_pose_x, _target_x, k)
	_pose_z = lerpf(_pose_z, _target_z, k)
	_pose_yaw = lerp_angle(_pose_yaw, _target_yaw, k)
	var surf_y: float = _window.height_at_world(_pose_x, _pose_z)
	if is_nan(surf_y):
		var u: float = clampf((_pose_x - sf.world_min.x) / sf.extent_m().x, 0.0, 1.0)
		var vv: float = clampf((_pose_z - sf.world_min.y) / sf.extent_m().y, 0.0, 1.0)
		surf_y = sf.height_uv(u, vv)
	_rover_root.transform = Transform3D(Basis(Vector3.UP, _pose_yaw),
		Vector3(_pose_x, surf_y + _root_lift, _pose_z))
	_update_stream_cam()


# Keep the far-field shader's window-rect uniforms in sync so it discards the coarse plane under the
# live fine window (no poke-through on slopes). (council #13)
func _update_farfield_window_uniforms() -> void:
	if _far_context == null or _window == null:
		return
	var mat := _far_context.material_override
	if mat is ShaderMaterial and _window.is_ready():
		var sm := mat as ShaderMaterial
		sm.set_shader_parameter("window_origin", _window.window_origin())
		sm.set_shader_parameter("window_side", _window.window_side_m())
		sm.set_shader_parameter("window_active", true)


# Headless live capture: connect -> drive forward (carving a TREAD/disturbance rut) -> DIG (carving a
# real height trench) -> capture. The rut+trench are read from the LIVE manifest textures the window
# mesh vertex-displaces (the NB-2 gate: v2's frozen mesh would have shown a static surface here).
func _run_live_auto() -> void:
	# This coroutine drives the runtime MANUALLY via _live_tick in its own loops. _process() must NOT
	# also run in live mode (Godot auto-enables it because the script defines it) — during a capture's
	# awaited frames it would re-run _live_tick + _update_chase_cam and STOMP the capture camera back to
	# the chase view (the window-capture-showed-the-chase-frame bug). Turn it off for the whole coroutine.
	set_process(false)
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_out_dir))
	# 1) wait for the connect keyframe -> initialize the live window node
	var tries := 0
	while (_window == null or not _window.is_ready()) and tries < 1200:
		_live_tick(0.0, 0.0)
		OS.delay_msec(5)
		tries += 1
	if _window == null or not _window.is_ready():
		push_error("viz2: live window never initialized (no keyframe within timeout)")
		get_tree().quit(6)
		return
	print("viz2: live window ready gen=%d origin=(%.1f,%.1f) side=%.2f m cell=%.3f" % [
		_applied_gen, _window.window_origin().x, _window.window_origin().y,
		_window.window_side_m().x, _window.fine_cell_m()])
	_place_rover_live()
	var start_pose: Vector2 = _drive_client.latest_pose

	# 2) drive a gentle left arc THROUGH the runtime for a fixed wall-duration, capturing periodically
	Input.action_press("viz2_forward", 1.0)
	Input.action_press("viz2_left", 0.10)
	var drive_ms := 7000
	var t_end := Time.get_ticks_msec() + drive_ms
	var next_cap := Time.get_ticks_msec()
	var i := 0
	while Time.get_ticks_msec() < t_end and i < _auto_frames:
		var lt := _read_twist_live()
		_live_tick(lt.x, lt.y)
		OS.delay_msec(15)
		if Time.get_ticks_msec() >= next_cap:
			await RenderingServer.frame_post_draw
			await RenderingServer.frame_post_draw
			_save_main("viz2_live_%03d.png" % i)
			i += 1
			next_cap += 550
	Input.action_release("viz2_forward")
	Input.action_release("viz2_left")
	# coast to a stop (zero twist), keep the link heartbeat alive
	for k in range(12):
		_live_tick(0.0, 0.0)
		OS.delay_msec(15)
	var drive_pose: Vector2 = _drive_client.latest_pose

	# 3) DIG — carve a real geometric trench under the rover (height drops; the window mesh displaces it)
	_drive_client.send_dig()
	for k in range(20):
		_live_tick(0.0, 0.0)
		OS.delay_msec(20)
	_place_rover_live()
	await _settle_and_capture("viz2_live_dig_chase.png")
	var dig_pose: Vector2 = _drive_client.latest_pose

	# 3b) DRIVE AWAY from the trench, then DUMP — spoil lands as a SEPARATE berm (a real height GAIN
	# the window mesh displaces upward). Separating the cut from the berm is the E3 contract: the diff
	# drape then shows cut(-) and berm(+) at distinct places, and observed cut-volume == cut_total_kg.
	Input.action_press("viz2_forward", 1.0)
	var haul_end := Time.get_ticks_msec() + 2600
	while Time.get_ticks_msec() < haul_end:
		var ht := _read_twist_live()
		_live_tick(ht.x, ht.y)
		OS.delay_msec(15)
	Input.action_release("viz2_forward")
	for k in range(8):
		_live_tick(0.0, 0.0)
		OS.delay_msec(15)
	_drive_client.send_dump()
	for k in range(20):
		_live_tick(0.0, 0.0)
		OS.delay_msec(20)
	_place_rover_live()
	var berm_pose: Vector2 = _drive_client.latest_pose

	# 4) the money shots: ISOLATE the live physics window (the static 4x-decimated context
	# plane would occlude it where its coarser height exceeds the window) and frame it tightly
	# so the carved TREAD rut path + the dug EXCAVATED trench + the placed berm are unambiguous.
	await _capture_window_closeup("viz2_live_window.png")
	await _capture_window_topdown("viz2_live_topdown.png")

	# 5) E2: the SIGNED DIFFERENCE DRAPE — toggle the diverging cut(blue)/berm(orange) falsecolor on
	# the SAME displaced window mesh and capture. This is the "dig and see the dispersion/cut-fill
	# patterns" deliverable; the frozen seams are untouched (a viz2-owned drape material swap).
	_window.set_diff_mode(true)
	await _capture_window_topdown("viz2_live_diff_topdown.png")
	await _capture_window_closeup("viz2_live_diff_closeup.png")
	_window.set_diff_mode(false)
	print("viz2: E2 diff drape captured — dig_pose=(%.2f,%.2f) berm_pose=(%.2f,%.2f)" % [
		dig_pose.x, dig_pose.y, berm_pose.x, berm_pose.y])

	# pose-tracking gate: rendered pose vs the runtime's reported pose (< 1 fine cell)
	var rp := Vector2(_pose_x, _pose_z)
	var dcell: float = rp.distance_to(_drive_client.latest_pose) / _window.fine_cell_m()
	print("viz2: LIVE auto done — start=(%.2f,%.2f) after-drive=(%.2f,%.2f) after-dig=(%.2f,%.2f) gen=%d" % [
		start_pose.x, start_pose.y, drive_pose.x, drive_pose.y,
		_drive_client.latest_pose.x, _drive_client.latest_pose.y, _applied_gen])
	print("viz2: drive distance=%.2f m  slip=%.3f  entrapped=%s" % [
		start_pose.distance_to(drive_pose), _drive_client.slip, str(_drive_client.entrapped)])
	print("viz2: POSE-TRACK rendered=(%.3f,%.3f) telemetry=(%.3f,%.3f) delta=%.3f cells" % [
		rp.x, rp.y, _drive_client.latest_pose.x, _drive_client.latest_pose.y, dcell])
	if _drive_client != null:
		_drive_client.close()
	get_tree().quit(0)


# ══════════════════════════════════════════════════════════════════════════════════════════
# Pixel-stream — continuous browser-driven LIVE loop + JPEG frame stream to the FastAPI server
# ══════════════════════════════════════════════════════════════════════════════════════════
#
# Reuses the ENTIRE B3 live path (Viz2Runtime drive client + moving-window mesh + chase cam). Each
# loop iteration drains browser control frames from the stream socket, drives ONE conserved step
# THROUGH the runtime (_live_tick), renders a fresh frame, captures the chase-cam viewport,
# JPEG-encodes it, and sends it length-prefixed to the server (which relays it to the browser as a
# binary WS frame). The awaited frame_post_draw paces the loop to the render rate (bounded by
# Engine.max_fps), so every streamed frame is a REAL render AFTER the drive step — the pixels change
# as the browser drives. No faked frames: get_viewport().get_texture().get_image() is the live GPU frame.
func _run_stream() -> void:
	# Drive the loop manually; _process() must NOT also run (it would re-seat the chase cam and
	# double-drive), exactly as _run_live_auto documents for the capture coroutine.
	set_process(false)
	if _stream_port <= 0:
		push_error("viz2: --stream requires --stream-port <server frame-seam port>")
		get_tree().quit(7)
		return
	_stream_io = Viz2StreamScript.new()
	if not _stream_io.connect_server(_stream_port):
		push_error("viz2: stream connect failed: %s" % _stream_io.error_msg)
		get_tree().quit(7)
		return
	print("viz2: STREAM connected to server frame seam on 127.0.0.1:%d" % _stream_port)

	# 1) wait for the runtime's connect keyframe -> initialize the live window node
	var tries := 0
	while (_window == null or not _window.is_ready()) and tries < 1200:
		_live_tick(0.0, 0.0)
		OS.delay_msec(5)
		tries += 1
	if _window == null or not _window.is_ready():
		push_error("viz2: stream — live window never initialized (no keyframe within timeout)")
		get_tree().quit(6)
		return
	_place_rover_live()
	Engine.max_fps = _stream_fps
	print("viz2: STREAM live — fps<=%d quality=%.2f window=gen%d — awaiting browser drive" % [
		_stream_fps, _stream_quality, _applied_gen])

	# 2) the continuous stream loop: input -> conserved drive -> render -> capture -> send
	var t_stop := Time.get_ticks_msec() + int(_stream_max_seconds * 1000.0)
	var sent := 0
	var last_t := Time.get_ticks_msec()
	var prev_cam := Transform3D()
	var prev_gen := -1
	while _stream_io.connected and Time.get_ticks_msec() < t_stop:
		var now := Time.get_ticks_msec()
		var dt := clampf(float(now - last_t) / 1000.0, 0.0, 0.1)   # real wall-clock dt (was nominal 1/fps)
		last_t = now
		var had_input := false
		for msg in _stream_io.poll_input():
			_apply_stream_input(msg)
			had_input = true
		# deadman recovery: re-handshake a dead / safe-stopped drive link (fresh epoch + keyframe) (#7)
		if _drive_client != null and (not _drive_client.connected or _drive_client.safe_stopped) \
				and now >= _next_reconnect_ms:
			_next_reconnect_ms = now + 1500
			if _drive_client.reconnect(_session_dir):
				_applied_gen = 0                 # force the fresh keyframe to re-sync the window
				print("viz2: STREAM drive reconnected (deadman recovery)")
		if _auto_traverse and not _waypoints.is_empty():
			var vo := _traverse_step()           # autonomous: steer toward the plotted waypoints
			_live_tick(vo.x, vo.y)
		else:
			_live_tick(_stream_v, _stream_omega)
		_seat_rover(dt)                          # glide the rendered pose toward telemetry (smooth motion)
		_update_farfield_window_uniforms()       # discard the coarse plane under the fine window (#13)
		_animate_rover(dt)
		# ONE post-draw wait: in a continuous loop the previous iteration already flushed state, so the
		# second wait (a one-shot-capture idiom for a stale first buffer) just halves fps. (council #1)
		await RenderingServer.frame_post_draw
		# Only read back + encode + send when something VISIBLY changed (physics advanced, driving, a
		# dig/dump gesture, a control input, or the camera moved) -> an idle viewer stops burning GPU
		# readback + JPEG + bandwidth on identical frames. (council n==0 + idle)
		var cam_xf := _cam.global_transform if _cam != null else Transform3D()
		var active_anim := _dig_anim_t > 0.0 or _dump_anim_t > 0.0 or absf(_manual_drum) > 1e-3
		var moving := absf(_stream_v) > 1e-4 or absf(_stream_omega) > 1e-4 or _auto_traverse
		var gliding := absf(_pose_x - _target_x) > 0.02 or absf(_pose_z - _target_z) > 0.02
		var changed := had_input or moving or active_anim or gliding or _applied_gen != prev_gen \
			or not cam_xf.is_equal_approx(prev_cam)
		if not changed:
			continue
		prev_gen = _applied_gen
		prev_cam = cam_xf
		var tex := get_viewport().get_texture()
		if tex == null:
			continue
		var img := tex.get_image()
		if img == null:                        # teardown race -> skip, do not deref a null image
			continue
		if img.get_format() != Image.FORMAT_RGB8:
			img.convert(Image.FORMAT_RGB8)     # JPEG has no alpha; encode a clean RGB frame
		var jpg := img.save_jpg_to_buffer(_stream_quality)
		if not _stream_io.send_frame(jpg):
			break
		sent += 1
		# periodic STATUS frame (slip / entrapment / pose) so the browser HUD shows the drive state, not
		# just pixels -- a stuck or entrapped rover reads instead of a mystery frozen image. (council #8)
		if sent % 12 == 0 and _drive_client != null:
			var st := {"type": "status", "slip": snappedf(_drive_client.slip, 0.001),
				"entrapped": _drive_client.entrapped, "safe_stop": _drive_client.safe_stopped,
				"x": snappedf(_pose_x, 0.1), "z": snappedf(_pose_z, 0.1),
				"yaw": snappedf(rad_to_deg(_pose_yaw), 0.1), "gen": _applied_gen}
			_stream_io.send_frame(JSON.stringify(st).to_utf8_buffer())
	_stream_io.close()
	if _drive_client != null:
		_drive_client.close()
	print("viz2: STREAM ended — %d frames sent, final gen=%d pose=(%.2f,%.2f)" % [
		sent, _applied_gen, _pose_x, _pose_z])
	get_tree().quit(0)


# Apply one browser control frame to the live drive. Twist is NORMALIZED intent [-1,1], scaled here
# to the runtime's IPEx envelope via the SAME LIVE_LIN/LIVE_ANG ceilings the interactive live path
# uses (so a browser command can never exceed the runtime's M-04 twist bound). dig/dump are one-shot
# conserved actions; sun_az/sun_el drive the single hard sun live.
func _apply_stream_input(msg: Dictionary) -> void:
	if msg.has("v") or msg.has("omega"):
		var v := clampf(float(msg.get("v", 0.0)), -1.0, 1.0)
		var om := clampf(float(msg.get("omega", 0.0)), -1.0, 1.0)
		_stream_v = v * LIVE_LIN
		# flip so the browser's LEFT (A / left-arrow, omega=+1) actually curves the rover to ITS left
		# in the world (it fed omega=+1 -> a right/CW arc before). (user-reported steering bug)
		_stream_omega = -om * LIVE_ANG
	if bool(msg.get("dig", false)) and _drive_client != null:
		_drive_client.send_dig()
		_dig_anim_t = DIG_ANIM_S
	if bool(msg.get("dump", false)) and _drive_client != null:
		_drive_client.send_dump()
		_dump_anim_t = DIG_ANIM_S
	# manual articulation: spin the drums + raise/lower each arm directly (full URDF control)
	if msg.has("drum"):
		_manual_drum = clampf(float(msg["drum"]), -1.0, 1.0)
	if msg.has("arm_front_d"):
		_arm_front_offset = clampf(_arm_front_offset + float(msg["arm_front_d"]), -0.4, 1.0)
	if msg.has("arm_back_d"):
		_arm_back_offset = clampf(_arm_back_offset + float(msg["arm_back_d"]), -0.4, 1.0)
	# planning: plot a waypoint from a canvas click, run/stop the autonomous traverse, clear the route
	if msg.has("click_px"):
		var p = msg["click_px"]
		_add_waypoint_from_click(float(p[0]), float(p[1]))
	if msg.has("traverse"):
		_auto_traverse = bool(msg["traverse"])
		if _auto_traverse and _wp_index >= _waypoints.size():
			_wp_index = 0
	if bool(msg.get("clear_wp", false)):
		_clear_waypoints()
	# analysis: toggle the slope-heatmap overlay on the terrain (path analysis vs grade)
	if msg.has("overlay"):
		var mode := 1 if String(msg["overlay"]) == "slope" else 0
		if _far_context != null and _far_context.material_override is ShaderMaterial:
			(_far_context.material_override as ShaderMaterial).set_shader_parameter("analysis_mode", mode)
		if _window != null:
			_window.set_analysis_mode(mode)
	if _sun != null and msg.has("sun_az"):
		_sun.rotation_degrees.y = float(msg["sun_az"])
	if _sun != null and msg.has("sun_el"):
		_sun.rotation_degrees.x = -float(msg["sun_el"])
	# camera-mode toggle (rover view <-> 3rd person) + orbit drag/zoom
	if bool(msg.get("cam_next", false)):
		_cam_mode = (_cam_mode + 1) % CAM_MODE_COUNT
	if msg.has("cam_mode"):
		_cam_mode = int(msg["cam_mode"]) % CAM_MODE_COUNT
	if msg.has("orbit_dyaw"):
		_orbit_yaw += deg_to_rad(float(msg["orbit_dyaw"]))
	if msg.has("orbit_dpitch"):
		_orbit_pitch = clampf(_orbit_pitch + deg_to_rad(float(msg["orbit_dpitch"])), 0.12, 1.45)
	if msg.has("orbit_dzoom"):
		var dz := float(msg["orbit_dzoom"])
		_orbit_radius = clampf(_orbit_radius + dz, 3.0, 40.0)       # orbit / top-down zoom
		_cam_zoom = clampf(_cam_zoom + dz * 0.06, 0.3, 3.0)         # chase / POV zoom (all modes now)
	_update_stream_cam()


# Robust capture: a full idle+draw cycle (process_frame) pushes any camera-transform change to
# the RenderingServer BEFORE the draw, then two post-draw waits ensure the new frame is on the
# GPU before get_image (a camera-only move otherwise samples the stale prior frame).
func _settle_and_capture(fname: String) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	_save_main(fname)


func _window_center() -> Vector3:
	var o: Vector2 = _window.window_origin()
	var side: Vector2 = _window.window_side_m()
	var cx := o.x + 0.5 * side.x
	var cz := o.y + 0.5 * side.y
	var h: float = _window.height_at_world(cx, cz)
	if is_nan(h):
		var u: float = clampf((cx - sf.world_min.x) / sf.extent_m().x, 0.0, 1.0)
		var vv: float = clampf((cz - sf.world_min.y) / sf.extent_m().y, 0.0, 1.0)
		h = sf.height_uv(u, vv)
	return Vector3(cx, h, cz)


# An oblique 3/4 aerial close-up of the LIVE window (far context hidden): the TREAD rut path +
# the dug EXCAVATED trench read as real vertex-displaced relief.
func _capture_window_closeup(fname: String) -> void:
	if _far_context != null:
		_far_context.visible = false
	var center := _window_center()
	var span: float = maxf(_window.window_side_m().x, _window.window_side_m().y)
	var eye := center + Vector3(-span * 0.30, span * 0.72, span * 0.60)
	_cam.global_transform = _look_at_xf(eye, center, Vector3.UP)
	await _settle_and_capture(fname)


# A near-nadir plan view of the whole LIVE window (far context hidden): the rut path + trench
# read as plan-view geometry against the vacuum background.
func _capture_window_topdown(fname: String) -> void:
	if _far_context != null:
		_far_context.visible = false
	var center := _window_center()
	var span: float = maxf(_window.window_side_m().x, _window.window_side_m().y)
	var eye := center + Vector3(0.001, span * 1.05, 0.001)
	_cam.global_transform = _look_at_xf(eye, center, Vector3(0.0, 0.0, -1.0))
	await _settle_and_capture(fname)
