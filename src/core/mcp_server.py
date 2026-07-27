"""
mcp_server.py — FastMCP Tool Server for AI Council OS

Exposes all AI Council OS capabilities as MCP (Model Context Protocol) tools.
This allows any MCP-compatible client (Claude Desktop, Cursor, etc.) to:
  - Run councils and generate content
  - Search the knowledge base
  - Trigger social publishing workflows
  - Read memory and analytics

Mount: app.mount("/mcp", mcp.sse_app()) in server.py
OR run standalone: python -m src.core.mcp_server

Usage with Claude Desktop (add to claude_desktop_config.json):
{
  "mcpServers": {
    "ai-council-os": {
      "command": "npx",
      "args": ["mcp-remote", "http://YOUR_SERVER_IP/mcp"]
    }
  }
}
"""

from __future__ import annotations

import os
from typing import Optional

from fastmcp import FastMCP

mcp = FastMCP(
    name="AI Council OS",
    instructions=(
        "You have access to the AI Council OS — a multi-agent debate engine that generates "
        "high-quality content through structured AI debate loops. Use these tools to run councils, "
        "search knowledge, and manage social publishing."
    ),
)


# ── Council Tools ──────────────────────────────────────────────────────────

@mcp.tool()
async def run_council(
    council: str,
    task: str,
    priority: str = "high",
) -> dict:
    """
    Run a multi-agent AI council debate to generate content.

    Args:
        council: One of 'sales', 'content', 'grant', 'strategy', 'support'
        task: The task description or content brief
        priority: 'low', 'medium', 'high' (affects model quality)

    Returns:
        Task ID and status. Poll get_task_status() for results.
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base}/api/councils/run", json={
            "council": council,
            "task_description": task,
            "priority": priority,
        })
        return resp.json()


@mcp.tool()
async def get_task_status(task_id: str) -> dict:
    """
    Get the current status and output of a council task.

    Args:
        task_id: The task ID returned by run_council()

    Returns:
        Task details including status, final_output, confidence_score, debate_history
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base}/api/tasks/{task_id}")
        return resp.json()


@mcp.tool()
async def list_recent_tasks(
    status: Optional[str] = None,
    council: Optional[str] = None,
) -> dict:
    """
    List recent council tasks.

    Args:
        status: Filter by status ('pending', 'awaiting_approval', 'approved', 'rejected', 'failed')
        council: Filter by council name

    Returns:
        List of tasks with their metadata
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    params = {}
    if status:
        params["status"] = status
    if council:
        params["council"] = council
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base}/api/tasks", params=params)
        return resp.json()


@mcp.tool()
async def approve_task(
    task_id: str,
    approved: bool = True,
    edited_output: str = "",
    notes: str = "",
) -> dict:
    """
    Approve or reject a task pending human review.

    Args:
        task_id: The task ID to approve/reject
        approved: True to approve, False to reject
        edited_output: Optional edited version of the AI output
        notes: Optional feedback notes (used for memory learning)

    Returns:
        Updated task status
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base}/api/tasks/{task_id}/approve", json={
            "approved": approved,
            "edited_output": edited_output,
            "notes": notes,
        })
        return resp.json()


# ── Knowledge Base Tools ───────────────────────────────────────────────────

@mcp.tool()
async def search_knowledge(query: str, top_k: int = 5) -> dict:
    """
    Search the RAG knowledge base for relevant information.

    Args:
        query: Natural language search query
        top_k: Number of results to return (max 10)

    Returns:
        List of relevant knowledge chunks with source document names
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{base}/api/knowledge/search", params={"q": query})
        return resp.json()


@mcp.tool()
async def list_knowledge_documents() -> dict:
    """
    List all documents in the knowledge base.

    Returns:
        List of uploaded documents with chunk counts and upload dates
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base}/api/knowledge/documents")
        return resp.json()


# ── Social Publishing Tools ────────────────────────────────────────────────

@mcp.tool()
async def trigger_instagram_commenter() -> dict:
    """
    Trigger the Instagram Comment Auto-Reply workflow.
    Reads recent comments on Instagram posts and generates AI replies.

    Returns:
        Summary with counts of processed, skipped, and failed comments
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{base}/api/workflows/instagram-comments")
        return resp.json()


@mcp.tool()
async def get_platform_status() -> dict:
    """
    Check which social media platforms are configured and ready.

    Returns:
        Dict of platform: configured (bool) for instagram, linkedin, facebook, twitter
    """
    required = {
        "instagram": ["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ID"],
        "linkedin": ["LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_ID"],
        "facebook": ["FACEBOOK_PAGE_ID", "META_ACCESS_TOKEN"],
        "twitter": ["TWITTER_API_KEY", "TWITTER_ACCESS_TOKEN"],
    }
    status = {}
    for platform, keys in required.items():
        status[platform] = all(bool(os.getenv(k)) for k in keys)
    return {"platforms": status, "configured_count": sum(status.values())}


# ── Memory & Analytics Tools ───────────────────────────────────────────────

@mcp.tool()
async def add_brand_guideline(guideline: str, council: str = "all") -> dict:
    """
    Add a brand guideline to the memory system.
    These are automatically injected into council prompts.

    Args:
        guideline: The brand rule (e.g. 'Always use conversational tone')
        council: Apply to specific council or 'all' (default)

    Returns:
        Confirmation of saved guideline
    """
    from src.core.memory_manager import add_guideline
    return await add_guideline(guideline, council)


@mcp.tool()
async def get_analytics() -> dict:
    """
    Get dashboard analytics and system statistics.

    Returns:
        Stats including task counts, cost totals, success rates, memory stats
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=10) as client:
        stats_resp = await client.get(f"{base}/api/stats")
        return stats_resp.json()


@mcp.tool()
async def get_kill_switch_status() -> dict:
    """
    Check the kill switch status (whether all workflows are paused).

    Returns:
        Kill switch state and reason if active
    """
    import httpx
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base}/api/kill-switch")
        return resp.json()


# ── Standalone runner ──────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
