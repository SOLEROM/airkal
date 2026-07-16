# PX4 SITL image, pinned release, headless (SIH quadcopter model — no external
# simulator process, no GUI). Built once per PX4 tag; run one container per drone.
#
#   docker build -t airkal-sitl:<tag> --build-arg PX4_TAG=<tag> sitl/
#
# Stage 1 builds PX4 from source; stage 2 is a small runtime with only the
# build output. The runtime container needs host networking (see Makefile):
# instance i exposes MAVLink to the host on udp 14540+i.

ARG PX4_TAG=v1.15.4

FROM ubuntu:22.04 AS build
ARG PX4_TAG
ARG PX4_REPO=https://github.com/PX4/PX4-Autopilot.git
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git sudo lsb-release tzdata \
    && rm -rf /var/lib/apt/lists/*
# Clone the main repo only; `make` initializes just the submodules the SITL
# target needs (a full recursive clone pulls NuttX without tags and breaks
# PX4's version-header generation).
RUN git clone --branch "${PX4_TAG}" --depth 1 "${PX4_REPO}" /px4
RUN /px4/Tools/setup/ubuntu.sh --no-nuttx --no-sim-tools
RUN cd /px4 && make px4_sitl_default

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /px4/build/px4_sitl_default /px4/build/px4_sitl_default
COPY entrypoint.sh /px4/entrypoint.sh
RUN chmod +x /px4/entrypoint.sh && mkdir -p /px4/rootfs
WORKDIR /px4/rootfs
ENTRYPOINT ["/px4/entrypoint.sh"]
