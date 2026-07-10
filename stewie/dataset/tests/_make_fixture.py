"""Generate the tiny REAL-DEM fixture GeoTIFF for the stewie.dataset tests.

This is a DEV/PROVENANCE tool, NOT shipped in the wheel and NOT run in CI. It reads a small
window of the REAL LOLA Haworth 1 m DEM (``datasets/lunar_dem/Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif``)
and writes it as a small, self-contained classic GeoTIFF carrying the SAME frame conventions as
the source (south-polar stereographic IAU_2015:30135, R=1737400 m sphere, PixelIsArea, 1 m pixels,
per-row strips, GDAL_NODATA sentinel). The tiepoint is set to the window's true NW-corner world
coordinate, so the fixture georeferences to its REAL location on the Moon -- the pixel values and
the geolocation are both real subsamples, nothing is fabricated (Aaron's rule: subsample real data
to a tiny fixture, never fabricate values).

Run once to (re)generate the committed fixture:

    python -m stewie.dataset.tests._make_fixture

It verifies the written file round-trips through ``dart.dem_import.load_lola_geotiff`` (Z equals the
source window to the bit, affine origin exact) before it is accepted.
"""
from __future__ import annotations

import json
import os
import struct

import numpy as np

from stewie.dataset.dem_source import resolve_dem_path

# The real source window (fully finite interior of the Haworth tile; verified non-nodata).
_ROW0, _COL0, _SIZE = 5000, 5000, 256
_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE_DIR = os.path.join(_HERE, "fixtures")
FIXTURE_TIF = os.path.join(_FIXTURE_DIR, "haworth_1m_fixture_256.tif")
FIXTURE_JSON = os.path.join(_FIXTURE_DIR, "haworth_1m_fixture_256.provenance.json")


# --- a minimal classic little-endian TIFF/GeoTIFF encoder (single band float32, per-row strips) ----

_LE = "<"


def _entry(tag: int, typ: int, count: int, value_bytes: bytes) -> bytes:
    """One 12-byte IFD entry; ``value_bytes`` is either the <=4-byte inline value (left-justified,
    padded) or the 4-byte out-of-line offset."""
    return struct.pack(_LE + "HHI", tag, typ, count) + value_bytes.ljust(4, b"\x00")[:4]


def write_geotiff_f32(path: str, Z: np.ndarray, *, tie_x: float, tie_y: float, px: float,
                      radius_m: float, nodata: str) -> None:
    """Write ``Z`` (float32, row 0 = top/north) as a classic GeoTIFF with per-row strips.

    ``(tie_x, tie_y)`` is the world coordinate of raster (0, 0) as the NW pixel CORNER
    (GTRasterType=1 / PixelIsArea, matching the PGDA source). ``nodata`` is the GDAL_NODATA sentinel
    string. Only the tags ``dart.dem_import`` + ``stewie.dataset.dem_source`` consume are written.
    """
    Z = np.ascontiguousarray(Z.astype("<f4"))
    H, W = Z.shape
    row_bytes = W * 4
    data_off = 8
    data = Z.tobytes()  # C-order rows, native strip layout
    strip_offsets = [data_off + r * row_bytes for r in range(H)]
    strip_counts = [row_bytes] * H

    # Out-of-line value blobs, appended after the IFD; we compute the IFD size first to place them.
    # GeoKeyDirectory: header (1,1,0,nkeys) + (1025 PixelIsArea) + (2057 SemiMajorAxis -> GeoDouble[0]).
    geo_dir = [1, 1, 0, 2, 1025, 0, 1, 1, 2057, 34736, 1, 0]
    geo_doubles = [float(radius_m)]
    nodata_ascii = (nodata + "\x00").encode("latin-1")

    tags: list[tuple[int, int, int, bytes | None]] = [
        (256, 4, 1, struct.pack(_LE + "I", W)),        # ImageWidth  LONG
        (257, 4, 1, struct.pack(_LE + "I", H)),        # ImageLength LONG
        (258, 3, 1, struct.pack(_LE + "H", 32)),       # BitsPerSample SHORT
        (259, 3, 1, struct.pack(_LE + "H", 1)),        # Compression = none
        (262, 3, 1, struct.pack(_LE + "H", 1)),        # Photometric = BlackIsZero
        (273, 4, H, None),                             # StripOffsets  (out-of-line)
        (277, 3, 1, struct.pack(_LE + "H", 1)),        # SamplesPerPixel
        (278, 3, 1, struct.pack(_LE + "H", 1)),        # RowsPerStrip = 1
        (279, 4, H, None),                             # StripByteCounts (out-of-line)
        (339, 3, 1, struct.pack(_LE + "H", 3)),        # SampleFormat = IEEE float
        (33550, 12, 3, None),                          # ModelPixelScale (3 doubles)
        (33922, 12, 6, None),                          # ModelTiepoint  (6 doubles)
        (34735, 3, len(geo_dir), None),                # GeoKeyDirectory
        (34736, 12, len(geo_doubles), None),           # GeoDoubleParams
        (42113, 2, len(nodata_ascii), None),           # GDAL_NODATA ascii
    ]

    n = len(tags)
    ifd_off = data_off + H * row_bytes
    # IFD = 2-byte count + n*12-byte entries + 4-byte next-IFD pointer.
    oo_off = ifd_off + 2 + n * 12 + 4  # where out-of-line blobs start

    # Materialize out-of-line blobs and remember their offsets.
    blobs: dict[int, bytes] = {
        273: struct.pack(_LE + "I" * H, *strip_offsets),
        279: struct.pack(_LE + "I" * H, *strip_counts),
        33550: struct.pack(_LE + "3d", px, px, 0.0),
        33922: struct.pack(_LE + "6d", 0.0, 0.0, 0.0, tie_x, tie_y, 0.0),
        34735: struct.pack(_LE + "H" * len(geo_dir), *geo_dir),
        34736: struct.pack(_LE + "d" * len(geo_doubles), *geo_doubles),
        42113: nodata_ascii,
    }
    cur = oo_off
    blob_off: dict[int, int] = {}
    blob_stream = bytearray()
    for tag in (273, 279, 33550, 33922, 34735, 34736, 42113):
        b = blobs[tag]
        if len(b) <= 4:            # small enough to be inline after all
            blob_off[tag] = -1     # sentinel: inline
        else:
            blob_off[tag] = cur
            blob_stream += b
            cur += len(b)

    # Build the IFD entries (tags MUST be ascending).
    ifd = struct.pack(_LE + "H", n)
    for tag, typ, count, inline in tags:
        if inline is not None:
            ifd += _entry(tag, typ, count, inline)
        else:
            b = blobs[tag]
            if blob_off[tag] == -1:
                ifd += _entry(tag, typ, count, b)
            else:
                ifd += _entry(tag, typ, count, struct.pack(_LE + "I", blob_off[tag]))
    ifd += struct.pack(_LE + "I", 0)  # next IFD = none

    with open(path, "wb") as f:
        f.write(b"II" + struct.pack(_LE + "H", 42) + struct.pack(_LE + "I", ifd_off))
        f.write(data)
        f.write(ifd)
        f.write(bytes(blob_stream))


