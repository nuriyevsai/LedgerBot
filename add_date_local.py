import sqlite3

# Connect to your local database
conn = sqlite3.connect("finance.db")
cursor = conn.cursor()

# Step 1: Rename the old table
cursor.execute("ALTER TABLE transactions RENAME TO old_transactions")

# Step 2: Create a new table with the date column
cursor.execute("""
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT,
    amount REAL,
    category TEXT,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Step 3: Copy old data into the new table (date will get current timestamp)
cursor.execute("""
INSERT INTO transactions (id, type, amount, category)
SELECT id, type, amount, category FROM old_transactions
""")

# Step 4: Delete the old table
cursor.execute("DROP TABLE old_transactions")

conn.commit()
conn.close()

print("Database updated successfully. 'date' column added.")
