"""
Scheduled jobs using python-telegram-bot's built-in JobQueue.
- Process recurring transactions
- Send daily reminders
- Auto-logout inactive users
"""
import logging
from datetime import time as dt_time, timezone, timedelta

from telegram.ext import ContextTypes

import db
from config import REMINDER_HOUR, REMINDER_MINUTE, TIMEZONE_OFFSET, AUTO_LOGOUT_MINUTES

logger = logging.getLogger(__name__)

# Will be set by bot.py when it starts
_logged_in_ref: set[int] | None = None


def set_logged_in_ref(ref: set[int]):
    """Give the scheduler a reference to the bot's login set."""
    global _logged_in_ref
    _logged_in_ref = ref


# ─── Job: Process Recurring Transactions ───────────────────────────────

async def process_recurring(context: ContextTypes.DEFAULT_TYPE):
    """Check for due recurring transactions and auto-insert them."""
    due = db.get_recurring_due()
    for rec_id, user_id, t_type, amount, category, frequency in due:
        tx_id = db.add_transaction(user_id, t_type, amount, category)
        db.mark_recurring_run(rec_id, frequency)
        logger.info(
            "Recurring tx #%d → user %d: %s %.2f %s (tx #%d)",
            rec_id, user_id, t_type, amount, category, tx_id,
        )
        # Notify user
        try:
            emoji = "📈" if t_type == "income" else "📉"
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔄 Recurring {emoji} {t_type}: {amount:.2f} ({category})",
            )
        except Exception as e:
            logger.warning("Could not notify user %d about recurring: %s", user_id, e)


# ─── Job: Daily Reminder ──────────────────────────────────────────────

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Remind users who haven't logged anything today."""
    if _logged_in_ref is None:
        return
    for user_id in list(_logged_in_ref):
        count = db.get_today_transaction_count(user_id)
        if count == 0:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="📊 Daily reminder: You haven't logged any transactions today!\n"
                         "Use /income or /expense to track your finances.",
                )
            except Exception as e:
                logger.warning("Could not send reminder to user %d: %s", user_id, e)


# ─── Job: Auto-Logout ─────────────────────────────────────────────────

async def auto_logout(context: ContextTypes.DEFAULT_TYPE):
    """Log out users who have been inactive for too long."""
    if _logged_in_ref is None:
        return
    inactive = db.get_inactive_users(AUTO_LOGOUT_MINUTES)
    for user_id in inactive:
        if user_id in _logged_in_ref:
            _logged_in_ref.discard(user_id)
            logger.info("Auto-logout user %d (inactive %d min)", user_id, AUTO_LOGOUT_MINUTES)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🔒 Auto-logged out after {AUTO_LOGOUT_MINUTES} min of inactivity.",
                )
            except Exception:
                pass


# ─── Register Jobs ────────────────────────────────────────────────────

def register_jobs(job_queue):
    """Register all scheduled jobs on the application's JobQueue."""
    tz = timezone(timedelta(hours=TIMEZONE_OFFSET))

    # Process recurring transactions every hour
    job_queue.run_repeating(process_recurring, interval=3600, first=60, name="recurring")

    # Daily reminder at configured time
    job_queue.run_daily(
        daily_reminder,
        time=dt_time(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, tzinfo=tz),
        name="daily_reminder",
    )

    # Auto-logout check every 5 minutes
    job_queue.run_repeating(auto_logout, interval=300, first=300, name="auto_logout")

    logger.info(
        "Scheduled jobs registered: recurring (hourly), reminder (%02d:%02d), auto-logout (5min)",
        REMINDER_HOUR, REMINDER_MINUTE,
    )
