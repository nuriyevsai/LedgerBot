import csv
import io
import logging
from datetime import datetime, timedelta
from functools import wraps

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN, DEFAULT_CURRENCY, EXCHANGE_RATE_API
import db
import charts
import nlp
import scheduler

# ──── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ──── Login state ───────────────────────────────────────────────────────
_logged_in: set[int] = set()


# ──── Auth decorator ────────────────────────────────────────────────────
def require_login(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in _logged_in:
            await update.message.reply_text("🔒 Login required. Use /login 1234")
            return
        db.update_last_active(user_id)
        return await func(update, context)
    return wrapper


# ──── Helpers ───────────────────────────────────────────────────────────

def _cur(user_id: int) -> str:
    return db.get_currency(user_id)


def _month_range(month_str: str = None):
    """Return (start_date, end_date) strings for a given month name or current month."""
    now = datetime.utcnow()
    if month_str:
        months_map = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        m = months_map.get(month_str.lower())
        if m:
            year = now.year
            start = datetime(year, m, 1)
            if m == 12:
                end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
            else:
                end = datetime(year, m + 1, 1) - timedelta(seconds=1)
            return start.strftime("%Y-%m-%d 00:00:00"), end.strftime("%Y-%m-%d 23:59:59")
    # Default: current month
    start = datetime(now.year, now.month, 1)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1) - timedelta(seconds=1)
    else:
        end = datetime(now.year, now.month + 1, 1) - timedelta(seconds=1)
    return start.strftime("%Y-%m-%d 00:00:00"), end.strftime("%Y-%m-%d 23:59:59")


def _today_range():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return f"{today} 00:00:00", f"{today} 23:59:59"


# ──── Main menu keyboard ──────────────────────────────────────────────

def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 Income", callback_data="menu_income"),
            InlineKeyboardButton("📉 Expense", callback_data="menu_expense"),
        ],
        [
            InlineKeyboardButton("💰 Balance", callback_data="menu_balance"),
            InlineKeyboardButton("📋 Summary", callback_data="menu_summary"),
        ],
        [
            InlineKeyboardButton("📊 Chart", callback_data="menu_chart"),
            InlineKeyboardButton("📁 Report", callback_data="menu_report"),
        ],
        [
            InlineKeyboardButton("📝 Notes", callback_data="menu_notes"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
        ],
    ])


def _settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💱 Currency", callback_data="set_currency"),
            InlineKeyboardButton("🔐 Change PIN", callback_data="set_pin"),
        ],
        [
            InlineKeyboardButton("📤 Export CSV", callback_data="set_export"),
            InlineKeyboardButton("💾 Backup DB", callback_data="set_backup"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="menu_main"),
        ],
    ])


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Security
# ══════════════════════════════════════════════════════════════════════

async def cmd_setpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args[0]) != 4 or not context.args[0].isdigit():
        await update.message.reply_text("PIN must be 4 digits. Usage: /setpin 1234")
        return
    db.set_pin(update.effective_user.id, context.args[0])
    await update.message.reply_text("✅ PIN saved (encrypted).")


async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /login 1234")
        return
    if not db.has_pin(user_id):
        await update.message.reply_text("No PIN set. Use /setpin 1234 first.")
        return
    if db.verify_pin(user_id, context.args[0]):
        _logged_in.add(user_id)
        db.update_last_active(user_id)
        await update.message.reply_text("✅ Logged in.", reply_markup=_main_keyboard())
    else:
        await update.message.reply_text("❌ Incorrect PIN.")


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _logged_in.discard(update.effective_user.id)
    await update.message.reply_text("👋 Logged out.")


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Core Finance
# ══════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *Finance Bot*\n\n"
        "🔐 *Security*\n"
        "/setpin `1234` — set PIN\n"
        "/login `1234` — log in\n"
        "/logout — log out\n\n"
        "💸 *Finance*\n"
        "/income `amount category`\n"
        "/expense `amount category`\n"
        "/balance — current balance\n"
        "/summary — recent transactions\n"
        "/report `[month]` — monthly report\n"
        "/categories — spending by category\n"
        "/chart — visual chart\n"
        "/delete `id` — delete a transaction\n"
        "/edit `id field value` — edit a transaction\n"
        "/reset — clear all transactions\n\n"
        "💰 *Budgets*\n"
        "/budget `category amount` — set budget\n"
        "/budgets — view all budgets\n\n"
        "🔄 *Recurring*\n"
        "/recurring `type amount cat freq`\n"
        "/myrecurring — list recurring\n"
        "/stoprecurring `id` — stop one\n\n"
        "💱 *Currency*\n"
        "/currency `USD` — set currency\n"
        "/convert `100 USD EUR` — convert\n\n"
        "👥 *Shared Budget*\n"
        "/share — create group\n"
        "/join `CODE` — join group\n"
        "/sharedbalance — group balance\n\n"
        "📝 *Notes*\n"
        "/note `text` — add note\n"
        "/mynotes — view notes\n\n"
        "📦 *Other*\n"
        "/export — download CSV\n"
        "/backup — download database\n\n"
        "💡 _Or just type naturally:_\n"
        '_"spent 50 on food"_\n'
        '_"earned 5000 salary"_',
        parse_mode="Markdown",
    )


