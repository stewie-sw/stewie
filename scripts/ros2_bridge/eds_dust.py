#!/usr/bin/env python3
"""EDS (electrodynamic dust shield) lens-occlusion model — IPEx Camera & Dust Mitigation (SCHULER24 §V.B).

IPEx's primary job is to excavate and move regolith, so its cameras WILL dust over. The documented
three-pronged mitigation chain:

  1. each camera carries a transparent **EDS lens cover** that accumulates dust (transmittance drops);
  2. an **AC EDS clear cycle** removes most of the dust but leaves a RESIDUAL (the paper: "a portion of
     dust contaminants to remain after clearing");
  3. an **HDRM** (Frangibolt) **jettisons the cover** as a last resort if the EDS can no longer clear it,
     plus a **fully redundant camera set** for unknown dust loading.

This models that chain and applies the resulting transmittance to a REAL rendered camera frame, so the
perception stack can be exercised against dust-degraded imagery (the path-dependent perception-failure
story: drive, kick up dust, lose acuity, clear/jettison, recover). The STRUCTURE is sourced; the
dust-rate / residual-fraction / transmittance-floor COEFFICIENTS are [CALIB] (the paper documents the
chain qualitatively, not numbers) — exposed as constructor knobs, never fabricated as "measured".

Pure numpy (host-testable); no cv2/rclpy/Godot dependency. It never invents pixels: a clean shield
(coverage 0) is an identity pass; dust only ATTENUATES the real frame (+ an optional veiling-haze term).
"""
from __future__ import annotations

import numpy as np

# [CALIB] defaults (documented chain, unsourced coefficients):
ACCUM_RATE = 0.10          # dust coverage gained per unit exposure (drive/dig time)
CLEAR_RESIDUAL_FRAC = 0.20 # fraction of dust LEFT after one EDS clear cycle (the documented residual)
TRANSMIT_FLOOR = 0.05      # transmittance at full coverage (a fully dusted cover still passes a little)


def dust_transmittance(coverage: float, *, floor: float = 0.0) -> float:
    """Lens transmittance [floor, 1] for a dust coverage [0, 1]. Clean (coverage 0) -> 1; fully covered
    -> ``floor``. Linear optical attenuation: tau = 1 - coverage*(1 - floor)."""
    c = min(1.0, max(0.0, float(coverage)))
    return 1.0 - c * (1.0 - float(floor))


def apply_occlusion(image, transmittance: float, *, haze: float = 0.0):
    """Apply a lens transmittance (+ optional additive veiling haze from forward-scattered light off the
    dust) to a real frame. ``out = clip(image*transmittance + haze, 0, max)``, same shape + dtype. A
    transmittance of 1 with haze 0 is the identity (no fabricated pixels)."""
    img = np.asarray(image)
    info_max = np.iinfo(img.dtype).max if np.issubdtype(img.dtype, np.integer) else 1.0
    out = np.clip(img.astype(np.float64) * float(transmittance) + float(haze), 0.0, info_max)
    return out.astype(img.dtype)


class EDSDustShield:
    """Stateful EDS lens cover: accumulate dust, run AC clear cycles (leave a residual), jettison the
    cover via the HDRM as a last resort. Coefficients are [CALIB] constructor knobs."""

    def __init__(self, *, accum_rate: float = ACCUM_RATE, clear_residual_frac: float = CLEAR_RESIDUAL_FRAC,
                 transmit_floor: float = TRANSMIT_FLOOR) -> None:
        self.coverage = 0.0
        self.n_clear_cycles = 0
        self.jettisoned = False
        self._accum_rate = float(accum_rate)
        self._clear_residual_frac = float(clear_residual_frac)
        self._transmit_floor = float(transmit_floor)

    def accumulate(self, exposure: float) -> None:
        """Add dust for ``exposure`` units of operation (drive/dig time). Coverage saturates at 1."""
        self.coverage = min(1.0, self.coverage + self._accum_rate * max(0.0, float(exposure)))

    def clear(self) -> None:
        """One AC EDS clear cycle: remove most of the dust, leaving ``clear_residual_frac``. No-op once
        the cover has been jettisoned (there is no EDS cover left to clear)."""
        if self.jettisoned:
            return
        self.coverage *= self._clear_residual_frac
        self.n_clear_cycles += 1

    def should_jettison(self, *, threshold: float = 0.6) -> bool:
        """The EDS can no longer recover (dust at/above ``threshold``) and the cover is still on -> the
        HDRM jettison is the indicated last resort."""
        return (not self.jettisoned) and self.coverage >= float(threshold)

    def jettison(self) -> None:
        """Fire the HDRM: eject the dusty cover -> a clean bare lens, ONE-SHOT. After this there is no EDS
        protection, so future dust accrues on the bare lens and clear() is a no-op (redundant cam takes over)."""
        self.jettisoned = True
        self.coverage = 0.0

    def transmittance(self) -> float:
        return dust_transmittance(self.coverage, floor=self._transmit_floor)

    def apply(self, image, *, haze: float = 0.0):
        """Apply the shield's current transmittance to a real frame."""
        return apply_occlusion(image, self.transmittance(), haze=haze)


if __name__ == "__main__":
    import argparse

    from PIL import Image
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="img", required=True, help="a real rendered camera PNG")
    ap.add_argument("--out", dest="out", required=True, help="output dusted PNG")
    ap.add_argument("--exposure", type=float, default=2.0, help="operation exposure before the snapshot")
    ap.add_argument("--clears", type=int, default=0, help="EDS clear cycles applied after accumulating")
    ap.add_argument("--haze", type=float, default=8.0, help="additive veiling haze [CALIB]")
    a = ap.parse_args()
    s = EDSDustShield()
    s.accumulate(a.exposure)
    for _ in range(a.clears):
        s.clear()
    im = np.asarray(Image.open(a.img).convert("L"))
    Image.fromarray(s.apply(im, haze=a.haze)).save(a.out)
    print(f"coverage={s.coverage:.3f} transmittance={s.transmittance():.3f} clears={s.n_clear_cycles} "
          f"jettisoned={s.jettisoned} -> {a.out}")
