# STEWIE lunar web-IDE (QWC2) — vendored source + lunar overlay

The QGIS-backed web IDE served live at **`artemis.stewie.space/ide/`**. It is a vendored,
lunar-retargeted build of the QGIS Web Client demo app. The OpenLayers viewer at `/` and this QWC2
IDE at `/ide/` coexist on the same nginx origin (`deploy/artemis-nginx.conf`), both read-only.

## Upstream (pinned)

- **App**: [`qwc2-demo-app`](https://github.com/qgis/qwc2-demo-app) — version **`2026.02.16`**,
  commit **`92e36368af29f310e2068555a2e92e2e5cedb648`** (2026-06-18).
- **Core lib**: `qwc2` `2026.02.16`, resolved as an npm dependency (see `package.json` +
  `yarn.lock`), aliased in `webpack.config.js`. It is NOT vendored — `build.sh` installs it into
  `node_modules/` from the pinned lockfile.

The upstream source tree is vendored here (its own `.git` and the dangling `qwc2` submodule pointer
in `.gitmodules` were removed so this lives as plain files in the STEWIE monorepo). To re-pull
upstream from scratch: `git clone https://github.com/qgis/qwc2-demo-app && git -C qwc2-demo-app
checkout 92e3636`, then re-apply the lunar deltas below.

## Lunar deltas (what we changed vs stock qwc2-demo-app)

The verbatim pre-change originals are kept on disk in `_stewie_orig/` (gitignored) so the diff is
always recoverable: `diff _stewie_orig/config.json.orig static/config.json`, etc.

- **`static/config.json`** — lunar CRS + Earth-isms stripped:
  - `projections`: replaced the Earth EPSG set with the two IAU 2015 lunar CRSes —
    `IAU_2015:30135` (Moon South Polar Stereographic, `+proj=stere +lat_0=-90 +R=1737400`) and
    `IAU_2015:30100` (Moon 2015 geographic / selenographic lon-lat, `+proj=longlat +R=1737400`).
  - `urlPositionCrs` → `IAU_2015:30135`; `geodesicMeasurements` → `false` (no WGS84 geodesy on the Moon).
  - Removed Earth-only plugins/config (`LayerCatalog` sourcepole catalog, `NewsPopup`), and the
    subpath-deploy keys `assetsPath: /ide/assets`, `translationsPath: /ide/translations`.
- **`static/themesConfig.json`** — a single lunar theme:
  - `defaultMapCrs` → `IAU_2015:30135`, `defaultTheme` → `stewie_lunar`; lunar `defaultScales`.
  - The one theme `stewie_lunar` points at `.../ows/?MAP=/io/data/code/gis/stewie_south_pole.qgz`,
    `mapCrs IAU_2015:30135`, `additionalMouseCrs [IAU_2015:30100]`, `defaultDisplayCrs
    IAU_2015:30100` (the **selenographic lon/lat readout** in the bottom bar), extent = the polar
    stereographic bounds, attribution `STEWIE / NASA LOLA / LROC`, no Earth background layers.
- **`static/themes.json`** — the generated theme index (WMS capabilities for `stewie_lunar`).
  See "Regenerating themes.json" below — this is a **vendored artifact**, not built by `build.sh`.
- **`webpack.config.js`** — `output.publicPath: '/ide/'` (so the injected bundle + lazy plugin
  chunks resolve under `/ide/`), plus a dev-server `/ows` proxy → `127.0.0.1:8082` on port 8084.
- The **"Mission Map"** print layout and the lunar `printResolutions` live in the QGIS project
  (`gis/stewie_south_pole.qgz`) and surface through the WMS GetProjectSettings capabilities that
  `themes.json` captures; they are not separate files here.

## Rebuild (produces `prod/`, served at `/ide/`)

```bash
gis/qwc2/build.sh
```

`build.sh` (from a clean checkout):

1. `yarn install --frozen-lockfile` — only if `node_modules/qwc2` is absent; pinned by `yarn.lock`.
2. `qwc_update_translations` + `qwc_build_iconfont` — both run **fully offline** from
   `node_modules/qwc2`. iconfont writes `icons/build/qwc2-icons.{woff,css}`, which `js/app.jsx`
   imports (so it must exist before webpack).
3. `webpack --mode production` — bundles `js/app.jsx`, copies `static/` (config.json, themes.json,
   themesConfig.json, translations/, assets/) into `prod/`, and injects `/ide/`-rooted asset URLs.
4. Sanity assertions (fails loudly): `prod/index.html` references `/ide/dist/QWC2App.js`,
   `prod/themes.json` has `stewie_lunar`, `prod/config.json` has `IAU_2015:30135`.

`build.sh` deliberately does **NOT** run `qwc_gen_themesconfig` (the upstream `prod` script does).
That step queries a live QGIS WMS to regenerate `static/themes.json`; skipping it keeps the build
deterministic and offline. Clean rebuild takes ~35 s on this host.

### The build is mount-safe; a full `rm -rf prod` is not

`deploy/compose.yml` **bind-mounts** `../gis/qwc2/prod` read-only into the `stewie-artemis-web`
nginx container. `build.sh` relies on webpack's `output.clean` to replace `prod/`'s **contents** in
place, preserving the directory inode — so a routine `./build.sh` updates the live `/ide/`
**without** a container restart (the new content-hashed bundle is served immediately).

If you instead delete the whole directory (`rm -rf prod`), you sever the bind mount from its inode
and the container serves a stale/empty mount (403 / 500). Recover by re-attaching the mount:

```bash
docker restart stewie-artemis-web    # re-resolves the bind mount to the fresh prod/ inode
```

## Regenerating `themes.json` (only when the `.qgz` layer set changes)

`static/themes.json` is a captured dump of the QGIS project's WMS capabilities. Regenerate it only
after you change `gis/stewie_south_pole.qgz` (layers, print layouts, extent), with the qgis-server
container up (it must be able to serve the theme's `url`):

```bash
cd gis/qwc2
docker compose -f ../../deploy/compose.yml --profile gis up -d qgis-server
npx qwc_gen_themesconfig      # reads static/themesConfig.json -> writes static/themes.json
./build.sh                    # rebuild prod/ with the refreshed theme index
```

Then commit the updated `static/themes.json`.

## What is gitignored (regenerated by `build.sh`, not committed)

Per the repo root `.gitignore` (targeted, replacing the old blanket `gis/qwc2/` ignore) plus this
dir's `.gitignore`:

- `node_modules/` — `yarn install --frozen-lockfile`
- `prod/`, `dist/` — `webpack` (the `/ide/` deploy artifact)
- `icons/build/` — `qwc_build_iconfont`
- `_stewie_orig/` — verbatim pre-change upstream copies (diff reference only)
- `proof/` — reproducibility screenshots (e.g. `proof/qwc2_reproduced.png`)

Everything else in this directory is the committed vendored source.
