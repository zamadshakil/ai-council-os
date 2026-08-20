"""Trusted Blender audio mixdown used by the render encode stage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args(values)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    import bpy

    bpy.ops.sound.mixdown(
        filepath=str(output),
        accuracy=1024,
        container="WAV",
        codec="PCM",
        format="S16",
    )
    if not output.exists() or output.stat().st_size <= 44:
        raise RuntimeError("Blender did not create a usable audio mixdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
