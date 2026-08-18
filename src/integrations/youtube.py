"""
youtube.py — YouTube API Integration

Handles all YouTube Data API v3 communication:
- Fetch all channel videos (with pagination)
- Fetch comments per video
- Post comment replies (OAuth required)
- Update video descriptions (OAuth required)
- Rate limiting and quota awareness
"""

import hashlib
import json
import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from src.core.integration_context import integration_value

load_dotenv()

_youtube_client = None
_youtube_client_fingerprint = ""


def get_youtube_client():
    """
    Initializes YouTube API client.
    
    For read-only (fetching videos/comments): API key is sufficient.
    For write (posting replies, updating descriptions): OAuth2 is required.
    
    When the client provides OAuth credentials (token.json), the OAuth path
    will be used automatically. Until then, API key works for reads.
    """
    global _youtube_client, _youtube_client_fingerprint
    token_json = integration_value("YOUTUBE_OAUTH_TOKEN_JSON", "").strip()
    token_path = integration_value("YOUTUBE_OAUTH_TOKEN", "./credentials/youtube_token.json").strip()
    api_key = integration_value("YOUTUBE_API_KEY", "").strip()
    fingerprint = hashlib.sha256(
        f"{token_json}|{token_path}|{api_key}".encode("utf-8")
    ).hexdigest()
    if _youtube_client is not None and _youtube_client_fingerprint == fingerprint:
        return _youtube_client

    from googleapiclient.discovery import build

    # Try OAuth first (needed for writes)
    if token_json or os.path.exists(token_path):
        try:
            from google.oauth2.credentials import Credentials
            scopes = ["https://www.googleapis.com/auth/youtube.force-ssl"]
            credentials = (
                Credentials.from_authorized_user_info(json.loads(token_json), scopes=scopes)
                if token_json
                else Credentials.from_authorized_user_file(token_path, scopes=scopes)
            )
            _youtube_client = build('youtube', 'v3', credentials=credentials)
            _youtube_client_fingerprint = fingerprint
            print("[YouTube] Connected with OAuth2 (read + write)")
            return _youtube_client
        except Exception as e:
            print(f"[YouTube] OAuth failed, falling back to API key: {e}")

    # Fallback to API key (read-only)
    if api_key:
        _youtube_client = build('youtube', 'v3', developerKey=api_key)
        _youtube_client_fingerprint = fingerprint
        print("[YouTube] Connected with API key (read-only)")
        return _youtube_client

    raise ValueError("No YouTube credentials configured. Set YOUTUBE_API_KEY or provide OAuth token.")