@require_login
async def cmd_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /income 500 salary")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return
    category = " ".join(context.args[1:])
    tx_id = db.add_transaction(user_id, "income", amount, category)
    cur = _cur(user_id)
    await update.message.reply_text(f"✅ Income #{tx_id}: {amount:.2f} {cur} ({category})")


@require_login
async def cmd_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /expense 30 food")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return
    category = " ".join(context.args[1:])
    tx_id = db.add_transaction(user_id, "expense", amount, category)
    cur = _cur(user_id)
    # Check budget
    status = db.check_budget_status(user_id, category)
    warning = ""
    if status:
        limit_amt, spent = status
        if spent + amount >= limit_amt:
            warning = f"\n⚠️ Budget alert! {category}: {spent + amount:.2f}/{limit_amt:.2f} {cur}"
        elif spent + amount >= limit_amt * 0.8:
            warning = f"\n⚡ 80% of budget used! {category}: {spent + amount:.2f}/{limit_amt:.2f} {cur}"
    await update.message.reply_text(f"✅ Expense #{tx_id}: {amount:.2f} {cur} ({category}){warning}")


@require_login
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = db.get_balance(update.effective_user.id)
    cur = _cur(update.effective_user.id)
    emoji = "📈" if bal >= 0 else "📉"
    await update.message.reply_text(f"{emoji} Balance: {bal:.2f} {cur}")


@require_login
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Check for date filter
    if context.args:
        arg = context.args[0].lower()
        if arg == "today":
            start, end = _today_range()
            rows = db.get_transactions_filtered(user_id, start, end)
            title = "Today's transactions"
        else:
            start, end = _month_range(arg)
            rows = db.get_transactions_filtered(user_id, start, end)
            title = f"Transactions for {arg.capitalize()}"
    else:
        rows = db.get_summary(user_id)
        title = "Recent transactions"

    if not rows:
        await update.message.reply_text("No transactions found.")
        return

    cur = _cur(user_id)
    lines = [f"📋 *{title}*\n"]
    for tx_id, t, amt, cat, date in rows:
        emoji = "📈" if t == "income" else "📉"
        lines.append(f"{emoji} `#{tx_id}` {t} | {amt:.2f} {cur} | {cat} | {date}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_login
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.reset_balance(update.effective_user.id)
    await update.message.reply_text("🗑 All transactions deleted.")


@require_login
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete 15")
        return
    try:
        tx_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID must be a number.")
        return
    if db.delete_transaction(update.effective_user.id, tx_id):
        await update.message.reply_text(f"✅ Transaction #{tx_id} deleted.")
    else:
        await update.message.reply_text(f"❌ Transaction #{tx_id} not found.")


@require_login
async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /edit ID FIELD VALUE\n"
            "Fields: amount, category, type\n"
            "Example: /edit 15 amount 200"
        )
        return
    try:
        tx_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID must be a number.")
        return
    field = context.args[1].lower()
    value = " ".join(context.args[2:])
    if field == "amount":
        try:
            value = float(value)
        except ValueError:
            await update.message.reply_text("Amount must be a number.")
            return
    if db.edit_transaction(update.effective_user.id, tx_id, field, value):
        await update.message.reply_text(f"✅ Transaction #{tx_id} updated: {field} → {value}")
    else:
        await update.message.reply_text(f"❌ Failed. Check ID and field name (amount/category/type).")


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Reports & Charts
# ══════════════════════════════════════════════════════════════════════

