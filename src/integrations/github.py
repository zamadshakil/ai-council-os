import os
import base64
import httpx
from datetime import datetime

GITHUB_PAT = os.getenv("GITHUB_PAT", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip() # Format: "username/repo"

async def push_file_to_github(content: str, filename: str, commit_message: str = "") -> dict:
    """
    Pushes a file directly to the configured GitHub repository via the REST API.
    """
    if not GITHUB_PAT or not GITHUB_REPO:
        return {"status": "error", "error": "GitHub PAT or Repository not configured in environment variables."}

    if not commit_message:
        commit_message = f"Auto-commit: {filename} from AI Council OS"

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    
    headers = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Base64 encode the content
    content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    
    payload = {
        "message": commit_message,
        "content": content_b64
    }

    async with httpx.AsyncClient() as client:
        # First, check if the file already exists to get its SHA (required for updates)
        check_res = await client.get(url, headers=headers)
        if check_res.status_code == 200:
            payload["sha"] = check_res.json()["sha"]
            
        # Put the new content
        res = await client.put(url, headers=headers, json=payload)
        
        if res.status_code in (200, 201):
            return {"status": "success", "url": res.json()["content"]["html_url"]}
        else:
            return {"status": "error", "error": f"GitHub API Error {res.status_code}: {res.text}"}
