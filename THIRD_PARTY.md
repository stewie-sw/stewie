# Third-Party Assets

> **License update (2026-06-10; re-reviewed 2026-06-17):** this repository's own code is
> **all-rights-reserved** (the prior CC0-1.0 dedication was withdrawn; it still applies to revisions
> published under it). Every vendored asset below was re-reviewed under the new license: each carries a
> **permissive or public-domain** upstream term (MIT, U.S.-Government public domain, Apache-2.0,
> SIL OFL-1.1) that is fully compatible with a proprietary repository — none impose copyleft on this
> repo. The lone copyleft / share-alike items (CC-BY-4.0 Shape-from-Shading DEMs; GPL-3.0 cratermaker)
> are deliberately **not vendored** (reference-only / facts-only), as noted per asset. Any residual
> "CC0 repo" wording in older per-asset notes is historical; the compatibility rationale is unchanged.
> See [`LICENSE`](LICENSE).

This section documents the vendored assets, which retain their **own upstream status** and are called
out here.

---

## EZ-RASSOR rover mesh

- **File:** `stewie/godot/assets/rover_base.glb` (was `godot_sidecar/assets/`; renamed 2026-06-09)
- **Derived from:** `packages/simulation/ezrassor_sim_description/meshes/base_unit.dae`
  in [FlaSpaceInst/EZ-RASSOR](https://github.com/FlaSpaceInst/EZ-RASSOR)
- **Transform applied:** Collada (Z-up) → glTF (Y-up), re-origined to ground-contact;
  conversion is reproducible via [`scripts/convert_rover_mesh.py`](scripts/convert_rover_mesh.py).
- **License:** MIT (reproduced verbatim below). The `.glb` is a format conversion of an
  MIT-licensed work and remains under MIT; attribution is retained here.

> **Excluded on license grounds:** EZ-RASSOR's `extra_models/` props (rocks, lander, ISRU
> plant, etc.) are third-party re-hosted art (clara.io / SketchUp Warehouse) with **no
> stated license** and are **not** used anywhere in this project. Clasts/rocks are generated
> procedurally (Golombek SFD) instead.

### EZ-RASSOR MIT License (verbatim)

