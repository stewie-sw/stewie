extends Node3D
# viz2_path.gd — STEWIE viz2 plan v4 Phase F (F2): draw the planned mission-route polyline.
#
# Reads a --path JSON (produced by scripts/viz2_path.py, which runs mission_planner.plan() over the
# REAL 1 m Haworth DEM with the rock-hazard keep-outs) whose "waypoints" are [x, height, z] in the
# SCENE WORLD frame — the SAME order-frame + GW-12 world mapping the clasts use
# (scene_x = x0 + c0*cell + local_x, scene_z = y0 + r0*cell + local_z, scene_y = DEM height). Godot
# cannot import Python, so the route is passed file-mediated exactly like the clast field.
#
# The route is drawn as a bright, unshaded EMISSIVE RIBBON (a flat band of width_m seated just above
# the surface) plus small node markers at each waypoint, so the DETOUR around the rock cluster reads
# in a plan-view capture. This node only DISPLAYS a real planner route; it never plans or edits terrain.

var center := Vector3.ZERO         # route bbox centre (scene frame) — used to frame the capture
var span := 0.0                    # route bbox horizontal span (m)
var n_waypoints := 0
var route_length_m := 0.0


func build_from_file(path_json: String, width_m: float = 1.0, lift_m: float = 0.35) -> bool:
	var f := FileAccess.open(path_json, FileAccess.READ)
	if f == null:
		push_error("viz2_path: --path file not readable: %s" % path_json)
		return false
	var parsed = JSON.parse_string(f.get_as_text())
	f.close()
	if typeof(parsed) != TYPE_DICTIONARY or not parsed.has("waypoints"):
		push_error("viz2_path: --path JSON missing a 'waypoints' array")
		return false
	return build(parsed["waypoints"], width_m, lift_m)


func build(waypoints: Array, width_m: float = 1.0, lift_m: float = 0.35) -> bool:
	if waypoints.size() < 2:
		push_warning("viz2_path: route has < 2 waypoints; nothing to draw")
		return false

	var pts: Array = []
	var lo := Vector3(INF, INF, INF)
	var hi := Vector3(-INF, -INF, -INF)
	route_length_m = 0.0
	var prev := Vector3.ZERO
	for i in range(waypoints.size()):
		var w = waypoints[i]
		var p := Vector3(float(w[0]), float(w[1]) + lift_m, float(w[2]))
		pts.append(p)
		lo = Vector3(minf(lo.x, p.x), minf(lo.y, p.y), minf(lo.z, p.z))
		hi = Vector3(maxf(hi.x, p.x), maxf(hi.y, p.y), maxf(hi.z, p.z))
		if i > 0:
			route_length_m += Vector2(p.x - prev.x, p.z - prev.z).length()
		prev = p

	# a bright unshaded emissive ribbon (double-sided so the plan-view nadir camera sees it)
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(0.10, 0.85, 1.0)
	mat.emission_enabled = true
	mat.emission = Color(0.10, 0.85, 1.0)
	mat.emission_energy_multiplier = 2.5
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED

	var im := ImmediateMesh.new()
	im.surface_begin(Mesh.PRIMITIVE_TRIANGLES, mat)
	var hw := width_m * 0.5
	for i in range(pts.size() - 1):
		var p0: Vector3 = pts[i]
		var p1: Vector3 = pts[i + 1]
		var dir := Vector3(p1.x - p0.x, 0.0, p1.z - p0.z)
		if dir.length() < 1e-6:
			continue
		dir = dir.normalized()
		var perp := Vector3(-dir.z, 0.0, dir.x) * hw     # horizontal offset -> a flat band on the ground
		var a0 := p0 + perp
		var a1 := p0 - perp
		var b0 := p1 + perp
		var b1 := p1 - perp
		for v in [a0, b0, b1, a0, b1, a1]:
			im.surface_add_vertex(v)
	im.surface_end()

	var ribbon := MeshInstance3D.new()
	ribbon.name = "RoutePolyline"
	ribbon.mesh = im
	add_child(ribbon)

	# endpoint markers (start = green, goal = amber) so the haul direction reads
	_add_marker(pts[0], Color(0.20, 1.0, 0.35), width_m * 1.6)
	_add_marker(pts[pts.size() - 1], Color(1.0, 0.70, 0.10), width_m * 1.6)

	center = (lo + hi) * 0.5
	span = maxf(hi.x - lo.x, hi.z - lo.z)
	n_waypoints = pts.size()
	print("viz2_path: drew %d-waypoint route (%.1f m) center=(%.1f,%.1f,%.1f) span=%.1f m" % [
		n_waypoints, route_length_m, center.x, center.y, center.z, span])
	return true


func _add_marker(pos: Vector3, col: Color, r: float) -> void:
	var sph := SphereMesh.new()
	sph.radius = maxf(r, 0.4)
	sph.height = sph.radius * 2.0
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = col
	m.emission_enabled = true
	m.emission = col
	m.emission_energy_multiplier = 2.0
	sph.material = m
	var mi := MeshInstance3D.new()
	mi.mesh = sph
	mi.position = pos
	add_child(mi)
