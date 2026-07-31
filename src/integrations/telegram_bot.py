"""
Telegram control and human-approval interface for AI Council OS.

Production flow:
- /task -> choose Content, Sales, or Grant Council -> send the task in chat
- FastAPI persists the task and runs the selected LangGraph council on the VPS
- The finished draft is sent back with Approve / Retry / Reject buttons
- Every action updates the same database task shown in the dashboard
- /kill and /resume update both workflow and dashboard kill-switch stores

Only chat IDs configured in TELEGRAM_ALLOWED_CHAT_IDS (or TELEGRAM_CHAT_ID as
backward-compatible fallback) may run commands or press action buttons.
"""

from __future__ import annotations

import html
import os
from typing import Optional

import httpx
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.core.kill_switch import activate, deactivate, get_status, is_killed

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://187.124.172.17.sslip.io").rstrip("/")


def _parse_chat_ids(value: str) -> set[int]:
    ids: set[int] = set()
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ids.add(int(raw))
        except ValueError:
            print(f"[Telegram] Ignoring invalid chat ID: {raw!r}")
    return ids


# Multiple destinations are supported for a future private operations group.
DESTINATION_CHAT_IDS = _parse_chat_ids(
    os.getenv("TELEGRAM_CHAT_IDS", "") or os.getenv("TELEGRAM_CHAT_ID", "")
)
ALLOWED_CHAT_IDS = _parse_chat_ids(
    os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
) or set(DESTINATION_CHAT_IDS)

_bot: Optional[Bot] = None
_app: Optional[Application] = None

# Chat -> selected council while waiting for the operator's task text.
_pending_council: dict[int, str] = {}
# Prevent duplicate callback execution during one process lifetime.
_handled_callbacks: set[str] = set()

COUNCIL_LABELS = {
    "content": "Content Council",
    "sales": "Sales Council",
    "grant": "Grant Council",
}


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TOKEN)
    return _bot


def _chat_id(update: Update) -> int | None:
    return update.effective_chat.id if update.effective_chat else None


def _is_authorized(update: Update) -> bool:
    chat_id = _chat_id(update)
    return chat_id is not None and chat_id in ALLOWED_CHAT_IDS


async def _reject_unauthorized(update: Update):
    chat_id = _chat_id(update)
    message = (
        "⛔ This chat is not authorized to operate AI Council OS.\n\n"
        f"Chat ID: `{chat_id}`\n"
        "Ask the system administrator to add it to `TELEGRAM_ALLOWED_CHAT_IDS`."
    )
    if update.callback_query:
        await update.callback_query.answer("Unauthorized", show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def _send_to_destinations(text: str, **kwargs):
    if not TOKEN or not DESTINATION_CHAT_IDS:
        return
    bot = _get_bot()
    for chat_id in DESTINATION_CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as exc:
            print(f"[Telegram] Failed sending to chat {chat_id}: {exc}")


# ── Workflow notifications ───────────────────────────────────────────────

async def notify_workflow_start(workflow_name: str, details: str = ""):
    kill_status = "🔴 KILLED" if is_killed() else "🟢 ACTIVE"
    msg = f"⚡ *Workflow Started: {workflow_name}*\nKill Switch: {kill_status}\n"
    if details:
        msg += f"\n{details}"
    await _send_to_destinations(msg, parse_mode=ParseMode.MARKDOWN)


async def notify_workflow_complete(workflow_name: str, summary: str):
    await _send_to_destinations(
        f"✅ *Workflow Complete: {workflow_name}*\n\n{summary}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def notify_workflow_error(workflow_name: str, error: str):
    # Escape arbitrary exceptions so malformed Markdown cannot suppress alerts.
    await _send_to_destinations(
        f"❌ <b>Workflow Failed: {html.escape(workflow_name)}</b>\n\n"
        f"<code>{html.escape(error[:2500])}</code>",
        parse_mode=ParseMode.HTML,
    )


async def send_draft_for_approval(
    task_id: str,
    workflow_name: str,
    draft_text: str,
    context_summary: str = "",
    confidence: float = 0.0,
    destination_chat_id: int | None = None,
):
    """Send a persisted task draft with DB-backed approval actions."""
    if not TOKEN:
        return

    display_draft = draft_text[:2400] + "…" if len(draft_text) > 2400 else draft_text
    msg = (
        f"📋 <b>Approval Required — {html.escape(workflow_name)}</b>\n"
        f"Confidence: <b>{confidence:.0f}/100</b>\n"
    )
    if context_summary:
        msg += f"Task: {html.escape(context_summary[:500])}\n"
    msg += (
        f"\n<blockquote>{html.escape(display_draft)}</blockquote>\n"
        f"Task ID: <code>{html.escape(task_id)}</code>"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{task_id}"),
            InlineKeyboardButton("🔄 Retry", callback_data=f"retry:{task_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{task_id}"),
        ],
        [InlineKeyboardButton("📊 Open in Dashboard", url=f"{DASHBOARD_URL}/approvals/{task_id}")]
    ])

    recipients = {destination_chat_id} if destination_chat_id else DESTINATION_CHAT_IDS
    bot = _get_bot()
    for chat_id in recipients:
        if chat_id is None:
            continue
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except Exception as exc:
            print(f"[Telegram] Failed to send approval draft to {chat_id}: {exc}")