```
MIT License

Copyright (c) 2019 Sean Rapp, Ronald Marrero, Tiger Sachse, Tyler Duncan, Samuel Lewis, Harrison Black, Camilo Lozano, Christopher Taliaferro, Cameron Taylor, Lucas Gonzalez, The Florida Space Institute, and The National Aeronautics and Space Administration

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## NASA RASSOR rover mesh (3D Resources)

- **Files:** `stewie/godot/assets/rassor_nasa/rassor.glb` (the original NASA download, Draco-compressed)
  and `rassor_godot.glb` (a decoded + decimated derivative for the vendored Godot, which lacks a Draco
  plugin). The original is a single static `rassor_shrinkwrap` visual mesh (~0.85 × 0.94 × 1.66 m, real
  RASSOR scale per the glTF POSITION accessor), not articulated parts.
- **Source:** NASA Science 3D Resources — [science.nasa.gov/3d-resources/regolith-advanced-surface-systems-operations-robot-rassor](https://science.nasa.gov/3d-resources/regolith-advanced-surface-systems-operations-robot-rassor/).
  Credit: **NASA/Dewey L. Smith; NASA/Jason M. Schuler** (the KSC Swamp Works / IPEx team).
- **Status:** NASA's 3D Resources are published as **"free and without copyright"**
  ([github.com/nasa/NASA-3D-Resources](https://github.com/nasa/NASA-3D-Resources)), subject to NASA's
  media-usage guidelines (attribution; no implied NASA endorsement). A work of the U.S. Government,
  treated as public-domain, compatible with this all-rights-reserved repo. The credit + no-endorsement
  notice ride along here per those guidelines.
- **Use:** RASSOR is the precursor to the modelled IPEx; this mesh is a static visual body for the
  `rassor2` vehicle (the RASSOR-2.0 entry in `terrain_authority/vehicles.py`), not the articulated
  per-part assembly the IPEx/EZ-RASSOR render path uses.

---

## LOLA south-pole DEM tile (PGDA Product 78)

- **File (committed):** the cropped 10 km @ 5 m Haworth sample tile under `samples/lunar_dem/` (a pixel-window crop of `Haworth_final_adj_5mpp_surf.tif`). The full 30 km source raster is **not** committed (lives gitignored under `.vendor/lola_raw/`).
- **Source:** NASA GSFC PGDA, *LOLA 5 m/px South-Pole DEMs* — [pgda.gsfc.nasa.gov/products/78](https://pgda.gsfc.nasa.gov/products/78), `data/LOLA_5mpp/Haworth/`.
- **Status:** a **work of the U.S. Government** (NASA GSFC). PGDA publishes **no formal license string**; under the general principle that U.S. Government works are not subject to domestic copyright, the tile is treated as **public-domain** for inclusion in this all-rights-reserved repository. This rests on that principle, **not** on a published CC0 license — stated honestly.
- **Frame / datum:** south polar stereographic, MOON_ME (DE421), R = 1737400 m (IAU_2015:30135); Z = surface height above the 1737400 m sphere in metres. **Cite** Barker et al. 2021 (Planet. Space Sci. 203:105119) + Mazarico et al. 2011 (Icarus 211:1066) as scholarly courtesy (see [`papers/CITATIONS.md`](papers/CITATIONS.md)).

> **Not committed (license-segregated):** the higher-detail **2026 Shape-from-Shading** DEMs (Bertone et al. 2026; Zenodo 10.5281/zenodo.17954508) are **CC-BY-4.0, not CC0** — kept reference-only (download script) or, if ever committed, only in a marked CC-BY-4.0 subfolder with an attribution NOTICE. The **Neukum production-function coefficient vector** is cross-checked against MintonGroup/cratermaker, which is **GPL-3.0** (verified 2026-05-31 at github.com/MintonGroup/cratermaker). GPL-3.0 is copyleft, so **no cratermaker code is — or may be — copied into this repo**; only the numeric coefficients are reused, and those are uncopyrightable scientific facts cited to **Neukum/Ivanov/Hartmann 2001** (the authority), not to cratermaker. cratermaker is therefore *not* a vendored asset here (no code is included).

---

## three.js (in-cockpit 3D playback)

- **File:** `stewie/server/web/assets/three.module.min.js`
- **Source:** [mrdoob/three.js](https://github.com/mrdoob/three.js) r170, the official minified ESM build.
- **License:** MIT — the `@license` SPDX header is retained verbatim at the top of the vendored file.
- **Use:** the in-cockpit 3D terrain dry-run (`stewie/server/web/assets/three3d.js`, #165): renders the
  work-area DEM heightfield (`GET /dem/heightfield`) in the planner's order frame, plus the planned
  physics-truth path / estimator belief / rover. Self-hosted same-origin (CSP `script-src 'self'`, no
  CDN); imported directly as an ES module (no build step).

---

## CesiumJS (cockpit globe)

- **Files:** the vendored CesiumJS build under [`stewie/server/cesium/`](stewie/server/cesium/)
  (`Cesium.js` + `Workers/`, `Widgets/`, `Assets/`, `ThirdParty/`). **Version 1.119**
  (`Cesium.VERSION="1.119"` in `Cesium.js`).
- **Source:** [CesiumGS/cesium](https://github.com/CesiumGS/cesium) (cesium.com).
- **License:** **Apache-2.0** (the upstream `LICENSE.md` header — "Cesium — https://github.com/CesiumGS/cesium,
  Cesium Contributors" — is retained in `Cesium.js`). Apache-2.0 is permissive and compatible with this
  all-rights-reserved repository (no copyleft).
- **Bundled third-party:** Cesium ships its own vendored decoders under `cesium/ThirdParty/` +
  `cesium/Workers/` — present here: `draco_decoder.wasm` (Draco, Apache-2.0), `basis_transcoder.wasm` +
  `transcodeKTX2.js` (Basis Universal / KTX2, Apache-2.0), `google-earth-dbroot-parser.js`. Each carries
  its own permissive upstream license inside the Cesium tree as distributed; unmodified here.
- **Use:** the cockpit's 3D globe + site map (pan/zoom/tilt, lat/lon pick, the Haworth work-area drape).
  Self-hosted same-origin (CSP forbids a CDN); no Cesium ion token is used (offline-capable base layers).

---

## swagger-ui-dist (cockpit API page)

- **Files:** [`stewie/server/web/assets/vendor/swagger/`](stewie/server/web/assets/vendor/swagger/) —
  `swagger-ui-bundle.js` + `swagger-ui.css` (+ `swagger-ui-bundle.js.LICENSE.txt`). swagger-ui **5.x**
  series (the vendored `.LICENSE.txt` is the authority for the terms; the exact patch is not asserted here).
- **Source:** [swagger-api/swagger-ui](https://github.com/swagger-api/swagger-ui) (npm `swagger-ui-dist`).
- **License:** **Apache-2.0** (the upstream `*.LICENSE.txt` is retained verbatim alongside the bundle).
  Permissive; compatible with this all-rights-reserved repository.
- **Use:** the System → API view (`GET /docs`, #176). Self-hosted same-origin so the OpenAPI explorer
  loads under the production CSP (the FastAPI default Swagger pulls CDN assets the CSP blocks).

---

## UI fonts (Orbitron + Inter)

- **Files:** `stewie/server/web/assets/fonts/orbitron-{500,700}.woff2` +
  `inter-{400,500,600}.woff2` (and `stewie/server/fonts/Orbitron.ttf` with its license at
  `stewie/server/fonts/OFL.txt`).
- **Sources:** **Orbitron** — [theleagueof/orbitron](https://github.com/theleagueof/orbitron)
  ("Copyright 2018 The Orbitron Project Authors", Reserved Font Name "Orbitron"); **Inter** —
  [rsms/inter](https://github.com/rsms/inter).
- **License:** **SIL Open Font License 1.1** (OFL-1.1) for both (`OFL.txt` vendored for Orbitron;
  Inter ships under the same OFL-1.1). The OFL permits bundling/embedding in any project, including a
  proprietary one, provided the fonts are not sold on their own and the Reserved Font Names are honored —
  both satisfied here (the fonts are UI assets, not resold; names unchanged).
- **Use:** cockpit typography (Orbitron for the STEWIE display/headings, Inter for body text), self-hosted
  same-origin (no Google Fonts CDN call) so type renders under the production CSP and offline.
