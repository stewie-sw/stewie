"""dynamic_cg.py -- VT-05: posture- and fill-dependent centre of gravity for the vehicle twin.

The static tip-over model (``stability.py``) needs a centre of gravity; the naive one is a single
LUMPED constant (``vehicles.get_vehicle(...).cg_height_m``, fore/aft centred). That is wrong for an
articulated bucket-drum excavator: IPEx carries most of its manoeuvring mass in TWO swinging RDS arms
and FOUR regolith-holding bucket drums, so the true CG walks fore/aft and up as the arms posture
(VT-03 ``ArmJointState``) and the drums fill (VT-04 ``DrumSet``). A 25 kg drum raised on the front arm
is the physical difference between "stable" and "one degree from tipping" -- exactly the
path-dependent failure a lumped CG hides.

``dynamic_cg`` COMPOSES the existing sourced pieces into the mass-weighted CG:

  * chassis dry mass + arm-link mass moment -- from ``arm_state`` geometry (``ARM_ORIGIN_FRONT/BACK``,
    ``ARM_LENGTH_M``, ``ARM_MASS_FRAC``) via the SAME tested engine ``ArmState.cg_offset_m`` that the
    posture/manoeuvre code already uses (one moment model, not a re-fabricated second one), driven by
    the two VT-03 ``ArmJointState`` joint angles;
  * per-drum fill moment -- the VT-04 ``DrumSet`` per-drum masses summed onto their arm and carried at
    the drum position, so a single loaded drum leans the CG toward its pivot;
  * the stowed lumped CG as the reference (arms horizontal, drums empty -> the classic
    ``cg_height_m``), plus the posture/fill shift on top.

Every mass and length is SOURCED, nothing fabricated: dry mass and the stowed CG height come from
``vehicles.get_vehicle`` (which reads ``ipex_specs``); the per-arm link mass is
``arm_state.ARM_MASS_FRAC`` of the dry mass (a documented [ASSUMPTION] tagged at its one source, i.e.
a dry-mass split, not an invented kilogram); the drum fill comes from the VT-04 ``DrumSet`` whose
capacity is the sourced 30 kg/cycle hold. The result feeds ``stability.stability`` directly:
``cg_z_m -> cg_height_m`` and ``cg_x_m -> cg_dx_m`` (the fore/aft pitch-lever offset), so the tip
margin becomes posture- and load-aware instead of static.

Reference convention (stated so the height is honest, not overclaimed): ``cg_offset_m`` measures the
drum/link height about the ARM PIVOT plane, so ``cg_z_m = cg_height_m + dz`` is a genuine absolute
mass-weighted height only under the [ASSUMPTION] that the RDS arm pivots at ~chassis-CG height (a
stow-horizontal drum then sits at CG height and adds no height shift; raising it lifts the CG). The
exact pivot-to-CG and base_link-to-ground offsets are figure-only in the public IPEx record, so that
reference is assumed, not fabricated. The fore/aft axis (``cg_x_m``, the stability-binding one on the
IPEx gauge>wheelbase geometry) carries no such assumption -- it is the exact mass-weighted offset.

The four-drum -> two-arm mapping is a stated modelling choice: the first half of the drums ride the
FRONT arm and the second half the REAR arm (IPEx has two bucket-drum halves per RDS arm; the exact
drum indexing is figure-only [ASSUMPTION]). For the IPEx four-drum set that is drums {0,1} -> front,
{2,3} -> rear.
"""
from __future__ import annotations

from dataclasses import dataclass

from stewie.physics import stability as _st
from stewie.physics.drum_set import DrumSet
from stewie.specs import vehicles as _veh
from stewie.specs.arm_joint import JOINT_FRONT, JOINT_REAR, ArmJointState
from stewie.specs.arm_state import ArmState


