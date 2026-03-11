import sqlite3
import json
from datetime import date, timedelta

DATABASE = "database.db"
COMPONENTS_FILE = "config/components.json"

def init_db():
    # -----------------------------
    # Load components from config
    # -----------------------------
    with open(COMPONENTS_FILE, "r") as f:
        components = json.load(f)

    component_list = list(components.keys())

    conn = sqlite3.connect(DATABASE)

    # Improve concurrency behavior
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")

    cursor = conn.cursor()

    # --------------------------------------------------
    # Tests table
    # --------------------------------------------------
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

    # --------------------------------------------------
    # Shift calendar table
    # --------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        shift TEXT NOT NULL,             -- morning / afternoon
        component_type TEXT NOT NULL,
        tester TEXT,
        UNIQUE(date, shift, component_type)
    )
    """)

    # --------------------------------------------------
    # Populate shifts
    # --------------------------------------------------
    today = date.today()

    start_date = date(today.year, 1, 1)
    end_date = date(today.year + 1, 12, 31)

    print(f"Populating shifts from {start_date} to {end_date}")

    current = start_date
    delta = timedelta(days=1)

    shifts_to_insert = []

    while current <= end_date:

        # Skip weekends
        if current.weekday() < 5:  # 0=Mon ... 4=Fri

            for comp in component_list:
                for shift in ["morning", "afternoon"]:

                    shifts_to_insert.append(
                        (current.isoformat(), shift, comp)
                    )

        current += delta

    cursor.executemany("""
        INSERT OR IGNORE INTO shifts (date, shift, component_type)
        VALUES (?, ?, ?)
    """, shifts_to_insert)

    conn.commit()
    conn.close()

    print("Database initialized successfully.")
    print(f"{len(shifts_to_insert)} shifts ensured.")
    print("Tables ensured: tests, shifts")
    print("WAL mode enabled.")
    print("Busy timeout set to 30 seconds.")


if __name__ == "__main__":
    init_db()
