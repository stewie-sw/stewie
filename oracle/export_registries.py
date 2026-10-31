"""Oracle export: write the real body registry and site catalog as JSON contract fixtures.

Source of truth today is the Python registry (stewie_bodies.BODIES, stewie.specs.sites.SITES); the Rust
contracts are tested against exactly these values. Output is byte-stable (sorted keys, fixed indent).

    python oracle/export_registries.py   # writes crates/stewie-contracts/fixtures/{bodies,sites,soil_baseline}.json
"""
from __future__ import annotations

import dataclasses
import json
import os

from stewie.physics import material as M
from stewie.specs import constants as K
from stewie.specs.sites import SITES
from stewie_bodies import BODIES

_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crates", "stewie-contracts", "fixtures")


def bodies() -> dict:
    out = {}
    for key, b in BODIES.items():
        d = dataclasses.asdict(b)
        k = d.pop("bekker")
        d["bekker"] = None if k is None else {"k_c": k[0], "k_phi": k[1], "n": k[2]}
        out[key] = d
    return out


def sites() -> dict:
    out = {}
    for key, s in SITES.items():
        d = dataclasses.asdict(s)
        bundle_dir = d.pop("bundle_dir")
        d["bundle"] = None if bundle_dir is None else os.path.basename(bundle_dir)
        out[key] = d
    return out


def soil_baseline() -> dict:
    """The constants.py regolith values the body registry lacks, with their honesty tags (see constants.py)."""
    spec = "spec section 5.2, stewie/specs/constants.py"
    return {"k_shear_m": {"value": float(K.K_SHEAR), "tag": "CALIB", "source": f"{spec} (1.0-1.8 cm)"},
            "slip_c1": {"value": float(K.SLIP_C1), "tag": "UNKNOWN", "source": f"{spec} (c1 ~0.4)"},
            "slip_c2": {"value": float(K.SLIP_C2), "tag": "UNKNOWN", "source": f"{spec} (c2 ~0.3)"},
            "rho_deep": {"value": float(K.RHO_DEEP), "tag": "CALIB", "source": f"{spec} (1.8-2.0 g/cm^3)"},
            "rho_grain": {"value": float(K.RHO_GRAIN), "tag": "FIXED",
                          "source": "spec section 5.1 grain specific gravity G_s 3.1 x water"},
            "rho_spoil": {"value": float(K.RHO_SPOIL), "tag": "CALIB",
                          "source": "loose surface density (Carrier & Mitchell, Lunar Sourcebook 1991, ch. 9)"},
            "rho_sintered": {"value": float(K.RHO_SINTERED), "tag": "SOURCED",
                             "source": "microwave-sintered simulant 2.23-2.34 g/cm^3 (Lin et al. 2024, J. Eur. Ceram. Soc.)"},
            "z_t_m": {"value": float(K.Z_T), "tag": "CALIB", "source": f"{spec} (z_t 10-15 cm)"},
            "w_ice_max": {"value": float(K.W_ICE_MAX), "tag": "UNKNOWN",
                          "source": f"{spec} (0-5.6 % PSR, LCROSS-derived)"},
            "phi_dense_deg": {"value": float(M.PHI_DENSE_DEG), "tag": "CALIB",
                              "source": f"{spec} (dense end of phi 30-50 deg), stewie/physics/material.py"},
            "cohesion_dense_pa": {"value": float(M.COHESION_DENSE_PA), "tag": "CALIB",
                                  "source": f"{spec} (dense end of c 0.1-1.0 kPa), stewie/physics/material.py"}}


def _write(name: str, data: dict) -> str:
    path = os.path.normpath(os.path.join(_OUT, name))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def main() -> None:
    print(_write("bodies.json", bodies()))
    print(_write("sites.json", sites()))
    print(_write("soil_baseline.json", soil_baseline()))


if __name__ == "__main__":
    main()
