import sqlite3

conn = sqlite3.connect("finance.db")
cursor = conn.cursor()

# Add user_id column if it doesn't exist
cursor.execute("ALTER TABLE transactions ADD COLUMN user_id INTEGER DEFAULT 0")

conn.commit()
conn.close()

print("user_id column added.")
