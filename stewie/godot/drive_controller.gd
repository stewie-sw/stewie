extends Node
# Real-time drive view: the intern drives the rover (WASD) and watches what it sees through the live
# 8-camera rig, at 60 fps. Reuses the sidecar scene/rover/rig builders and CameraRigScript; the rover
# pose is integrated by a GDScript port of rover.step_pose (the conserved Python authority stays the
# analysis/export tier). Posture buttons reload a posture (arm angles from ipex_postures.json) and
# rebuild the rig faithfully. This is the terrain-modeller's mapping/planning drive view (prototype).

const CameraRigScript := preload("res://camera_rig.gd")
const ARM_L := 0.388245
const WHEEL_R := 0.1524
const JOINT_AXIS := Vector3(0, 0, -1)
const PANES := ["front_left", "front_right", "left_mono", "drum_front_cam",
                "rear_left", "rear_right", "right_mono", "drum_back_cam"]
const MOUNTS := {
    "front_left": Vector3(0.30, -0.10, 0.035), "front_right": Vector3(0.30, -0.10, -0.035),
    "rear_left": Vector3(-0.30, -0.10, 0.035), "rear_right": Vector3(-0.30, -0.10, -0.035),
    "left_mono": Vector3(0.0, -0.05, 0.285), "right_mono": Vector3(0.0, -0.05, -0.285),
    "drum_front_cam": Vector3(0.10, 0.18, 0.0), "drum_back_cam": Vector3(-0.10, 0.18, 0.0)}

var sidecar: Node
var sf
var cams: Array = []
var rover_root: Node3D
var pose_x := 0.0
var pose_z := 0.0
var pose_yaw := 0.0
var drop := 0.0
var af := 0.65
var ab := 0.65
var postures := {}
var auto_frames := 0
var _tick := 0
var _tex_rects := {}
var _labels := {}
var _status: Label


func setup(p_sidecar: Node, p_sf, p_auto: int) -> void:
    sidecar = p_sidecar
    sf = p_sf
    auto_frames = p_auto
    _load_postures()
    _rebuild_rig()
    pose_x = rover_root.global_transform.origin.x
    pose_z = rover_root.global_transform.origin.z
    _build_ui()
    set_process(true)


func _load_postures() -> void:
    var path := ProjectSettings.globalize_path("res://") + "../terrain_authority/data/ipex_postures.json"
    var f := FileAccess.open(path, FileAccess.READ)
    if f:
        var doc = JSON.parse_string(f.get_as_text())
        if doc and doc.has("postures"):
            postures = doc["postures"]


func _arm_drop(pitch: float) -> float:
    return ARM_L * sin(max(0.0, -pitch))


func _chassis_lift(a: float, b: float) -> float:
    var fr: float = max(_arm_drop(a), WHEEL_R)
    var bk: float = max(_arm_drop(b), WHEEL_R)
    return 0.5 * (fr + bk) - WHEEL_R


func _posture_pitch(a: float, b: float) -> float:
    return atan2(max(_arm_drop(a), WHEEL_R) - max(_arm_drop(b), WHEEL_R), 0.40)


func _cam_height(name: String) -> float:
    var m: Vector3 = MOUNTS[name]
    var p := _posture_pitch(af, ab)
    var up := m.x * sin(p) + m.y * cos(p)
    return WHEEL_R + _chassis_lift(af, ab) + up


func _rebuild_rig() -> void:
    var old = sidecar._find_rover_root()
    if old != null:
        old.free()
    sidecar._arm_front_pitch_override = af
    sidecar._arm_back_pitch_override = ab
    sidecar._chassis_lift_m = _chassis_lift(af, ab)
    sidecar._build_rover()
    rover_root = sidecar._find_rover_root()
    if drop != 0.0 or pose_x != 0.0:           # preserve the driven pose across a posture rebuild
        _apply_pose()
    var world := sidecar.get_viewport().world_3d
    cams = CameraRigScript.build(sidecar, rover_root, world, sidecar._viewport_size, sidecar._cam_pitch_deg)
    for e in cams:
        e["sv"].render_target_update_mode = SubViewport.UPDATE_ALWAYS   # live: render every frame
        if _tex_rects.has(e["image"]):
            _tex_rects[e["image"]].texture = e["sv"].get_texture()


