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
from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from src.core.integration_context import integration_value

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://councilos.invalid").rstrip("/")
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
_runtime_token = ""
_runtime_allowed_chat_ids: set[int] = set()


def _service_headers() -> dict[str, str]:
    if len(INTERNAL_SERVICE_TOKEN) < 32:
        raise RuntimeError("Telegram service authentication is not configured")
    return {
        "X-Service-Token": INTERNAL_SERVICE_TOKEN,
        "X-Service-Actor": "telegram",
    }


async def _kill_switch_status() -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{API_BASE_URL}/api/kill-switch", headers=_service_headers()
        )
        response.raise_for_status()
        return response.json()


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


def configure_telegram_runtime(values: dict[str, str]) -> None:
    """Install a verified portal connection without writing it to process env."""
    global _runtime_token, _runtime_allowed_chat_ids, _bot
    new_token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    if new_token != _runtime_token:
        _bot = None
    _runtime_token = new_token
    _runtime_allowed_chat_ids = _parse_chat_ids(
        values.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
    )


def _token() -> str:
    return _runtime_token or integration_value("TELEGRAM_BOT_TOKEN", "").strip()


def _allowed_chat_ids() -> set[int]:
    if _runtime_allowed_chat_ids:
        return set(_runtime_allowed_chat_ids)
    configured_destinations = _parse_chat_ids(
        integration_value("TELEGRAM_CHAT_IDS", "")
        or integration_value("TELEGRAM_CHAT_ID", "")
    )
    return _parse_chat_ids(
        integration_value("TELEGRAM_ALLOWED_CHAT_IDS", "")
    ) or configured_destinations


def _destination_chat_ids() -> set[int]:
    configured = _parse_chat_ids(
        integration_value("TELEGRAM_CHAT_IDS", "")
        or integration_value("TELEGRAM_CHAT_ID", "")
    )
    return configured or _allowed_chat_ids()

_bot: Optional[Bot] = None
_app: Optional[Application] = None

# Chat -> selected council/context while waiting for the operator's task text.
_pending_task: dict[int, dict] = {}
# Chat -> in-progress knowledge base document picker state.
_doc_picker_state: dict[int, dict] = {}
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
        token = _token()
        if not token:
            raise RuntimeError("Telegram bot token is not configured")
        _bot = Bot(token=token)
    return _bot


