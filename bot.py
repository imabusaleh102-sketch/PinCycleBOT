import os
import asyncio
from typing import Dict, Tuple

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Allowed durations only
DURATIONS = {
    "4h": 4 * 60 * 60,
    "8h": 8 * 60 * 60,
    "12h": 12 * 60 * 60,
    "24h": 24 * 60 * 60,
}

# chat_id -> (duration_seconds, task)
active_cycles: Dict[int, Tuple[int, asyncio.Task]] = {}


# =========================
# OWNER CHECK
# =========================

def is_owner(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == OWNER_ID


# =========================
# /start
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    await update.message.reply_text(
        "📌 Pin Cycle Bot\n\n"
        "Commands:\n"
        "/pin 4h\n"
        "/pin 8h\n"
        "/pin 12h\n"
        "/pin 24h"
    )


# =========================
# /pin
# =========================

async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return

    # Must be used inside a group/supergroup
    if chat.type not in ("group", "supergroup"):
        await message.reply_text(
            "❌ Please use this command inside the group."
        )
        return

    if len(context.args) != 1:
        await message.reply_text(
            "❌ Invalid command.\n\n"
            "Use one of:\n"
            "/pin 4h\n"
            "/pin 8h\n"
            "/pin 12h\n"
            "/pin 24h"
        )
        return

    duration_text = context.args[0].lower()

    if duration_text not in DURATIONS:
        await message.reply_text(
            "❌ Invalid duration.\n\n"
            "Only these are allowed:\n"
            "/pin 4h\n"
            "/pin 8h\n"
            "/pin 12h\n"
            "/pin 24h"
        )
        return

    duration_seconds = DURATIONS[duration_text]

    # Cancel an existing cycle in this group
    if chat.id in active_cycles:
        old_task = active_cycles[chat.id][1]

        if not old_task.done():
            old_task.cancel()

        del active_cycles[chat.id]

    # Alert message
    await message.reply_text(
        f"📌 Pin Cycle is ready. Next post will be pinned for "
        f"{duration_text[:-1]} hours, except admins."
    )

    # Start waiting for the next member post
    task = asyncio.create_task(
        cycle_timeout(chat.id, duration_seconds)
    )

    active_cycles[chat.id] = (duration_seconds, task)


# =========================
# WAITING TIMEOUT
# =========================

async def cycle_timeout(chat_id: int, duration_seconds: int):
    """
    This task only keeps the cycle active.
    The actual timer starts after a member message is pinned.
    """
    try:
        # No timeout for waiting for the next post.
        # This task simply stays alive until cancelled.
        await asyncio.Event().wait()

    except asyncio.CancelledError:
        return


# =========================
# MEMBER MESSAGE HANDLER
# =========================

async def handle_member_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return

    if chat.type not in ("group", "supergroup"):
        return

    # Ignore bots
    if user.is_bot:
        return

    # Is there an active cycle in this group?
    if chat.id not in active_cycles:
        return

    # Check whether sender is an admin
    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user.id
        )

        if member.status in ("administrator", "creator"):
            return

    except Exception:
        # If admin status cannot be checked,
        # do not pin the message.
        return

    duration_seconds, waiting_task = active_cycles[chat.id]

    # Stop waiting for the next post
    if not waiting_task.done():
        waiting_task.cancel()

    # Remove active cycle before pinning
    del active_cycles[chat.id]

    # Pin the member's message
    try:
        await context.bot.pin_chat_message(
            chat_id=chat.id,
            message_id=message.message_id,
            disable_notification=False
        )
    except Exception:
        return

    # Start timer for automatic unpin
    asyncio.create_task(
        unpin_after_time(
            context,
            chat.id,
            message.message_id,
            duration_seconds
        )
    )


# =========================
# AUTO UNPIN
# =========================

async def unpin_after_time(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    duration_seconds: int
):
    try:
        await asyncio.sleep(duration_seconds)

        await context.bot.unpin_chat_message(
            chat_id=chat_id,
            message_id=message_id
        )

    except asyncio.CancelledError:
        pass

    except Exception:
        # Ignore errors if the message was already unpinned/deleted
        pass


# =========================
# ERROR HANDLER
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    print(f"Bot error: {context.error}")


# =========================
# MAIN
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing. Add it to Railway Variables."
        )

    if OWNER_ID == 0:
        raise RuntimeError(
            "OWNER_ID is missing. Add your Telegram user ID."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pin", pin_command))

    # Handle all normal group messages
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_member_message
        )
    )

    app.add_error_handler(error_handler)

    print("📌 PinCycleBOT is running...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
