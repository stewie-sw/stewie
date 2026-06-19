# COLMAP built FROM SOURCE for CUDA 12.2 + Ampere (sm_86) -- the one combination no prebuilt
# graffitytech tag offers, which is what a host with an RTX 3090 (sm_86) on driver 535 (CUDA 12.2
# ceiling) needs for dense MVS:
#   * the 12.8 prebuilt tag -> CUDA 12.8 > driver 12.2 -> "forward compatibility on non supported HW"
#   * the 12.2/COLMAP-3.9 prebuilt tag -> built without sm_86 -> "no kernel image for the device"
# So we compile COLMAP ourselves on a CUDA-12.2 base with CMAKE_CUDA_ARCHITECTURES=86.
#
# COLMAP 3.9.1: the first release that DROPPED the bundled PBA (whose legacy CUDA texture-reference API
# does not compile on CUDA 12), and it builds against Ubuntu 22.04's apt Ceres 2.0 (verified: the prebuilt
# graffitytech 3.9-cuda12.2.2 image uses Ceres 2.0.0), so we need not build Ceres. (3.8 fails: PBA + CUDA 12.)
# Build with --network=host (the build apt needs archive.ubuntu.com):
#   docker build --network=host -f scripts/colmap/colmap-src.Dockerfile \
#     -t fossipex/colmap:src-cuda12.2-sm86 scripts/colmap/
#
# Run is identical to the prebuilt image (CPU SIFT + CUDA dense on a headless server):
#   docker run --rm --gpus all -v "$PWD":/work -w /work fossipex/colmap:src-cuda12.2-sm86 \
#     python3 scripts/colmap/colmap_recon.py recon --images out/colmap/views \
#       --work out/colmap/recon --no-gpu --dense
FROM nvidia/cuda:12.2.2-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ARG COLMAP_REF=3.9.1
ARG CUDA_ARCH=86

RUN apt-get update && apt-get install -y --no-install-recommends \
        git cmake ninja-build build-essential ca-certificates \
        libboost-all-dev \
        libeigen3-dev libflann-dev libfreeimage-dev libmetis-dev \
        libgoogle-glog-dev libgflags-dev libsqlite3-dev libglew-dev \
        libceres-dev libcgal-dev \
        qtbase5-dev libqt5opengl5-dev \
        python3 python3-numpy \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch "${COLMAP_REF}" --depth 1 https://github.com/colmap/colmap.git /opt/colmap \
    && cmake -S /opt/colmap -B /opt/colmap/build -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCH}" \
        -DCUDA_ENABLED=ON \
        -DGUI_ENABLED=OFF \
        -DTESTS_ENABLED=OFF \
    && cmake --build /opt/colmap/build --target install -j"$(nproc)" \
    && rm -rf /opt/colmap

ENTRYPOINT []
WORKDIR /work
CMD ["bash", "-lc", "colmap -h 2>&1 | head -n 1 && python3 -c 'import numpy; print(\"numpy\", numpy.__version__)'"]
