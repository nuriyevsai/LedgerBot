# Telegram Personal Finance Bot 💰

A powerful, feature-rich personal finance tracker built entirely within Telegram. It acts as your personal accountant with natural language processing, visual charts, recurring transactions, and tight security.

## ✨ Features

- **🗣️ Natural Language Processing:** Just text `"spent 50 on coffee"` and it parses the amount, category, and type automatically.
- **📊 Visual Charts & Reports:** Request beautiful pie and bar charts (`/chart`) and detailed monthly category reports.
- **🛡️ Secure PIN & Session:** Your account is protected by an encrypted (SHA-256) 4-digit PIN with an auto-logout timeout.
- **👥 Shared Budgets:** Generate an invite code (`/share`) and let your partner join (`/join`) to track collective group expenses.
- **💱 Live Currency Conversion:** Support for multi-currency display (`/currency`) and live conversions (`/convert`).
- **🔄 Recurring Transactions:** Automate your rent or salary to trigger daily, weekly, or monthly.
- **🚨 Budgets & Alerts:** Set category limits (e.g. `$500 for groceries`) and get proactive warnings when you hit 80% and 100%.
- **📅 Daily Reminders:** Never forget to track! The bot checks if you logged expenses by 8:00 PM and gently reminds you if not.
- **📤 Export & Backup:** Completely own your data. Export to CSV (`/export`) or download the full SQLite database (`/backup`).

## 🚀 Setup & Installation

### Requirements
- Python 3.10+
- A Telegram Bot Token from [@BotFather](https://t.me/botfather)

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/tgbot-finance.git
cd tgbot-finance
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Add Your Bot Token
Open `config.py` and replace `YOUR_TELEGRAM_BOT_TOKEN_HERE` with your actual bot token, or simply set it as an environment variable:
```bash
# Windows
set BOT_TOKEN=your_token_here
# Linux/Mac
export BOT_TOKEN=your_token_here
```

### 4. Run the Bot
```bash
python bot.py
```
*Note: The SQLite database (`finance.db`) will be automatically generated on the first run.*

## 💻 Tech Stack
- `python-telegram-bot` (JobQueues, Handlers, Conversations)
- `sqlite3` (Thread-safe, WAL journal mode enabled, optimized indexing)
- `matplotlib` (Headless chart generation via Agg backend)
- `requests` (Live exchange rate API fetching)

## 🗂️ Project Structure
- `bot.py`: Main Telegram interface & command routing.
- `db.py`: Optimized SQLite layer with indexes and thread-safe connections.
- `scheduler.py`: Background tasks (recurring, auto-logout, reminders).
- `charts.py`: Graph generation for data visualization.
- `nlp.py`: Natural language string parser using regex.
- `config.py`: Configuration and variables.
