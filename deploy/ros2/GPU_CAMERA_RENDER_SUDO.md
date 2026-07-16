# Unblocking Gazebo camera render of a HEIGHTMAP world (GPU graphics in the container)

**Why this exists.** The Gazebo camera **cannot render a heightmap world on this host today**. `gz sim`
SIGABRTs the instant a camera has to render terrain (verified at DEM size 512 *and* 513, and it reproduces
with zero rocks — so it is the terrain, not the rock field). ogre2's **Terra** (heightmap) render path needs
a real modern-GL/compute context, and the container's software renderer (Mesa **llvmpipe**) can't provide one
— `glxinfo -B` reports *no* "OpenGL core profile version" under llvmpipe.

This was invisible until now because `stewie_lunar.sdf` — the world the working `gz-render` service actually
uses — is a **flat plane** (two `<plane>`, zero `<heightmap>`). So the camera path was only ever exercised on
a plane. BA-12/BA-13 put a real DEM + 4,184 rock collision models in the world; their geometry is verified
from gz's own entity tree, but **no camera has ever drawn the terrain**.

**The fix is host-side and needs `sudo`.** These are the exact steps.

---

## What is already done (verified, no action needed)

- **GPU present:** NVIDIA RTX 3090, driver 535.261.03.
- **CDI graphics spec exists:** `/var/run/cdi/nvidia.yaml` (root-owned, 15 KB) already carries the graphics
  libraries — `grep -c 'graphics\|libGLX_nvidia\|libEGL_nvidia' /var/run/cdi/nvidia.yaml` → 7. It was
  regenerated 2026-07-08. If in doubt, regenerate it (step 1).
- **Docker supports CDI:** Docker 29.6.1 has `features.cdi: true`.

The gap is that **the compose GPU config uses the legacy compute-only reservation**
(`deploy/compose.yml:234` → `reservations.devices: [{ driver: nvidia, capabilities: [ "gpu" ] }]`), which
injects `nvidia-smi` (compute) but **NOT** the graphics driver — so the container falls back to llvmpipe, and
a *visible-but-undriveable* GPU makes ogre2 pick EGL and segfault (which is exactly why the service currently
hides the GPU). The switch below gives the container a **real graphics-capable** GPU via CDI.

---

## Step 1 — (re)generate the CDI spec WITH graphics libs  `[sudo]`

```bash
sudo cp /var/run/cdi/nvidia.yaml /var/run/cdi/nvidia.yaml.bak-$(date +%Y%m%d)
sudo nvidia-ctk cdi generate --output=/var/run/cdi/nvidia.yaml
# verify graphics libs landed (expect > 0):
grep -c 'libGLX_nvidia\|libEGL_nvidia\|graphics' /var/run/cdi/nvidia.yaml
```

## Step 2 — give the render container the CDI GPU (graphics), not the compute-only reservation

Two ways; pick one.

**(a) One-off `docker run` (fastest to test):** add `--device nvidia.com/gpu=all` and drop the GPU-hiding
env. This is what a test render uses.

**(b) Compose (durable):** in `deploy/compose.yml`, for the render service (`gz-render` / the `godot`
profile), REPLACE the legacy block

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - { driver: nvidia, count: all, capabilities: [ "gpu" ] }
```

with the CDI device request:

```yaml
    devices:
      - "nvidia.com/gpu=all"     # CDI: injects the GRAPHICS driver (libGLX/libEGL_nvidia), not just compute
```

and **remove** the `LIBGL_ALWAYS_SOFTWARE=1` / `GALLIUM_DRIVER=llvmpipe` env from that service (they force
the software renderer we are trying to leave).

## Step 3 — make ogre2 select the NVIDIA GL, not llvmpipe

With the GPU now graphics-capable in the container, render via **GLX on Xvfb** (this repo's proven path — see
`gz_sim.launch.py`, which notes GLX-on-xvfb "renders on both CPU and GPU"; the EGL `--headless-rendering`
path could not get a GL 3.3 context and crashed ogre2). Env for the render process:

```bash
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 -ac &
# do NOT set LIBGL_ALWAYS_SOFTWARE / GALLIUM_DRIVER — let it pick the nvidia GL
export __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia   # force the nvidia GLX vendor
```

Confirm the container now sees a real GL: `glxinfo -B | grep -i 'OpenGL renderer'` should report the RTX 3090,
**not** `llvmpipe`.

## Step 4 — the small code fix that pairs with this (no sudo)

ogre2 warns `Heightmap final sampling should be 2^n` — the DEM export is currently **513 = 2^9+1** (ogre1's
convention). Change `scripts/dem_to_gazebo_heightfield._pow2_plus_1` to emit **2^n (512)**, and regenerate the
world (`python -m scripts.dem_to_gazebo_heightfield`). This alone does NOT fix the crash under llvmpipe (512
still SIGABRTs), but it is required for a clean ogre2 heightmap and should land together with the GPU fix.

## Step 5 — verify a real terrain camera frame

```bash
# with the GPU-graphics container + Xvfb + the 2^n world:
docker build -f deploy/ros2/Dockerfile.ros2dev ... # (already built as stewie-ros2dev:jazzy)
# bring up gz_sim.launch.py on haworth_heightfield.sdf, spawn the ez-rassor (z~9.1, terrain @ ~8.5 m),
# bridge /model/ipex/camera/front_left/image, and capture ONE frame.
```

Success = a rendered frame showing the **sloped Haworth terrain with boulders on it**, from the rover's own
camera. Gate on the IMAGE (a screenshot), not on "no errors" — the whole point is that the numbers already
verify and only the picture is missing. See task #52 for the full harness already scaffolded this session.

---

## If it still won't render on the GPU

Fallback ladder, in order:
1. `PROJ_IGNORE_CELESTIAL_BODY` is a RED HERRING here — that is the DEM *georef* warning (Moon vs Earth),
   harmless, unrelated to the render crash. Do **not** set it (it would compute the extent against Earth's
   radius — a wrong number that looks right).
2. Try `ogre` (ogre1) instead of `ogre2` for the sensor render engine (`<render_engine>ogre</render_engine>`
   in the world's Sensors plugin) — ogre1's Terra path is older and may tolerate the software/edge cases
   ogre2 does not. Lower fidelity, but it renders.
3. If the driver 535 + ogre2 combination is the blocker, a newer NVIDIA driver may be required; that is a
   host-level upgrade decision.
