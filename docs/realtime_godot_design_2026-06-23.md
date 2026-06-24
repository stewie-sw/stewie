# Realtime Godot rendering — design pass (2026-06-23)

Scope of the decision the user asked for ("ensuring Godot renders realtime"). This is a **design pass**,
not an implementation — realtime Godot is a new subsystem, not a config tweak, and the current sidecar
architecture has to change before any of it is built. This doc scopes that change so the build is bounded.

## Where we are (offline, batch, disk-based)

Verified from the code:

- **Per-render spawn, one-shot.** `stewie/godot/render.sh` launches Godot under `xvfb-run` + `--rendering-driver
  vulkan`, runs a scene (`sidecar.tscn`), the capture coroutines `await RenderingServer.frame_post_draw`,
  `save_png` to `stewie/godot/out/…`, and the process **quits**. Every render is a fresh process.
- **The cockpit consumes static PNGs.** The Perception pane (`cockpit.js` `loadPanorama` / `loadPointCloud`)
  fetches the **served PNG files** — it is a gallery of pre-rendered frames, not a live view.
- **A continuous loop already exists, but writes to disk.** `drive_controller.gd::_process` runs a per-step
  loop (`frame_post_draw` ×2 → `save_png` per SubViewport) — this is the closest thing to a render loop and
  is the **template** for a persistent process, but its sink is the filesystem, not a stream.
- **Scale is fixed close-up.** The sidecar camera far-plane is 100 m — a ~5 m rover-patch *perception*
  renderer. The 10 km LOLA globe is the planner's CesiumJS view, NOT this path. Realtime applies only at
  the perception scale.
- **No streaming seam.** No WebSocket / MJPEG / WebRTC render endpoint exists; the live Chrono producer is
  a stub.

So "realtime" is genuinely new: a **live frame stream the cockpit watches update**, vs today's
render-to-disk-then-serve-PNG.

## The actual goal — a live digital-twin EXECUTION view (user, 2026-06-23)

> "we should be able to plot points and operations and watch everything unfold in godot rendered in
> selected dem exact coordinates with current status of the ground from previous digging berms etc."

This is bigger than a perception preview — it is the **live digital twin**: plot operations on the map, then
watch them *unfold in Godot at the selected DEM's exact coordinates, with the ground reflecting the
accumulated state of every prior dig / berm.* The key realization: **the pieces already exist offline**; the
work is making them live, and pointing the render at the right SOURCE.

- **Render source = the conserved authority's PERSISTENT state, not a fresh scene.** "Current status of the
  ground from previous digging berms" *is* `stewie/physics/column_state.py` — the single conserved terrain
  authority that accumulates every cut / fill / sinter / berm (mass-conserving). The live render samples
  THAT state, so what you see is the real DEM base **plus every prior mutation** — the STEWIE "Terrain
  Memory" paradigm, made live.
- **The render bridge already exists: Seam-1.** The authority writes texture-encoded state fields
  (heightmap, density, disturbance, state labels) to disk and Godot samples them in shaders — this is the
  existing `--layers state` false-colour render. Realtime = re-write those textures on each mutation + have
  the persistent Godot process re-sample + re-render. **No new render path** — the existing Seam-1 made live.
- **DEM-coordinate accuracy already exists.** `latlon_to_dem_origin` / the globe-pick siting places the
  authority *and* the render at the real LOLA tile origin (`IAU_2015:30135`). The live view is the real
  terrain at the picked coordinates.
- **Operations execute AGAINST the authority.** Plotting + running an operation (cut / fill / berm) steps
  the conserved cut/fill/berm primitives → mutates `column_state` → Seam-1 textures update → Godot
  re-renders; the rover drives (`drive_controller.gd`) and digs/builds visibly. "Watch everything unfold" =
  the authority's state changing live, op by op.
- **Persistence = the Terrain Memory.** The accumulated `column_state` IS the source of truth, so prior
  digs/berms persist across operations + sessions — the next operation builds on the real, mutated ground.

This makes realtime Godot the **keystone "watch the build unfold" capability** (the live execution view of
the authoritative world model), not a side preview — and it keeps the core rail intact: **the conserved
authority mutates; Godot renders a VIEW of it.** It just runs live.

**How this reshapes the rest of this doc:**
- The **control seam** (below) carries not only camera/sun but **operation triggers** ("run this op",
  "step the sim N s") + the rover `cmd_vel`.
- The **stream** shows the authority's *mutating terrain state* (heightmap + state labels at the real DEM
  origin), not just camera frames.
- A **live session** = (the authority's `column_state` at the picked DEM coords) + (the persistent Godot
  process sampling Seam-1). Each op steps the authority → re-textures → re-renders → streams.
- A new **operation-execution loop** phase (Phase 2.5 below): plot op → step `column_state` → rewrite Seam-1
  textures → signal Godot → frame, on top of the raw streaming. This is the part that delivers the vision.

## What "realtime" requires (the four changes)

1. **A long-running Godot process** (not per-frame spawn) that boots the scene once and stays up.
2. **A streaming seam** Godot → cockpit (frames pushed live).
3. **GPU contention management** on the single RTX 3090 (shared with training, COLMAP, other renders).
4. **A cockpit live consumer** (the Perception pane shows a live stream instead of static PNGs).

## Streaming seam — options + recommendation