@require_login
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    month_arg = context.args[0] if context.args else None
    start, end = _month_range(month_arg)
    cur = _cur(user_id)

    # Category totals
    expense_cats = db.get_category_totals(user_id, "expense", start, end)
    income_cats = db.get_category_totals(user_id, "income", start, end)

    total_income = sum(c[1] for c in income_cats)
    total_expense = sum(c[1] for c in expense_cats)
    net = total_income - total_expense

    month_label = month_arg.capitalize() if month_arg else datetime.utcnow().strftime("%B %Y")
    lines = [f"📊 *Report: {month_label}*\n"]
    lines.append(f"📈 Total Income: {total_income:.2f} {cur}")
    lines.append(f"📉 Total Expense: {total_expense:.2f} {cur}")
    emoji = "✅" if net >= 0 else "🔴"
    lines.append(f"{emoji} Net: {net:.2f} {cur}\n")

    if expense_cats:
        lines.append("*Expenses by Category:*")
        for cat, total in expense_cats:
            pct = (total / total_expense * 100) if total_expense else 0
            bar_len = int(pct / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"  {cat}: {total:.2f} {cur} ({pct:.0f}%)\n  {bar}")

    if income_cats:
        lines.append("\n*Income by Category:*")
        for cat, total in income_cats:
            lines.append(f"  {cat}: {total:.2f} {cur}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_login
async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur = _cur(user_id)
    expense_cats = db.get_category_totals(user_id, "expense")
    income_cats = db.get_category_totals(user_id, "income")

    if not expense_cats and not income_cats:
        await update.message.reply_text("No transactions yet.")
        return

    lines = ["📂 *All Categories*\n"]
    if expense_cats:
        lines.append("📉 *Expenses:*")
        for cat, total in expense_cats:
            lines.append(f"  • {cat}: {total:.2f} {cur}")
    if income_cats:
        lines.append("\n📈 *Income:*")
        for cat, total in income_cats:
            lines.append(f"  • {cat}: {total:.2f} {cur}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_login
async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("📊 Generating charts...")

    # Pie chart
    pie = charts.expense_pie_chart(user_id)
    if pie:
        await update.message.reply_photo(photo=pie, caption="Expenses by Category")

    # Bar chart
    bar = charts.income_vs_expense_bar(user_id)
    if bar:
        await update.message.reply_photo(photo=bar, caption="Income vs Expense (6 months)")

    if not pie and not bar:
        await update.message.reply_text("Not enough data to generate charts.")


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Budgets
# ══════════════════════════════════════════════════════════════════════

@require_login
async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /budget food 5000")
        return
    category = context.args[0]
    try:
        limit_amt = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return
    db.set_budget(update.effective_user.id, category, limit_amt)
    cur = _cur(update.effective_user.id)
    await update.message.reply_text(f"✅ Budget set: {category} → {limit_amt:.2f} {cur}/month")


@require_login
async def cmd_budgets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = db.get_budgets(user_id)
    if not rows:
        await update.message.reply_text("No budgets set. Use /budget category amount")
        return
    cur = _cur(user_id)
    lines = ["📋 *Your Budgets*\n"]
    for bid, cat, limit_amt, period in rows:
        status = db.check_budget_status(user_id, cat)
        spent = status[1] if status else 0
        pct = (spent / limit_amt * 100) if limit_amt else 0
        if pct >= 100:
            emoji = "🔴"
        elif pct >= 80:
            emoji = "🟡"
        else:
            emoji = "🟢"
        bar_len = min(int(pct / 5), 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(
            f"{emoji} *{cat}*: {spent:.2f}/{limit_amt:.2f} {cur} ({pct:.0f}%)\n"
            f"  {bar}  `#{bid}`"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Recurring
# ══════════════════════════════════════════════════════════════════════

@require_login
async def cmd_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage: /recurring income 3000 salary monthly\n"
            "Frequencies: daily, weekly, monthly"
        )
        return
    t_type = context.args[0].lower()
    if t_type not in ("income", "expense"):
        await update.message.reply_text("Type must be income or expense.")
        return
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return
    category = context.args[2]
    frequency = context.args[3].lower()
    if frequency not in ("daily", "weekly", "monthly"):
        await update.message.reply_text("Frequency must be daily, weekly, or monthly.")
        return
    rec_id = db.add_recurring(update.effective_user.id, t_type, amount, category, frequency)
    await update.message.reply_text(
        f"🔄 Recurring #{rec_id}: {t_type} {amount:.2f} ({category}) — {frequency}"
    )


@require_login
async def cmd_myrecurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_recurring_list(update.effective_user.id)
    if not rows:
        await update.message.reply_text("No recurring transactions.")
        return
    cur = _cur(update.effective_user.id)
    lines = ["🔄 *Recurring Transactions*\n"]
    for rid, t, amt, cat, freq, next_run in rows:
        emoji = "📈" if t == "income" else "📉"
        lines.append(f"{emoji} `#{rid}` {t} {amt:.2f} {cur} ({cat}) — {freq}\n   Next: {next_run}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_login
async def cmd_stoprecurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /stoprecurring 3")
        return
    try:
        rec_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID must be a number.")
        return
    if db.delete_recurring(update.effective_user.id, rec_id):
        await update.message.reply_text(f"✅ Recurring #{rec_id} stopped.")
    else:
        await update.message.reply_text(f"❌ Recurring #{rec_id} not found.")


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Currency
# ══════════════════════════════════════════════════════════════════════

@require_login
async def cmd_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        cur = _cur(update.effective_user.id)
        await update.message.reply_text(f"Current currency: {cur}\nUsage: /currency EUR")
        return
    new_cur = context.args[0].upper()
    db.set_currency(update.effective_user.id, new_cur)
    await update.message.reply_text(f"✅ Currency set to {new_cur}")


@require_login
async def cmd_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /convert 100 USD EUR")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return
    from_cur = context.args[1].upper()
    to_cur = context.args[2].upper()
    try:
        resp = requests.get(
            EXCHANGE_RATE_API,
            params={"base": from_cur, "symbols": to_cur},
            timeout=10,
        )
        data = resp.json()
        if not data.get("success", True) or "rates" not in data:
            await update.message.reply_text("❌ Could not fetch exchange rates. Try again later.")
            return
        rate = data["rates"][to_cur]
        result = amount * rate
        await update.message.reply_text(
            f"💱 {amount:.2f} {from_cur} = {result:.2f} {to_cur}\n"
            f"Rate: 1 {from_cur} = {rate:.4f} {to_cur}"
        )
    except Exception as e:
        logger.error("Exchange rate error: %s", e)
        await update.message.reply_text("❌ Exchange rate service unavailable.")


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Shared Budget
# ══════════════════════════════════════════════════════════════════════

@require_login
async def cmd_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = db.create_shared_group(update.effective_user.id)
    await update.message.reply_text(
        f"👥 Shared group created!\n"
        f"Invite code: `{code}`\n\n"
        f"Share this code — others can join with /join {code}",
        parse_mode="Markdown",
    )


@require_login
async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /join CODE")
        return
    code = context.args[0]
    if db.join_shared_group(update.effective_user.id, code):
        await update.message.reply_text("✅ Joined shared budget group!")
    else:
        await update.message.reply_text("❌ Invalid invite code.")


@require_login
async def cmd_sharedbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    balances = db.get_shared_balance(update.effective_user.id)
    if not balances:
        await update.message.reply_text("You're not in a shared group. Use /share to create one.")
        return
    cur = _cur(update.effective_user.id)
    lines = ["👥 *Shared Group Balances*\n"]
    total = 0
    for uid, bal in balances.items():
        emoji = "📈" if bal >= 0 else "📉"
        tag = " (you)" if uid == update.effective_user.id else ""
        lines.append(f"{emoji} User {uid}{tag}: {bal:.2f} {cur}")
        total += bal
    lines.append(f"\n💰 Combined: {total:.2f} {cur}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Notes
# ══════════════════════════════════════════════════════════════════════

@require_login
async def cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /note your text here")
        return
    text = " ".join(context.args)
    db.add_note(update.effective_user.id, text)
    await update.message.reply_text("📝 Note saved.")


@require_login
async def cmd_mynotes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_notes(update.effective_user.id)
    if not rows:
        await update.message.reply_text("No notes yet.")
        return
    lines = ["📝 *Your Notes*\n"]
    for note_text, date in rows:
        lines.append(f"📌 {date} — {note_text}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════
#   COMMANDS — Export / Backup
# ══════════════════════════════════════════════════════════════════════

@require_login
async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_all_transactions_for_export(update.effective_user.id)
    if not rows:
        await update.message.reply_text("No transactions to export.")
        return
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Type", "Amount", "Category", "Date"])
    for row in rows:
        writer.writerow(row)
    csv_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
    csv_bytes.name = "transactions.csv"
    await update.message.reply_document(document=csv_bytes, caption="📤 Your transactions")


@require_login
async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open(db.DB_NAME, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="finance_backup.db",
                caption="💾 Database backup",
            )
    except Exception as e:
        logger.error("Backup error: %s", e)
        await update.message.reply_text("❌ Could not create backup.")


# ══════════════════════════════════════════════════════════════════════
#   CALLBACK QUERY — Inline Keyboard Actions
# ══════════════════════════════════════════════════════════════════════

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id not in _logged_in:
        await query.edit_message_text("🔒 Session expired. Use /login 1234")
        return

    db.update_last_active(user_id)

    if data == "menu_main":
        await query.edit_message_text("💰 *Finance Bot*", parse_mode="Markdown", reply_markup=_main_keyboard())

    elif data == "menu_income":
        await query.edit_message_text(
            "📈 *Add Income*\n\nSend a message like:\n`/income 5000 salary`\n\n"
            "Or type naturally: _earned 5000 salary_",
            parse_mode="Markdown",
        )

    elif data == "menu_expense":
        await query.edit_message_text(
            "📉 *Add Expense*\n\nSend a message like:\n`/expense 30 food`\n\n"
            "Or type naturally: _spent 30 on food_",
            parse_mode="Markdown",
        )

    elif data == "menu_balance":
        bal = db.get_balance(user_id)
        cur = _cur(user_id)
        emoji = "📈" if bal >= 0 else "📉"
        await query.edit_message_text(
            f"{emoji} *Balance: {bal:.2f} {cur}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu_main")]
            ]),
        )

    elif data == "menu_summary":
        rows = db.get_summary(user_id, limit=10)
        cur = _cur(user_id)
        if not rows:
            text = "No transactions yet."
        else:
            lines = ["📋 *Last 10 Transactions*\n"]
            for tx_id, t, amt, cat, date in rows:
                emoji = "📈" if t == "income" else "📉"
                lines.append(f"{emoji} `#{tx_id}` {amt:.2f} {cur} | {cat}")
            text = "\n".join(lines)
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Full Summary", callback_data="menu_full_summary")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
            ]),
        )

    elif data == "menu_full_summary":
        rows = db.get_summary(user_id)
        cur = _cur(user_id)
        if not rows:
            text = "No transactions yet."
        else:
            lines = ["📋 *All Transactions*\n"]
            for tx_id, t, amt, cat, date in rows:
                emoji = "📈" if t == "income" else "📉"
                lines.append(f"{emoji} `#{tx_id}` {t} | {amt:.2f} {cur} | {cat} | {date}")
            text = "\n".join(lines)
        # Truncate if too long for Telegram
        if len(text) > 4000:
            text = text[:4000] + "\n\n... (use /export for full data)"
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu_main")]
            ]),
        )

    elif data == "menu_chart":
        await query.edit_message_text("📊 Generating charts...")
        pie = charts.expense_pie_chart(user_id)
        bar = charts.income_vs_expense_bar(user_id)
        if pie:
            await context.bot.send_photo(chat_id=user_id, photo=pie, caption="Expenses by Category")
        if bar:
            await context.bot.send_photo(chat_id=user_id, photo=bar, caption="Income vs Expense")
        if not pie and not bar:
            await context.bot.send_message(chat_id=user_id, text="Not enough data for charts.")
        await context.bot.send_message(
            chat_id=user_id, text="📊 Charts", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_main")]
            ]),
        )

    elif data == "menu_report":
        # Current month report
        start, end = _month_range()
        cur = _cur(user_id)
        expense_cats = db.get_category_totals(user_id, "expense", start, end)
        income_cats = db.get_category_totals(user_id, "income", start, end)
        total_income = sum(c[1] for c in income_cats)
        total_expense = sum(c[1] for c in expense_cats)
        net = total_income - total_expense
        month_label = datetime.utcnow().strftime("%B %Y")
        lines = [f"📊 *{month_label} Report*\n"]
        lines.append(f"📈 Income: {total_income:.2f} {cur}")
        lines.append(f"📉 Expense: {total_expense:.2f} {cur}")
        emoji = "✅" if net >= 0 else "🔴"
        lines.append(f"{emoji} Net: {net:.2f} {cur}")
        if expense_cats:
            lines.append("\n*Top Expenses:*")
            for cat, total in expense_cats[:5]:
                lines.append(f"  • {cat}: {total:.2f} {cur}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu_main")]
            ]),
        )

    elif data == "menu_notes":
        rows = db.get_notes(user_id, limit=10)
        if not rows:
            text = "📝 No notes yet.\n\nUse /note your text here"
        else:
            lines = ["📝 *Recent Notes*\n"]
            for note_text, date in rows:
                lines.append(f"📌 {date} — {note_text}")
            text = "\n".join(lines)
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu_main")]
            ]),
        )

    elif data == "menu_settings":
        cur = _cur(user_id)
        await query.edit_message_text(
            f"⚙️ *Settings*\n\nCurrency: {cur}",
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(),
        )

    elif data == "set_currency":
        await query.edit_message_text(
            "💱 Send /currency CODE to change.\nExamples: USD, EUR, GBP, AED, TRY",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
            ]),
        )

    elif data == "set_pin":
        await query.edit_message_text(
            "🔐 Send /setpin 1234 to change your PIN.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
            ]),
        )

    elif data == "set_export":
        await query.edit_message_text("Preparing export...")
        rows = db.get_all_transactions_for_export(user_id)
        if not rows:
            await context.bot.send_message(chat_id=user_id, text="No transactions to export.")
        else:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["ID", "Type", "Amount", "Category", "Date"])
            for row in rows:
                writer.writerow(row)
            csv_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
            csv_bytes.name = "transactions.csv"
            await context.bot.send_document(chat_id=user_id, document=csv_bytes, caption="📤 Transactions")

    elif data == "set_backup":
        try:
            with open(db.DB_NAME, "rb") as f:
                await context.bot.send_document(
                    chat_id=user_id, document=f,
                    filename="finance_backup.db", caption="💾 Database backup",
                )
        except Exception as e:
            logger.error("Backup error: %s", e)
            await context.bot.send_message(chat_id=user_id, text="❌ Backup failed.")


