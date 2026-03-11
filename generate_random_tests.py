import json
import sqlite3
import random
from datetime import datetime, timedelta

# -------------------------
# CONFIG FILES
# -------------------------
with open("config/components.json") as f:
    components_cfg = json.load(f)

with open("config/testers.json") as f:
    testers_cfg = json.load(f)
    # Convert to list of names in case some are dicts
    testers = [t if isinstance(t, str) else t["name"] for t in testers_cfg]

with open("config/failure_modes.json") as f:
    failure_modes_cfg = json.load(f)

# -------------------------
# DATABASE
# -------------------------
db_file = "database.db"
conn = sqlite3.connect(db_file)
cur = conn.cursor()

# -------------------------
# HELPER FUNCTIONS
# -------------------------
def existing_count(component):
    """Return the number of existing tests for a component."""
    cur.execute("SELECT COUNT(*) FROM tests WHERE component_type=?", (component,))
    return cur.fetchone()[0]

def random_serial():
    """Generate a random serial number (e.g., 8 alphanumeric chars)."""
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))

def random_status():
    return random.choice(["good", "bad", "under investigation"])

def random_failure(component):
    """Return a random failure mode for the component, or None."""
    modes = failure_modes_cfg.get(component, [])
    return random.choice(modes) if modes else None

# -------------------------
# GENERATE TESTS
# -------------------------
for comp, cfg in components_cfg.items():
    goal = cfg["goal"]
    count_existing = existing_count(comp)
    remaining = goal - count_existing
    if remaining <= 0:
        print(f"{comp}: already has {count_existing}/{goal}, skipping")
        continue

    print(f"{comp}: generating {remaining} random tests to reach goal {goal}")

    for _ in range(remaining):
        serial = random_serial()
        tester = random.choice(testers)
        status = random_status()
        failure = random_failure(comp) if status in ["bad", "under investigation"] else None
        timestamp = datetime.now() - timedelta(days=random.randint(0,30))  # random past 30 days

        cur.execute(
            "INSERT INTO tests (component_type, serial_number, tester, status, failure_mode, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (comp, serial, tester, status, failure, timestamp.isoformat())
        )

# Commit and close
conn.commit()
conn.close()

print("Random test generation complete.")
