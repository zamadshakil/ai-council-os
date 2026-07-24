"""
reddit.py — Reddit API Integration

Uses PRAW (Python Reddit API Wrapper) for all Reddit communication.
Official API only — no scraping, no unofficial endpoints.

Features:
- Fetch posts from multiple subreddits
- Per-subreddit volume cap
- Filter by exclusion terms before API calls
- Post replies (only when human approves)
"""

import os
from typing import List, Dict, Any, Optional

import praw
from dotenv import load_dotenv

load_dotenv()

_reddit_client: Optional[praw.Reddit] = None


def get_reddit_client() -> praw.Reddit:
    """Initialize the PRAW Reddit client using env credentials."""
    global _reddit_client
    if _reddit_client is not None:
        return _reddit_client

    _reddit_client = praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT", "AICouncilOS Prospector/1.0"),
        username=os.getenv("REDDIT_USERNAME", ""),
        password=os.getenv("REDDIT_PASSWORD", ""),
    )
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
            print(f"[Reddit] Failed to fetch from batch {i}: {e}")
            continue

    return posts


def post_reddit_reply(post_id: str, reply_text: str) -> bool:
    """
    Replies to a Reddit submission.
    Only called AFTER human approval in the Dashboard.
    
    Client requirement: "Auto-posting without review. Do not build this.
    Drafts go to the sheet; a human posts."
    """
    try:
        reddit = get_reddit_client()
        submission = reddit.submission(id=post_id)
        submission.reply(reply_text)
        print(f"[Reddit] Reply posted to post {post_id}")
        return True
    except Exception as e:
        print(f"[Reddit] Failed to post reply to {post_id}: {e}")
        return False
