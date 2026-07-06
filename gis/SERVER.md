# QGIS Server — publishing `stewie_south_pole.qgz` (P1.8)

The web-render foundation for the dual-client architecture: QGIS Server publishes the **same**
`stewie_south_pole.qgz` that QGIS Desktop opens, so the browser gets pole-truthful map images in
`IAU_2015:30135` without a client-side projection engine. This is the "one project, two clients"
promise (plan `design/STEWIE_QGIS_PIVOT_PLAN_2026-07-05.md` §3.3 / P1.8 / gate item 2).

**Proof, in one line:** a server GetMap of Site01 in `IAU_2015:30135` is **byte-for-byte identical**
(all 1,960,000 RGB pixels, `max_abs_diff = 0`) to the QGIS Desktop proof render
`proof/site01_render.png` — see `proof/site01_server_getmap.png`. The same result holds across QGIS
Desktop 3.22, host QGIS Server 3.22.16, and Docker QGIS Server 3.34.

---

## Two serving lanes

Both publish the identical `.qgz`; either satisfies gate 2. The `.qgz` uses **project-relative**
datasource paths (`../../data/gis/...` from `code/gis/`), so whatever serves it must let those paths
resolve to `/mnt/projects/stewie/data/gis`.

### Lane A — Docker `qgis/qgis-server` (preferred deployment shape; the compose service)

A new `qgis-server` service in `code/deploy/compose.yml`, **local-only** (`127.0.0.1:8082`),
**opt-in** via the `gis` profile so it never starts with a default `up` and never touches the live
`app.stewie.space` backend/frontend.

```bash
# start (from anywhere; --project-directory defaults to deploy/, which auto-loads deploy/.env)
docker compose -f /mnt/projects/stewie/code/deploy/compose.yml --profile gis up -d qgis-server
# stop / remove
docker compose -f /mnt/projects/stewie/code/deploy/compose.yml --profile gis down qgis-server
#   (or: docker rm -f stewie-qgis-server)
# logs
docker logs -f stewie-qgis-server
```

The mounts are the critical detail — they place the project so its relative paths resolve:

| host | container | why |
|---|---|---|
| `code/gis` (carries the `.qgz`) | `/io/data/code/gis` (ro) | project dir |
| `data/gis` (COGs, hillshade, vectors) | `/io/data/data/gis` (ro) | `<projectdir>/../../data/gis` resolves here |

**Image pin `qgis/qgis-server:3.34`, NOT `:3.22`.** The exact-version 3.22 image ships **PROJ 6.3.1**
whose `proj.db` has **zero IAU rows** → it cannot resolve the project CRS `IAU_2015:30135` (`proj_create_from_database: crs not found`). The 3.34 image bundles **PROJ 9.4** (IAU registry present) and
reads the 3.22 project forward-compatibly, rendering byte-identically to Desktop 3.22.

### Lane B — host `qgis_mapserver` (exact-version; the fallback that produced the saved proof)

The host has QGIS Server **3.22.16** (`/usr/lib/cgi-bin/qgis_mapserv.fcgi` + the
`qgis_mapserver` development server) — the *exact* version the project was authored in, with an
IAU-aware PROJ (host PROJ resolves `IAU_2015:30135`). `spawn-fcgi` is not installed and needs no
sudo here because `qgis_mapserver` serves HTTP directly and caches the pinned project.

```bash
export QT_QPA_PLATFORM=offscreen
export XDG_RUNTIME_DIR=/tmp/qgisrt && mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
export QGIS_SERVER_PARALLEL_RENDERING=true QGIS_SERVER_MAX_THREADS=2
qgis_mapserver -p /mnt/projects/stewie/code/gis/stewie_south_pole.qgz 127.0.0.1:8081
# stop: Ctrl-C (or pkill -f 'qgis_mapserver.*8081')
```

**Which lane and why.** The saved `proof/site01_server_getmap.png` was produced by **Lane B** (host
3.22.16) because it is the exact project version → its render is *pixel-identical* to Desktop, the
strongest possible gate-2 evidence. **Lane A is the deployment shape** and renders the identical
image; it is the compose service to carry into P2/P3. Lane B is the documented fallback for
Docker-impractical situations (here: 3.22 image's PROJ lacks IAU + bridged-container egress stalls,
see caveats).

---

## Proof commands (gate 2 + server side of gate 3)

Endpoints differ only in how the project is addressed: host lane pins it with `-p` (no `MAP` arg);
Docker lane routes through nginx `/ows/` and needs `MAP=<in-container path>`.