def _read_source_window() -> tuple[np.ndarray, float, float, float, str, dict]:
    """Read the real source window straight from the raw TIFF strips (no full-array load)."""
    from dart.dem_import import _parse_geokeys, _read_tiff_ifd0
    src = resolve_dem_path()
    if src is None:
        raise SystemExit("real Haworth 1 m DEM not found; cannot regenerate the fixture")
    tags, _bo = _read_tiff_ifd0(src)
    W = int(tags[256][0]); px = float(tags[33550][0])
    strip = tags[273]; rps = int(tags[278][0]); nodata = str(tags[42113][0])
    gk = _parse_geokeys(tags.get(34735), tags.get(34736))
    R = float(gk.get(2057, 1737400.0))
    tie = tags[33922]
    # first-pixel-center origin (dem_import convention) then window corner world coords
    x0c = tie[3] - tie[1] * px + (px / 2.0 if int(gk.get(1025, 2)) == 1 else 0.0)
    y0c = tie[4] + tie[0] * px - (px / 2.0 if int(gk.get(1025, 2)) == 1 else 0.0)
    # window (row0,col0) pixel CENTER, then back to its NW CORNER for the fixture tiepoint
    win_cx = x0c + _COL0 * px
    win_cy = y0c - _ROW0 * px
    tie_x = win_cx - px / 2.0
    tie_y = win_cy + px / 2.0
    out = np.empty((_SIZE, _SIZE), dtype="<f4")
    with open(src, "rb") as f:
        for i in range(_SIZE):
            r = _ROW0 + i
            f.seek(strip[r // rps] + (r % rps) * W * 4 + _COL0 * 4)
            out[i] = np.frombuffer(f.read(_SIZE * 4), dtype="<f4")
    prov = {
        "source_dem": os.path.basename(src),
        "source_resolved_path": src,
        "window_row0_col0_size": [_ROW0, _COL0, _SIZE],
        "px_m": px, "sphere_radius_m": R, "nodata": nodata,
        "fixture_tiepoint_nw_corner_m": [tie_x, tie_y],
        "frame": "south polar stereographic, R=1737400 m sphere (IAU_2015:30135)",
        "citation": "Barker et al. 2021 (Planet. Space Sci. 203:105119); Mazarico et al. 2011 (Icarus 211:1066)",
        "note": "REAL subsampled window of the PGDA LOLA Haworth 1 m v3 DEM; real pixel values + real "
                "geolocation. Regenerate via `python -m stewie.dataset.tests._make_fixture`.",
    }
    return out, tie_x, tie_y, px, nodata, prov


def main() -> int:
    os.makedirs(_FIXTURE_DIR, exist_ok=True)
    Z, tie_x, tie_y, px, nodata, prov = _read_source_window()
    write_geotiff_f32(FIXTURE_TIF, Z, tie_x=tie_x, tie_y=tie_y, px=px,
                      radius_m=prov["sphere_radius_m"], nodata=nodata)
    # verify round-trip through the frozen ingest
    from dart.dem_import import load_lola_geotiff
    Zr, aff, meta = load_lola_geotiff(FIXTURE_TIF)
    assert Zr.shape == Z.shape, (Zr.shape, Z.shape)
    assert np.array_equal(Zr, Z), "fixture Z != source window"
    assert abs(aff.px - px) < 1e-9
    assert abs(aff.x0 - (tie_x + px / 2.0)) < 1e-6, (aff.x0, tie_x)
    assert abs(aff.y0 - (tie_y - px / 2.0)) < 1e-6, (aff.y0, tie_y)
    prov["verified"] = {
        "load_lola_geotiff_shape": list(Zr.shape),
        "affine_first_pixel_center_m": [aff.x0, aff.y0],
        "meta_frame": meta["frame"],
    }
    with open(FIXTURE_JSON, "w") as f:
        json.dump(prov, f, indent=2)
    print(f"wrote {FIXTURE_TIF} ({os.path.getsize(FIXTURE_TIF)} bytes)")
    print(f"wrote {FIXTURE_JSON}")
    print("round-trip via load_lola_geotiff: OK  affine center=", aff.x0, aff.y0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
