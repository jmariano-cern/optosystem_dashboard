import sqlite3

conn = sqlite3.connect("database.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_type TEXT NOT NULL,
    serial_number TEXT NOT NULL,
    tester TEXT NOT NULL,
    status TEXT NOT NULL,
    failure_mode TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()
conn.close()
