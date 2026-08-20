# syntax=docker/dockerfile:1.7

ARG KASM_BASE_IMAGE=kasmweb/core-ubuntu-noble@sha256:491cdbb3f6e5fb25d9cbd41320e1f5f415713e4ab646097a03e5c551bd817835
FROM ${KASM_BASE_IMAGE}

USER root

ARG BLENDER_VERSION=5.0.1
ARG BLENDER_SHA256=8019580ee1b7262e505f4196a00237ccf743c88d205b38d34201510676e60b09

ENV DEBIAN_FRONTEND=noninteractive \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display,video \
    BLENDER_BINARY=/opt/blender/blender \
    BLENDER_AGENT_PORT=8001 \
    BLENDER_WORKSPACE_ROOT=/workspace \
    BLENDER_GDRIVE_REMOTE=gdrive: \
    RCLONE_CONFIG=/workspace/.config/rclone/rclone.conf \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg jq libasound2t64 libegl1 libgl1 libglvnd0 \
        libice6 libsm6 libvulkan1 libx11-6 libxcursor1 libxext6 libxfixes3 \
        libxi6 libxinerama1 libxkbcommon0 libxkbcommon-x11-0 libxrandr2 libxrender1 libxxf86vm1 \
        mesa-utils procps python3-venv rclone util-linux xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --retry 5 --retry-delay 3 \
        "https://download.blender.org/release/Blender5.0/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        --output /tmp/blender.tar.xz \
    && echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum --check --strict \
    && mkdir -p /opt/blender \
    && tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && rm /tmp/blender.tar.xz \
    && /opt/blender/blender --background --version

RUN /opt/blender/5.0/python/bin/python3.11 -m pip install --no-cache-dir --upgrade \
        "setuptools==83.0.0" "urllib3==2.7.0"

RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade accountsservice libaccountsservice0 \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/council-agent \
    && /opt/council-agent/bin/pip install --no-cache-dir \
        "fastapi==0.141.1" "starlette==1.3.1" "pydantic==2.11.7" "uvicorn==0.35.0" \
        "nvidia-ml-py==13.580.82" "psutil==7.0.0" "Pillow==12.3.0"

RUN mkdir -p /opt/council /workspace/render_jobs /workspace/logs /workspace/.config/rclone \
        /home/kasm-default-profile/Desktop /home/kasm-default-profile/.config/rclone

COPY src/scripts/blender_listener.py src/scripts/blender_job.py src/scripts/blender_mixdown.py src/scripts/blender_gui_bootstrap.py /opt/council/
COPY docker/blender-runpod/blender-launcher.sh /usr/local/bin/blender
COPY docker/blender-runpod/custom_startup.sh /dockerstartup/custom_startup.sh
COPY docker/blender-runpod/Blender.desktop /home/kasm-default-profile/Desktop/Blender.desktop

RUN chmod 0755 /usr/local/bin/blender /dockerstartup/custom_startup.sh \
        /home/kasm-default-profile/Desktop/Blender.desktop \
    && chmod 0644 /opt/council/*.py \
    && ln -s /workspace /home/kasm-default-profile/Desktop/Workspace \
    && chown -R 1000:0 /home/kasm-default-profile /workspace /opt/council \
    && chmod -R g=u /home/kasm-default-profile /workspace \
    && /dockerstartup/set_user_permission.sh /home/kasm-default-profile

EXPOSE 6901 8001
USER 1000
