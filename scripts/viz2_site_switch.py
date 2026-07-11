"""viz2 PRD Phase G / G1 — the cross-site SWITCHER over the real ``samples/lunar_dem/`` bundles.

The viz2 scene already loads ANY bundle through the existing ``--site <bundle_dir>`` flag (Phase A).
G1 is the enumeration + switch on top of it: this driver lists every LOADABLE on-disk bundle (one
that carries the full state-field set the Godot ``state_fields.gd`` loader needs — heightmap +
density + disturbance + state_label) and renders each through the SAME ``viz2.sh --site`` path, so a
single run captures the different real sites side by side. No new loader; the switch is over the one
:func:`dem_site_compare.list_site_bundles` enumeration the backend comparator also uses.

A bundle that is metadata-only (e.g. ``de_gerlache_kocher_10km_5m``, no ``heightmap.rf32``) is
reported as NOT loadable and skipped — never rendered as a fabricated surface.

    # render the 3 most-distinct-relief sites (needs the Godot binary + a GPU/xvfb):
    GODOT=<...>/Godot_v4.6.3-stable_linux.x86_64 \
      PYTHONPATH=<repo>:... .venv/bin/python scripts/viz2_site_switch.py --n 3 --auto 6
    # just list what is switchable (no GPU):
    .venv/bin/python scripts/viz2_site_switch.py --list
"""
from __future__ import annotations

import argparse
import os
import subprocess

from dart import dem_site_compare as dsc

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# state_fields.gd load_scene requires these fields (mass_areal is optional for the consumer).
_REQUIRED_FIELDS = ("heightmap.rf32", "density.rf32", "disturbance.rf32", "state_label.r8")


def loadable_site_bundles(root: str = dsc.DEFAULT_SITE_ROOT) -> list[str]:
    """The on-disk bundles the viz2 Godot scene can actually LOAD (full state-field set present).
    Reuses :func:`dem_site_compare.list_site_bundles`; filters to the ``state_fields.gd`` requirement."""
    out = []
    for b in dsc.list_site_bundles(root):
        if all(os.path.exists(os.path.join(b, f)) for f in _REQUIRED_FIELDS):
            out.append(b)
    return out


def pick_distinct_relief(n: int, root: str = dsc.DEFAULT_SITE_ROOT) -> list[str]:
    """The ``n`` loadable bundles with the most DISTINCT relief (so a switch capture reads as visibly
    different terrain): sort by relief, then greedily pick the extremes inward. Real relief from the
    compare table (no fabrication)."""
    loadable = loadable_site_bundles(root)
    loadable_names = {os.path.basename(b) for b in loadable}
    rows = [r for r in dsc.compare_table(root) if r.name in loadable_names]
    rows.sort(key=lambda r: r.relief_m)
    if n >= len(rows):
        chosen = rows
    else:
        # greedy spread: take min, max, then fill from the middle outward
        idx = [0, len(rows) - 1]
        while len(idx) < n:
            # pick the row whose relief is farthest from all already-chosen
            best, best_gap = -1, -1.0
            for k in range(len(rows)):
                if k in idx:
                    continue
                gap = min(abs(rows[k].relief_m - rows[j].relief_m) for j in idx)
                if gap > best_gap:
                    best, best_gap = k, gap
            idx.append(best)
        chosen = [rows[k] for k in sorted(idx)]
    name_to_bundle = {os.path.basename(b): b for b in loadable}
    return [name_to_bundle[r.name] for r in chosen]


def render_site(bundle: str, out_dir: str, *, auto: int, size: str, godot: str | None) -> int:
    """Render ONE site through ``viz2.sh --site <bundle> --auto <auto>`` (the existing Phase-A path).
    Returns the subprocess exit code. Requires the Godot binary + a GPU/xvfb display."""
    viz2 = os.path.join(_REPO_ROOT, "stewie", "godot", "viz2.sh")
    env = dict(os.environ)
    if godot:
        env["GODOT"] = godot
    cmd = ["bash", viz2, "--", "--site", bundle, "--auto", str(auto), "--out", out_dir, "--size", size]
    print(f"[switch] {os.path.basename(bundle)} -> {out_dir}")
    return subprocess.call(cmd, env=env)


def main() -> None:
    ap = argparse.ArgumentParser(description="viz2 Phase G / G1 cross-site switcher")
    ap.add_argument("--n", type=int, default=3, help="number of most-distinct-relief sites to render")
    ap.add_argument("--auto", type=int, default=6, help="frames per site (viz2 --auto)")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--out-root", default=os.path.join(_REPO_ROOT, "out", "viz2", "switch"))
    ap.add_argument("--godot", default=os.environ.get("GODOT"), help="path to the Godot binary")
    ap.add_argument("--all", action="store_true", help="render every loadable site, not just --n")
    ap.add_argument("--list", action="store_true", help="list switchable sites and exit (no render)")
    args = ap.parse_args()

    loadable = loadable_site_bundles()
    all_bundles = dsc.list_site_bundles()
    skipped = [os.path.basename(b) for b in all_bundles if b not in loadable]
    rows = {r.name: r for r in dsc.compare_table()}
    print(f"switchable sites ({len(loadable)} loadable, {len(skipped)} metadata-only skipped):")
    for b in loadable:
        r = rows[os.path.basename(b)]
        print(f"  {r.name:26s} relief {r.relief_m:7.0f} m  @ {r.cell_m:g} m  ({r.region})")
    if skipped:
        print("  skipped (no heightmap.rf32):", ", ".join(skipped))
    if args.list:
        return

    chosen = loadable if args.all else pick_distinct_relief(args.n)
    print(f"\nrendering {len(chosen)} site(s): {[os.path.basename(b) for b in chosen]}")
    results = []
    for b in chosen:
        name = os.path.basename(b)
        out_dir = os.path.join(args.out_root, name)
        rc = render_site(b, out_dir, auto=args.auto, size=args.size, godot=args.godot)
        ov = os.path.join(out_dir, "viz2_overview.png")
        results.append((name, rc, ov if os.path.exists(ov) else "(no overview)"))
    print("\n=== switch capture results ===")
    for name, rc, ov in results:
        r = rows[name]
        print(f"  {name:26s} rc={rc} relief={r.relief_m:.0f}m -> {ov}")


if __name__ == "__main__":
    main()
