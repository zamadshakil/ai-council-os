# syntax=docker/dockerfile:1.7

ARG KASM_BASE_IMAGE=kasmweb/core-ubuntu-noble@sha256:491cdbb3f6e5fb25d9cbd41320e1f5f415713e4ab646097a03e5c551bd817835
ARG FLAMENCO_GO_BUILDER=mirror.gcr.io/library/golang@sha256:116d58cbd88c1297624acc6e967a060012422bacf9930927e23fb719189c6f36

# Blender Foundation's latest stable Flamenco release is still 3.9.3, but its
# published binaries were compiled with Go dependencies that now have fixed
# HIGH/CRITICAL advisories. Rebuild the exact official release commit with the
# fixed dependency set instead of weakening the image scan or using a beta.
FROM ${FLAMENCO_GO_BUILDER} AS flamenco-build

USER root

ARG FLAMENCO_SOURCE_COMMIT=6f0311eae5cf183132811da3d8941532c67b4f90
ARG FLAMENCO_VERSION=3.9.3

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git make \
    && rm -rf /var/lib/apt/lists/* \
    && git init /src \
    && git -C /src remote add origin https://projects.blender.org/studio/flamenco.git \
    && git -C /src fetch --depth 1 origin "${FLAMENCO_SOURCE_COMMIT}" \
    && git -C /src checkout --detach FETCH_HEAD \
    && test "$(git -C /src rev-parse HEAD)" = "${FLAMENCO_SOURCE_COMMIT}" \
    && test "$(sed -n 's/^VERSION := //p' /src/Makefile)" = "${FLAMENCO_VERSION}" \
    && useradd --create-home --uid 10001 flamenco-build \
    && chown -R flamenco-build:flamenco-build /src

USER 10001:10001
WORKDIR /src

RUN go version | grep --fixed-strings 'go1.26.6' \
    && go mod edit -toolchain=go1.26.6 \
    && go get \
        github.com/getkin/kin-openapi@v0.144.0 \
        golang.org/x/crypto@v0.53.0 \
        golang.org/x/net@v0.56.0 \
        golang.org/x/text@v0.39.0 \
    && go mod tidy \
    && go mod verify \
    && go test ./... \
    && make flamenco-manager-without-webapp flamenco-worker \
    && ./flamenco-manager -version | grep --fixed-strings "${FLAMENCO_VERSION}" \
    && ./flamenco-worker -version | grep --fixed-strings "${FLAMENCO_VERSION}" \
    && mkdir -p /tmp/flamenco-release \
    && cp flamenco-manager flamenco-worker LICENSE README.md /tmp/flamenco-release/

# Build a tiny, auditable compatibility library against the same Noble base
# as the final image. Some RunPod hosts return EPERM for close_range(2), while
# GLib only activates its safe fd-walk fallback for ENOSYS. Without this shim,
# XFCE cannot launch any desktop application even though the application is
# healthy. The shim preserves the denied syscall and only translates errno.
FROM ${KASM_BASE_IMAGE} AS desktop-compat-build

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY docker/blender-runpod/close_range_compat.c /tmp/close_range_compat.c

RUN gcc -shared -fPIC -O2 -Wall -Wextra -Werror \
        -Wl,-z,relro,-z,now \
        -o /tmp/libcouncil-close-range-compat.so \
        /tmp/close_range_compat.c \
    && readelf -Ws /tmp/libcouncil-close-range-compat.so \
        | grep --extended-regexp '[[:space:]]close_range$'

FROM ${KASM_BASE_IMAGE}

USER root

ARG BLENDER_VERSION=5.0.1
ARG BLENDER_SHA256=8019580ee1b7262e505f4196a00237ccf743c88d205b38d34201510676e60b09
ARG BLENDER_SAMPLE_SHA256=d566eec833f933762daa206b57bbc3e05ef38bbdf0aacd373ae68818f0b404e7
ARG GOOGLE_CHROME_VERSION=151.0.7922.173-1
ARG GOOGLE_CHROME_SHA256=878e5ab495b8a694980fca61bc09b37e651ccedce2291c73434d16e48a2646fd
ARG BLENDER_GPU_SAMPLE_SHA256=74f5dc6d718fc565e0ff50e355be7f8b1a58983cc9ae79775608d8905c269ee4
ARG FLAMENCO_VERSION=3.9.3

ENV DEBIAN_FRONTEND=noninteractive \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display,video \
    BLENDER_BINARY=/opt/blender/blender \
    BLENDER_AGENT_PORT=8001 \
    BLENDER_WORKSPACE_ROOT=/workspace \
    BLENDER_GDRIVE_REMOTE=gdrive: \
    FLAMENCO_HOME=/workspace/.council-flamenco \
    FLAMENCO_MANAGER_URL=http://127.0.0.1:8080 \
    RCLONE_CONFIG=/workspace/.config/rclone/rclone.conf \
    VNCOPTIONS="-PreferBandwidth -DynamicQualityMin=4 -DynamicQualityMax=7 -DLP_ClipDelay=0 -sslOnly 0" \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg jq libasound2t64 libegl1 libgl1 libglvnd0 \
        libice6 libsm6 libvulkan1 libx11-6 libxcursor1 libxext6 libxfixes3 \
        libxi6 libxinerama1 libxkbcommon0 libxkbcommon-x11-0 libxrandr2 libxrender1 libxxf86vm1 \
        mesa-utils procps python3-venv rclone ristretto unzip util-linux xz-utils \
    && rm -rf /var/lib/apt/lists/*

# The Kasm core desktop ships an XFCE "Web Browser" launcher but no browser.
# Install a checksum-pinned Chrome build, then wrap it with the same container-
# safe flags used by Kasm's maintained Chrome workspace.
RUN curl --fail --location --retry 5 --retry-delay 3 \
        "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${GOOGLE_CHROME_VERSION}_amd64.deb" \
        --output /tmp/google-chrome.deb \
    && echo "${GOOGLE_CHROME_SHA256}  /tmp/google-chrome.deb" | sha256sum --check --strict \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/google-chrome.deb \
    && rm -f /tmp/google-chrome.deb /etc/apt/sources.list.d/google-chrome.list \
    && rm -rf /var/lib/apt/lists/* \
    && mv /usr/bin/google-chrome /usr/bin/google-chrome-orig \
    && sed -i 's/-stable//g' /usr/share/applications/google-chrome.desktop

RUN curl --fail --location --retry 5 --retry-delay 3 \
        "https://download.blender.org/release/Blender5.0/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        --output /tmp/blender.tar.xz \
    && echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum --check --strict \
    && mkdir -p /opt/blender \
    && tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && rm /tmp/blender.tar.xz \
    && /opt/blender/blender --background --version

# The Manager remains private inside the pod; Council OS reaches it through the
# authenticated agent. Workers use shared /workspace paths. The source/build
# toolchain is discarded with the builder stage.
COPY --from=flamenco-build /tmp/flamenco-release/ /opt/flamenco/
COPY --from=desktop-compat-build /tmp/libcouncil-close-range-compat.so /opt/council/libcouncil-close-range-compat.so
ENV LD_PRELOAD=/opt/council/libcouncil-close-range-compat.so
RUN /opt/flamenco/flamenco-manager -version | grep --fixed-strings "${FLAMENCO_VERSION}" \
    && /opt/flamenco/flamenco-worker -version | grep --fixed-strings "${FLAMENCO_VERSION}"

# Small, checksum-pinned Blender Foundation demo used only for an explicitly
# requested GPU smoke test. It avoids depending on an artist upload while
# keeping arbitrary remote downloads out of the runtime agent.
RUN mkdir -p /opt/council/samples \
    && curl --fail --location --retry 5 --retry-delay 3 \
        "https://download.blender.org/demo/Blender-282.blend" \
        --output /opt/council/samples/Blender-282.blend \
    && echo "${BLENDER_SAMPLE_SHA256}  /opt/council/samples/Blender-282.blend" \
        | sha256sum --check --strict

# A small official Cycles benchmark with packed resources. Unlike the UI demo
# above, this scene can pass the missing-asset gate and prove real GPU compute.
RUN curl --fail --location --retry 5 --retry-delay 3 \
        "https://download.blender.org/demo/test/BMW27_2.blend.zip" \
        --output /tmp/BMW27_2.blend.zip \
    && echo "${BLENDER_GPU_SAMPLE_SHA256}  /tmp/BMW27_2.blend.zip" \
        | sha256sum --check --strict \
    && unzip -q /tmp/BMW27_2.blend.zip -d /tmp/bmw27 \
    && mv /tmp/bmw27/bmw27/bmw27_gpu.blend /opt/council/samples/BMW27_GPU.blend \
    && rm -rf /tmp/BMW27_2.blend.zip /tmp/bmw27

RUN /opt/blender/5.0/python/bin/python3.11 -m pip install --no-cache-dir --upgrade \
        "setuptools==83.0.0" "urllib3==2.7.0"

RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade accountsservice libaccountsservice0 \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/council-agent \
    && /opt/council-agent/bin/pip install --no-cache-dir \
        "fastapi==0.141.1" "starlette==1.3.1" "pydantic==2.11.7" "uvicorn==0.35.0" \
        "httpx==0.28.1" "nvidia-ml-py==13.580.82" "psutil==7.0.0" "Pillow==12.3.0"

RUN mkdir -p /opt/council /workspace/render_jobs /workspace/logs /workspace/.config/rclone \
        /workspace/.council-flamenco \
        /home/kasm-default-profile/Desktop /home/kasm-default-profile/.config/rclone

COPY src/scripts/blender_listener.py src/scripts/blender_job.py src/scripts/blender_mixdown.py src/scripts/blender_gui_bootstrap.py \
    src/scripts/desktop_control.py src/scripts/flamenco_control.py src/scripts/flamenco_gateway.py \
    src/scripts/flamenco_gpu_bootstrap.py /opt/council/
COPY docker/blender-runpod/blender-launcher.sh /usr/local/bin/blender
COPY docker/blender-runpod/chrome-launcher.sh /usr/bin/google-chrome
COPY docker/blender-runpod/custom_startup.sh /dockerstartup/custom_startup.sh
COPY docker/blender-runpod/Blender.desktop /home/kasm-default-profile/Desktop/Blender.desktop
COPY docker/blender-runpod/Renders.desktop /home/kasm-default-profile/Desktop/Renders.desktop

RUN chmod 0755 /usr/local/bin/blender /usr/bin/google-chrome /dockerstartup/custom_startup.sh \
        /home/kasm-default-profile/Desktop/Blender.desktop \
        /home/kasm-default-profile/Desktop/Renders.desktop \
    && chmod 0644 /opt/council/*.py \
    && cp /usr/share/applications/google-chrome.desktop \
        /home/kasm-default-profile/Desktop/google-chrome.desktop \
    && chmod 0755 /home/kasm-default-profile/Desktop/google-chrome.desktop \
    && mkdir -p /home/kasm-default-profile/.config \
    && HOME=/home/kasm-default-profile xdg-mime default google-chrome.desktop text/html \
    && HOME=/home/kasm-default-profile xdg-mime default google-chrome.desktop x-scheme-handler/http \
    && HOME=/home/kasm-default-profile xdg-mime default google-chrome.desktop x-scheme-handler/https \
    && viewer_desktop="$(find /usr/share/applications -maxdepth 1 -type f -iname '*ristretto*.desktop' -printf '%f\n' | head -n 1)" \
    && test -n "$viewer_desktop" \
    && HOME=/home/kasm-default-profile xdg-mime default "$viewer_desktop" image/png \
    && HOME=/home/kasm-default-profile xdg-mime default "$viewer_desktop" image/jpeg \
    && HOME=/home/kasm-default-profile xdg-mime default "$viewer_desktop" image/webp \
    && update-alternatives --install /usr/bin/x-www-browser x-www-browser /usr/bin/google-chrome 250 \
    && update-alternatives --set x-www-browser /usr/bin/google-chrome \
    && ln -s /workspace /home/kasm-default-profile/Desktop/Workspace \
    && chown -R 1000:0 /home/kasm-default-profile /workspace /opt/council \
    && chmod -R g=u /home/kasm-default-profile /workspace \
    && /dockerstartup/set_user_permission.sh /home/kasm-default-profile

EXPOSE 6901 8001
USER 1000
