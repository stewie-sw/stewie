#!/usr/bin/env bash
#
# STEWIE lunar QWC2 web-IDE — reproducible build for the artemis.stewie.space/ide/ deploy.
#
# Produces gis/qwc2/prod/ (webpack publicPath=/ide/) from the vendored source in this
# directory. deploy/compose.yml bind-mounts this prod/ read-only into the nginx container
# at /usr/share/nginx/ide, served by deploy/artemis-nginx.conf `location /ide/`.
#
# Upstream: qwc2-demo-app (github.com/qgis/qwc2-demo-app) pinned at v2026.02.16
#           (commit 92e36368af29f310e2068555a2e92e2e5cedb648). The qwc2 core lib
#           (dependency "qwc2":"2026.02.16") is resolved from node_modules via yarn.lock.
#
# See README_STEWIE.md for the lunar deltas and how to regenerate the vendored themes.json.
#
set -euo pipefail
cd "$(dirname "$0")"

# 1. Dependencies. Installed only when absent, pinned exactly by yarn.lock. node_modules/,
#    prod/, dist/, icons/build/ are gitignored (regenerated); a fresh git checkout has none.
if [ ! -d node_modules/qwc2 ]; then
  echo "[build] installing dependencies (yarn install --frozen-lockfile) ..."
  yarn install --frozen-lockfile
else
  echo "[build] node_modules/qwc2 present — skipping install."
fi

# 2. Generated inputs (both run fully offline from node_modules/qwc2):
#    - translations: merge qwc2 core + local strings into static/translations/*.json
#    - iconfont:     build the qwc2 icon webfont into icons/build/ (imported by js/app.jsx)
echo "[build] translations (qwc_update_translations) ..."
npx qwc_update_translations
echo "[build] iconfont (qwc_build_iconfont) ..."
npx qwc_build_iconfont

# NOTE: we deliberately DO NOT run `qwc_gen_themesconfig` (the upstream `prod` script does).
# That step queries a live QGIS WMS (localhost:8082) to regenerate static/themes.json from
# static/themesConfig.json. For a deterministic, offline, always-reproducible build we treat
# static/themes.json as a VENDORED artifact (checked in). Refresh it only when the .qgz layer
# set changes — see README_STEWIE.md "Regenerating themes.json".

# 3. Bundle. publicPath=/ide/ is set in webpack.config.js. CopyWebpackPlugin copies static/
#    (config.json, themes.json, themesConfig.json, translations/, assets/) into prod/.
echo "[build] webpack (production, publicPath=/ide/) ..."
npx webpack --mode production --progress

# 3b. Vendor Cesium (self-hosted, no CDN) into prod/cesium/ for the "Whole Moon" 3-D overview. Reuses the
#     repo's already-vendored Cesium 1.119 build (the SAME one the app.stewie.space cockpit serves) so there
#     is one Cesium of record and no 20 MB duplicated into git. Copied AFTER webpack because webpack's
#     output.clean wipes prod/ at the start of the bundle step (this is mount-safe: it empties the dir, it
#     does not remove the bind-mount point). Served by nginx `location /ide/` at /ide/cesium/ (CESIUM_BASE_URL
#     in js/mission/wholeMoonGlobe.js). prod/ is gitignored, so this stays out of version control.
CESIUM_SRC="../../stewie/server/cesium"
if [ ! -f "$CESIUM_SRC/Cesium.js" ]; then
  echo "FAIL: vendored Cesium not found at $CESIUM_SRC (needed for the Whole Moon overview)"; exit 1
fi
echo "[build] vendoring Cesium 1.119 -> prod/cesium/ (self-hosted, no CDN) ..."
rm -rf prod/cesium
cp -r "$CESIUM_SRC" prod/cesium

# 4. Sanity assertions — fail loudly rather than deploy a broken /ide/.
test -f prod/index.html            || { echo "FAIL: prod/index.html missing"; exit 1; }
test -f prod/dist/QWC2App.js       || { echo "FAIL: prod/dist/QWC2App.js missing"; exit 1; }
test -f prod/cesium/Cesium.js      || { echo "FAIL: prod/cesium/Cesium.js missing (Whole Moon overview)"; exit 1; }
test -f prod/cesium/Widgets/widgets.css || { echo "FAIL: prod/cesium/Widgets/widgets.css missing"; exit 1; }
grep -q '/ide/dist/QWC2App.js' prod/index.html || { echo "FAIL: prod/index.html not built for /ide/"; exit 1; }
grep -q 'stewie_lunar' prod/themes.json  || { echo "FAIL: lunar theme missing from prod/themes.json"; exit 1; }
grep -q 'IAU_2015:30135' prod/config.json || { echo "FAIL: lunar proj4 missing from prod/config.json"; exit 1; }
grep -q '"WholeMoon"' prod/config.json || { echo "FAIL: WholeMoon plugin missing from prod/config.json"; exit 1; }

echo "[build] OK — prod/ ready. Mounted by deploy/compose.yml at nginx /ide/."
