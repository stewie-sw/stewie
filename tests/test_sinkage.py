"""TDD math-validation for the Bekker pressure-sinkage model (terramechanics).

These tests encode the closed-form Bekker math INDEPENDENTLY of the implementation
(known-answer), so they validate the equations, not just the code. Real lunar
moduli (NTRS 20220010732). Slip-sinkage/entrapment is out of scope (matches dustgym).
"""
from solnav.terramechanics import sinkage as sk


def test_moon_moduli_match_dustgym_nasa_ltv():
    # k_c=1400 N/m^2, k_phi=820000 N/m^3, n=1.0 (NASA LTV white paper NTRS 20220010732)
    assert sk.MOON.k_c == 1400.0 and sk.MOON.k_phi == 820000.0 and sk.MOON.n == 1.0


def test_bekker_inversion_known_answer():
    # z = (p / (k_c/b + k_phi*s))^(1/n); with p=1000, b=0.18, s=1, Moon moduli, n=1
    p, b = 1000.0, 0.18
    denom = 1400.0 / b + 820000.0 * 1.0
    expected = (p / denom) ** (1.0 / 1.0)
    assert abs(sk.bekker_sinkage(p, b_m=b, params=sk.MOON) - expected) < 1e-12


def test_pressure_definition():
    # p = load / (b * l)
    assert abs(sk.contact_pressure(12.15, 0.18, 0.10) - 12.15 / (0.18 * 0.10)) < 1e-9


def test_more_load_sinks_more():
    z_light = sk.wheel_sinkage(12.15, params=sk.MOON)     # dry ~12 N/wheel
    z_heavy = sk.wheel_sinkage(24.30, params=sk.MOON)     # loaded ~24 N/wheel
    assert z_heavy > z_light > 0


def test_smaller_contact_sinks_more():
    # a drum on a narrow contact patch sinks more than a wide wheel at equal load
    z_wheel = sk.wheel_sinkage(12.15, wheel_width_m=0.18, contact_len_m=0.10, params=sk.MOON)
    z_drum = sk.drum_sinkage(12.15, drum_len_m=0.20, contact_len_m=0.04, params=sk.MOON)
    assert z_drum > z_wheel


def test_softer_soil_sinks_more():
    # lower density stiffening s -> larger sinkage
    z_firm = sk.bekker_sinkage(1000.0, b_m=0.18, params=sk.MOON, density_factor=2.0)
    z_soft = sk.bekker_sinkage(1000.0, b_m=0.18, params=sk.MOON, density_factor=1.0)
    assert z_soft > z_firm


def test_static_load_per_contact_lunar():
    # dry 30 kg, lunar g, 4 wheels -> ~12.15 N/wheel (matches dustgym)
    assert abs(sk.static_load_per_contact(30.0, n_contacts=4) - 30.0 * 1.62 / 4) < 1e-6


def test_effective_height_drops_by_sinkage():
    drop = sk.effective_height_drop(nominal_height_m=0.30, sinkage_m=0.002)
    assert abs(drop - 0.298) < 1e-9


def test_dig_depth_adds_settle():
    # commanded cut + load-bearing settle = effective drum depth
    assert abs(sk.effective_dig_depth(0.05, 0.003) - 0.053) < 1e-9


def test_sinkage_wired_into_camera_height():
    # camera height under a posture drops by the sinkage; bearing on drums sinks more
    from solnav.posture import kinematics as kin
    ps = kin.posture("MEERKAT")
    h_wheel, _, z_wheel = kin.camera_height_with_sinkage(0.30, ps, 30.0, on_drums=False)
    h_drum, _, z_drum = kin.camera_height_with_sinkage(0.30, ps, 30.0, on_drums=True)
    assert z_drum > z_wheel > 0          # drums sink more than wheels
    assert h_drum < h_wheel              # so the camera sits lower on drums
