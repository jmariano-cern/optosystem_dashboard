import json
import sqlite3
import random
from datetime import datetime, timedelta, date

# -------------------------
# CONFIG FILES
# -------------------------
with open("config/components.json") as f:
    components_cfg = json.load(f)

with open("config/testers.json") as f:
    testers_cfg = json.load(f)

with open("config/failure_modes.json") as f:
    failure_modes_cfg = json.load(f)

# Normalize tester names
testers = [t if isinstance(t, str) else t["name"] for t in testers_cfg]

# -------------------------
# DATABASE
# -------------------------
conn = sqlite3.connect("database.db")
cur = conn.cursor()

# -------------------------
# HELPERS
# -------------------------
def existing_count(component):
    cur.execute("SELECT COUNT(*) FROM tests WHERE component_type=?", (component,))
    return cur.fetchone()[0]


def existing_serials(component):
    cur.execute("SELECT serial_number FROM tests WHERE component_type=?", (component,))
    return {r[0] for r in cur.fetchall()}


def random_serial(existing):
    while True:
        s = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
        if s not in existing:
            existing.add(s)
            return s


def random_status():
    return random.choices(
        ["good", "bad", "under investigation"],
        weights=[0.75, 0.2, 0.05]
    )[0]


def random_failure(component):
    modes = failure_modes_cfg.get(component, [])
    if not modes:
        return None
    return random.choice(modes)

# -------------------------
# GENERATE TESTS
# -------------------------
start_date = datetime.today() - timedelta(days=120)  # ~4 months history
today = datetime.today()

for comp, cfg in components_cfg.items():
    goal = cfg["goal"]
    count_existing = existing_count(comp)
    remaining = goal - count_existing
    if remaining <= 0:
        print(f"{comp}: already at goal ({count_existing}/{goal})")
        continue

    serials = existing_serials(comp)
    print(f"{comp}: generating {remaining} tests")

    current_day = start_date
    generated = 0

    while generated < remaining and current_day <= today:
        if current_day.weekday() >= 5:  # skip weekends
            current_day += timedelta(days=1)
            continue

        tests_today = random.randint(1, 6)
        for _ in range(tests_today):
            if generated >= remaining:
                break

            serial = random_serial(serials)
            tester = random.choice(testers)
            status = random_status()
            failure = random_failure(comp) if status in ["bad", "under investigation"] else None
            timestamp = current_day + timedelta(
                hours=random.randint(8, 17),
                minutes=random.randint(0, 59)
            )

            cur.execute(
                "INSERT INTO tests (component_type, serial_number, tester, status, failure_mode, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (comp, serial, tester, status, failure, timestamp.isoformat())
            )
            generated += 1

        current_day += timedelta(days=1)

conn.commit()
print("Random tests generated.")

# -------------------------
# GENERATE SHIFTS
# -------------------------
today_date = date.today()
year_start = date(today_date.year, 1, 1)
year_end = date(today_date.year + 1, 12, 31)

current_day = year_start
shifts_to_insert = []

while current_day <= year_end:
    if current_day.weekday() < 5:  # Mon-Fri
        for comp in components_cfg:
            for shift in ["morning", "afternoon"]:
                # Assign a tester 70% of the time
                tester = random.choice(testers) if random.random() < 0.7 else None
                shifts_to_insert.append((current_day.isoformat(), shift, comp, tester))
    current_day += timedelta(days=1)

cur.executemany("""
    INSERT OR REPLACE INTO shifts (date, shift, component_type, tester)
    VALUES (?, ?, ?, ?)
""", shifts_to_insert)
conn.commit()
conn.close()

print("Random shifts generated.")
