"""Retired legacy MCP entry point.

Council OS now exposes its only MCP surface at ``POST /mcp`` on the FastAPI
application. That transport requires a hashed, expiring bearer token and
offers read/propose tools only. Keeping the old standalone FastMCP tool set
would preserve a second unaudited path to approvals, publishing, schedules and
legacy filesystem memory, so it is intentionally unavailable.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "The standalone MCP server is retired. Use the authenticated FastAPI "
        "Streamable HTTP endpoint at /mcp with an administrator-issued token."
    )


if __name__ == "__main__":
    main()
