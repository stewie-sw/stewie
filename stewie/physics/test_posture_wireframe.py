from stewie.physics import posture_a3 as kin
from stewie.physics import posture_wireframe as wireframe


def test_skeleton_returns_polylines_for_each_posture():
    for name, (af, ar) in kin.POSTURES.items():
        polys, meta = wireframe.rover_skeleton(af, ar)
        assert len(polys) > 10                     # ground + chassis + wheels + arms + drums
        assert all(p.ndim == 2 and p.shape[1] == 3 for p in polys)
        assert "lift_m" in meta and "pitch_deg" in meta


def test_raised_posture_skeleton_sits_higher():
    polys_t, _ = wireframe.rover_skeleton(*kin.POSTURES["TRANSIT"])
    polys_m, _ = wireframe.rover_skeleton(*kin.POSTURES["IRON_CROSS"])
    max_z_t = max(p[:, 2].max() for p in polys_t)
    max_z_m = max(p[:, 2].max() for p in polys_m)
    assert max_z_m > max_z_t                        # raised chassis -> higher skeleton


def test_one_sided_skeleton_is_tilted():
    polys, meta = wireframe.rover_skeleton(*kin.POSTURES["MEERKAT_1S"])
    assert meta["pitch_deg"] > 10.0                 # one-sided -> pitched body
