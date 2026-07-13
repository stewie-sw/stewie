extends RefCounted
class_name Viz2SunHud
# viz2 Phase C — the interactive SUN az/el HUD (viz2 plan v4, task C1).
#
# A CanvasLayer overlay with two sliders — azimuth (0..360 deg) and elevation (-5..+90 deg) —
# that drive the scene's single DirectionalLight3D through the FROZEN sun convention
#   sun.rotation_degrees = Vector3(-elevation, azimuth, 0)
# the SAME convention sun_sweep.gd (sun_sweep.gd:121) and viz2_root._setup_environment
# (viz2_root.gd:196) use, so the interactive sun and the scripted sun-sweep agree exactly.
#
# The grazing-polar-band annotation highlights when the elevation is inside the documented
# grazing band [0, SUN_ELEVATION_DEG_POLAR]. SUN_ELEVATION_DEG_POLAR = 7.0 deg is the polar
# hillshade band cap (stewie/specs/constants.py:46 [FIXED] spec 5.1; a DOCUMENTED ASSUMPTION,
# NOT a mission value) — the same constant sun_sweep.gd's EL_MAX carries.
#
# The HUD only OWNS the light's rotation; it never edits the frozen sidecar/sun_sweep. The
# headless capture path drives the same light through --sun-az/--sun-el instead of the sliders
# (viz2_root), so a capture is reproducible without the HUD.

# Grazing polar band cap [deg] — stewie/specs/constants.py:46 SUN_ELEVATION_DEG_POLAR (FIXED).
const GRAZING_BAND_MAX_DEG := 7.0
const AZ_MIN := 0.0
const AZ_MAX := 360.0
const EL_MIN := -5.0
const EL_MAX := 90.0

var _sun: DirectionalLight3D
var _az_slider: HSlider
var _el_slider: HSlider
var _readout: Label
var _band: Label
var _layer: CanvasLayer

# Live values (kept in sync with the sliders; also the headless-override entry points).
var azimuth_deg := 135.0
var elevation_deg := 22.0


# Build the HUD under `host` and bind it to `sun`. Seeds the sliders at the scene's current
# sun az/el. Returns the CanvasLayer (also stored). `_apply()` drives the light immediately so
# the light + labels match the sliders from frame 0.
func build(host: Node, sun: DirectionalLight3D, azim0: float, elev0: float) -> CanvasLayer:
	_sun = sun
	azimuth_deg = clampf(azim0, AZ_MIN, AZ_MAX)
	elevation_deg = clampf(elev0, EL_MIN, EL_MAX)

	_layer = CanvasLayer.new()
	_layer.name = "SunHud"
	host.add_child(_layer)

	var panel := PanelContainer.new()
	panel.position = Vector2(12, 12)
	_layer.add_child(panel)
	var root := VBoxContainer.new()
	root.custom_minimum_size = Vector2(320, 0)
	panel.add_child(root)

	var title := Label.new()
	title.text = "SUN (interactive)"
	root.add_child(title)

	_readout = Label.new()
	root.add_child(_readout)

	root.add_child(_slider_row("Azimuth", AZ_MIN, AZ_MAX, azimuth_deg, true))
	root.add_child(_slider_row("Elevation", EL_MIN, EL_MAX, elevation_deg, false))

	_band = Label.new()
	root.add_child(_band)

	_apply()
	return _layer


# One "<name>  [slider]" row. `is_az` routes the slider's value_changed to the az/el handler and
# stashes the slider ref so the headless override can move it (which re-fires value_changed).
func _slider_row(name: String, lo: float, hi: float, val: float, is_az: bool) -> HBoxContainer:
	var row := HBoxContainer.new()
	var lbl := Label.new()
	lbl.text = name
	lbl.custom_minimum_size = Vector2(84, 0)
	row.add_child(lbl)
	var sl := HSlider.new()
	sl.min_value = lo
	sl.max_value = hi
	sl.step = 1.0
	sl.value = val
	sl.custom_minimum_size = Vector2(210, 0)
	sl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(sl)
	if is_az:
		_az_slider = sl
		sl.value_changed.connect(_on_az)
	else:
		_el_slider = sl
		sl.value_changed.connect(_on_el)
	return row


func _on_az(v: float) -> void:
	azimuth_deg = clampf(v, AZ_MIN, AZ_MAX)
	_apply()


func _on_el(v: float) -> void:
	elevation_deg = clampf(v, EL_MIN, EL_MAX)
	_apply()


# Drive the light and refresh the labels. The ONE place the sun convention is applied.
func _apply() -> void:
	if _sun != null:
		_sun.rotation_degrees = Vector3(-elevation_deg, azimuth_deg, 0.0)
	if _readout != null:
		_readout.text = "az %.1f deg   el %.1f deg" % [azimuth_deg, elevation_deg]
	if _band != null:
		if elevation_deg >= 0.0 and elevation_deg <= GRAZING_BAND_MAX_DEG:
			_band.text = "GRAZING POLAR BAND (0-%.0f deg) — long shadows" % GRAZING_BAND_MAX_DEG
			_band.modulate = Color(1.0, 0.78, 0.28)     # amber: inside the grazing band
		elif elevation_deg < 0.0:
			_band.text = "SUN BELOW HORIZON (el < 0) — no direct illumination"
			_band.modulate = Color(0.75, 0.45, 0.45)
		else:
			_band.text = "above grazing band (el > %.0f deg)" % GRAZING_BAND_MAX_DEG
			_band.modulate = Color(0.7, 0.72, 0.78)


# --- headless overrides (also what --hud-selfcheck drives): move the slider so value_changed
# fires the SAME handler the human drag uses, then the light + labels update through _apply(). ---
func set_azimuth(deg: float) -> void:
	if _az_slider != null:
		_az_slider.value = clampf(deg, AZ_MIN, AZ_MAX)   # fires _on_az -> _apply
	else:
		_on_az(deg)


func set_elevation(deg: float) -> void:
	if _el_slider != null:
		_el_slider.value = clampf(deg, EL_MIN, EL_MAX)   # fires _on_el -> _apply
	else:
		_on_el(deg)
