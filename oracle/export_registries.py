"""Oracle export: write the real body registry and site catalog as JSON contract fixtures.

Source of truth today is the Python registry (stewie_bodies.BODIES, stewie.specs.sites.SITES); the Rust
contracts are tested against exactly these values. Output is byte-stable (sorted keys, fixed indent).

    python oracle/export_registries.py   # writes crates/stewie-contracts/fixtures/{bodies,sites,soil_baseline}.json
"""
from __future__ import annotations

import dataclasses
import json
import os

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
    """The constants.py soil values the body registry lacks, with their honesty tags (see constants.py)."""
    spec = "spec section 5.2, stewie/specs/constants.py"
    return {"k_shear_m": {"value": float(K.K_SHEAR), "tag": "CALIB", "source": f"{spec} (1.0-1.8 cm)"},
            "slip_c1": {"value": float(K.SLIP_C1), "tag": "UNKNOWN", "source": f"{spec} (c1 ~0.4)"},
            "slip_c2": {"value": float(K.SLIP_C2), "tag": "UNKNOWN", "source": f"{spec} (c2 ~0.3)"},
            "rho_deep": {"value": float(K.RHO_DEEP), "tag": "CALIB", "source": f"{spec} (1.8-2.0 g/cm^3)"}}


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