def _build_doc_picker_keyboard(available_docs: list[dict], selected: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for idx, doc in enumerate(available_docs):
        checked = "☑️" if idx in selected else "⬜"
        label = doc["filename"][:40]
        rows.append([InlineKeyboardButton(f"{checked} {label}", callback_data=f"docsel:{idx}")])
    rows.append([
        InlineKeyboardButton("📚 Use All Documents", callback_data="docsel_all"),
        InlineKeyboardButton("✅ Continue", callback_data="docsel_done"),
    ])
    return InlineKeyboardMarkup(rows)


async def _start_task_entry(chat_id: int, council: str, base_context: dict, edit_message=None):
    """
    After a council (and platform, for Content) is chosen, offer to scope the
    task to specific knowledge base documents before asking for the task text.
    Falls straight through to the text prompt if the knowledge base is empty.
    """
    if council != "grant":
        _pending_task[chat_id] = {"council": council, "context": base_context}
        text = (
            f"📝 <b>{html.escape(COUNCIL_LABELS.get(council, council.title()))} selected</b>\n\n"
            "Now send the complete task as your next Telegram message.\n\nUse /cancel to stop."
        )
        if edit_message:
            await edit_message(text, parse_mode=ParseMode.HTML)
        return

    try:
        from src.core.rag_engine import get_all_documents
        available_docs = await get_all_documents()
    except Exception as exc:
        print(f"[Telegram] Could not list knowledge base documents: {exc}")
        available_docs = []

    if not available_docs:
        _pending_task[chat_id] = {"council": council, "context": base_context}
        text = (
            f"📝 <b>{html.escape(COUNCIL_LABELS.get(council, council.title()))} selected</b>\n\n"
            "Now send the complete task as your next Telegram message.\n\nUse /cancel to stop."
        )
        if edit_message:
            await edit_message(text, parse_mode=ParseMode.HTML)
        return

    _doc_picker_state[chat_id] = {
        "council": council,
        "context": base_context,
        "available_docs": available_docs,
        "selected": set(),
    }
    text = (
        "📚 <b>Knowledge base documents</b>\n\n"
        "Tap to select specific documents to focus this task on, or use all. "
        "Then tap Continue."
    )
    keyboard = _build_doc_picker_keyboard(available_docs, set())
    if edit_message:
        await edit_message(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


def _chat_id(update: Update) -> int | None:
    return update.effective_chat.id if update.effective_chat else None


def _is_authorized(update: Update) -> bool:
    chat_id = _chat_id(update)
    return bool(
        update.effective_chat
        and update.effective_chat.type == "private"
        and chat_id is not None
        and chat_id in _allowed_chat_ids()
    )


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
    if not _token():
        raise RuntimeError("Telegram bot token is not configured")
    destination_chat_ids = _destination_chat_ids()
    if not destination_chat_ids:
        raise RuntimeError("No Telegram notification destination is configured")
    bot = _get_bot()
    failures: list[str] = []
    for chat_id in destination_chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as exc:
            failures.append(f"{chat_id}: {type(exc).__name__}: {exc}")
    if failures:
        raise RuntimeError("Telegram delivery failed: " + "; ".join(failures))


# ── Workflow notifications ───────────────────────────────────────────────

async def notify_workflow_start(workflow_name: str, details: str = ""):
    if not _token() or not _destination_chat_ids():
        return
    try:
        switch = await _kill_switch_status()
        kill_status = "🔴 KILLED" if switch.get("is_active") else "🟢 ACTIVE"
    except Exception:
        kill_status = "⚠️ STATUS UNAVAILABLE"
    msg = f"⚡ *Workflow Started: {workflow_name}*\nKill Switch: {kill_status}\n"
    if details:
        msg += f"\n{details}"
    await _send_to_destinations(msg, parse_mode=ParseMode.MARKDOWN)


async def notify_workflow_complete(workflow_name: str, summary: str):
    if not _token() or not _destination_chat_ids():
        return
    await _send_to_destinations(
        f"✅ *Workflow Complete: {workflow_name}*\n\n{summary}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def notify_workflow_error(workflow_name: str, error: str):
    if not _token() or not _destination_chat_ids():
        return
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
    council: str = "",
    retrieval_warnings: list[str] | None = None,
    knowledge_sources: list[str] | None = None,
    skill_revisions: list[str] | None = None,
):
    """Send a persisted task draft with DB-backed approval actions."""
    if not _token():
        raise RuntimeError("Telegram bot token is not configured")

    display_draft = draft_text[:2400] + "…" if len(draft_text) > 2400 else draft_text
    msg = (
        f"📋 <b>Approval Required — {html.escape(workflow_name)}</b>\n"
        f"Confidence: <b>{confidence:.0f}/100</b>\n"
    )
    if context_summary:
        msg += f"Task: {html.escape(context_summary[:500])}\n"
    if knowledge_sources:
        msg += f"Evidence: <b>{len(knowledge_sources)}</b> scoped source(s)\n"
    if skill_revisions:
        msg += "Skills: " + html.escape(", ".join(skill_revisions[:4])) + "\n"
    if retrieval_warnings:
        warning_text = "; ".join(str(item) for item in retrieval_warnings[:3])
        msg += f"⚠️ Retrieval: {html.escape(warning_text[:700])}\n"
    msg += (
        f"\n<blockquote>{html.escape(display_draft)}</blockquote>\n"
        f"Task ID: <code>{html.escape(task_id)}</code>"
    )

    docx_download_url = f"{DASHBOARD_URL}/api/tasks/{task_id}/export/docx"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{task_id}"),
            InlineKeyboardButton("🔄 Retry", callback_data=f"retry:{task_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{task_id}"),
        ],
        [
            InlineKeyboardButton("📊 Open in Dashboard", url=f"{DASHBOARD_URL}/approvals/{task_id}"),
            InlineKeyboardButton("📄 Download DOCX", url=docx_download_url),
        ],
    ])

    recipients = {destination_chat_id} if destination_chat_id else _destination_chat_ids()
    if not recipients:
        raise RuntimeError("No Telegram approval destination is configured")
    bot = _get_bot()

    docx_bytes = None
    docx_filename = None
    if council.lower() == "grant":
        try:
            from src.integrations.docx_export import build_task_docx, build_task_docx_filename
            task_snapshot = {
                "task_id": task_id,
                "council": council,
                "task_description": context_summary,
                "final_output": draft_text,
                "confidence_score": confidence,
            }
            docx_bytes = build_task_docx(task_snapshot)
            docx_filename = build_task_docx_filename(task_snapshot)
        except Exception as exc:
            print(f"[Telegram] DOCX generation failed for {task_id}: {exc}")

    failures: list[str] = []
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
            if docx_bytes and docx_filename:
                from io import BytesIO
                await bot.send_document(
                    chat_id=chat_id,
                    document=BytesIO(docx_bytes),
                    filename=docx_filename,
                    caption=f"📄 Proposal document for task {task_id} — ready to review and manually submit.",
                )
        except Exception as exc:
            failures.append(f"{chat_id}: {type(exc).__name__}: {exc}")
    if failures:
        raise RuntimeError("Telegram approval delivery failed: " + "; ".join(failures))


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
    try:
        if (await _kill_switch_status()).get("is_active"):
            await update.effective_message.reply_text(
                "🛑 The kill switch is active. Use /resume before submitting new work."
            )
            return
    except Exception as exc:
        await update.effective_message.reply_text(
            f"❌ The protected backend is unavailable: <code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
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
        _pending_task.pop(chat_id, None)
        _doc_picker_state.pop(chat_id, None)
    await update.effective_message.reply_text("Task entry cancelled. Use /task to start again.")


async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    reason = "Manual kill via Telegram"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.put(
                f"{API_BASE_URL}/api/kill-switch",
                headers=_service_headers(),
                json={"active": True, "reason": reason},
            )
            response.raise_for_status()
        await update.effective_message.reply_text(
            "🛑 <b>Kill switch ACTIVATED</b>\nAll workflows and new council tasks are blocked.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        await update.effective_message.reply_text(
            f"❌ Kill switch update failed: <code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
        )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.put(
                f"{API_BASE_URL}/api/kill-switch",
                headers=_service_headers(),
                json={"active": False, "reason": "Resumed via Telegram"},
            )
            response.raise_for_status()
        await update.effective_message.reply_text(
            "✅ <b>Kill switch DEACTIVATED</b>\nWorkflows and council tasks may run again.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        await update.effective_message.reply_text(
            f"❌ Kill switch update failed: <code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    try:
        status = await _kill_switch_status()
    except Exception as exc:
        await update.effective_message.reply_text(
            f"❌ Backend status unavailable: <code>{html.escape(str(exc))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
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
    if chat_id is None or chat_id not in _pending_task:
        return
    selection = _pending_task.pop(chat_id)
    council = selection["council"]
    task_text = (update.effective_message.text or "").strip()
    if len(task_text) < 10:
        _pending_task[chat_id] = selection
        await update.effective_message.reply_text("Please provide a more detailed task (at least 10 characters).")
        return

    payload = {
        "council": council,
        "task_description": task_text,
        "priority": "high",
        "selected_document_hashes": list(selection.get("context", {}).get("selected_docs", [])),
        "context": {
            **{
                key: value
                for key, value in selection.get("context", {}).items()
                if key != "selected_docs"
            },
            "source": "telegram",
            "telegram_chat_id": chat_id,
            "telegram_user": update.effective_user.username or str(update.effective_user.id),
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{API_BASE_URL}/api/council-runs",
                headers={**_service_headers(), "Idempotency-Key": f"telegram:{update.update_id}"},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            task_id = (result.get("resource") or {}).get("task_id")
            if not task_id:
                raise RuntimeError("Backend response did not contain a task ID")
        await update.effective_message.reply_text(
            f"⚙️ <b>{html.escape(COUNCIL_LABELS[council])} is working</b>\n\n"
            f"Task ID: <code>{html.escape(task_id)}</code>\n"
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
        try:
            if (await _kill_switch_status()).get("is_active"):
                await query.answer("Kill switch is active", show_alert=True)
                return
        except Exception:
            await query.answer("Protected backend unavailable", show_alert=True)
            return
        chat_id = _chat_id(update)
        await query.answer()
        if council == "content":
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Instagram", callback_data="platform:instagram"),
                    InlineKeyboardButton("LinkedIn", callback_data="platform:linkedin"),
                ],
                [
                    InlineKeyboardButton("X / Twitter", callback_data="platform:twitter"),
                    InlineKeyboardButton("Facebook", callback_data="platform:facebook"),
                ],
                [
                    InlineKeyboardButton("Reddit", callback_data="platform:reddit"),
                    InlineKeyboardButton("Discord", callback_data="platform:discord"),
                ],
                [InlineKeyboardButton("All 6 platforms", callback_data="platform:all")],
            ])
            await query.edit_message_text(
                "✍️ <b>Content Council selected</b>\n\nChoose the output platform:",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return

        if chat_id is not None:
            await _start_task_entry(chat_id, council, {}, edit_message=query.edit_message_text)
        return

    if data.startswith("platform:"):
        platform = data.split(":", 1)[1]
        allowed_platforms = {"all", "instagram", "linkedin", "twitter", "facebook", "reddit", "discord"}
        if platform not in allowed_platforms:
            await query.answer("Unknown platform", show_alert=True)
            return
        chat_id = _chat_id(update)
        await query.answer()
        if chat_id is not None:
            await _start_task_entry(chat_id, "content", {"platform": platform}, edit_message=query.edit_message_text)
        return

    if data.startswith("docsel:") or data in ("docsel_all", "docsel_done"):
        chat_id = _chat_id(update)
        state = _doc_picker_state.get(chat_id) if chat_id is not None else None
        if not state:
            await query.answer("This selection expired, use /task again.", show_alert=True)
            return

        if data.startswith("docsel:"):
            idx = int(data.split(":", 1)[1])
            if idx in state["selected"]:
                state["selected"].discard(idx)
            else:
                state["selected"].add(idx)
            await query.answer()
            await query.edit_message_reply_markup(
                reply_markup=_build_doc_picker_keyboard(state["available_docs"], state["selected"])
            )
            return

        if data == "docsel_all":
            state["selected"] = set()

        # docsel_done or docsel_all: finalize and move to task-text prompt.
        selected_hashes = [
            state["available_docs"][i]["doc_hash"] for i in state["selected"]
        ]
        final_context = {**state["context"]}
        if selected_hashes:
            final_context["selected_docs"] = selected_hashes
        _pending_task[chat_id] = {"council": state["council"], "context": final_context}
        _doc_picker_state.pop(chat_id, None)

        await query.answer()
        doc_summary = (
            f"Using {len(selected_hashes)} selected document(s)."
            if selected_hashes else "Searching your entire knowledge base."
        )
        await query.edit_message_text(
            f"📝 <b>{html.escape(COUNCIL_LABELS.get(state['council'], state['council'].title()))} selected</b>\n"
            f"{doc_summary}\n\n"
            "Now send the complete task as your next Telegram message.\n\nUse /cancel to stop.",
            parse_mode=ParseMode.HTML,
        )
        return

    if ":" not in data:
        await query.answer("Invalid action", show_alert=True)
        return

    action, task_id = data.split(":", 1)
    callback_key = f"{query.message.chat_id}:{query.id}"
    if callback_key in _handled_callbacks:
        await query.answer("This action was already processed.", show_alert=True)
        return

    await query.answer("Processing…")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            headers = _service_headers()
            task_response = await client.get(
                f"{API_BASE_URL}/api/tasks/{task_id}", headers=headers
            )
            task_response.raise_for_status()
            task = task_response.json()
            expected_version = task.get("approval_version")
            if expected_version is None:
                raise RuntimeError("Task is not awaiting an approval decision")
            action_payload = {
                "action": action,
                "expected_version": expected_version,
                "idempotency_key": f"telegram:{query.id}",
                "notes": f"{action.title()} requested via Telegram",
            }
            response = await client.post(
                f"{API_BASE_URL}/api/approvals/{task_id}/actions",
                headers=headers,
                json=action_payload,
            )
            response.raise_for_status()

            if action == "approve":
                result_text = (
                    f"✅ <b>Approved</b> — Task <code>{html.escape(task_id)}</code>\n"
                    "The persisted approval is visible in the dashboard."
                )

            elif action == "reject":
                result_text = (
                    f"❌ <b>Rejected</b> — Task <code>{html.escape(task_id)}</code>\n"
                    "The persisted decision is visible in the dashboard."
                )

            elif action == "retry":
                result_text = (
                    f"🔄 <b>Retry started</b>\n"
                    f"Task: <code>{html.escape(task_id)}</code>\n"
                    "A fresh council run was queued and will return here for approval."
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
    token = _token()
    if not token:
        print("[Telegram] No bot token configured. Skipping bot startup.")
        return
    if not _allowed_chat_ids():
        print("[Telegram] No authorized chat IDs configured. Skipping bot startup.")
        return
    global _app
    _app = Application.builder().token(token).build()
    _register_handlers(_app)
    print("🤖 [Telegram] Bot started. Listening for authorized commands...")
    _app.run_polling(stop_signals=None, close_loop=False)


async def start_telegram_bot_async():
    token = _token()
    if not token:
        print("[Telegram] No bot token configured. Skipping bot startup.")
        return
    if not _allowed_chat_ids():
        print("[Telegram] No authorized chat IDs configured. Skipping bot startup.")
        return
    global _app
    _app = Application.builder().token(token).build()
    _register_handlers(_app)
    await _app.initialize()
    await _app.start()
    # Production uses long polling for the private administrator control
    # plane. Telegram does not allow getUpdates while an old webhook remains.
    await _app.bot.delete_webhook(drop_pending_updates=False)
    await _app.bot.set_my_commands([
        BotCommand("task", "Assign work to Content, Sales, or Grant Council"),
        BotCommand("status", "Check system and kill-switch status"),
        BotCommand("kill", "Emergency stop all workflows"),
        BotCommand("resume", "Resume workflow execution"),
        BotCommand("help", "Show available commands"),
        BotCommand("cancel", "Cancel current task entry"),
    ])
    await _app.updater.start_polling()
    print("🤖 [Telegram] Bot started (async). Listening for authorized commands...")


async def stop_telegram_bot_async():
    """Stop the polling application when its durable workflow is disabled."""
    global _app
    if _app is None:
        return
    try:
        if _app.updater and _app.updater.running:
            await _app.updater.stop()
        if _app.running:
            await _app.stop()
        await _app.shutdown()
    finally:
        _app = None
