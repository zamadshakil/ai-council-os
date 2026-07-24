"""
google_sheets.py — Google Sheets Integration

Client requirement: "Every workflow logs every processed item to a Google Sheet.
The sheet is the memory."

Uses gspread with a service account for server-to-server auth.
"""

import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()


_sheets_client = None


def get_sheets_client():
    """Lazy-load the gspread client using a service account."""
    global _sheets_client
    if _sheets_client is None:
        import gspread
        creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "./credentials/sheets_service_account.json")
        _sheets_client = gspread.service_account(filename=creds_path)
    return _sheets_client


def get_or_create_worksheet(spreadsheet_id: str, sheet_name: str, headers: List[str]):
    """
    Get a worksheet by name, creating it with headers if it doesn't exist.
    
    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID
        sheet_name: Name of the worksheet tab
        headers: Column headers for a new sheet
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except Exception:
        # Sheet doesn't exist, create it
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(headers))
        worksheet.append_row(headers)
    
    return worksheet


# ── Logging Functions (one per workflow) ─────────────────────────────────

SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")


def log_youtube_comment(
    comment_id: str,
    video_id: str,
    video_title: str,
    original_comment: str,
    ai_reply: str,
    confidence: float,
    status: str = "staged",
):
    """Log a YouTube comment auto-reply to the 'Comment Replies' sheet."""
    if not SPREADSHEET_ID:
        print("[Sheets] No SPREADSHEET_ID configured. Skipping log.")
        return
    
    headers = ["Timestamp", "Comment ID", "Video ID", "Video Title", "Original Comment", "AI Reply", "Confidence", "Status"]
    ws = get_or_create_worksheet(SPREADSHEET_ID, "Comment Replies", headers)
    ws.append_row([
        datetime.now(timezone.utc).isoformat(),
        comment_id,
        video_id,
        video_title,
        original_comment,
        ai_reply,
        confidence,
        status,
    ])


def log_reddit_lead(
    post_id: str,
    subreddit: str,
    title: str,
    author: str,
    url: str,
    intent_score: float,
    ai_reply: str,
    status: str = "pending_review",
):
    """Log a Reddit lead prospect to the 'Reddit Leads' sheet."""
    if not SPREADSHEET_ID:
        print("[Sheets] No SPREADSHEET_ID configured. Skipping log.")
        return
    
    headers = ["Timestamp", "Post ID", "Subreddit", "Title", "Author", "URL", "Intent Score", "AI Reply", "Status"]
    ws = get_or_create_worksheet(SPREADSHEET_ID, "Reddit Leads", headers)
    ws.append_row([
        datetime.now(timezone.utc).isoformat(),
        post_id,
        subreddit,
        title,
        author,
        url,
        intent_score,
        ai_reply,
        status,
    ])


def log_description_update(
    video_id: str,
    video_title: str,
    old_description_snippet: str,
    new_description: str,
    status: str = "staged",
):
    """Log a YouTube description update to the 'Description Updates' sheet."""
    if not SPREADSHEET_ID:
        print("[Sheets] No SPREADSHEET_ID configured. Skipping log.")
        return
    
    headers = ["Timestamp", "Video ID", "Video Title", "Old Description (first 200 chars)", "New Description", "Status"]
    ws = get_or_create_worksheet(SPREADSHEET_ID, "Description Updates", headers)
    ws.append_row([
        datetime.now(timezone.utc).isoformat(),
        video_id,
        video_title,
        old_description_snippet[:200],
        new_description,
        status,
    ])


def log_content_variant(
    source_video_id: str,
    platform: str,
    content: str,
    status: str = "staged",
):
    """Log a multi-platform content variant to the 'Content Distribution' sheet."""
    if not SPREADSHEET_ID:
        print("[Sheets] No SPREADSHEET_ID configured. Skipping log.")
        return
    
    headers = ["Timestamp", "Source Video ID", "Platform", "Content", "Status"]
    ws = get_or_create_worksheet(SPREADSHEET_ID, "Content Distribution", headers)
    ws.append_row([
        datetime.now(timezone.utc).isoformat(),
        source_video_id,
        platform,
        content,
        status,
    ])


def update_row_status(sheet_name: str, item_id_column: str, item_id: str, new_status: str):
    """
    Find a row by item ID and update its status.
    Used when a human approves/rejects a draft in the dashboard.
    """
    if not SPREADSHEET_ID:
        return
    
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    
    try:
        ws = spreadsheet.worksheet(sheet_name)
        headers = ws.row_values(1)
        id_col_index = headers.index(item_id_column) + 1
        status_col_index = headers.index("Status") + 1
        
        # Find the row with matching ID
        id_cells = ws.col_values(id_col_index)
        for row_num, cell_value in enumerate(id_cells, start=1):
            if cell_value == item_id:
                ws.update_cell(row_num, status_col_index, new_status)
                return True
    except Exception as e:
        print(f"[Sheets] Failed to update status: {e}")
    
    return False
