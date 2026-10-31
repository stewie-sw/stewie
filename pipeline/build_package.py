"""Build an installable data package (RW-60b, navigator N11) from the pinned inputs.

The package is a directory: the terrain layers named in LAYERS (fetched by pipeline/fetch.py), the bundled
ephemeris pack, and manifest.json. Every file is pinned by size and sha256; every layer carries its source,
version (PDS PRODUCT_VERSION_ID), license, resolution and the latitude band the reader answers in, all
derived from the labels and the fetch manifests, never typed in. Files are hard-linked from the cache when the filesystem allows, else copied.
The manifest is also written to pipeline/packages/<name>.json so CI can regenerate it and diff (drift check).

    python pipeline/fetch.py terrain_sources.json && python pipeline/build_package.py
"""
from __future__ import annotations

import json
import math
import os
import shutil

import fetch

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, ".."))
EPHEM_DIR = os.path.join(REPO, "crates", "lunar-ephem", "data")
EPHEM_NAME = "moon_de440_2026_2035"
NAME = "lola_base"

# (layer id, priority): polar tiers first, so the poles never fall to LDEM_16's empty half-pixel caps.
LAYERS = (("ldem_85s_40m", 1), ("ldem_75s_240m", 2), ("ldem_75n_240m", 2), ("ldem_16", 9))

PDS_LICENSE = {"statement": "PDS Geosciences Node: \"Data sets archived in the PDS are in the public domain.\"",
               "url": "https://pds-geosciences.wustl.edu/faq.html"}
NAIF_LICENSE = {"statement": "Repacked from NAIF-distributed SPICE kernels by STEWIE pipeline/ephem_pack.py, renamed "
                             "and annotated as NAIF requires of modified kernels. NAIF: \"SPICE kernels placed on "
                             "the NAIF server may be downloaded and used by anyone\".",
                "url": "https://naif.jpl.nasa.gov/naif/rules.html"}


def _label(path: str) -> dict:
    """KEY = value pairs of a PDS3 label (comments, quotes and <units> stripped)."""
    out = {}
    for line in open(path, encoding="ascii", errors="replace"):
        line = line.split("/*", 1)[0].strip()
        if "=" in line:
            k, v = (x.strip() for x in line.split("=", 1))
            out[k] = v.split("<", 1)[0].strip().strip('"')
    return out


def _place(src: str, out_dir: str) -> dict:
    """Link (or copy) `src` into the package and return its File entry."""
    dest = os.path.join(out_dir, os.path.basename(src))
    if os.path.exists(dest):
        os.remove(dest)
    try:
        os.link(src, dest)
    except OSError:
        shutil.copyfile(src, dest)
    return {"path": os.path.basename(src), "bytes": os.path.getsize(dest), "sha256": fetch.sha256(dest)}


def _layer(lid: str, priority: int, files: dict, entries: dict, out_dir: str) -> dict:
    lab = _label(files[f"{lid}.lbl"])
    radius = float(lab["A_AXIS_RADIUS"]) * 1000.0
    lines, samples = int(lab["LINES"]), int(lab["LINE_SAMPLES"])
    l0, s0 = float(lab["LINE_PROJECTION_OFFSET"]), float(lab["SAMPLE_PROJECTION_OFFSET"])
    # The band is where the reader answers: inside the hull of pixel centres (it never extrapolates), which
    # is a little short of the label's nominal MINIMUM/MAXIMUM_LATITUDE.
    if lab["MAP_PROJECTION_TYPE"] == "POLAR STEREOGRAPHIC":
        kind, res = "pds_polar_stereographic", float(lab["MAP_SCALE"])
        hull_m = min(s0, l0, samples - 1 - s0, lines - 1 - l0) * res
        colat = math.degrees(2.0 * math.atan(hull_m / (2.0 * radius)))
        pole = float(lab["CENTER_LATITUDE"])
        band = (-90.0, -90.0 + colat) if pole < 0 else (90.0 - colat, 90.0)
    else:
        ppd = float(lab["MAP_RESOLUTION"])
        kind, res = "pds_simple_cylindrical", 2.0 * math.pi * radius / 360.0 / ppd
        band = ((l0 - (lines - 1)) / ppd, l0 / ppd)
    return {"id": lid, "priority": priority, "kind": kind,
            "image": _place(files[f"{lid}.img"], out_dir), "label": _place(files[f"{lid}.lbl"], out_dir),
            "source": entries[f"{lid}.img"]["url"], "version": lab["PRODUCT_VERSION_ID"],
            "license": PDS_LICENSE, "resolution_m": res,
            "lat_min_deg": band[0], "lat_max_deg": band[1]}


def build(out_root: str = os.path.join(fetch.CACHE_ROOT, "package")) -> str:
    """Write the package directory and the committed manifest copy; return the package directory."""
    files = fetch.fetch("terrain_sources.json")
    entries = json.load(open(os.path.join(HERE, "terrain_sources.json"), encoding="utf-8"))["entries"]
    out_dir = os.path.join(out_root, NAME)
    os.makedirs(out_dir, exist_ok=True)
    header_path = os.path.join(EPHEM_DIR, f"{EPHEM_NAME}.json")
    header = json.load(open(header_path, encoding="utf-8"))
    manifest = {
        "format": "stewie-package-v1", "name": NAME, "body": "moon",
        "layers": [_layer(lid, p, files, entries, out_dir) for lid, p in LAYERS],
        "ephemeris": {"name": EPHEM_NAME, "data": _place(os.path.join(EPHEM_DIR, f"{EPHEM_NAME}.bin"), out_dir),
                      "header": _place(header_path, out_dir), "span_utc": header["span_utc"],
                      "source": f"{header['generator']} over NAIF " + ", ".join(sorted(header["kernels"])),
                      "license": NAIF_LICENSE},
    }
    text = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    for path in (os.path.join(out_dir, "manifest.json"), os.path.join(HERE, "packages", f"{NAME}.json")):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return out_dir


if __name__ == "__main__":
    print(build())
