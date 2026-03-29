import sqlite3
import hashlib
import threading
import uuid
from datetime import datetime, timedelta

DB_NAME = "finance.db"

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Return a per-thread SQLite connection (created lazily)."""
    if not hasattr(_local, "conn"):
        conn = sqlite3.connect(DB_NAME)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")
        _local.conn = conn
    return _local.conn


# ─── Helpers ────────────────────────────────────────────────────────────

def _hash_pin(pin: str) -> str:
    """SHA-256 hash a PIN string."""
    return hashlib.sha256(pin.encode()).hexdigest()


# ─── Schema ─────────────────────────────────────────────────────────────

def _init_tables():
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        note TEXT NOT NULL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        pin TEXT NOT NULL,
        currency TEXT DEFAULT 'USD',
        auto_logout_minutes INTEGER DEFAULT 30,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        limit_amount REAL NOT NULL,
        period TEXT DEFAULT 'monthly',
        UNIQUE(user_id, category)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS recurring (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT NOT NULL,
        frequency TEXT NOT NULL,
        next_run TIMESTAMP NOT NULL,
        active INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS shared_groups (
        group_id TEXT NOT NULL,
        invite_code TEXT UNIQUE,
        user_id INTEGER NOT NULL,
        role TEXT DEFAULT 'member',
        PRIMARY KEY (group_id, user_id)
    )
    """)

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions (user_id, date DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_user_cat ON transactions (user_id, category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_user ON notes (user_id, date DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_budgets_user ON budgets (user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recurring_next ON recurring (active, next_run)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shared_user ON shared_groups (user_id)")

    # Migrate: add new columns to existing users table if missing
    try:
        cur.execute("ALTER TABLE users ADD COLUMN currency TEXT DEFAULT 'USD'")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN auto_logout_minutes INTEGER DEFAULT 30")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    conn.commit()


_init_tables()


# ─── Users (PIN / Settings) ────────────────────────────────────────────

def set_pin(user_id: int, pin: str):
    conn = _get_conn()
    hashed = _hash_pin(pin)
    conn.execute(
        "INSERT INTO users (user_id, pin) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET pin = excluded.pin",
        (user_id, hashed),
    )
    conn.commit()


def verify_pin(user_id: int, pin: str) -> bool:
    cur = _get_conn().execute("SELECT pin FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        return False
    return row[0] == _hash_pin(pin)


def has_pin(user_id: int) -> bool:
    cur = _get_conn().execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    return cur.fetchone() is not None


def set_currency(user_id: int, currency: str):
    conn = _get_conn()
    conn.execute("UPDATE users SET currency = ? WHERE user_id = ?", (currency.upper(), user_id))
    conn.commit()


def get_currency(user_id: int) -> str:
    cur = _get_conn().execute("SELECT currency FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else "USD"


def update_last_active(user_id: int):
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()


def get_inactive_users(minutes: int = 30) -> list[int]:
    cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    cur = _get_conn().execute(
        "SELECT user_id FROM users WHERE last_active < ?", (cutoff,)
    )
    return [row[0] for row in cur.fetchall()]


# ─── Transactions ──────────────────────────────────────────────────────

def add_transaction(user_id: int, t_type: str, amount: float, category: str) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO transactions (user_id, type, amount, category) VALUES (?, ?, ?, ?)",
        (user_id, t_type, amount, category),
    )
    conn.commit()
    return cur.lastrowid


def delete_transaction(user_id: int, tx_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)
    )
    conn.commit()
    return cur.rowcount > 0


def edit_transaction(user_id: int, tx_id: int, field: str, value) -> bool:
    allowed = {"amount", "category", "type"}
    if field not in allowed:
        return False
    conn = _get_conn()
    cur = conn.execute(
        f"UPDATE transactions SET {field} = ? WHERE id = ? AND user_id = ?",
        (value, tx_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


def get_balance(user_id: int) -> float:
    cur = _get_conn().execute(
        "SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE -amount END), 0) "
        "FROM transactions WHERE user_id = ?",
        (user_id,),
    )
    return cur.fetchone()[0]


def get_summary(user_id: int, limit: int = 50) -> list:
    cur = _get_conn().execute(
        "SELECT id, type, amount, category, date "
        "FROM transactions WHERE user_id = ? "
        "ORDER BY date DESC LIMIT ?",
        (user_id, limit),
    )
    return cur.fetchall()


def get_transactions_filtered(user_id: int, start_date: str, end_date: str) -> list:
    cur = _get_conn().execute(
        "SELECT id, type, amount, category, date "
        "FROM transactions WHERE user_id = ? AND date BETWEEN ? AND ? "
        "ORDER BY date DESC",
        (user_id, start_date, end_date),
    )
    return cur.fetchall()


def get_category_totals(user_id: int, t_type: str = "expense",
                         start_date: str = None, end_date: str = None) -> list:
    """Return [(category, total), ...] sorted by total descending."""
    if start_date and end_date:
        cur = _get_conn().execute(
            "SELECT category, SUM(amount) FROM transactions "
            "WHERE user_id = ? AND type = ? AND date BETWEEN ? AND ? "
            "GROUP BY category ORDER BY SUM(amount) DESC",
            (user_id, t_type, start_date, end_date),
        )
    else:
        cur = _get_conn().execute(
            "SELECT category, SUM(amount) FROM transactions "
            "WHERE user_id = ? AND type = ? "
            "GROUP BY category ORDER BY SUM(amount) DESC",
            (user_id, t_type),
        )
    return cur.fetchall()


def get_monthly_totals(user_id: int, months: int = 6) -> list:
    """Return [(month_str, income_total, expense_total), ...] for the last N months."""
    cutoff = (datetime.utcnow() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    cur = _get_conn().execute(
        "SELECT strftime('%Y-%m', date) AS month, type, SUM(amount) "
        "FROM transactions WHERE user_id = ? AND date >= ? "
        "GROUP BY month, type ORDER BY month",
        (user_id, cutoff),
    )
    rows = cur.fetchall()
    monthly = {}
    for month, t_type, total in rows:
        if month not in monthly:
            monthly[month] = {"income": 0.0, "expense": 0.0}
        monthly[month][t_type] = total
    return [(m, d["income"], d["expense"]) for m, d in sorted(monthly.items())]


def get_all_transactions_for_export(user_id: int) -> list:
    cur = _get_conn().execute(
        "SELECT id, type, amount, category, date FROM transactions "
        "WHERE user_id = ? ORDER BY date DESC",
        (user_id,),
    )
    return cur.fetchall()


def get_today_transaction_count(user_id: int) -> int:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cur = _get_conn().execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND date >= ?",
        (user_id, today),
    )
    return cur.fetchone()[0]


def reset_balance(user_id: int):
    conn = _get_conn()
    conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    conn.commit()


# ─── Budgets ───────────────────────────────────────────────────────────

def set_budget(user_id: int, category: str, limit_amount: float, period: str = "monthly"):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO budgets (user_id, category, limit_amount, period) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, category) DO UPDATE SET limit_amount = excluded.limit_amount, period = excluded.period",
        (user_id, category.lower(), limit_amount, period),
    )
    conn.commit()


def get_budgets(user_id: int) -> list:
    cur = _get_conn().execute(
        "SELECT id, category, limit_amount, period FROM budgets WHERE user_id = ?", (user_id,)
    )
    return cur.fetchall()


def delete_budget(user_id: int, budget_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM budgets WHERE id = ? AND user_id = ?", (budget_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def check_budget_status(user_id: int, category: str) -> tuple | None:
    """Return (limit_amount, spent_this_month) or None if no budget set."""
    cur = _get_conn().execute(
        "SELECT limit_amount FROM budgets WHERE user_id = ? AND category = ?",
        (user_id, category.lower()),
    )
    row = cur.fetchone()
    if not row:
        return None
    limit_amount = row[0]
    # Current month spending
    month_start = datetime.utcnow().strftime("%Y-%m-01")
    cur2 = _get_conn().execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions "
        "WHERE user_id = ? AND type = 'expense' AND LOWER(category) = ? AND date >= ?",
        (user_id, category.lower(), month_start),
    )
    spent = cur2.fetchone()[0]
    return (limit_amount, spent)


# ─── Recurring ─────────────────────────────────────────────────────────

def add_recurring(user_id: int, t_type: str, amount: float, category: str, frequency: str) -> int:
    freq_days = {"daily": 1, "weekly": 7, "monthly": 30}
    days = freq_days.get(frequency, 30)
    next_run = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO recurring (user_id, type, amount, category, frequency, next_run) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, t_type, amount, category, frequency, next_run),
    )
    conn.commit()
    return cur.lastrowid


def get_recurring_list(user_id: int) -> list:
    cur = _get_conn().execute(
        "SELECT id, type, amount, category, frequency, next_run FROM recurring "
        "WHERE user_id = ? AND active = 1",
        (user_id,),
    )
    return cur.fetchall()


def delete_recurring(user_id: int, rec_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE recurring SET active = 0 WHERE id = ? AND user_id = ?", (rec_id, user_id)
    )
    conn.commit()
    return cur.rowcount > 0


def get_recurring_due() -> list:
    """Return all active recurring transactions that are due."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur = _get_conn().execute(
        "SELECT id, user_id, type, amount, category, frequency "
        "FROM recurring WHERE active = 1 AND next_run <= ?",
        (now,),
    )
    return cur.fetchall()


def mark_recurring_run(rec_id: int, frequency: str):
    freq_days = {"daily": 1, "weekly": 7, "monthly": 30}
    days = freq_days.get(frequency, 30)
    next_run = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn()
    conn.execute("UPDATE recurring SET next_run = ? WHERE id = ?", (next_run, rec_id))
    conn.commit()


# ─── Notes ─────────────────────────────────────────────────────────────

def add_note(user_id: int, text: str):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO notes (user_id, note) VALUES (?, ?)", (user_id, text)
    )
    conn.commit()


def get_notes(user_id: int, limit: int = 50) -> list:
    cur = _get_conn().execute(
        "SELECT note, date FROM notes WHERE user_id = ? ORDER BY date DESC LIMIT ?",
        (user_id, limit),
    )
    return cur.fetchall()


# ─── Shared Budgets ───────────────────────────────────────────────────

def create_shared_group(user_id: int) -> str:
    """Create a new shared group, return the invite code."""
    group_id = str(uuid.uuid4())[:8]
    invite_code = str(uuid.uuid4())[:6].upper()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO shared_groups (group_id, invite_code, user_id, role) VALUES (?, ?, ?, 'owner')",
        (group_id, invite_code, user_id),
    )
    conn.commit()
    return invite_code


def join_shared_group(user_id: int, invite_code: str) -> bool:
    cur = _get_conn().execute(
        "SELECT group_id FROM shared_groups WHERE invite_code = ?", (invite_code.upper(),)
    )
    row = cur.fetchone()
    if not row:
        return False
    group_id = row[0]
    # Check if already in group
    cur2 = _get_conn().execute(
        "SELECT 1 FROM shared_groups WHERE group_id = ? AND user_id = ?", (group_id, user_id)
    )
    if cur2.fetchone():
        return True  # already joined
    conn = _get_conn()
    conn.execute(
        "INSERT INTO shared_groups (group_id, invite_code, user_id, role) VALUES (?, NULL, ?, 'member')",
        (group_id, user_id),
    )
    conn.commit()
    return True


def get_shared_group_members(user_id: int) -> list[int]:
    """Return all user_ids in the same group as user_id."""
    cur = _get_conn().execute(
        "SELECT group_id FROM shared_groups WHERE user_id = ?", (user_id,)
    )
    row = cur.fetchone()
    if not row:
        return []
    group_id = row[0]
    cur2 = _get_conn().execute(
        "SELECT user_id FROM shared_groups WHERE group_id = ?", (group_id,)
    )
    return [r[0] for r in cur2.fetchall()]


def get_shared_balance(user_id: int) -> dict:
    """Return combined balance for all users in the shared group."""
    members = get_shared_group_members(user_id)
    if not members:
        return {}
    placeholders = ",".join("?" * len(members))
    cur = _get_conn().execute(
        f"SELECT user_id, "
        f"COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE -amount END), 0) "
        f"FROM transactions WHERE user_id IN ({placeholders}) GROUP BY user_id",
        members,
    )
    return {row[0]: row[1] for row in cur.fetchall()}
