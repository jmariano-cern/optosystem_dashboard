import json
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g
from datetime import datetime, timedelta, date
import matplotlib.colors as mcolors
from math import sqrt

database = "database.db"

# -------------------------
# LOAD CONFIG FILES
# -------------------------

with open("config/components.json") as f:
    components_cfg = json.load(f)

with open("config/testers.json") as f:
    testers_cfg = json.load(f)

# -------------------------
# COLOR HELPERS
# -------------------------

def lighten_color(hex_color, factor=0.5):
    rgb = mcolors.to_rgb(hex_color)
    lighter = tuple(min(1, c + (1 - c) * factor) for c in rgb)
    return mcolors.to_hex(lighter)

default_colors = [
    "#FF5733", "#33C1FF", "#33FF57", "#FFC300",
    "#C700FF", "#FF33A8", "#33FFF6", "#FF8C33"
]

# -------------------------
# PREPARE COMPONENT DATA
# -------------------------

# Prepare components
components = {}
failure_modes_cfg = {} # dumb hack
for i, comp in enumerate(components_cfg):
    cfg = components_cfg[comp]
    base_color = cfg.get("color") or default_colors[i % len(default_colors)]
    components[comp] = {
        "goal": cfg["goal"],
        "color": base_color,
        "light_color": lighten_color(base_color, 0.7),
        "failure_modes": cfg.get("failure_modes", []),
        "active": cfg.get("active", True)
    }
    failure_modes_cfg[comp] = cfg.get("failure_modes", [])

# -------------------------
# PREPARE TESTER DATA
# -------------------------

testers = {}

for i, (name, cfg) in enumerate(testers_cfg.items()):

    base_color = cfg.get("color") or default_colors[i % len(default_colors)]

    testers[name] = {
        "color": base_color,
        "light_color": lighten_color(base_color, 0.6)
    }

# -------------------------
# DATABASE HELPERS
# -------------------------

def get_db():
    db = sqlite3.connect(database, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    db = get_db()
    cur = db.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


# def execute_db(query, args=()):
#     db = get_db()
#     db.execute(query, args)
#     db.commit()


# -------------------------
# THROUGHPUT DASHBOARD
# -------------------------

today = date.today().isoformat()

# ------------------------------------------------------------------
# 1.  Fetch every completed, assigned shift before today.
#     One row per (date, shift, component_type, tester).
# ------------------------------------------------------------------
shift_rows = query_db("""
SELECT date, shift, component_type, tester
FROM   shifts
WHERE  tester IS NOT NULL
AND    date   <  ?
ORDER  BY tester, component_type, date, shift
""", (today,))

print("############")
print("## SHIFTS ##")
print("############")
for r in shift_rows:
    for col in r:
        print(col,end=" ")
    print()
    
# ------------------------------------------------------------------
# 2.  Fetch every test before today, keeping only the fields we need
#     to match against shifts.
#     We aggregate into a lookup keyed by (tester, comp, date, slot):
#         test_lookup[(tester, comp, date_str, 'morning'|'afternoon')]
#             = count of tests in that slot
# ------------------------------------------------------------------
test_rows = query_db("""
SELECT
tester,
component_type,
DATE(timestamp)                                   AS test_date,
CASE WHEN TIME(timestamp) < '12:45' THEN 'morning'
ELSE 'afternoon' END                         AS slot,
COUNT(*)                                          AS cnt
FROM   tests
WHERE  DATE(timestamp) < ?
GROUP  BY tester, component_type, test_date, slot
""", (today,))

print("###########")
print("## TESTS ##")
print("###########")
for r in test_rows:
    for col in r:
        print(col,end=" ")
    print()

# Build the lookup dict
test_lookup = {}
for r in test_rows:
    key = (r["tester"], r["component_type"], r["test_date"], r["slot"])
    test_lookup[key] = r["cnt"]
    
# ------------------------------------------------------------------
# 3.  For each (comp, tester) pair accumulate the per-shift vector.
#     Each shift contributes exactly one element (0 if no tests logged).
# ------------------------------------------------------------------

# vectors[comp][tester] = [int, int, ...]
vectors = {comp: {} for comp in components}

for r in shift_rows:
    comp   = r["component_type"]
    tester = r["tester"]
    key    = (tester, comp, r["date"], r["shift"])
    
    count = test_lookup.get(key, 0)
    
    vectors[comp].setdefault(tester, []).append(count)

print(json.dumps(vectors,indent=4))
# ------------------------------------------------------------------
# 4.  Compute sample mean and sample stdev from each vector.
#     throughput[comp][tester] = {"mean": float, "sd": float|None, "n": int}
# ------------------------------------------------------------------
throughput = {}

for comp in components:
    throughput[comp] = {}

    for tester, vec in vectors[comp].items():
        n    = len(vec)
        mean = sum(vec) / n

        if n >= 2:
            variance = sum((x - mean) ** 2 for x in vec) / (n - 1)
            sd = sqrt(variance)
        else:
            sd = None   # sample stdev undefined for a single observation
            
        throughput[comp][tester] = {
            "mean": round(mean, 3),
            "sd":   round(sd, 3) if sd is not None else None,
            "n":    n
        }

