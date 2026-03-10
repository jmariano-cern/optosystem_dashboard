import json
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g
from datetime import datetime, timedelta
import math

app = Flask(__name__)

database = "database.db"

# -------------------------
# LOAD CONFIG FILES
# -------------------------

with open("config/components.json") as f:
    components = json.load(f)

with open("config/testers.json") as f:
    testers = json.load(f)

with open("config/failure_modes.json") as f:
    failure_modes = json.load(f)

# -------------------------
# DATABASE HELPERS
# -------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            database,
            timeout=30,                # wait for locks
            check_same_thread=False    # allow use in threaded servers
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

# def query_db(query, args=()):

#     conn = sqlite3.connect(DB, timeout=30)
#     conn.row_factory = sqlite3.Row
#     cur = conn.cursor()

#     cur.execute(query, args)
#     rows = cur.fetchall()

#     conn.close()

#     return rows


# def execute_db(query, args=()):

#     conn = sqlite3.connect(DB, timeout=30)
#     cur = conn.cursor()

#     cur.execute(query, args)
#     conn.commit()

#     conn.close()

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# -------------------------
# HOME PAGE
# -------------------------

@app.route("/")
def index():
    # Build summary stats for each component
    summary = {}
    for comp in components:
        rows = query_db("SELECT * FROM tests WHERE component_type=?", (comp,))
        total = len(rows)
        good = sum(r["status"]=="good" for r in rows)
        bad = sum(r["status"]=="bad" for r in rows)
        investigation = sum(r["status"]=="under investigation" for r in rows)
        yield_estimate = good / total if total else 0
        goal = components[comp]["goal"]
        progress = good / goal if goal else 0

        summary[comp] = {
            "total": total,
            "good": good,
            "bad": bad,
            "investigation": investigation,
            "yield_estimate": yield_estimate,
            "goal": goal,
            "progress": progress
        }

    return render_template(
        "index.html",
        components=components,
        summary=summary
    )

# -------------------------
# SUBMIT PAGE
# -------------------------

