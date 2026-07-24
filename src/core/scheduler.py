"""
scheduler.py — Background Automation Scheduler

Runs all workflow pipelines on configurable intervals using APScheduler.
No circular imports — receives tasks_store as a parameter.

Every job checks the kill switch before executing.

Jobs:
1. Reddit Lead Prospector — every 60 minutes
2. YouTube Comment Auto-Reply — every 30 minutes
3. (YouTube Descriptions and Content Engine are manual-trigger only)
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.core.kill_switch import is_killed

scheduler = AsyncIOScheduler()

# This will be set by the API server during startup
_tasks_store: dict = {}


def set_tasks_store(store: dict):
    """Called by server.py to inject the shared tasks_store without circular imports."""
    global _tasks_store
    _tasks_store = store


async def _job_reddit_prospector():
    """Scheduled job: Reddit Lead Prospector."""
    if is_killed():
        print("🛑 [Scheduler] Kill switch active. Skipping Reddit Prospector.")
        return

    from src.workflows.reddit_prospector import run_reddit_prospector
    result = await run_reddit_prospector(_tasks_store)
    print(f"📊 [Scheduler] Reddit Prospector result: {result}")


async def _job_youtube_comments():
    """Scheduled job: YouTube Comment Auto-Reply."""
    if is_killed():
        print("🛑 [Scheduler] Kill switch active. Skipping YouTube Comments.")
        return

    from src.workflows.youtube_comments import run_youtube_comment_workflow
    result = await run_youtube_comment_workflow(_tasks_store)
    print(f"📊 [Scheduler] YouTube Comments result: {result}")


def start_scheduler():
    """
    Start all background automation jobs.
    Called during FastAPI startup.
    """
    # Reddit Prospector — every 60 minutes
    scheduler.add_job(
        _job_reddit_prospector,
        'interval',
        minutes=60,
        id='reddit_prospector',
        name='Reddit Lead Prospector',
        replace_existing=True,
    )

    # YouTube Comment Auto-Reply — every 30 minutes
    scheduler.add_job(
        _job_youtube_comments,
        'interval',
        minutes=30,
        id='youtube_comments',
        name='YouTube Comment Auto-Reply',
        replace_existing=True,
    )

    scheduler.start()
    print("[Scheduler] Background automation scheduler started.")
    print("   - Reddit Prospector: every 60 min")
    print("   - YouTube Comments: every 30 min")
    print("   - YouTube Descriptions: manual trigger only")
    print("   - Content Engine: manual trigger only")