async def notify_publish_success(workflow_name: str, platform: str, details: str = ""):
    msg = f"🚀 *Published Successfully!*\nWorkflow: {workflow_name}\nPlatform: {platform}"
    if details:
        msg += f"\n{details}"
    await _send_to_destinations(msg, parse_mode=ParseMode.MARKDOWN)


# ── Commands ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = _chat_id(update)
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    await update.effective_message.reply_text(
        "👋 <b>AI Council OS is connected</b>\n\n"
        f"Authorized Chat ID: <code>{chat_id}</code>\n\n"
        "Use /task to assign work to a council.\n"
        "Use /status to check the system.\n"
        "Use /kill for an emergency stop and /resume to restart workflows.\n"
        "Use /help to see all commands.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    await update.effective_message.reply_text(
        "<b>AI Council OS commands</b>\n\n"
        "/task — choose a council and submit a task\n"
        "/cancel — cancel the current task entry\n"
        "/status — system and kill-switch status\n"
        "/kill — immediately stop all workflow execution\n"
        "/resume — allow workflows to run again\n\n"
        "Completed tasks appear both here and in the dashboard. "
        "Approve, Retry, and Reject update the same persisted task record.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    if is_killed():
        await update.effective_message.reply_text(
            "🛑 The kill switch is active. Use /resume before submitting new work."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Content Council", callback_data="select:content")],
        [InlineKeyboardButton("💼 Sales Council", callback_data="select:sales")],
        [InlineKeyboardButton("🔬 Grant Council", callback_data="select:grant")],
    ])
    await update.effective_message.reply_text(
        "🏛 <b>Choose the council for this task</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    chat_id = _chat_id(update)
    if chat_id is not None:
        _pending_council.pop(chat_id, None)
    await update.effective_message.reply_text("Task entry cancelled. Use /task to start again.")


async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    user = update.effective_user.username or str(update.effective_user.id)
    reason = "Manual kill via Telegram"
    activate(toggled_by=f"telegram:{user}", reason=reason)
    from src.core.database import set_kill_switch_db
    await set_kill_switch_db(True, toggled_by=f"telegram:{user}", reason=reason)
    await update.effective_message.reply_text(
        "🛑 <b>Kill switch ACTIVATED</b>\nAll workflows and new council tasks are blocked.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    user = update.effective_user.username or str(update.effective_user.id)
    deactivate(toggled_by=f"telegram:{user}")
    from src.core.database import set_kill_switch_db
    await set_kill_switch_db(False, toggled_by=f"telegram:{user}")
    await update.effective_message.reply_text(
        "✅ <b>Kill switch DEACTIVATED</b>\nWorkflows and council tasks may run again.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    status = get_status()
    state = "🔴 KILLED" if status["is_active"] else "🟢 ACTIVE"
    msg = (
        f"<b>AI Council OS Status</b>\n\n"
        f"Kill Switch: {state}\n"
        f"Last toggled by: {html.escape(str(status['toggled_by']))}\n"
        f"Last toggled at: {html.escape(str(status['toggled_at']))}\n"
        f"VPS Backend: 🟢 ONLINE"
    )
    if status.get("reason"):
        msg += f"\nReason: {html.escape(str(status['reason']))}"
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


async def handle_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive task text after /task council selection and submit it to FastAPI."""
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    chat_id = _chat_id(update)
    if chat_id is None or chat_id not in _pending_council:
        return
    if is_killed():
        _pending_council.pop(chat_id, None)
        await update.effective_message.reply_text("🛑 Task not submitted: kill switch is active.")
        return

    council = _pending_council.pop(chat_id)
    task_text = (update.effective_message.text or "").strip()
    if len(task_text) < 10:
        _pending_council[chat_id] = council
        await update.effective_message.reply_text("Please provide a more detailed task (at least 10 characters).")
        return

    payload = {
        "council": council,
        "task_description": task_text,
        "priority": "high",
        "context": {
            "source": "telegram",
            "telegram_chat_id": chat_id,
            "telegram_user": update.effective_user.username or str(update.effective_user.id),
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{API_BASE_URL}/api/councils/run", json=payload)
            response.raise_for_status()
            result = response.json()
        await update.effective_message.reply_text(
            f"⚙️ <b>{html.escape(COUNCIL_LABELS[council])} is working</b>\n\n"
            f"Task ID: <code>{html.escape(result['task_id'])}</code>\n"
            "The agents will generate, critique, and refine the answer. "
            "The completed draft will return here for approval and will also appear in the dashboard.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        await update.effective_message.reply_text(
            f"❌ Could not submit task: <code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
        )


# ── Inline callbacks ─────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return

    data = query.data or ""
    if data.startswith("select:"):
        council = data.split(":", 1)[1]
        if council not in COUNCIL_LABELS:
            await query.answer("Unknown council", show_alert=True)
            return
        if is_killed():
            await query.answer("Kill switch is active", show_alert=True)
            return
        chat_id = _chat_id(update)
        if chat_id is not None:
            _pending_council[chat_id] = council
        await query.answer()
        await query.edit_message_text(
            f"📝 <b>{html.escape(COUNCIL_LABELS[council])} selected</b>\n\n"
            "Now send the complete task as your next Telegram message.\n\n"
            "Example: <i>Create an Instagram caption and LinkedIn post from this product announcement: …</i>\n\n"
            "Use /cancel to stop.",
            parse_mode=ParseMode.HTML,
        )
        return

    if ":" not in data:
        await query.answer("Invalid action", show_alert=True)
        return

    action, task_id = data.split(":", 1)
    callback_key = f"{query.message.chat_id}:{data}"
    if callback_key in _handled_callbacks:
        await query.answer("This action was already processed.", show_alert=True)
        return

    await query.answer("Processing…")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            task_response = await client.get(f"{API_BASE_URL}/api/tasks/{task_id}")
            task_response.raise_for_status()
            task = task_response.json()

            if action == "approve":
                response = await client.post(
                    f"{API_BASE_URL}/api/tasks/{task_id}/approve",
                    json={"approved": True, "notes": "Approved via Telegram"},
                )
                response.raise_for_status()
                result_text = (
                    f"✅ <b>Approved</b> — Task <code>{html.escape(task_id)}</code>\n"
                    "The dashboard now shows this task as approved and the decision was stored in memory."
                )

            elif action == "reject":
                response = await client.post(
                    f"{API_BASE_URL}/api/tasks/{task_id}/approve",
                    json={"approved": False, "notes": "Rejected via Telegram"},
                )
                response.raise_for_status()
                result_text = (
                    f"❌ <b>Rejected</b> — Task <code>{html.escape(task_id)}</code>\n"
                    "The dashboard now shows this task as rejected and the decision was stored for learning."
                )

            elif action == "retry":
                await client.post(
                    f"{API_BASE_URL}/api/tasks/{task_id}/approve",
                    json={"approved": False, "notes": "Retry requested via Telegram"},
                )
                retry_payload = {
                    "council": task.get("council", "content"),
                    "task_description": task.get("task_description", "")
                        + "\n\nRetry this task with a materially improved answer. Address weaknesses in the previous result.",
                    "priority": "high",
                    "context": {
                        **(task.get("context") or {}),
                        "source": "telegram_retry",
                        "retry_of": task_id,
                    },
                }
                retry_response = await client.post(
                    f"{API_BASE_URL}/api/councils/run", json=retry_payload
                )
                retry_response.raise_for_status()
                new_task_id = retry_response.json()["task_id"]
                result_text = (
                    f"🔄 <b>Retry started</b>\n"
                    f"Original: <code>{html.escape(task_id)}</code> (marked rejected)\n"
                    f"New task: <code>{html.escape(new_task_id)}</code>\n"
                    "A new improved draft will return here for approval."
                )
            else:
                await query.answer("Unknown action", show_alert=True)
                return

        _handled_callbacks.add(callback_key)
        await query.edit_message_text(result_text, parse_mode=ParseMode.HTML)
    except Exception as exc:
        await query.edit_message_text(
            f"❌ Action failed for <code>{html.escape(task_id)}</code>: "
            f"<code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
        )


# ── Startup ──────────────────────────────────────────────────────────────

def _register_handlers(app: Application):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("task", cmd_task))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("kill", cmd_kill))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_text))


def start_telegram_bot():
    if not TOKEN:
        print("[Telegram] No bot token configured. Skipping bot startup.")
        return
    if not ALLOWED_CHAT_IDS:
        print("[Telegram] No authorized chat IDs configured. Skipping bot startup.")
        return
    global _app
    _app = Application.builder().token(TOKEN).build()
    _register_handlers(_app)
    print("🤖 [Telegram] Bot started. Listening for authorized commands...")
    _app.run_polling(stop_signals=None, close_loop=False)


async def start_telegram_bot_async():
    if not TOKEN:
        print("[Telegram] No bot token configured. Skipping bot startup.")
        return
    if not ALLOWED_CHAT_IDS:
        print("[Telegram] No authorized chat IDs configured. Skipping bot startup.")
        return
    global _app
    _app = Application.builder().token(TOKEN).build()
    _register_handlers(_app)
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling()
    print("🤖 [Telegram] Bot started (async). Listening for authorized commands...")