def verify_youtube_connection(channel_id: str, oauth_token_json: str = "") -> dict:
    """Prove the configured OAuth credential can access the intended channel."""
    token_json = oauth_token_json.strip() or integration_value("YOUTUBE_OAUTH_TOKEN_JSON", "").strip()
    token_path = integration_value("YOUTUBE_OAUTH_TOKEN", "").strip()
    if not token_json and (not token_path or not os.path.isfile(token_path)):
        raise RuntimeError("A YouTube OAuth token is required for write verification")

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/youtube.force-ssl"]
    credentials = (
        Credentials.from_authorized_user_info(json.loads(token_json), scopes=scopes)
        if token_json
        else Credentials.from_authorized_user_file(token_path, scopes=scopes)
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials.valid:
        raise RuntimeError("YouTube OAuth credentials are invalid or expired")
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    response = service.channels().list(part="id,snippet", id=channel_id).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("YouTube channel was not accessible with the configured OAuth token")
    global _youtube_client, _youtube_client_fingerprint
    _youtube_client = service
    _youtube_client_fingerprint = hashlib.sha256(
        f"{token_json}|{token_path}|{integration_value('YOUTUBE_API_KEY', '')}".encode("utf-8")
    ).hexdigest()
    return {
        "channel_id": items[0]["id"],
        "channel_title": items[0].get("snippet", {}).get("title", ""),
        "oauth": True,
    }


def fetch_channel_videos(channel_id: str, max_results: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch all videos from a channel with pagination.
    
    Returns list of dicts with: video_id, title, description, published_at
    """
    youtube = get_youtube_client()
    videos = []
    next_page_token = None

    try:
        while len(videos) < max_results:
            request_params = {
                "part": "snippet",
                "channelId": channel_id,
                "maxResults": min(50, max_results - len(videos)),
                "order": "date",
                "type": "video",
            }
            if next_page_token:
                request_params["pageToken"] = next_page_token

            response = youtube.search().list(**request_params).execute()

            for item in response.get("items", []):
                if item["id"].get("kind") == "youtube#video" or "videoId" in item.get("id", {}):
                    videos.append({
                        "video_id": item["id"].get("videoId", item["id"].get("video_id", "")),
                        "title": item["snippet"]["title"],
                        "description": item["snippet"].get("description", ""),
                        "published_at": item["snippet"]["publishedAt"],
                        "channel_title": item["snippet"].get("channelTitle", ""),
                    })

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        return videos

    except Exception as e:
        raise RuntimeError(f"YouTube video fetch failed: {e}") from e


def fetch_recent_comments(video_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Fetches recent top-level comments for a specific video."""
    youtube = get_youtube_client()
    comments = []

    try:
        next_page_token = None
        while len(comments) < limit:
            request_params = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": min(100, limit - len(comments)),
                "order": "time",
            }
            if next_page_token:
                request_params["pageToken"] = next_page_token

            response = youtube.commentThreads().list(**request_params).execute()

            for item in response.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "comment_id": item["id"],
                    "video_id": video_id,
                    "author": snippet["authorDisplayName"],
                    "text": snippet["textOriginal"],
                    "like_count": snippet["likeCount"],
                    "published_at": snippet["publishedAt"],
                })

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        return comments

    except Exception as e:
        raise RuntimeError(f"YouTube comment fetch failed for {video_id}: {e}") from e


def post_comment_reply(comment_id: str, reply_text: str) -> Optional[dict]:
    """Posts a reply to an existing comment. Requires OAuth."""
    youtube = get_youtube_client()
    try:
        request = youtube.comments().insert(
            part="snippet",
            body={
                "snippet": {
                    "parentId": comment_id,
                    "textOriginal": reply_text,
                }
            }
        )
        result = request.execute()
        print(f"[YouTube] Reply posted to comment {comment_id}")
        return result
    except Exception as e:
        print(f"[YouTube] Failed to post reply to {comment_id}: {e}")
        return None


def update_video_description(video_id: str, new_description: str) -> Optional[dict]:
    """
    Updates the description of a specific video. Requires OAuth.
    
    Preserves existing title, tags, and categoryId.
    """
    youtube = get_youtube_client()
    try:
        # First fetch the current video to preserve other fields
        video_response = youtube.videos().list(
            part="snippet,status",
            id=video_id
        ).execute()

        if not video_response.get("items"):
            print(f"[YouTube] Video {video_id} not found")
            return None

        video = video_response["items"][0]
        snippet = video["snippet"]
        snippet["description"] = new_description

        # YouTube API requires categoryId on updates
        if "categoryId" not in snippet:
            snippet["categoryId"] = "22"  # Default: People & Blogs

        update_response = youtube.videos().update(
            part="snippet",
            body={
                "id": video_id,
                "snippet": snippet,
            }
        ).execute()

        print(f"[YouTube] Description updated for video {video_id}")
        return update_response

    except Exception as e:
        print(f"[YouTube] Failed to update description for {video_id}: {e}")
        return None


def fetch_video_details(video_id: str) -> Optional[Dict[str, Any]]:
    """Fetch full details for a single video (title, description, tags, etc.)."""
    youtube = get_youtube_client()
    try:
        response = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=video_id
        ).execute()

        if not response.get("items"):
            return None

        item = response["items"][0]
        return {
            "video_id": video_id,
            "title": item["snippet"]["title"],
            "description": item["snippet"]["description"],
            "tags": item["snippet"].get("tags", []),
            "published_at": item["snippet"]["publishedAt"],
            "view_count": int(item["statistics"].get("viewCount", 0)),
            "like_count": int(item["statistics"].get("likeCount", 0)),
            "comment_count": int(item["statistics"].get("commentCount", 0)),
            "duration": item["contentDetails"]["duration"],
        }
    except Exception as e:
        print(f"[YouTube] Failed to fetch details for {video_id}: {e}")
        return None
