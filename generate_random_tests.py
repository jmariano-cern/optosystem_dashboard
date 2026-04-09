import json
import sqlite3
import random
import math
from datetime import datetime, timedelta, date, time
from collections import defaultdict

# =============================================================================
# TUNING PARAMETERS  ← adjust these to change the output characteristics
# =============================================================================

TARGET_FILL         = 0.75   # target fraction of each component's goal to reach
                             # e.g. 0.75 → ~75 % of goal tested

LAMBDA_MEAN         = 8.0    # centre of the per-component lambda distribution
LAMBDA_STDEV        = 1.5    # spread; each component draws one lambda at startup
                             # (Normal truncated at 1 so lambdas stay positive)

TESTER_ASSIGN_RATE  = 0.70   # fraction of past shifts that have an assigned tester

# =============================================================================
# NOTE: this script only inserts past shifts (date < today) and their tests.
# Future shifts are handled by initdb.py which populates the full calendar.
# =============================================================================

# -------------------------
# CONFIG FILES
# -------------------------
with open("config/components.json") as f:
    components_cfg = json.load(f)

with open("config/testers.json") as f:
    testers_cfg = json.load(f)

testers = list(testers_cfg.keys())

# -------------------------
# DATABASE
# -------------------------
conn = sqlite3.connect("database.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# -------------------------
# WIPE EXISTING DATA
# -------------------------
# cur.execute("DELETE FROM tests")
# cur.execute("DELETE FROM shifts")
# conn.commit()
# print("Cleared existing tests and shifts.")

# -------------------------
# HELPERS
# -------------------------
used_serials = {comp: set() for comp in components_cfg}

def random_serial(comp):
    existing = used_serials[comp]
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
    modes = components_cfg[component].get("failure_modes", [])
    return random.choice(modes) if modes else None

def random_time_in_slot(shift):
    """Return a random time within morning (08:00–12:44) or afternoon (12:45–17:30)."""
    if shift == "morning":
        lo, hi = 8 * 60, 12 * 60 + 44
    else:
        lo, hi = 12 * 60 + 45, 17 * 60 + 30
    m = random.randint(lo, hi)
    return time(m // 60, m % 60)

def poisson_sample(lam):
    """Knuth's algorithm for Poisson(lam)."""
    L = math.exp(-lam)
    k, p = 0, 1.0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1

def sample_lambda():
    """Draw one lambda from Normal(LAMBDA_MEAN, LAMBDA_STDEV), truncated at 1."""
    while True:
        lam = random.gauss(LAMBDA_MEAN, LAMBDA_STDEV)
        if lam >= 1.0:
            return lam

def start_date_for_n_shifts(n_shifts_needed, today):
    """
    Walk backwards from today to find the start date that yields approximately
    n_shifts_needed past assigned shifts.

    E[assigned shifts per weekday] = 2 slots × TESTER_ASSIGN_RATE
    → weekdays_needed = ceil(n_shifts_needed / (2 × TESTER_ASSIGN_RATE))
    """
    weekdays_needed = math.ceil(n_shifts_needed / (2 * TESTER_ASSIGN_RATE))
    d = today - timedelta(days=1)
    counted = 0
    while counted < weekdays_needed:
        if d.weekday() < 5:
            counted += 1
        d -= timedelta(days=1)
    return d + timedelta(days=1)

# -------------------------
# ACTIVE COMPONENTS
# -------------------------
active_components = [c for c, cfg in components_cfg.items() if cfg.get("active", True)]

today_date = date.today()

# -------------------------
# PER-COMPONENT SETUP
# -------------------------
comp_lambda     = {}
comp_start_date = {}

print(f"\n{'Component':20s}  {'goal':>5}  {'lambda':>6}  "
      f"{'target':>7}  {'shifts_needed':>13}  {'history_start'}")
print("-" * 80)

for comp in active_components:
    goal   = components_cfg[comp]["goal"]
    lam    = sample_lambda()
    target = TARGET_FILL * goal

    n_shifts_needed = target / lam

    start = start_date_for_n_shifts(n_shifts_needed, today_date)
    
    comp_lambda[comp]     = lam
    comp_start_date[comp] = start

    print(f"{comp:20s}  {goal:5d}  {lam:6.2f}  "
          f"{target:7.0f}  {n_shifts_needed:13.1f}  {start}")

global_start = min(comp_start_date.values())
year_end     = date(today_date.year + 1, 12, 31)

# -------------------------
# GENERATE SHIFTS AND TESTS
# -------------------------
# Shifts are inserted for the full window (past + today + future) to populate
# the shift calendar for planning purposes.
# Tests are only generated for strictly past shifts (date < today).
# The tests/shift summary counts only past shifts as the denominator.
shifts_to_insert    = []
tests_to_insert     = []
past_shifts_by_comp = defaultdict(int)
tests_by_comp       = defaultdict(int)

current_day = global_start

while current_day <= year_end:
    
    if current_day.weekday() >= 5:
        current_day += timedelta(days=1)
        continue

    is_past = current_day < today_date

    for comp in active_components:
        
        if current_day < comp_start_date[comp]:
            continue

        lam = comp_lambda[comp]

        for shift in ["morning", "afternoon"]:

            if random.random() >= TESTER_ASSIGN_RATE:
                continue

            tester = random.choice(testers)

            shifts_to_insert.append(
                (current_day.isoformat(), shift, comp, tester)
            )

            if not is_past:
                continue

            past_shifts_by_comp[comp] += 1

            n_tests = poisson_sample(lam)
            tests_by_comp[comp] += n_tests

            for _ in range(n_tests):
                t  = random_time_in_slot(shift)
                ts = datetime.combine(current_day, t)

                status  = random_status()
                failure = random_failure(comp) if status in ("bad", "under investigation") else None
                serial  = random_serial(comp)
                
                tests_to_insert.append(
                    (comp, serial, tester, status, failure, ts.isoformat())
                )                
    current_day += timedelta(days=1)

# -------------------------
# COMMIT
# -------------------------
cur.executemany("""
    INSERT OR REPLACE INTO shifts (date, shift, component_type, tester)
    VALUES (?, ?, ?, ?)
""", shifts_to_insert)

cur.executemany("""
    INSERT INTO tests (component_type, serial_number, tester, status, failure_mode, timestamp)
    VALUES (?, ?, ?, ?, ?, ?)
""", tests_to_insert)

conn.commit()
conn.close()

# -------------------------
# SUMMARY  (past shifts only in denominator)
# -------------------------
total_past_shifts = sum(past_shifts_by_comp.values())
total_shifts      = len(shifts_to_insert)
total_tests       = sum(tests_by_comp.values())

print(f"\nTotal shifts inserted : {total_shifts}  "
      f"({total_past_shifts} past + {total_shifts - total_past_shifts} future/today)")
print(f"Total tests  inserted : {total_tests}")
print(f"Tests / past shift    : {total_tests / total_past_shifts:.2f}  "
      f"(target ≈ {LAMBDA_MEAN})\n")

print(f"{'Component':20s}  {'past_sh':>7}  {'tests':>6}  "
      f"{'t/s':>5}  {'goal':>5}  {'fill':>5}")
print("-" * 58)
for comp in active_components:
    goal  = components_cfg[comp]["goal"]
    sh    = past_shifts_by_comp[comp]
    te    = tests_by_comp[comp]
    ratio = te / sh if sh else 0
    print(f"{comp:20s}  {sh:7d}  {te:6d}  "
          f"{ratio:5.2f}  {goal:5d}  {100*te/goal:4.0f}%")

print("\nDone.")
