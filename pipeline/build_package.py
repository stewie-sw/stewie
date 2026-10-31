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


SITES_NAME = "south_polar_sites"
CROP_SOURCE = "ldem_85s_40m"
CROP_RADIUS_M = 20_000.0     # near field at 40 m; beyond it the 240 m polar tier and LDEM_16 answer


def _rewrite_label(text: str, values: dict) -> str:
    """Replace `KEY = value` lines of a PDS3 label, keeping each line's layout and any <unit>."""
    out = []
    for line in text.splitlines(keepends=True):
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("/*") else None
        if key in values:
            head, rest = line.split("=", 1)
            unit = (" <" + rest.split("<", 1)[1].split(">", 1)[0] + ">") if "<" in rest else ""
            line = f"{head}= {values[key]}{unit}\n"
        out.append(line)
    return "".join(out)


def _crop_layer(site: str, lat: float, lon: float, files: dict, entries: dict, out_dir: str) -> dict | None:
    """A real ±CROP_RADIUS_M window of LDEM_85S_40M around a site (the rows copied byte for byte), with a
    label whose offsets place it exactly where it sat in the full grid. None when the site is off the grid."""
    lab_text = open(files[f"{CROP_SOURCE}.lbl"], encoding="ascii", errors="replace").read()
    lab = _label(files[f"{CROP_SOURCE}.lbl"])
    lines, samples = int(lab["LINES"]), int(lab["LINE_SAMPLES"])
    l0, s0, cell = float(lab["LINE_PROJECTION_OFFSET"]), float(lab["SAMPLE_PROJECTION_OFFSET"]), float(lab["MAP_SCALE"])
    radius = float(lab["A_AXIS_RADIUS"]) * 1000.0
    rho = 2.0 * radius * math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)          # south polar stereographic
    e, n = rho * math.sin(math.radians(lon)), rho * math.cos(math.radians(lon))
    row, col = round(l0 - n / cell), round(s0 + e / cell)
    half = int(CROP_RADIUS_M / cell)
    r0, r1 = max(0, row - half), min(lines, row + half + 1)
    c0, c1 = max(0, col - half), min(samples, col + half + 1)
    if r1 - r0 < 2 or c1 - c0 < 2:
        return None
    lid = f"{CROP_SOURCE}_{site}"
    with open(files[f"{CROP_SOURCE}.img"], "rb") as src, open(os.path.join(out_dir, f"{lid}.img"), "wb") as dst:
        for r in range(r0, r1):
            src.seek((r * samples + c0) * 2)
            dst.write(src.read((c1 - c0) * 2))
    label = _rewrite_label(lab_text, {"LINES": r1 - r0, "LINE_SAMPLES": c1 - c0,
                                      "FILE_RECORDS": r1 - r0, "RECORD_BYTES": 2 * (c1 - c0),
                                      "LINE_PROJECTION_OFFSET": f"{l0 - r0}", "SAMPLE_PROJECTION_OFFSET": f"{s0 - c0}",
                                      "LINE_LAST_PIXEL": r1 - r0, "SAMPLE_LAST_PIXEL": c1 - c0})
    with open(os.path.join(out_dir, f"{lid}.lbl"), "w", encoding="ascii") as fh:
        fh.write(label)
    file_entry = lambda name: {"path": name, "bytes": os.path.getsize(os.path.join(out_dir, name)),   # noqa: E731
                               "sha256": fetch.sha256(os.path.join(out_dir, name))}
    return {"id": lid, "priority": 1, "kind": "pds_polar_stereographic",
            "image": file_entry(f"{lid}.img"), "label": file_entry(f"{lid}.lbl"),
            "source": entries[f"{CROP_SOURCE}.img"]["url"],
            "version": f"{lab['PRODUCT_VERSION_ID']}; crop rows {r0}-{r1 - 1} cols {c0}-{c1 - 1}",
            "license": PDS_LICENSE, "resolution_m": cell,
            "polar_box_m": [(c0 - s0) * cell, (l0 - (r1 - 1)) * cell, (c1 - 1 - s0) * cell, (l0 - r0) * cell]}


def build_sites(out_root: str = os.path.join(fetch.CACHE_ROOT, "package")) -> str:
    """The device package (RW-60d): a 40 m crop around every catalog site inside LDEM_85S_40M, over the whole
    240 m south polar tier and LDEM_16, with the bundled ephemeris. Sized for a browser or tablet."""
    files = fetch.fetch("terrain_sources.json")
    entries = json.load(open(os.path.join(HERE, "terrain_sources.json"), encoding="utf-8"))["entries"]
    sites = json.load(open(os.path.join(REPO, "crates", "stewie-contracts", "fixtures", "sites.json"), encoding="utf-8"))
    out_dir = os.path.join(out_root, SITES_NAME)
    os.makedirs(out_dir, exist_ok=True)
    crops = [c for name in sorted(sites) if sites[name]["lat_deg"] < 0
             for c in [_crop_layer(name, sites[name]["lat_deg"], sites[name]["lon_deg"], files, entries, out_dir)] if c]
    header_path = os.path.join(EPHEM_DIR, f"{EPHEM_NAME}.json")
    header = json.load(open(header_path, encoding="utf-8"))
    manifest = {
        "format": "stewie-package-v1", "name": SITES_NAME, "body": "moon",
        "layers": crops + [_layer(lid, p, files, entries, out_dir) for lid, p in (("ldem_75s_240m", 2), ("ldem_16", 9))],
        "ephemeris": {"name": EPHEM_NAME, "data": _place(os.path.join(EPHEM_DIR, f"{EPHEM_NAME}.bin"), out_dir),
                      "header": _place(header_path, out_dir), "span_utc": header["span_utc"],
                      "source": f"{header['generator']} over NAIF " + ", ".join(sorted(header["kernels"])),
                      "license": NAIF_LICENSE},
    }
    text = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    for path in (os.path.join(out_dir, "manifest.json"), os.path.join(HERE, "packages", f"{SITES_NAME}.json")):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return out_dir


if __name__ == "__main__":
    print(build())
    print(build_sites())
