"""#242 increment 1: the per-cell density where the rover is TRAVERSING must stiffen BEARING (sinkage),
not just shear. The drive loop already read cs.density for cohesion/friction; this closes the other half
so a compacted trail (density up) sinks LESS on the next pass. Reuses the GROUNDED density_stiffening
relation (terramechanics.py) -- no invented law. density=None / surface density == the prior s=1 behavior
(back-compat). Real conserved-physics; no synthetic data."""
import math

from stewie.physics import slip, terramechanics as tm


def test_wheel_static_sinkage_responds_to_density():
    p = tm.TerramechanicsParams.from_constants()
    loose = tm.wheel_static_sinkage(300.0, params=p, contact_len_m=0.10, contact_width_m=0.18,
                                    density=p.rho_surface)            # density_stiffening == 1
    dense = tm.wheel_static_sinkage(300.0, params=p, contact_len_m=0.10, contact_width_m=0.18,
                                    density=p.rho_deep)               # compacted -> factor > 1
    none = tm.wheel_static_sinkage(300.0, params=p, contact_len_m=0.10, contact_width_m=0.18, density=None)
    assert dense < loose, "denser (compacted) ground must sink LESS than loose surface"
    assert abs(none - loose) < 1e-9, "density=None must equal loose-surface density (s=1 back-compat)"


def test_slip_sinkage_equilibrium_responds_to_density():
    p = tm.TerramechanicsParams.from_constants()
    loose = slip.slip_sinkage_equilibrium(300.0, math.radians(10.0), params=p, density=p.rho_surface)
    dense = slip.slip_sinkage_equilibrium(300.0, math.radians(10.0), params=p, density=p.rho_deep)
    none = slip.slip_sinkage_equilibrium(300.0, math.radians(10.0), params=p, density=None)
    assert dense["sinkage_m"] < loose["sinkage_m"], "compacted ground -> less sinkage through the slip solve"
    assert abs(none["sinkage_m"] - loose["sinkage_m"]) < 1e-9, "density=None == loose surface (back-compat)"
