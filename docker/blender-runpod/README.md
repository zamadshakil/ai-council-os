# Council OS Blender/Kasm image

This image provides both workflows without modifying the artist's source:

- Kasm is the interactive editor and inspection surface.
- The recommended production path uses pinned Flamenco 3.9.3 to schedule
  restartable headless frame tasks while Council OS remains authoritative for
  approval, telemetry, frame validation, encoding, delivery, and billing gates.
- An optional manual mode lets the artist choose **Render → Render Animation**
  in Kasm; an authenticated manifest applies only the approved GPU and image
  sequence settings in memory.

Build from the repository root:

```text
docker build -f docker/blender-runpod/Dockerfile -t council-blender:test .
```

Required runtime values are `VNC_PW` and `BLENDER_AGENT_TOKEN`. Council OS
generates the agent token. The RunPod/NVIDIA runtime supplies the host driver;
do not install an NVIDIA kernel driver in this image.

Flamenco Manager binds to `127.0.0.1:8080` and is never published by RunPod.
Council OS reaches it only through the authenticated pod agent. The first
baseline starts one Manager and one Worker in the same A6000 Pod. Both use the
persistent `/workspace` shared-storage path. The Worker runs a trusted Blender
load handler that selects the benchmark-approved OptiX/CUDA backend; a render
still passes only after Council OS observes the Blender PID and non-zero NVML
compute activity.

Multi-Pod Workers are deliberately not enabled by default. When scaling is
approved after the 50-frame soak, every Pod must mount the same RunPod network
volume at `/workspace` and receive `FLAMENCO_COORDINATOR_AGENT_URL` pointing to
the coordinator's authenticated agent URL plus the separate write-only
`FLAMENCO_COORDINATOR_AGENT_TOKEN`. Its local gateway forwards only Flamenco
Worker protocol routes. This value is the coordinator's generated
`FLAMENCO_WORKER_PROXY_TOKEN`, not its full Blender-agent token, so Manager and
pod administration remain inaccessible.

Google Drive is never mounted as Blender's render filesystem. If Drive delivery
is enabled, place its rclone configuration at the persistent path
`/workspace/.config/rclone/rclone.conf`; Council OS performs a write/read/delete
probe before rendering and a checksum verification after the one-way upload.
