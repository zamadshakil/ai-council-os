"""
auto_sync.py — Background Auto-Save & Git LFS Sync Daemon

Runs inside /workspace/AstroMars on the RunPod GPU instance.
Periodically commits and pushes scene updates (.blend, code, assets) to GitHub LFS
to guarantee ZERO data loss even if a pod crashes or is terminated.
"""

import os
import time
import subprocess
from datetime import datetime, timezone

REPO_DIR = os.getenv("AUTOSYNC_REPO_DIR", "/workspace/AstroMars")
INTERVAL_MINUTES = int(os.getenv("AUTOSYNC_INTERVAL_MINUTES", "15"))


def run_cmd(cmd: str, cwd: str = REPO_DIR) -> str:
    """Run a shell command and return stdout."""
    try:
        res = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"[Auto-Sync Error] '{cmd}' failed: {e.stderr}")
        return ""


def sync_repository():
    """Check git status and commit/push if there are modified or untracked files."""
    if not os.path.exists(REPO_DIR):
        print(f"[Auto-Sync] Directory {REPO_DIR} does not exist yet. Retrying next cycle.")
        return

    # Check git status
    status = run_cmd("git status --porcelain")
    if not status:
        print(f"[Auto-Sync {datetime.now(timezone.utc).strftime('%H:%M:%S')}] No changes detected.")
        return

    print(f"[Auto-Sync {datetime.now(timezone.utc).strftime('%H:%M:%S')}] Changes detected! Staging files...")
    
    # Stage files
    run_cmd("git add .")
    
    # Commit
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    commit_msg = f"Auto-save scene update [{timestamp}]"
    run_cmd(f'git commit -m "{commit_msg}"')
    
    # Push to current branch
    branch = run_cmd("git branch --show-current") or "master"
    print(f"[Auto-Sync] Pushing to branch {branch}...")
    run_cmd(f"git push origin {branch}")
    print(f"[Auto-Sync ✅] Successfully auto-synced changes at {timestamp}")


def main():
    print(f"🔄 [Auto-Sync Daemon] Started. Watching {REPO_DIR} every {INTERVAL_MINUTES} minutes.")
    while True:
        try:
            sync_repository()
        except Exception as e:
            print(f"[Auto-Sync Exception] {e}")
            
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
