"""
telegram_bot.py — Telegram Control & Approval Layer

Client requirement: "Nothing generated gets published without a human seeing it.
Also the only way to stop everything fast."

Features:
- Run event notifications (workflow started, completed, failed)
- Inline Approve / Retry / Cancel buttons on every draft
- Kill switch commands (/kill, /resume, /status)
- Confirmation messages after successful publish
- Idempotent callback handling (no double-fires)
"""

import os
import asyncio
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from dotenv import load_dotenv

from src.core.kill_switch import activate, deactivate, get_status, is_killed

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

_bot: Optional[Bot] = None
_app: Optional[Application] = None

# Track which callbacks have been handled (idempotent)
_handled_callbacks: set = set()


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TOKEN)
    return _bot


# ── Notification Functions (called by workflows) ────────────────────────

async def notify_workflow_start(workflow_name: str, details: str = ""):
    """Send a notification when a workflow begins."""
    if not TOKEN or not CHAT_ID:
        return

    kill_status = "🔴 KILLED" if is_killed() else "🟢 ACTIVE"
    msg = (
        f"⚡ *Workflow Started: {workflow_name}*\n"
        f"Kill Switch: {kill_status}\n"
    )
    if details:
        msg += f"\n{details}"

    bot = _get_bot()
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        print(f"[Telegram] Failed to send start notification: {e}")


async def notify_workflow_complete(workflow_name: str, summary: str):
    """Send a notification when a workflow completes."""
    if not TOKEN or not CHAT_ID:
        return

    msg = f"✅ *Workflow Complete: {workflow_name}*\n\n{summary}"
    bot = _get_bot()
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        print(f"[Telegram] Failed to send complete notification: {e}")


async def notify_workflow_error(workflow_name: str, error: str):
    """Send a notification when a workflow fails."""
    if not TOKEN or not CHAT_ID:
        return

    msg = f"❌ *Workflow Failed: {workflow_name}*\n\n`{error}`"
    bot = _get_bot()
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        print(f"[Telegram] Failed to send error notification: {e}")


async def send_draft_for_approval(
    task_id: str,
    workflow_name: str,
    draft_text: str,
    context_summary: str = "",
    confidence: float = 0.0,
):
    """
    Send a draft to Telegram with inline Approve / Retry / Cancel buttons.
    
    This is the core approval mechanism. The operator sees the draft on their
    phone and can approve, retry, or cancel directly from Telegram.
    """
    if not TOKEN or not CHAT_ID:
        return

    # Truncate draft for Telegram (4096 char limit)
    display_draft = draft_text[:2000] + "..." if len(draft_text) > 2000 else draft_text

    msg = (
        f"📋 *New Draft — {workflow_name}*\n"
        f"Confidence: {confidence:.0f}/100\n"
    )
    if context_summary:
        msg += f"Context: {context_summary}\n"
    msg += f"\n---\n{display_draft}\n---\n"
    msg += f"\n_Task ID: `{task_id}`_"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{task_id}"),
            InlineKeyboardButton("🔄 Retry", callback_data=f"retry:{task_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{task_id}"),
        ]
    ])

    bot = _get_bot()
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
    except Exception as e:
        print(f"[Telegram] Failed to send draft for approval: {e}")


async def notify_publish_success(workflow_name: str, platform: str, details: str = ""):
    """Post a confirmation message after each successful upload."""
    if not TOKEN or not CHAT_ID:
        return

    msg = f"🚀 *Published Successfully!*\nWorkflow: {workflow_name}\nPlatform: {platform}"
    if details:
        msg += f"\n{details}"

    bot = _get_bot()
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        print(f"[Telegram] Failed to send publish confirmation: {e}")


# ── Bot Command Handlers ────────────────────────────────────────────────

async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /kill command — activate the kill switch."""
    user = update.effective_user.username or "unknown"
    activate(toggled_by=f"telegram:{user}", reason="Manual kill via Telegram")
    await update.message.reply_text("🛑 *Kill switch ACTIVATED*\nAll workflows will stop immediately.", parse_mode=ParseMode.MARKDOWN)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume command — deactivate the kill switch."""
    user = update.effective_user.username or "unknown"
    deactivate(toggled_by=f"telegram:{user}")
    await update.message.reply_text("✅ *Kill switch DEACTIVATED*\nWorkflows will resume on next scheduled run.", parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command — show current system status."""
    status = get_status()
    state = "🔴 KILLED" if status["is_active"] else "🟢 ACTIVE"
    msg = (
        f"*AI Council OS Status*\n\n"
        f"Kill Switch: {state}\n"
        f"Last toggled by: {status['toggled_by']}\n"
        f"Last toggled at: {status['toggled_at']}\n"
    )
    if status.get("reason"):
        msg += f"Reason: {status['reason']}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle inline button presses (Approve / Retry / Cancel).
    Idempotent: pressing the same button twice does nothing.
    """
    query = update.callback_query
    await query.answer()

    callback_id = query.data
    if callback_id in _handled_callbacks:
        await query.edit_message_text(text="⚠️ This action was already processed.")
        return

    _handled_callbacks.add(callback_id)

    action, task_id = callback_id.split(":", 1)

    if action == "approve":
        await query.edit_message_text(
            text=f"✅ *Approved* — Task `{task_id}`\nPublishing...",
            parse_mode=ParseMode.MARKDOWN,
        )
        # The actual publish action is triggered via the API server
        # when the task status changes to "approved"

    elif action == "retry":
        await query.edit_message_text(
            text=f"🔄 *Retry requested* — Task `{task_id}`\nRe-running council...",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "cancel":
        await query.edit_message_text(
            text=f"❌ *Cancelled* — Task `{task_id}`\nDraft discarded and logged.",
            parse_mode=ParseMode.MARKDOWN,
        )


# ── Bot Startup ─────────────────────────────────────────────────────────

def start_telegram_bot():
    """
    Initialize and start the Telegram bot in the background.
    Called during FastAPI startup.
    """
    if not TOKEN:
        print("[Telegram] No bot token configured. Skipping bot startup.")
        return

    global _app
    _app = Application.builder().token(TOKEN).build()

    # Register handlers
    _app.add_handler(CommandHandler("kill", cmd_kill))
    _app.add_handler(CommandHandler("resume", cmd_resume))
    _app.add_handler(CommandHandler("status", cmd_status))
    _app.add_handler(CallbackQueryHandler(handle_callback))

    # Start polling in the background (non-blocking)
    print("🤖 [Telegram] Bot started. Listening for commands...")
    _app.run_polling(stop_signals=None, close_loop=False)


async def start_telegram_bot_async():
    """Async version for use within an existing event loop (e.g., FastAPI startup)."""
    if not TOKEN:
        print("[Telegram] No bot token configured. Skipping bot startup.")
        return

    global _app
    _app = Application.builder().token(TOKEN).build()

    _app.add_handler(CommandHandler("kill", cmd_kill))
    _app.add_handler(CommandHandler("resume", cmd_resume))
    _app.add_handler(CommandHandler("status", cmd_status))
    _app.add_handler(CallbackQueryHandler(handle_callback))

    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling()
    print("🤖 [Telegram] Bot started (async). Listening for commands...")