@dataclass(frozen=True)
class DynamicCG:
    """The mass-weighted centre of gravity for one articulated + loaded vehicle posture.

    ``cg_x_m`` is the fore/aft offset in base_link [m] (+ toward the FRONT arm; 0 = the stowed-empty
    centred CG). ``cg_z_m`` is the CG height above the wheel-contact plane [m] (the stowed
    ``cg_height_m`` plus the posture/fill height shift). ``cg_y_m`` is the lateral offset [m], 0 in
    this planar two-arm model (both arms sit on the fore/aft centreline). ``front_drum_kg`` /
    ``rear_drum_kg`` are the per-arm regolith loads the CG was built from; ``total_mass_kg`` is
    ``dry + total drum fill``; ``stowed_cg_height_m`` is the lumped reference the shift was added to.
    """

    cg_x_m: float
    cg_z_m: float
    cg_y_m: float
    total_mass_kg: float
    front_drum_kg: float
    rear_drum_kg: float
    stowed_cg_height_m: float
    vehicle: str

    @property
    def cg_dx_m(self) -> float:
        """The fore/aft offset in ``stability.py``'s vocabulary (its ``cg_dx_m`` pitch-lever input)."""
        return self.cg_x_m

    def stability(self, pitch_deg: float, roll_deg: float) -> dict[str, object]:
        """Feed this dynamic CG into the static tip-over model (VT-06): the tip margin now moves with
        posture + load instead of a lumped constant. Reuses ``stability.stability`` with this CG's
        height and fore/aft offset and the vehicle's own gauge/wheelbase from the registry."""
        veh = _veh.get_vehicle(self.vehicle)
        return _st.stability(pitch_deg, roll_deg, gauge_m=veh.gauge_m, wheelbase_m=veh.wheelbase_m,
                             cg_height_m=self.cg_z_m, cg_dx_m=self.cg_x_m)


def _split_drums(drums: DrumSet) -> tuple[float, float]:
    """Sum the VT-04 per-drum fills onto the two RDS arms: the first half of the drums -> front arm,
    the second half -> rear arm (see the module docstring for the [ASSUMPTION])."""
    per = drums.per_drum_fill
    half = drums.n_drums // 2
    return float(sum(per[:half])), float(sum(per[half:]))


def dynamic_cg(front: ArmJointState, rear: ArmJointState, drums: DrumSet, *,
               vehicle: str = "ipex") -> DynamicCG:
    """Compose the vehicle twin's mass-weighted CG from chassis mass, arm pose, and per-drum fill.

    ``front`` / ``rear`` are the VT-03 joint states (their ``angle_deg`` drives the arm-mass moment);
    ``drums`` is the VT-04 per-drum fill (its per-drum masses drive the drum-mass moment). Masses and
    the stowed CG height come from the ``vehicles`` registry (sourced ``ipex_specs``). The arm/drum
    moment is the tested ``ArmState.cg_offset_m`` engine; this function maps the typed VT-03/VT-04
    records onto it and adds the stowed reference, returning the absolute CG (which then feeds
    ``stability`` / VT-06). The CG moves whenever an arm angle changes or a drum fills -- that is the
    VT-05 acceptance (a distributed CG, not a static lumped one).
    """
    if front.joint != JOINT_FRONT:
        raise ValueError(f"front joint must be {JOINT_FRONT!r}, got {front.joint!r}")
    if rear.joint != JOINT_REAR:
        raise ValueError(f"rear joint must be {JOINT_REAR!r}, got {rear.joint!r}")

    veh = _veh.get_vehicle(vehicle)
    dry_mass_kg = float(veh.dry_mass_kg)
    stowed_cg_height_m = float(veh.cg_height_m)

    front_drum_kg, rear_drum_kg = _split_drums(drums)

    # ONE moment model: reuse the tested arm/drum CG-shift engine, driven by the VT-03 joint angles.
    arm = ArmState(front_deg=float(front.angle_deg), back_deg=float(rear.angle_deg))
    dx_m, dz_m = arm.cg_offset_m(front_drum_kg=front_drum_kg, back_drum_kg=rear_drum_kg,
                                 dry_mass_kg=dry_mass_kg)

    return DynamicCG(
        cg_x_m=float(dx_m),                          # fore/aft, exact mass-weighted offset
        cg_z_m=stowed_cg_height_m + float(dz_m),     # height = stowed lumped ref + posture/fill shift
        cg_y_m=0.0,                                  # planar two-arm model: laterally centred
        total_mass_kg=dry_mass_kg + front_drum_kg + rear_drum_kg,
        front_drum_kg=front_drum_kg,
        rear_drum_kg=rear_drum_kg,
        stowed_cg_height_m=stowed_cg_height_m,
        vehicle=veh.name,
    )