@app.route("/submit", methods=["GET", "POST"])
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
            message = f"ERROR: {component} with serial number {serial} already exists."
            return render_template(
                "submit.html",
                components=components,
                testers=testers,
                failure_modes=failure_modes,
                message=message,
                failures={}
            )
        
        execute_db("""
        INSERT INTO tests
        (component_type, serial_number, tester, status, failure_mode, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (component, serial, tester, status, failure, timestamp))

        message = f"Component {serial} recorded successfully."

    return render_template(
        "submit.html",
        components=components,
        testers=testers,
        failures=failure_modes,
        message=message
    )


# -------------------------
# STATUS PAGE
# -------------------------

@app.route("/status/<component>")
def status(component):
    from datetime import datetime, timedelta
    import math

    # Fetch all tests for this component
    rows = query_db(
        "SELECT * FROM tests WHERE component_type=? ORDER BY timestamp",
        (component,)
    )

    total = len(rows)
    good = sum(r["status"] == "good" for r in rows)
    bad = sum(r["status"] == "bad" for r in rows)
    investigation = sum(r["status"] == "under investigation" for r in rows)
    yield_estimate = good / total if total else 0

    goal = components[component]["goal"]
    progress = (good / goal * 100) if goal else 0

    # --- Status counts for pie chart ---
    status_counts = {
        "good": good,
        "bad": bad,
        "under investigation": investigation
    }

    # --- Failure mode counts (bad + under investigation only) ---
    failure_counts = {}
    for r in rows:
        if r["status"] in ("bad", "under investigation") and r["failure_mode"]:
            failure_counts[r["failure_mode"]] = failure_counts.get(r["failure_mode"], 0) + 1

    # --- Forecasting logic ---
    if rows:
        first_ts = datetime.fromisoformat(rows[0]["timestamp"])
        last_ts = datetime.fromisoformat(rows[-1]["timestamp"])
    else:
        first_ts = last_ts = datetime.today()

    # Number of business days since first test
    num_days = sum(
        1 for i in range((last_ts.date() - first_ts.date()).days + 1)
        if (first_ts.date() + timedelta(days=i)).weekday() < 5
    )

    avg_good_per_day = good / num_days if num_days else 0
    remaining_good = max(goal - good, 0)

    # Predict expected completion date
    if avg_good_per_day > 0:
        expected_testing_days = remaining_good / avg_good_per_day
        predicted_completion_date = datetime.today()
        days_added = 0
        while days_added < expected_testing_days:
            predicted_completion_date += timedelta(days=1)
            if predicted_completion_date.weekday() < 5:
                days_added += 1
        predicted_completion_date = predicted_completion_date.date()
    else:
        expected_testing_days = math.nan
        predicted_completion_date = "NaN"

    forecast_data = {
        "total_good": good,
        "first_day": first_ts.date(),
        "num_days": num_days,
        "avg_good_per_day": avg_good_per_day,
        "remaining_good": remaining_good,
        "expected_testing_days": expected_testing_days,
        "predicted_completion_date": predicted_completion_date
    }

    # --- Prepare Testing History for chart ---
    history_dates = []
    history_good = []
    history_bad = []
    history_under = []

    cumulative_good = cumulative_bad = cumulative_under = 0
    for r in rows:
        ts_date = datetime.fromisoformat(r["timestamp"]).date().isoformat()
        history_dates.append(ts_date)
        if r["status"] == "good":
            cumulative_good += 1
        elif r["status"] == "bad":
            cumulative_bad += 1
        elif r["status"] == "under investigation":
            cumulative_under += 1
        history_good.append(cumulative_good)
        history_bad.append(cumulative_bad)
        history_under.append(cumulative_under)

    # --- Recent tests (latest 20) ---
    recent_tests = rows[-20:][::-1]  # most recent first

    # Optional: failure mode colors
    failure_mode_colors = ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40"]
    # repeat colors if more modes
    while len(failure_mode_colors) < len(failure_counts):
        failure_mode_colors *= 2
    failure_mode_colors = failure_mode_colors[:len(failure_counts)]

    return render_template(
        "status.html",
        component=component,
        total=total,
        yield_estimate=yield_estimate,
        goal=goal,
        progress=progress,
        status_counts=status_counts,
        failure_mode_counts=failure_counts,
        failure_mode_colors=failure_mode_colors,
        history_dates=history_dates,
        history_good=history_good,
        history_bad=history_bad,
        history_under=history_under,
        recent_tests=[dict(r) for r in recent_tests],
        forecast=forecast_data
    )

# @app.route("/status/<component>")
# def status(component):
#     rows = query_db(
#         "SELECT * FROM tests WHERE component_type=? ORDER BY timestamp",
#         (component,)
#     )

#     total = len(rows)
#     good = sum(r["status"] == "good" for r in rows)
#     bad = sum(r["status"] == "bad" for r in rows)
#     investigation = sum(r["status"] == "under investigation" for r in rows)
#     yield_estimate = good / total if total else 0

#     goal = components[component]["goal"]
#     progress = good / goal if goal else 0

#     # Count failure modes (bad + under investigation)
#     failure_counts = {}
#     for r in rows:
#         if r["failure_mode"]:
#             failure_counts[r["failure_mode"]] = failure_counts.get(r["failure_mode"], 0) + 1

#     # --- Forecasting logic ---
#     from datetime import datetime, timedelta
#     import math

#     if rows:
#         first_ts = datetime.fromisoformat(rows[0]["timestamp"])
#         last_ts = datetime.fromisoformat(rows[-1]["timestamp"])
#     else:
#         first_ts = last_ts = datetime.today()

#     # Number of business days since first test
#     num_days = sum(1 for i in range((last_ts.date() - first_ts.date()).days + 1)
#                    if (first_ts.date() + timedelta(days=i)).weekday() < 5)

#     avg_good_per_day = good / num_days if num_days else 0
#     remaining_good = max(goal - good, 0)

#     # Handle zero average gracefully
#     if avg_good_per_day > 0:
#         expected_testing_days = remaining_good / avg_good_per_day
#         # Project expected completion date skipping weekends
#         predicted_completion_date = datetime.today()
#         days_added = 0
#         while days_added < expected_testing_days:
#             predicted_completion_date += timedelta(days=1)
#             if predicted_completion_date.weekday() < 5:
#                 days_added += 1
#         predicted_completion_date = predicted_completion_date.date()
#     else:
#         expected_testing_days = math.nan
#         predicted_completion_date = "NaN"

#     forecast_data = {
#         "total_good": good,
#         "first_day": first_ts.date(),
#         "num_days": num_days,
#         "avg_good_per_day": avg_good_per_day,
#         "remaining_good": remaining_good,
#         "expected_testing_days": expected_testing_days,
#         "predicted_completion_date": predicted_completion_date
#     }

#     return render_template(
#         "status.html",
#         component=component,
#         total=total,
#         good=good,
#         bad=bad,
#         investigation=investigation,
#         yield_estimate=yield_estimate,
#         goal=goal,
#         progress=progress,
#         failures=failure_counts,
#         rows=[dict(r) for r in rows],
#         forecast=forecast_data
#     )

# @app.route("/status/<component>")
# def status(component):

#     rows = query_db(
#         "SELECT * FROM tests WHERE component_type=? ORDER BY timestamp",
#         (component,)
#     )

#     total = len(rows)
#     good = sum(r["status"] == "good" for r in rows)
#     bad = sum(r["status"] == "bad" for r in rows)
#     investigation = sum(r["status"] == "under investigation" for r in rows)
#     yield_estimate = good / total if total else 0

#     goal = components[component]["goal"]
#     progress = good / goal if goal else 0

#     failure_counts = {}
#     for r in rows:
#         if r["failure_mode"]:
#             failure_counts[r["failure_mode"]] = failure_counts.get(r["failure_mode"], 0) + 1

#     # --- Forecasting logic ---
#     if rows:
#         first_ts = datetime.fromisoformat(rows[0]["timestamp"])
#         last_ts = datetime.fromisoformat(rows[-1]["timestamp"])
#     else:
#         first_ts = last_ts = datetime.today()

#     # compute number of business days (Mon-Fri) excluding weekends
#     num_days = 0
#     for i in range((last_ts.date() - first_ts.date()).days + 1):
#         day = first_ts.date() + timedelta(days=i)
#         if day.weekday() < 5:  # 0=Mon, 6=Sun
#             num_days += 1

#     avg_good_per_day = good / num_days if num_days else 0
#     remaining_good = max(goal - good, 0)
#     expected_testing_days = remaining_good / avg_good_per_day if avg_good_per_day else 0

#     # project expected completion date skipping weekends
#     predicted_completion_date = datetime.today()
#     days_added = 0
#     while days_added < expected_testing_days:
#         predicted_completion_date += timedelta(days=1)
#         if predicted_completion_date.weekday() < 5:  # count only weekdays
#             days_added += 1

#     # prepare all quantities for template
#     forecast_data = {
#         "total_good": good,
#         "first_day": first_ts.date(),
#         "num_days": num_days,
#         "avg_good_per_day": avg_good_per_day,
#         "remaining_good": remaining_good,
#         "expected_testing_days": expected_testing_days,
#         "predicted_completion_date": predicted_completion_date.date()
#     }

#     return render_template(
#         "status.html",
#         component=component,
#         total=total,
#         good=good,
#         bad=bad,
#         investigation=investigation,
#         yield_estimate=yield_estimate,
#         goal=goal,
#         progress=progress,
#         failures=failure_counts,
#         rows=[dict(r) for r in rows],  # convert for JSON
#         forecast=forecast_data
#     )

# @app.route("/status/<component>")
# def status(component):

#     rows = query_db(
#         "SELECT * FROM tests WHERE component_type=? ORDER BY timestamp",
#         (component,)
#     )

#     total = len(rows)

#     good = sum(r["status"] == "good" for r in rows)
#     bad = sum(r["status"] == "bad" for r in rows)
#     investigation = sum(r["status"] == "under investigation" for r in rows)

#     yield_estimate = good / total if total else 0

#     goal = components[component]["goal"]
#     progress = good / goal if goal else 0

#     failure_counts = {}

#     for r in rows:
#         if r["failure_mode"]:
#             failure_counts[r["failure_mode"]] = \
#                 failure_counts.get(r["failure_mode"], 0) + 1

#     return render_template(
#         "status.html",

#         component=component,

#         total=total,
#         good=good,
#         bad=bad,
#         investigation=investigation,

#         yield_estimate=yield_estimate,
#         goal=goal,
#         progress=progress,

#         failures=failure_counts,
#         rows=[dict(r) for r in rows]  # convert for JSON
#     )

# -------------------------
# LIST COMPONENT TESTS
# -------------------------
@app.route("/list/<component>")
def list_component(component):
    # Fetch all tests for this component
    rows = query_db("SELECT * FROM tests WHERE component_type=? ORDER BY timestamp DESC", (component,))
    return render_template(
        "list_component.html",
        component=component,
        rows=[dict(r) for r in rows],
        testers=testers,
        failure_modes=failure_modes.get(component, [])
    )

# -------------------------
# UPDATE TEST ENTRY
# -------------------------

@app.route("/update_test/<int:test_id>", methods=["POST"])
def update_test(test_id):
    serial = request.form["serial"]
    status = request.form["status"]
    tester = request.form["tester"]
    failure_mode = request.form.get("failure_mode")

    execute_db("""
        UPDATE tests
        SET serial_number=?, status=?, tester=?, failure_mode=?
        WHERE id=?
    """, (serial, status, tester, failure_mode, test_id))

    # Get component type
    row = query_db("SELECT component_type FROM tests WHERE id=?", (test_id,))
    component = row[0]["component_type"] if row else "Unknown"

    # Simple feedback message
    message = f"Test ID {test_id} updated successfully."

    # Redirect back to the list page with message via query string
    return redirect(url_for("list_component", component=component, message=message))

@app.route("/delete_test/<int:test_id>", methods=["POST"])
def delete_test(test_id):
    row = query_db("SELECT component_type FROM tests WHERE id=?", (test_id,))
    component = row[0]["component_type"] if row else "Unknown"

    execute_db("DELETE FROM tests WHERE id=?", (test_id,))

    message = f"Test ID {test_id} deleted successfully."
    return redirect(url_for("list_component", component=component, message=message))

# @app.route("/update_test/<int:test_id>", methods=["POST"])
# def update_test(test_id):
#     # Get updated fields from form
#     serial = request.form["serial"]
#     status = request.form["status"]
#     tester = request.form["tester"]
#     failure_mode = request.form.get("failure_mode")

#     # Update database
#     execute_db("""
#         UPDATE tests
#         SET serial_number=?, status=?, tester=?, failure_mode=?
#         WHERE id=?
#     """, (serial, status, tester, failure_mode, test_id))

#     # Redirect back to list page for the same component
#     # First, fetch component type of updated row
#     row = query_db("SELECT component_type FROM tests WHERE id=?", (test_id,))
#     component = row[0]["component_type"] if row else "Unknown"

#     return redirect(url_for("list_component", component=component))

@app.route("/tester_dashboard")
def tester_dashboard():
    tester_summary = {}

    # component → tester counts (for pie charts)
    for comp in components:
        rows = query_db(
            "SELECT tester FROM tests WHERE component_type=?",
            (comp,)
        )

        counts = {}
        for r in rows:
            tester = r["tester"] or "Unknown"
            counts[tester] = counts.get(tester, 0) + 1

        tester_summary[comp] = counts

    # tester → component counts (for stacked bar chart)
    rows = query_db("SELECT tester, component_type FROM tests")

    tester_component_counts = {}

    for r in rows:
        tester = r["tester"] or "Unknown"
        comp = r["component_type"]

        if tester not in tester_component_counts:
            tester_component_counts[tester] = {c:0 for c in components}

        tester_component_counts[tester][comp] += 1

    return render_template(
        "tester_dashboard.html",
        components=components,
        tester_summary=tester_summary,
        tester_component_counts=tester_component_counts
    )

# @app.route("/tester_dashboard")
# def tester_dashboard():
#     tester_summary = {}
#     tester_totals = {}

#     for comp in components:
#         rows = query_db(
#             "SELECT tester FROM tests WHERE component_type=?",
#             (comp,)
#         )

#         counts = {}

#         for r in rows:
#             tester = r["tester"] or "Unknown"

#             # per-component counts
#             counts[tester] = counts.get(tester, 0) + 1

#             # global totals
#             tester_totals[tester] = tester_totals.get(tester, 0) + 1

#         tester_summary[comp] = counts

#     return render_template(
#         "tester_dashboard.html",
#         components=components,
#         tester_summary=tester_summary,
#         tester_totals=tester_totals
#     )

# @app.route("/tester_dashboard")
# def tester_dashboard():
#     tester_summary = {}

#     for comp in components:
#         rows = query_db(
#             "SELECT tester FROM tests WHERE component_type=?",
#             (comp,)
#         )

#         counts = {}
#         for r in rows:
#             tester = r["tester"] or "Unknown"
#             counts[tester] = counts.get(tester, 0) + 1

#         tester_summary[comp] = counts

#     return render_template(
#         "tester_dashboard.html",
#         components=components,
#         tester_summary=tester_summary
#     )

# -------------------------
# RUN SERVER
# -------------------------

if __name__ == "__main__":
    app.run(debug=True)
