extends Node3D
# Standalone P5 validation scene (solnav's own; does NOT touch John's read-only godot_sidecar).
# A known POST_H-metre post on a plane, directional shadows ON, moderate Sun, TOP-DOWN ORTHOGRAPHIC
# camera so image distance maps exactly to ground distance (m/pixel = cam.size / viewport_height).
# Renders one PNG; solnav reads the cast-shadow length -> H = L*tan(e), validated vs POST_H.

const POST_H := 1.0          # true post height (m) -- the P5 ground-truth
const ORTHO_SIZE := 6.0      # camera vertical extent (m); m/pixel = ORTHO_SIZE / height

func _args() -> Dictionary:
	var d := {"elev": 30.0, "azim": 135.0, "out": "res://p5_out.png"}
	var a := OS.get_cmdline_user_args()
	var i := 0
	while i < a.size():
		match a[i]:
			"--elev": i += 1; d.elev = float(a[i])
			"--azim": i += 1; d.azim = float(a[i])
			"--out": i += 1; d.out = a[i]
		i += 1
	return d

func _ready() -> void:
	var args := _args()
	_build_scene(args.elev, args.azim)
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(args.out)
	if err != OK:
		push_error("save_png failed: %d" % err); get_tree().quit(1); return
	print("wrote ", args.out, " size=", img.get_width(), "x", img.get_height(),
		" elev=", args.elev, " azim=", args.azim, " m_per_px=", ORTHO_SIZE / img.get_height(),
		" post_h=", POST_H)
	get_tree().quit(0)

func _build_scene(elev: float, azim: float) -> void:
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-elev, azim, 0.0)
	sun.light_energy = 1.3
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_ORTHOGONAL
	add_child(sun)

	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.02, 0.02, 0.03)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	env.environment = e
	add_child(env)

	var plane := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(20, 20)
	plane.mesh = pm
	var pmat := StandardMaterial3D.new()
	pmat.albedo_color = Color(0.55, 0.52, 0.50)
	pmat.roughness = 0.95
	plane.material_override = pmat
	add_child(plane)

	var post := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = Vector3(0.08, POST_H, 0.08)
	post.mesh = bm
	post.position = Vector3(0, POST_H * 0.5, 0)
	var cmat := StandardMaterial3D.new()
	cmat.albedo_color = Color(0.6, 0.57, 0.53)
	post.material_override = cmat
	add_child(post)

	var cam := Camera3D.new()
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	cam.size = ORTHO_SIZE
	cam.near = 0.05
	cam.far = 100.0
	add_child(cam)
	cam.look_at_from_position(Vector3(0, 10, 0), Vector3(0, 0, 0), Vector3(0, 0, -1))
