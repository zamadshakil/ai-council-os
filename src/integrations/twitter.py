from __future__ import annotations
import os
import tweepy

"""
twitter.py — Twitter/X Publisher

Posts AI-generated content to Twitter/X.
Uses Twitter API v2 via Tweepy.

Requires:
  TWITTER_API_KEY
  TWITTER_API_SECRET
  TWITTER_ACCESS_TOKEN
  TWITTER_ACCESS_SECRET
  TWITTER_BEARER_TOKEN (optional, for read operations)
"""

async def _get_client() -> tweepy.Client:
    """Returns authenticated v2 client."""
    api_key = os.environ.get("TWITTER_API_KEY")
    api_secret = os.environ.get("TWITTER_API_SECRET")
    access_token = os.environ.get("TWITTER_ACCESS_TOKEN")
    access_secret = os.environ.get("TWITTER_ACCESS_SECRET")
    bearer_token = os.environ.get("TWITTER_BEARER_TOKEN")
    
    if not all([api_key, api_secret, access_token, access_secret]):
        raise RuntimeError("Missing one or more required Twitter credentials.")
        
    return tweepy.Client(
        bearer_token=bearer_token,
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret
    )

def _truncate_for_twitter(text: str, limit: int = 270) -> str:
    """Truncates with '...' if over limit."""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."

async def publish(content: str, media_url: str | None = None) -> dict:
    """Posts a tweet (280 char limit handling)."""
    client = await _get_client()
    text = _truncate_for_twitter(content)
    
    try:
        response = client.create_tweet(text=text)
        if response.errors:
            raise RuntimeError(f"Twitter API error: {response.errors}")
        return {"id": response.data["id"], "text": response.data["text"]}
    except Exception as e:
        raise RuntimeError(f"Failed to post to Twitter: {str(e)}")
