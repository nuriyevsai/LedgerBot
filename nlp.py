"""
Simple regex-based natural language parser for finance transactions.
No external NLP libraries needed.
"""
import re
from dataclasses import dataclass


@dataclass
class ParsedTransaction:
    type: str       # "income" or "expense"
    amount: float
    category: str


# Patterns: each is (regex, type)
_EXPENSE_PATTERNS = [
    # "spent 50 on food"  /  "spent 50.5 on coffee"
    r"spent\s+(\d+(?:\.\d+)?)\s+(?:on\s+)?(.+)",
    # "paid 200 for electricity"
    r"paid\s+(\d+(?:\.\d+)?)\s+(?:for\s+)?(.+)",
    # "bought food for 30" / "bought coffee 5"
    r"bought\s+(.+?)\s+(?:for\s+)?(\d+(?:\.\d+)?)",
    # "50 on food" / "50 food"
    r"(\d+(?:\.\d+)?)\s+(?:on\s+)?(?:for\s+)?(.+)",
]

_INCOME_PATTERNS = [
    # "earned 5000 salary" / "earned 5000 from salary"
    r"earned\s+(\d+(?:\.\d+)?)\s+(?:from\s+)?(.+)",
    # "got 200 from freelance"
    r"got\s+(\d+(?:\.\d+)?)\s+(?:from\s+)?(.+)",
    # "received 1000 bonus"
    r"received\s+(\d+(?:\.\d+)?)\s+(?:from\s+)?(.+)",
    # "income 3000 salary"
    r"income\s+(\d+(?:\.\d+)?)\s+(.+)",
]

# Patterns where amount and category are swapped (category first)
_EXPENSE_SWAPPED = [
    r"bought\s+(.+?)\s+(?:for\s+)?(\d+(?:\.\d+)?)",
]


def parse(text: str) -> ParsedTransaction | None:
    """
    Try to extract a transaction from natural language text.
    Returns ParsedTransaction or None if no match.
    """
    text = text.strip().lower()
    if not text or len(text) < 3:
        return None

    # Try income patterns first (more specific keywords)
    for pattern in _INCOME_PATTERNS:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            amount = float(m.group(1))
            category = m.group(2).strip()
            if category and amount > 0:
                return ParsedTransaction("income", amount, category)

    # Try expense patterns with swapped groups (category, amount)
    for pattern in _EXPENSE_SWAPPED:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            category = m.group(1).strip()
            amount = float(m.group(2))
            if category and amount > 0:
                return ParsedTransaction("expense", amount, category)

    # Try expense patterns (amount, category)
    for pattern in _EXPENSE_PATTERNS:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            try:
                amount = float(m.group(1))
                category = m.group(2).strip()
            except ValueError:
                continue
            if category and amount > 0:
                return ParsedTransaction("expense", amount, category)

    return None