func _apply_pose() -> void:
    var u: float = clampf((pose_x - sf.world_min.x) / sf.extent_m().x, 0.0, 1.0)
    var v: float = clampf((pose_z - sf.world_min.y) / sf.extent_m().y, 0.0, 1.0)
    var surf_y: float = sf.height_uv(u, v)
    rover_root.transform = Transform3D(Basis(Vector3.UP, pose_yaw), Vector3(pose_x, surf_y + WHEEL_R + _chassis_lift(af, ab), pose_z))


func _build_ui() -> void:
    var layer := CanvasLayer.new()
    add_child(layer)
    var root := VBoxContainer.new()
    layer.add_child(root)
    _status = Label.new()
    root.add_child(_status)
    var grid := GridContainer.new()
    grid.columns = 4
    root.add_child(grid)
    for name in PANES:
        var vb := VBoxContainer.new()
        var tr := TextureRect.new()
        tr.custom_minimum_size = Vector2(260, 195)
        tr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
        for e in cams:
            if e["image"] == name:
                tr.texture = e["sv"].get_texture()
        var lbl := Label.new()
        vb.add_child(tr); vb.add_child(lbl); grid.add_child(vb)
        _tex_rects[name] = tr; _labels[name] = lbl
    var bar := HBoxContainer.new()
    root.add_child(bar)
    for pname in ["TRANSIT", "DIG", "DUMP_Z", "MEERKAT", "IRON_CROSS", "COBRA"]:
        var btn := Button.new()
        btn.text = pname
        btn.pressed.connect(_on_posture.bind(pname))
        bar.add_child(btn)


func _on_posture(pname: String) -> void:
    if postures.has(pname):
        af = float(postures[pname]["arm_front_pitch_rad"])
        ab = float(postures[pname]["arm_back_pitch_rad"])
        _rebuild_rig()


func _process(delta: float) -> void:
    var v := 0.0
    var om := 0.0
    if auto_frames > 0:
        v = 0.4; om = 0.06                      # scripted drive (headless verification)
    else:
        if Input.is_key_pressed(KEY_W): v += 0.5
        if Input.is_key_pressed(KEY_S): v -= 0.5
        if Input.is_key_pressed(KEY_A): om += 0.7
        if Input.is_key_pressed(KEY_D): om -= 0.7
    pose_yaw += om * delta
    var fwd := Basis(Vector3.UP, pose_yaw) * Vector3(1, 0, 0)
    pose_x += v * fwd.x * delta
    pose_z += v * fwd.z * delta
    _apply_pose()
    _status.text = "DRIVE  pos=(%.2f, %.2f) yaw=%.0f deg  arms=(%.2f, %.2f) lift=%.3f m  (WASD to drive; buttons load a posture)" % [
        pose_x, pose_z, rad_to_deg(pose_yaw), af, ab, _chassis_lift(af, ab)]
    for name in PANES:
        _labels[name].text = "%s  h=%+.2f m" % [name, _cam_height(name)]
    if auto_frames > 0:
        _tick += 1
        if _tick >= auto_frames:
            await RenderingServer.frame_post_draw
            await RenderingServer.frame_post_draw
            # Composite the 8 LIVE camera feeds into one grid image in-engine (robust headless capture
            # + the exportable view; the interactive window shows the TextureRect grid directly).
            var _flush = sidecar.get_viewport().get_texture().get_image()   # force a draw flush so the SubViewport targets are current
            for e in cams:                                                   # save each LIVE feed (proven path)
                e["sv"].get_texture().get_image().save_png(
                    ProjectSettings.globalize_path("res://out/drive_cam_%s" % e["image"]))
            print("drive: wrote 8 live cam frames after ", _tick, " frames; final pos=(%.2f,%.2f)" % [pose_x, pose_z])
            sidecar.get_tree().quit(0)
