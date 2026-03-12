import json
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g
from datetime import datetime, timedelta
import math
import matplotlib.colors as mcolors

app = Flask(__name__)

database = "database.db"

# -------------------------
# LOAD CONFIG FILES
# -------------------------

with open("config/components.json") as f:
    components_cfg = json.load(f)

with open("config/testers.json") as f:
    testers_cfg = json.load(f)

with open("config/failure_modes.json") as f:
    failure_modes_cfg = json.load(f)

# -------------------------
# PREPARE COLORS
# -------------------------

def lighten_color(hex_color, factor=0.5):
    """Return a lighter version of the hex color."""
    rgb = mcolors.to_rgb(hex_color)
    lighter = tuple(min(1, c + (1 - c) * factor) for c in rgb)
    return mcolors.to_hex(lighter)

# Assign base colors for components and testers if missing
default_colors = [
    "#FF5733", "#33C1FF", "#33FF57", "#FFC300",
    "#C700FF", "#FF33A8", "#33FFF6", "#FF8C33"
]

components = {}
for i, comp in enumerate(components_cfg):
    base_color = components_cfg[comp].get("color") or default_colors[i % len(default_colors)]
    components[comp] = {
        "goal": components_cfg[comp]["goal"],
        "color": base_color,
        "light_color": lighten_color(base_color, 0.6)
    }

testers = {}
for i, t in enumerate(testers_cfg):
    base_color = t.get("color") if isinstance(t, dict) else default_colors[i % len(default_colors)]
    testers_name = t if isinstance(t, str) else t["name"]
    testers[testers_name] = {
        "color": base_color,
        "light_color": lighten_color(base_color, 0.6)
    }

# -------------------------
# DATABASE HELPERS
# -------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            database,
            timeout=30,
            check_same_thread=False
        )
        g.db.row_factory = sqlite3.Row
    return g.db

def query_db(query, args=(), one=False):
    db = get_db()
    cur = db.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    db = get_db()
    db.execute(query, args)
    db.commit()

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()

# -------------------------
# HOME PAGE
# -------------------------

@app.route("/")
def index():
    summary = {}
    for comp in components:
        rows = query_db("SELECT * FROM tests WHERE component_type=?", (comp,))
        total = len(rows)
        good = sum(r["status"]=="good" for r in rows)
        bad = sum(r["status"]=="bad" for r in rows)
        under = sum(r["status"]=="under investigation" for r in rows)
        goal = components[comp]["goal"]
        progress = good / goal * 100 if goal else 0
        yield_estimate = good / total if total else 0  # <-- Add this line

        summary[comp] = {
            "total": total,
            "good": good,
            "bad": bad,
            "under": under,
            "progress": progress,
            "yield_estimate": yield_estimate  # <-- Include it here
        }
    return render_template("index.html", components=components, summary=summary)

# -------------------------
# SUBMIT PAGE
# -------------------------

@app.route("/submit", methods=["GET","POST"])
def submit():
    message = None
    if request.method == "POST":
        component = request.form["component"]
        serial = request.form["serial"]
        tester = request.form["tester"]
        status = request.form["status"]
        failure = request.form.get("failure_mode")
        timestamp = datetime.now().isoformat()

        existing = query_db(
            "SELECT id FROM tests WHERE component_type=? AND serial_number=?",
            (component, serial),
            one=True
        )
        if existing:
            message = f"ERROR: {component} with serial {serial} already exists."
        else:
            execute_db(
                "INSERT INTO tests (component_type, serial_number, tester, status, failure_mode, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (component, serial, tester, status, failure, timestamp)
            )
            message = f"{component} {serial} recorded successfully."

    return render_template(
        "submit.html",
        components=components,
        testers=testers,
        failures=failure_modes_cfg,
        message=message
    )

# -------------------------
# STATUS PAGE
# -------------------------

