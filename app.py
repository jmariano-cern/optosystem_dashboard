import json
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g
from datetime import datetime, timedelta, date
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

# testers = {}

# for i, t in enumerate(testers_cfg):

#     if isinstance(t, dict):
#         name = t["name"]
#         base_color = t.get("color") or default_colors[i % len(default_colors)]
#     else:
#         name = t
#         base_color = default_colors[i % len(default_colors)]

#     testers[name] = {
#         "color": base_color,
#         "light_color": lighten_color(base_color, 0.6)
#     }

# -------------------------
# CONTEXT PROCESSOR
# -------------------------

@app.context_processor
def inject_color_maps():

    component_colors = {
        c: {
            "base": components[c]["color"],
            "light": components[c]["light_color"]
        }
        for c in components
    }

    tester_colors = {
        t: testers[t]["color"]
        for t in testers
    }

    return dict(
        component_colors=component_colors,
        tester_colors=tester_colors
    )

# -------------------------
# DATABASE HELPERS
# -------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(database, timeout=30, check_same_thread=False)
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

    return render_template(
        "index.html"
    )

# -------------------------
# HOME PAGE
# -------------------------

@app.route("/component_dashboard")
def component_dashboard():

    summary = {}

    for comp in components:

        rows = query_db(
            "SELECT * FROM tests WHERE component_type=?",
            (comp,)
        )

        total = len(rows)
        good = sum(r["status"] == "good" for r in rows)
        bad = sum(r["status"] == "bad" for r in rows)
        under = sum(r["status"] == "under investigation" for r in rows)

        goal = components[comp]["goal"]

        progress = 100.0 * (good / goal) if goal else 0
        yield_estimate = good / total if total else 0

        summary[comp] = {
            "total": total,
            "good": good,
            "bad": bad,
            "under": under,
            "progress": progress,
            "yield_estimate": yield_estimate,
            "goal": goal
        }

    return render_template(
        "component_dashboard.html",
        components=components,
        summary=summary
    )

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
    good = sum(r["status"] == "good" for r in rows)
    bad = sum(r["status"] == "bad" for r in rows)
    under = sum(r["status"] == "under investigation" for r in rows)

    goal = components[component]["goal"]

    progress = good / goal * 100 if goal else 0

    status_counts = {
        "good": good,
        "bad": bad,
        "under investigation": under
    }

    failure_counts = {}

    for r in rows:
        if r["status"] in ("bad", "under investigation") and r["failure_mode"]:
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

    expected_testing_days = remaining_good / avg_good_per_day if avg_good_per_day > 0 else float("inf")

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

    recent_tests = [dict(r) for r in rows[-20:][::-1]]

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
        forecast=forecast
    )

# -------------------------
# LIST COMPONENT TESTS
# -------------------------

@app.route("/list/<component>", endpoint="list_component")
def list_component(component):

    rows = query_db(
        "SELECT * FROM tests WHERE component_type=? ORDER BY timestamp DESC",
        (component,)
    )

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

    row = query_db(
        "SELECT component_type FROM tests WHERE id=?",
        (test_id,),
        one=True
    )

    component = row["component_type"] if row else "Unknown"

    return redirect(
        url_for("list_component", component=component)
    )


@app.route("/delete_test/<int:test_id>", methods=["POST"])
def delete_test(test_id):

    row = query_db(
        "SELECT component_type FROM tests WHERE id=?",
        (test_id,),
        one=True
    )

    component = row["component_type"] if row else "Unknown"

    execute_db(
        "DELETE FROM tests WHERE id=?",
        (test_id,)
    )

    return redirect(
        url_for("list_component", component=component)
    )

# -------------------------
# TESTER DASHBOARD
# -------------------------

@app.route("/tester_dashboard")
def tester_dashboard():

    tester_summary = {}

    for comp in components:

        rows = query_db(
            "SELECT tester FROM tests WHERE component_type=?",
            (comp,)
        )

        counts = {}

        for r in rows:
            t = r["tester"] or "Unknown"
            counts[t] = counts.get(t, 0) + 1

        tester_summary[comp] = counts

    # ------------------------------------
    # Tests per tester per component
    # ------------------------------------

    rows = query_db("SELECT tester, component_type FROM tests")

    tester_component_counts = {}

    for r in rows:

        t = r["tester"] or "Unknown"
        comp = r["component_type"]

        if t not in tester_component_counts:
            tester_component_counts[t] = {c: 0 for c in components}

        tester_component_counts[t][comp] += 1

    # ------------------------------------
    # NEW: Shifts per tester per component
    # ------------------------------------

    today = date.today().isoformat()
    
    rows = query_db("""
    SELECT tester, component_type
    FROM shifts
    WHERE tester IS NOT NULL
    AND date <= ?
    """, (today,))
    
    # rows = query_db("""
    #     SELECT tester, component_type
    #     FROM shifts
    #     WHERE tester IS NOT NULL
    # """)

    tester_shift_counts = {}

    for r in rows:

        t = r["tester"]
        comp = r["component_type"]

        if t not in tester_shift_counts:
            tester_shift_counts[t] = {c: 0 for c in components}

        tester_shift_counts[t][comp] += 1

    return render_template(
        "tester_dashboard.html",
        tester_summary=tester_summary,
        tester_component_counts=tester_component_counts,
        tester_shift_counts=tester_shift_counts,
        components=components
    )

