# Council OS Blender/Kasm image

This image provides both workflows without modifying the artist's source:

- Kasm is the interactive editor and inspection surface.
- The recommended production path renders restartable frame batches headlessly.
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

Google Drive is never mounted as Blender's render filesystem. If Drive delivery
is enabled, place its rclone configuration at the persistent path
`/workspace/.config/rclone/rclone.conf`; Council OS performs a write/read/delete
probe before rendering and a checksum verification after the one-way upload.
