"""Loopback-only authenticated gateway from a remote Flamenco Worker.

The Flamenco Worker cannot attach Council OS bearer authentication itself.
This process binds only to 127.0.0.1, adds the pod agent token, and forwards
worker protocol calls to the coordinator pod agent. It exposes no management
endpoints and accepts no non-Flamenco paths.
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request, Response


app = FastAPI(title="Council OS Flamenco Worker Gateway", docs_url=None, redoc_url=None)


def _coordinator() -> tuple[str, str]:
    base = os.getenv("FLAMENCO_COORDINATOR_AGENT_URL", "").strip().rstrip("/")
    # A remote Worker has its own BLENDER_AGENT_TOKEN for its local agent. It
    # authenticates to the coordinator with the coordinator's distinct token,
    # preserving the Pod-to-Pod trust boundary.
    token = os.getenv("FLAMENCO_COORDINATOR_AGENT_TOKEN", "").strip()
    if not base.startswith("https://") or len(token) < 32:
        raise HTTPException(status_code=503, detail="Flamenco coordinator is not configured")
    return base, token


def _allowed(path: str) -> bool:
    normalized = f"/{path.lstrip('/')}"
    return normalized == "/api/v3/version" or normalized.startswith("/api/v3/worker/")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> Response:
    target_path = f"/{path.lstrip('/')}"
    if not _allowed(target_path) or ".." in target_path:
        raise HTTPException(status_code=403, detail="Only the Flamenco Worker protocol is allowed")
    base, token = _coordinator()
    body = await request.body()
    headers = {"Authorization": f"Bearer {token}"}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120)) as client:
            upstream = await client.request(
                request.method,
                f"{base}/v1/flamenco/worker-proxy{target_path}",
                params=request.query_params,
                headers=headers,
                content=body,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Flamenco coordinator is unavailable") from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8181, access_log=False)