# -------------------------
# CALENDAR
# -------------------------

@app.route("/calendar")
def calendar_page():
    today = datetime.today().date()
    week_offset = int(request.args.get("week", 0))

    # Find Sunday of current week
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    start_of_week = this_sunday + timedelta(days=7 * week_offset)
    days = [start_of_week + timedelta(days=i) for i in range(7)]

    # Query shifts for this week
    rows = query_db(
        "SELECT * FROM shifts WHERE date BETWEEN ? AND ? ORDER BY date, shift, component_type",
        (days[0].isoformat(), days[-1].isoformat())
    )

    # Initialize calendar dict
    calendar = {}
    for d in days:
        calendar[d] = {"morning": [], "afternoon": []}

    for r in rows:
        d = datetime.fromisoformat(r["date"]).date()
        calendar[d][r["shift"]].append({
            "component": r["component_type"],
            "tester": r["tester"],
            "id": r["id"]
        })

    # Component colors for calendar: taken = base, open = lighter
    component_colors = {
        comp: {
            "taken": components[comp]["color"],
            "open": components[comp]["light_color"]
        } for comp in components
    }

    return render_template(
        "calendar.html",
        calendar=calendar,
        days=days,
        today=today,
        components=components,
        component_colors=component_colors,
        week_offset=week_offset
    )

@app.route("/shift/<int:shift_id>", methods=["GET", "POST"])
def edit_shift(shift_id):
    row = query_db("SELECT * FROM shifts WHERE id=?", (shift_id,), one=True)

    if request.method == "POST":
        tester = request.form.get("tester", "").strip() or None

        if row:
            execute_db(
                "UPDATE shifts SET tester=? WHERE id=?",
                (tester, shift_id)
            )
            message = f"Shift updated successfully for {row['component_type']} on {row['date']} ({row['shift']})"
        else:
            date_val = request.form["date"]
            shift_val = request.form["shift"]
            component_val = request.form["component"]

            execute_db(
                "INSERT INTO shifts (date, shift, component_type, tester) VALUES (?, ?, ?, ?)",
                (date_val, shift_val, component_val, tester)
            )
            message = f"Shift created successfully for {component_val} on {date_val} ({shift_val})"

        return redirect("/calendar")

    return render_template(
        "edit_shift.html",
        shift=row,
        testers=testers.keys(),
        message=None
    )

# -------------------------
# DAILY SNAPSHOT
# -------------------------

@app.route("/daily_snapshot")
def daily_snapshot():
    today = datetime.today().date()

    # Prepare today's shifts
    rows = query_db(
        "SELECT * FROM shifts WHERE date=? ORDER BY shift, component_type",
        (today.isoformat(),)
    )

    calendar = {"morning": [], "afternoon": []}
    for r in rows:
        calendar[r["shift"]].append({
            "component": r["component_type"],
            "tester": r["tester"],
            "date": datetime.fromisoformat(r["date"]).date()
        })

    # Prepare today's component testing stats
    components_tested_today = {}
    for comp in components:
        rows_comp = query_db(
            "SELECT status FROM tests WHERE component_type=? AND DATE(timestamp)=?",
            (comp, today.isoformat())
        )
        total = len(rows_comp)
        good = sum(1 for r in rows_comp if r["status"] == "good")
        bad = sum(1 for r in rows_comp if r["status"] == "bad")
        under = sum(1 for r in rows_comp if r["status"] == "under investigation")
        components_tested_today[comp] = {
            "total": total,
            "good": good,
            "bad": bad,
            "under": under
        }

    return render_template(
        "daily_snapshot.html",
        today=today,
        calendar=calendar,
        components=components,
        component_colors={c: components[c]["color"] for c in components},
        tester_colors={t: testers[t]["color"] for t in testers},
        components_tested_today=components_tested_today
    )

# -------------------------
# RUN SERVER
# -------------------------

if __name__ == "__main__":
    app.run(debug=True)