```bash
# choose one:
HOST='http://127.0.0.1:8081/?'                                              # Lane B (host)
DOCK='http://127.0.0.1:8082/ows/?MAP=/io/data/code/gis/stewie_south_pole.qgz&'  # Lane A (docker)
S="$DOCK"   # or "$HOST"

# 1) GetCapabilities lists the project's layers + advertises IAU_2015:30135
curl -s "${S}SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities" \
  | grep -oE '<Name>[^<]*</Name>'         # -> Site01 DEM/Hillshade/Slope, per-site groups, Haworth, vectors, WMS drapes

# 2) GetMap of Site01 in IAU_2015:30135 -> proof/site01_server_getmap.png (matches the desktop render)
#    BBOX is the Site01 DEM extent (gdalinfo): minx,miny,maxx,maxy in metres.
#    LAYERS order = Hillshade,DEM,Slope: WMS draws first at the BOTTOM, so Slope ends up on top,
#    matching Desktop's setLayers([Slope, DEM, Hillshade]).
curl -s "${S}SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap\
&LAYERS=Site01%20Hillshade,Site01%20DEM,Site01%20Slope&STYLES=\
&CRS=IAU_2015:30135&BBOX=-19000,-20000,-3000,-4000\
&WIDTH=1400&HEIGHT=1400&FORMAT=image/png&BGCOLOR=0x000000&TRANSPARENT=FALSE" \
  -o proof/site01_server_getmap.png

# 3) GetFeatureInfo returns the real Float32 elevation (cross-check vs gdallocationinfo).
#    Request at the DEM's native 3200x3200 so 1 image pixel == 1 DEM cell (unambiguous).
curl -s "${S}SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo\
&LAYERS=Site01%20DEM&QUERY_LAYERS=Site01%20DEM&CRS=IAU_2015:30135\
&BBOX=-19000,-20000,-3000,-4000&WIDTH=3200&HEIGHT=3200&I=1600&J=1600&INFO_FORMAT=application/json"
#   -> {"...":{"Band 1":"1944.77"}}   ;  gdallocationinfo -valonly cog/Site01/dem.tif 1600 1600 -> 1944.76708984375
```

**GetFeatureInfo precision (honest).** The server reads the *real* Float32 COG value — verified against
`gdallocationinfo` on 4 pixel-exact spot checks (e.g. server `1944.77` vs COG `1944.76708984375`;
`117.411` vs `117.410675...`). The only loss is the WMS **text display** rounding to ~6 significant
figures (~cm at these elevations). If a bit-exact float readout is ever needed, the plan's noted
fallback (§8 risk 2) is a small backend endpoint over the COGs (rasterio) — **not built here**.

---

## Headless test

`test_server.py` (pytest): discovers a running server (`$STEWIE_QGIS_SERVER`, then `:8081`, then
`:8082`), asserts GetCapabilities lists Site01 + advertises `IAU_2015:30135`, and asserts a Site01
GetMap is a correctly-sized, non-blank PNG. It **skips cleanly** (never fails) when no server is up,
and needs only Pillow (`pytest.importorskip`) + stdlib `urllib`.

```bash
/mnt/projects/07_runtime_system/venv/bin/python -m pytest gis/test_server.py -v
# force one lane:  STEWIE_QGIS_SERVER='http://127.0.0.1:8082/ows/' ... pytest gis/test_server.py
```

---

## Caveats / environment notes

- **Container egress (Lunaserv WMS).** On the archimedes docker bridge, egress to `wms.im-ldi.com`
  times out, so the 3 Lunaserv imagery drapes would stall project load ~60 s before being dropped.
  The compose service resolves `wms.im-ldi.com → 127.0.0.1` (`extra_hosts`) so those layers 404
  instantly and `QGIS_SERVER_IGNORE_BAD_LAYERS=1` drops them. **Remove that `extra_hosts` line on a
  host whose bridge can reach Lunaserv** so the imagery drapes render. The host lane (B) reaches
  Lunaserv fine.
- **Backend `/ogc` drape.** The `.qgz` references the STEWIE backend WMS at `http://127.0.0.1:8000`.
  From a bridged container that is container-loopback (dead) → dropped by IGNORE_BAD_LAYERS; the
  `host.docker.internal:host-gateway` mapping is in place for the P2.0 wiring that points it at the
  host. The authoritative on-disk COG/vector layers render regardless.
- **Not public.** Both lanes bind `127.0.0.1` only. Edge gating (Cloudflare Access + backend token)
  is Phase 3; nothing here touches `app.stewie.space` or `/etc/cloudflared`.
