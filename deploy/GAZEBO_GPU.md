# Gazebo GPU rendering — what is actually blocking it (measured 2026-08-02)

`CLAUDE.md` records that **a Gazebo camera render of a heightmap has never worked in this repo**: gz
SIGABRTs the instant a camera renders a heightmap (n=513 and 512, reproduces with zero rocks), because
ogre2's Terra component needs modern GL/compute that Mesa llvmpipe cannot provide. The recorded fix was
"GPU graphics in the container (host CDI graphics cap, a sudo change)".

This narrows that to a specific, tested diagnosis and a specific command.

## What is already true (no change needed)

| Thing | State |
|---|---|
| GPU | NVIDIA GeForce RTX 3090, driver 535.261.03 |
| `nvidia-ctk` | installed at `/usr/bin/nvidia-ctk` |
| Docker `nvidia` runtime | **registered** (`Runtimes: io.containerd.runc.v2 nvidia runc`) |
| `docker run --gpus all` | **works without sudo** — `nvidia-smi -L` inside the container sees the 3090 |
| Device nodes in-container | `/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-uvm-tools` present |

So GPU **compute** reaches the container today. That is not the blocker.

## What is actually missing

Measured inside `stewie-gazebo:jazzy` with `--gpus all -e NVIDIA_DRIVER_CAPABILITIES=all`:

```
eglQueryDevicesEXT  -> devices = 0
eglInitialize (EGL_PLATFORM_DEVICE_EXT) -> False
libEGL warning: pci id for fd 3: 10de:2204, driver (null)      # 10de:2204 == GA102 (RTX 3090)
find / -name 'libnvidia-glcore*'  -> (nothing)
```

`libnvidia-glcore` — the NVIDIA OpenGL implementation — **is not in the container**. Only the platform
shims are (`libnvidia-egl-gbm`, `libnvidia-egl-wayland`). That is the exact signature of the toolkit
injecting the *compute* capability but not *graphics*: the driver cannot enumerate an EGL device, so
ogre2 gets no hardware GL context.

`/usr/lib/x86_64-linux-gnu/nvidia/current/libEGL_nvidia.so` and `/usr/share/glvnd/egl_vendor.d/10_nvidia.json`
ARE present, but they come from the image's Debian packaging, not from driver injection — pointing the
loader at them (`__EGL_VENDOR_LIBRARY_FILENAMES`, `LD_LIBRARY_PATH`) still yields `devices = 0`, because
the userspace GL core the driver needs is absent.

**No CDI spec exists**: `/etc/cdi/*.yaml` and `/var/run/cdi/*.yaml` are both empty. `--gpus all` is
therefore taking the legacy hook path, which is why `NVIDIA_DRIVER_CAPABILITIES=all` did not produce the
graphics injection.

## The change (requires sudo — host-level, Aaron's)

```bash
# 1. Generate the CDI spec so the toolkit can inject the full capability set.
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
sudo nvidia-ctk cdi list                      # expect nvidia.com/gpu=all

# 2. Verify graphics now reaches a container -- this is the gate, not nvidia-smi:
docker run --rm --device nvidia.com/gpu=all -e NVIDIA_DRIVER_CAPABILITIES=all \
  stewie-gazebo:jazzy bash -lc 'find / -name "libnvidia-glcore*" | head -1'
# a hit means graphics is injected; empty means it is still compute-only and gz will still fall back
```

Then in `deploy/compose.yml`, the `gz-render` service (currently and DELIBERATELY GPU-free):

```yaml
  gz-render:
    environment:
      NVIDIA_DRIVER_CAPABILITIES: all        # graphics + display, not just compute+utility
      # DELETE these two -- they force software rendering and are the current workaround:
      # LIBGL_ALWAYS_SOFTWARE: "1"
      # GALLIUM_DRIVER: llvmpipe
    deploy:
      resources:
        reservations:
          devices:
            - { driver: nvidia, count: all, capabilities: [ gpu, graphics, display ] }
```

## Why the current config hides the GPU on purpose

`compose.yml` says, above `gz-render`:

> NO GPU is requested (no deploy.resources / no /dev/dri): a visible-but-undriveable GPU makes ogre2
> pick EGL and segfault, so hiding it is what lets Mesa llvmpipe render cleanly.

That is a correct workaround for the current state and **must not be removed until step 2 above
verifies**. A half-attached GPU is worse than none: ogre2 selects EGL, gets no usable context, and
aborts. Remove `LIBGL_ALWAYS_SOFTWARE`/`GALLIUM_DRIVER` only once `libnvidia-glcore` is confirmed
present in the container.

## What this unblocks, honestly

Only the **camera render** of a heightmap. It does not change the architectural decision of record: the
conserved numpy authority remains the single physics authority for terrain and rover, and Gazebo remains
a ROS sensor shell. Excavation can never live there (baked heightfield, no deformable path).

`BA-12`/`BA-13` geometry is currently verified from gz's own entity tree (8,368 `<sphere>`), not by
camera. With this fixed, that verification could be done by render instead — which is the real gain.
