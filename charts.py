"""
Generate charts for finance data using matplotlib.
Returns BytesIO buffers containing PNG images.
"""
import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend (no GUI needed)
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

import db

# ─── Theme ──────────────────────────────────────────────────────────────

DARK_BG = "#1a1a2e"
CARD_BG = "#16213e"
TEXT_COLOR = "#e0e0e0"
ACCENT_COLORS = [
    "#e94560", "#0f3460", "#533483", "#48c9b0",
    "#f39c12", "#3498db", "#e74c3c", "#2ecc71",
    "#9b59b6", "#1abc9c", "#e67e22", "#34495e",
]

plt.rcParams.update({
    "figure.facecolor": DARK_BG,
    "axes.facecolor": CARD_BG,
    "axes.edgecolor": TEXT_COLOR,
    "text.color": TEXT_COLOR,
    "xtick.color": TEXT_COLOR,
    "ytick.color": TEXT_COLOR,
    "axes.labelcolor": TEXT_COLOR,
    "font.size": 12,
    "font.family": "sans-serif",
})


# ─── Pie Chart: Expenses by Category ───────────────────────────────────

def expense_pie_chart(user_id: int, start_date: str = None, end_date: str = None) -> io.BytesIO | None:
    """Generate a pie chart of expenses grouped by category. Returns PNG BytesIO or None."""
    rows = db.get_category_totals(user_id, "expense", start_date, end_date)
    if not rows:
        return None

    categories = [r[0] or "Uncategorized" for r in rows]
    amounts = [r[1] for r in rows]
    colors = ACCENT_COLORS[: len(categories)]

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        amounts,
        labels=categories,
        colors=colors,
        autopct="%1.1f%%",
        startangle=140,
        pctdistance=0.8,
        wedgeprops={"edgecolor": DARK_BG, "linewidth": 2},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontsize(10)
    for t in texts:
        t.set_fontsize(11)

    total = sum(amounts)
    currency = db.get_currency(user_id)
    ax.set_title(f"Expenses by Category — Total: {total:,.2f} {currency}", fontsize=14, pad=20)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


# ─── Bar Chart: Income vs Expense Over Time ────────────────────────────

def income_vs_expense_bar(user_id: int, months: int = 6) -> io.BytesIO | None:
    """Generate a grouped bar chart of income vs expense per month. Returns PNG BytesIO or None."""
    data = db.get_monthly_totals(user_id, months)
    if not data:
        return None

    month_labels = [d[0] for d in data]
    incomes = [d[1] for d in data]
    expenses = [d[2] for d in data]

    x = range(len(month_labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 5))
    bars1 = ax.bar([i - width / 2 for i in x], incomes, width, label="Income", color="#2ecc71")
    bars2 = ax.bar([i + width / 2 for i in x], expenses, width, label="Expense", color="#e94560")

    ax.set_xlabel("Month")
    ax.set_ylabel("Amount")
    currency = db.get_currency(user_id)
    ax.set_title(f"Income vs Expense ({currency})", fontsize=14, pad=15)
    ax.set_xticks(list(x))
    ax.set_xticklabels(month_labels, rotation=45, ha="right")
    ax.legend()
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    # Value labels on bars
    for bar in bars1 + bars2:
        h = bar.get_height()
        if h > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2, h,
                f"{h:,.0f}", ha="center", va="bottom", fontsize=8, color=TEXT_COLOR,
            )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
