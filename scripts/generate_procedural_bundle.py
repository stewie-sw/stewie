#!/usr/bin/env python3
"""CLI: generate a SYNTHETIC procedural terrain bundle (seed-driven fbm_global generator).

Writes a normal INTERFACE.md raster bundle under ``out/procedural_sandbox/<name>/`` that Godot's
``viz2.sh --site out/procedural_sandbox/<name>`` renders exactly like a real DEM bundle. The bundle
is UNMISTAKABLY synthetic (metadata.synthetic + dem_provenance.synthetic true, citation null) and
SEGREGATED from samples/lunar_dem/ (the producer refuses a samples destination).

    python scripts/generate_procedural_bundle.py --name demo --seed 7 \
        --extent-m 256 --cell-m 1.0 \
        --H 0.9 --wavelength-m 40 --amplitude-m 8 --octaves 6

``--seed`` is the single re-roll knob; the 4 --H/--wavelength-m/--amplitude-m/--octaves params tune
the surface. Deterministic: same args -> byte-identical bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # noqa: E402

from stewie.terrain import procedural_bundle as pb  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate a SYNTHETIC procedural terrain bundle.")
    ap.add_argument("--name", required=True,
                    help="bundle name (a subdir under out/procedural_sandbox/), or an absolute out dir")
    ap.add_argument("--seed", type=int, default=0, help="world_seed (the re-roll knob)")
    ap.add_argument("--extent-m", type=float, default=256.0, help="square patch side [m]")
    ap.add_argument("--cell-m", type=float, default=1.0, help="cell size [m]")
    ap.add_argument("--H", type=float, default=pb.DEFAULT_PARAMS["H"],
                    help="Hurst / roughness exponent in (0, 1]")
    ap.add_argument("--wavelength-m", type=float,
                    default=pb.DEFAULT_PARAMS["feature_wavelength_m"],
                    help="octave-0 feature wavelength [m]")
    ap.add_argument("--amplitude-m", type=float, default=pb.DEFAULT_PARAMS["amplitude_m"],
                    help="target surface roughness (sample std ~ amplitude_m) [m]")
    ap.add_argument("--octaves", type=int, default=pb.DEFAULT_PARAMS["octaves"])
    ap.add_argument("--world-x0", type=float, default=0.0, help="global origin X [m] (determinism)")
    ap.add_argument("--world-y0", type=float, default=0.0, help="global origin Y [m] (determinism)")
    ap.add_argument("--base-elevation-m", type=float, default=0.0,
                    help="constant base elevation added to the zero-mean fbm relief [m]")
    ap.add_argument("--no-previews", action="store_true", help="skip the hillshade/height PNGs")
    args = ap.parse_args(argv)

    params = {
        "H": args.H,
        "feature_wavelength_m": args.wavelength_m,
        "amplitude_m": args.amplitude_m,
        "octaves": args.octaves,
    }
    fields, meta = pb.generate_procedural_bundle(
        args.name, world_seed=args.seed, params=params,
        extent_m=args.extent_m, cell_m=args.cell_m,
        world_x0=args.world_x0, world_y0=args.world_y0,
        base_elevation_m=args.base_elevation_m,
        write_previews=not args.no_previews)

    out_dir = pb._resolve_out_dir(args.name)
    Z = fields["heightmap"]
    print(f"wrote SYNTHETIC bundle -> {out_dir}")
    print(f"  grid={meta['grid']['width']}x{meta['grid']['height']} @ {meta['grid']['cell_m']} m  "
          f"height std={float(Z.std()):.3f} m  range={meta['height_range_m']}")
    print(f"  provenance={json.dumps(meta['dem_provenance'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