@app.route("/status/<component>")
def status(component):
    rows = query_db(
        "SELECT * FROM tests WHERE component_type=? ORDER BY timestamp",
        (component,)
    )
    total = len(rows)
    good = sum(r["status"]=="good" for r in rows)
    bad = sum(r["status"]=="bad" for r in rows)
    under = sum(r["status"]=="under investigation" for r in rows)
    goal = components_cfg[component]["goal"]
    progress = good / goal * 100 if goal else 0

    # Status counts for charts
    status_counts = {"good": good, "bad": bad, "under investigation": under}

    # Failure mode counts
    failure_counts = {}
    for r in rows:
        if r["status"] in ("bad","under investigation") and r["failure_mode"]:
            failure_counts[r["failure_mode"]] = failure_counts.get(r["failure_mode"], 0) + 1

    # Forecast
    if rows:
        first_ts = datetime.fromisoformat(rows[0]["timestamp"])
        last_ts = datetime.fromisoformat(rows[-1]["timestamp"])
    else:
        first_ts = last_ts = datetime.today()

    num_days = sum(
        1 for i in range((last_ts.date() - first_ts.date()).days + 1)
        if (first_ts.date() + timedelta(days=i)).weekday() < 5
    )
    avg_good_per_day = good / num_days if num_days else 0
    remaining_good = max(goal - good, 0)

    # Expected testing days until goal
    expected_testing_days = remaining_good / avg_good_per_day if avg_good_per_day > 0 else float("inf")

    # Predicted completion date (skip weekends)
    predicted_date = datetime.today()
    days_added = 0
    if avg_good_per_day > 0:
        while days_added < expected_testing_days:
            predicted_date += timedelta(days=1)
            if predicted_date.weekday() < 5:
                days_added += 1
        predicted_date = predicted_date.date()
    else:
        predicted_date = "NaN"

    forecast = {
        "total_good": good,
        "first_day": first_ts.date(),
        "num_days": num_days,
        "avg_good_per_day": avg_good_per_day,
        "remaining_good": remaining_good,
        "expected_testing_days": expected_testing_days,
        "predicted_completion_date": predicted_date
    }

    # Recent tests
    recent_tests = [dict(r) for r in rows[-20:][::-1]]

    # Prepare component_colors dict with 'base' key for template
    component_colors = {}
    default_colors = [
        "#FF5733", "#33C1FF", "#33FF57", "#FFC300",
        "#C700FF", "#FF33A8", "#33FFF6", "#FF8C33"
    ]
    for i, comp in enumerate(components_cfg):
        base = components_cfg[comp].get("color") or default_colors[i % len(default_colors)]
        component_colors[comp] = {"base": base, "light": lighten_color(base, 0.6)}

    # Prepare tester_colors dict mapping tester -> color
    tester_colors = {}
    for i, t in enumerate(testers_cfg):
        base = default_colors[i % len(default_colors)]
        tester_colors[t] = base

    return render_template(
        "status.html",
        component=component,
        goal=goal,
        progress=progress,
        status_counts=status_counts,
        failure_mode_counts=failure_counts,
        history_dates=[datetime.fromisoformat(r["timestamp"]).date().isoformat() for r in rows],
        history_good=[sum(1 for x in rows[:i+1] if x["status"]=="good") for i in range(len(rows))],
        history_bad=[sum(1 for x in rows[:i+1] if x["status"]=="bad") for i in range(len(rows))],
        history_under=[sum(1 for x in rows[:i+1] if x["status"]=="under investigation") for i in range(len(rows))],
        recent_tests=recent_tests,
        forecast=forecast,
        component_colors=component_colors,
        tester_colors=tester_colors
    )

# -------------------------
# LIST COMPONENT TESTS
# -------------------------

@app.route("/list/<component>", endpoint="list_component")
def list_component(component):
    rows = query_db("SELECT * FROM tests WHERE component_type=? ORDER BY timestamp DESC", (component,))
    return render_template(
        "list_component.html",
        component=component,
        rows=[dict(r) for r in rows],
        testers=testers,
        failure_modes=failure_modes_cfg.get(component, [])
    )

# -------------------------
# UPDATE / DELETE TESTS
# -------------------------

@app.route("/update_test/<int:test_id>", methods=["POST"])
def update_test(test_id):
    serial = request.form["serial"]
    status = request.form["status"]
    tester = request.form["tester"]
    failure_mode = request.form.get("failure_mode")
    execute_db(
        "UPDATE tests SET serial_number=?, status=?, tester=?, failure_mode=? WHERE id=?",
        (serial, status, tester, failure_mode, test_id)
    )
    row = query_db("SELECT component_type FROM tests WHERE id=?", (test_id,), one=True)
    component = row["component_type"] if row else "Unknown"
    return redirect(url_for("list_component", component=component, message=f"Updated test {test_id}"))

@app.route("/delete_test/<int:test_id>", methods=["POST"])
def delete_test(test_id):
    row = query_db("SELECT component_type FROM tests WHERE id=?", (test_id,), one=True)
    component = row["component_type"] if row else "Unknown"
    execute_db("DELETE FROM tests WHERE id=?", (test_id,))
    return redirect(url_for("list_component", component=component, message=f"Deleted test {test_id}"))

# -------------------------
# TESTER DASHBOARD
# -------------------------

@app.route("/tester_dashboard")
def tester_dashboard():
    tester_summary = {}
    for comp in components:
        rows = query_db("SELECT tester FROM tests WHERE component_type=?", (comp,))
        counts = {}
        for r in rows:
            t = r["tester"] or "Unknown"
            counts[t] = counts.get(t,0) + 1
        tester_summary[comp] = counts

    rows = query_db("SELECT tester, component_type FROM tests")
    tester_component_counts = {}
    for r in rows:
        t = r["tester"] or "Unknown"
        comp = r["component_type"]
        if t not in tester_component_counts:
            tester_component_counts[t] = {c:0 for c in components}
        tester_component_counts[t][comp] += 1

    # Prepare component_colors dict with 'base' key for template                                                                               
    component_colors = {}
    default_colors = [
	"#FF5733", "#33C1FF", "#33FF57", "#FFC300",
	"#C700FF", "#FF33A8", "#33FFF6", "#FF8C33"
    ]
    for i, comp in enumerate(components_cfg):
        base = components_cfg[comp].get("color") or default_colors[i % len(default_colors)]
        component_colors[comp] = {"base": base, "light": lighten_color(base, 0.6)}

    # Prepare tester_colors dict mapping tester -> color                                                                                       
    tester_colors = {}
    for i, t in enumerate(testers_cfg):
        base = default_colors[i % len(default_colors)]
        tester_colors[t] = base
        
    return render_template(
        "tester_dashboard.html",
        tester_summary=tester_summary,
        tester_component_counts=tester_component_counts,
        components=components,
        tester_colors=tester_colors,
        component_colors=component_colors
    )

# -------------------------
# RUN SERVER
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
