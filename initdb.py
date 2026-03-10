import sqlite3

DATABASE = "database.db"

def init_db():
    conn = sqlite3.connect(DATABASE)

    # Improve concurrency behavior
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")  # wait up to 30 seconds for locks

    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component_type TEXT NOT NULL,
        serial_number TEXT NOT NULL,
        tester TEXT NOT NULL,
        status TEXT NOT NULL,
        failure_mode TEXT,
        timestamp TEXT NOT NULL,
        UNIQUE(component_type, serial_number)
    )
    """)

    conn.commit()
    conn.close()

    print("Database initialized successfully.")
    print("WAL mode enabled.")
    print("Busy timeout set to 30 seconds.")


if __name__ == "__main__":
    init_db()