| Option | Mechanism | Pros | Cons | Verdict |
|---|---|---|---|---|
| **MJPEG over HTTP** | `multipart/x-mixed-replace` stream; cockpit `<img src="/render/live">` | Trivial client (an `<img>`), works through Cloudflare + the existing FastAPI server, no codec | Re-sends full JPEG/frame (bandwidth); ~5–15 fps practical | **v1 — recommended** |
| **WebSocket binary frames** | server pushes JPEG/PNG; cockpit decodes → `<canvas>` | Backpressure, multiple streams, per-frame metadata | More client JS; still frame-by-frame, no inter-frame compression | v2 if fps/control demands it |
| **WebRTC** | H.264/VP8 video, signaling + ICE + a media path | Lowest latency, real video codec | Heavy (signaling server, a Godot WebRTC plugin or an external encoder) | Overkill for a low-fps perception preview |

**Recommendation: MJPEG-over-HTTP for v1.** It is the simplest *honest* path that works through the existing
Cloudflare tunnel + FastAPI, needs almost no client code, and degrades gracefully. Upgrade to WS/WebRTC only
if a measured fps/latency requirement forces it — don't pay that complexity up front.

## The long-running-sidecar refactor

From `spawn → render → quit` to a **persistent render server**:

1. Boot `sidecar.tscn` once (xvfb+Vulkan, as today).
2. Run a **control loop** (extend `drive_controller.gd::_process`): poll a control seam for operator inputs —
   sun elev/azim, camera selection, rover pose, plan edits — reusing the existing `cmd_vel` / polled-dir
   pattern from the drive loop.
3. Render each frame and **emit it to the stream sink** (a frame buffer / named pipe / shared-memory tile)
   instead of (or in addition to) `save_png`.
4. The FastAPI side reads that sink and serves the MJPEG stream.

The `drive_controller` loop already proves the per-frame render cadence; the work is (a) keep the process
alive, (b) read commands from the control seam, (c) write frames to the stream sink.

## GPU budget + multi-user (the real constraint)

- A 1024×768 sidecar at ~10 fps is **light** (<1 GB, sub-ms/frame on the 3090, proven 2026-06-04). The
  headless `xvfb`+Vulkan path works; in a container use `--gpus all` + the present nvidia CDI runtime.
- **One shared 3090 ⇒ one live session at a time** (or a short queue). A GPU **session lock** + an fps /
  resolution **budget** (in `config.py`) is mandatory — otherwise concurrent live renders + training thrash
  the card. Per-user concurrent live render needs more GPUs or a strict per-session budget; surface this
  limit honestly in the UI ("live render busy — N ahead").
- **Fallback (no regression):** a GPU-less deploy shows the committed sample renders with an honest
  "live render unavailable (no GPU)" state — the existing static-PNG path stays as the floor.

## Cockpit consumer

- A **"Live" sub-tab in the Perception (Validate→Perception) pane**: `<img src="/render/live?session=…">`
  for the MJPEG stream + controls (sun-elev/azim sliders, camera select, rover position) that POST to the
  control seam → Godot re-renders → the stream updates. Minimal client JS; reuses the existing pane.
- Honest empty/fallback state as above.

## Architectural rails (do NOT break)

- **Godot stays render-only.** The conserved-physics authority (`stewie/physics/column_state.py`) remains
  the sole terrain mutator; the live render is a *view* of that state, never a second authority. (This is
  the project's core invariant — keep it.)
- **Ground/trainer tool, not flight.** Realtime render serves perception hardening + operator preview at
  TRL ~3–4; it does not command a rover (the LIVE/ARMED command tier stays gated, MO-04).
- **Perception scale only.** Keep live render to the ~5 m rover patch; the globe is Cesium.
- **No React rewrite.** The MJPEG `<img>` in the existing pane is the v1 client — do not repeat the reverted
  big-bang rewrite.

## Phasing (≈2–4 weeks, gated on GPU + the stream architecture)

- **Phase 0 — design (this doc).**
- **Phase 1 — persistent process:** refactor the sidecar to a long-running process with a control loop
  (read commands, render, still save to disk). Proves the loop survives + responds. (~days)
- **Phase 2 — stream sink:** Godot frame → buffer/pipe → a FastAPI `GET /render/live` MJPEG endpoint. (~days)
- **Phase 2.5 — operation-execution loop (THE vision):** the control seam triggers a `column_state` op
  (cut / fill / berm / drive) at the picked DEM origin; the conserved authority mutates (mass-conserving);
  Seam-1 textures are rewritten; the persistent Godot process re-samples + emits a frame. This is what turns
  the raw stream into "plot an operation and watch it unfold against the accumulated ground." (~days)
- **Phase 3 — cockpit live-view:** the Perception "Live" sub-tab consuming the stream; plot operations on the
  map and run them (POST to the control seam) → watch the terrain change live; sun/camera controls too. (~days)
- **Phase 4 — GPU scheduler + budget:** session lock/queue + fps/resolution budget (`config.py`) + the
  GPU-less fallback + the "busy" UI. (~days)
- **Phase 5 — containerize + deploy:** the live-render service in a `--gpus` container behind the deploy. (~days)

## What it does NOT need

A React rewrite · a new physics engine · WebRTC (for v1) · changes to the conserved authority or the command
authority model. It is an additive render-streaming service + a thin cockpit consumer, on top of the existing
Godot sidecar and FastAPI server.

## Open decisions for the user (before Phase 1)

1. **fps / resolution target** for v1 (drives the GPU budget). Default proposal: 1024×768 @ ~10 fps.
2. **Concurrency policy**: single shared live session (simplest) vs a small queue vs per-user budget.
3. **What the operator drives live**: just sun + camera (cheap), or full rover pose / plan-edit re-render
   (closes more of the loop, more control-seam work).
