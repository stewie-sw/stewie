"""T6.3: the 2D->3D handoff renders under the planner's mission-time sun (one solar authority)."""
from scripts.plan_render_pipeline import render_cmd


def test_render_cmd_threads_both_sun_angles():
    cmd = render_cmd("/tmp/scene", "x.png", sun_elev_deg=4.5, sun_az_deg=211.0)
    assert cmd[cmd.index("--sun-elev") + 1] == "4.5"
    assert cmd[cmd.index("--sun-azim") + 1] == "211.0"


def test_render_cmd_omits_sun_when_unset():
    cmd = render_cmd("/tmp/scene", "x.png")
    assert "--sun-elev" not in cmd and "--sun-azim" not in cmd