# ══════════════════════════════════════════════════════════════════════
#   NATURAL LANGUAGE HANDLER
# ══════════════════════════════════════════════════════════════════════

async def natural_language_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback handler: try to parse natural language into a transaction."""
    user_id = update.effective_user.id
    if user_id not in _logged_in:
        return  # Silently ignore if not logged in

    text = update.message.text
    if not text:
        return

    parsed = nlp.parse(text)
    if parsed is None:
        return  # Not recognized — just ignore

    db.update_last_active(user_id)
    tx_id = db.add_transaction(user_id, parsed.type, parsed.amount, parsed.category)
    cur = _cur(user_id)
    emoji = "📈" if parsed.type == "income" else "📉"

    warning = ""
    if parsed.type == "expense":
        status = db.check_budget_status(user_id, parsed.category)
        if status:
            limit_amt, spent = status
            if spent >= limit_amt:
                warning = f"\n⚠️ Budget exceeded! {parsed.category}: {spent:.2f}/{limit_amt:.2f} {cur}"

    await update.message.reply_text(
        f"{emoji} Got it! {parsed.type.capitalize()} #{tx_id}: "
        f"{parsed.amount:.2f} {cur} ({parsed.category}){warning}"
    )


# ══════════════════════════════════════════════════════════════════════
#   ERROR HANDLER
# ══════════════════════════════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception", exc_info=context.error)


# ══════════════════════════════════════════════════════════════════════
#   APP SETUP
# ══════════════════════════════════════════════════════════════════════

def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # Command handlers
    commands = [
        ("start", cmd_start),
        ("setpin", cmd_setpin),
        ("login", cmd_login),
        ("logout", cmd_logout),
        ("income", cmd_income),
        ("expense", cmd_expense),
        ("balance", cmd_balance),
        ("summary", cmd_summary),
        ("reset", cmd_reset),
        ("delete", cmd_delete),
        ("edit", cmd_edit),
        ("report", cmd_report),
        ("categories", cmd_categories),
        ("chart", cmd_chart),
        ("budget", cmd_budget),
        ("budgets", cmd_budgets),
        ("recurring", cmd_recurring),
        ("myrecurring", cmd_myrecurring),
        ("stoprecurring", cmd_stoprecurring),
        ("currency", cmd_currency),
        ("convert", cmd_convert),
        ("share", cmd_share),
        ("join", cmd_join),
        ("sharedbalance", cmd_sharedbalance),
        ("note", cmd_note),
        ("mynotes", cmd_mynotes),
        ("export", cmd_export),
        ("backup", cmd_backup),
    ]
    for name, callback in commands:
        app.add_handler(CommandHandler(name, callback))

    # Inline keyboard callback handler
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Natural language fallback (only text messages, not commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, natural_language_handler))

    # Error handler
    app.add_error_handler(error_handler)

    # Register scheduled jobs
    scheduler.set_logged_in_ref(_logged_in)
    scheduler.register_jobs(app.job_queue)

    logger.info("Bot starting with %d commands...", len(commands))
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
