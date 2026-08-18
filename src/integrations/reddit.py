"""
reddit.py — Reddit API Integration

Uses PRAW (Python Reddit API Wrapper) for all Reddit communication.
Official API only — no scraping, no unofficial endpoints.

Features:
- Fetch posts from multiple subreddits
- Per-subreddit volume cap
- Filter by exclusion terms before API calls
- Fail-closed publishing guard (approved drafts are posted manually)
"""

import hashlib
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from dotenv import load_dotenv
from src.core.integration_context import integration_value

if TYPE_CHECKING:
    pass

load_dotenv()

_reddit_client: Optional[Any] = None
_reddit_client_fingerprint = ""


def get_reddit_client() -> Any:
    """Initialize the PRAW Reddit client using env credentials."""
    global _reddit_client, _reddit_client_fingerprint
    client_id = integration_value("REDDIT_CLIENT_ID")
    client_secret = integration_value("REDDIT_CLIENT_SECRET")
    user_agent = integration_value("REDDIT_USER_AGENT", "AICouncilOS Prospector/1.0")
    username = integration_value("REDDIT_USERNAME", "")
    password = integration_value("REDDIT_PASSWORD", "")
    fingerprint = hashlib.sha256(
        f"{client_id}|{client_secret}|{user_agent}|{username}|{password}".encode("utf-8")
    ).hexdigest()
    if _reddit_client is not None and _reddit_client_fingerprint == fingerprint:
        return _reddit_client

    import praw

    _reddit_client = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        username=username,
        password=password,
    )
    _reddit_client_fingerprint = fingerprint
    return _reddit_client


def fetch_prospect_leads(
    subreddits: List[str],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Scans recent posts across multiple subreddits to find potential leads.
    
    Args:
        subreddits: List of subreddit names to scan
        limit: Max posts PER SUBREDDIT (volume cap)
    """
    reddit = get_reddit_client()
    posts = []

    # Process subreddits in batches using '+' separator (max ~100 at a time)
    batch_size = 50
    for i in range(0, len(subreddits), batch_size):
        batch = subreddits[i:i + batch_size]
        subreddit_query = "+".join(batch)

        try:
            subreddit = reddit.subreddit(subreddit_query)
            for post in subreddit.new(limit=limit * len(batch)):
                # Skip empty, removed, or deleted posts
                if not post.selftext or post.selftext in ["[removed]", "[deleted]"]:
                    continue

                # Skip very short posts (usually not real questions)
                if len(post.selftext) < 30:
                    continue

                posts.append({
                    "id": post.id,
                    "title": post.title,
                    "body": post.selftext,
                    "subreddit": post.subreddit.display_name,
                    "author": str(post.author) if post.author else "[deleted]",
                    "url": f"https://reddit.com{post.permalink}",
                    "created_utc": post.created_utc,
                    "score": post.score,
                    "num_comments": post.num_comments,
                })
        except Exception as e:
            raise RuntimeError(f"Reddit API fetch failed for batch {i}: {e}") from e

    return posts


def post_reddit_reply(post_id: str, reply_text: str) -> bool:
    """
    Deliberately refuse all programmatic Reddit replies.

    Kept as a compatibility guard so an old API route cannot accidentally
    re-enable posting merely by importing the historical function name.
    """
    raise PermissionError(
        "Reddit publishing is disabled by policy. Approved drafts must be copied and posted manually."
    )
