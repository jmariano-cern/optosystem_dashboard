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
    components = json.load(f)

with open("config/testers.json") as f:
    testers = json.load(f)

with open("config/failure_modes.json") as f:
    failure_modes = json.load(f)

def generate_week_shifts(start_date=None):
    """
    Generate a week-long calendar dict (Monday → Sunday) with morning/afternoon shifts
    for all components. Pre-populate slots even if no one has signed up.
    """
    if start_date is None:
        start_date = datetime.today()
    
    # Find Monday of the current week
    monday = start_date - timedelta(days=start_date.weekday())
    
    week_days = [(monday + timedelta(days=i)).date() for i in range(7)]
    
    # Build empty calendar
    calendar = {}
    for d in week_days:
        calendar[d.isoformat()] = {"morning": [], "afternoon": []}
        for shift in ["morning", "afternoon"]:
            for comp in components:
                calendar[d.isoformat()][shift].append({
                    "component": comp,
                    "tester": None,  # no one signed up yet
                    "id": None       # will be filled from db if exists
                })
    
    # Overlay actual shift data from DB
    rows = query_db("SELECT * FROM shifts")
    for r in rows:
        d = r["date"]
        shift = r["shift"]
        comp = r["component_type"]
        if d in calendar:
            for slot in calendar[d][shift]:
                if slot["component"] == comp:
                    slot["tester"] = r["tester"]
                    slot["id"] = r["id"]
    
    return calendar, week_days
    
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

# @app.route("/calendar")
# def calendar_page():
#     # --- 1. Define the week to display (current week Monday-Sunday) ---
#     today = date.today()
#     start_of_week = today - timedelta(days=today.weekday())  # Monday
#     days = [(start_of_week + timedelta(days=i)) for i in range(7)]
#     day_strs = [d.isoformat() for d in days]  # e.g., "2026-03-10"

#     # --- 2. Fetch existing shifts ---
#     rows = query_db(
#         "SELECT * FROM shifts WHERE date BETWEEN ? AND ?",
#         (day_strs[0], day_strs[-1])
#     )

#     # --- 3. Build a mapping from (date, shift, component) -> tester ---
#     db_map = {}
#     for r in rows:
#         key = (r["date"], r["shift"], r["component_type"])
#         db_map[key] = {"tester": r["tester"], "id": r["id"]}

#     # --- 4. Pre-fill calendar with all components / shifts ---
#     calendar = {}
#     for d in day_strs:
#         calendar[d] = {"morning": [], "afternoon": []}
#         for shift in ["morning", "afternoon"]:
#             for comp in components:
#                 key = (d, shift, comp)
#                 if key in db_map:
#                     calendar[d][shift].append({
#                         "component": comp,
#                         "tester": db_map[key]["tester"],
#                         "id": db_map[key]["id"]
#                     })
#                 else:
#                     calendar[d][shift].append({
#                         "component": comp,
#                         "tester": None,
#                         "id": None  # No DB row yet
#                     })

#     # --- 5. Assign colors to components ---
#     import matplotlib.colors as mcolors
#     palette = list(mcolors.TABLEAU_COLORS.values())
#     component_colors = {comp: palette[i % len(palette)] for i, comp in enumerate(components)}

#     return render_template(
#         "calendar.html",
#         calendar=calendar,
#         days=day_strs,
#         components=components,
#         component_colors=component_colors
#     )

# @app.route("/calendar")
# def calendar_page():
#     from datetime import date, timedelta

#     start_date = date.today()
#     days = [(start_date + timedelta(days=i)) for i in range(7)]
#     day_strs = [d.strftime("%Y-%m-%d") for d in days]

#     # Ensure every component, shift, and day has a row in the DB
#     for d in day_strs:
#         for shift in ["morning", "afternoon"]:
#             for comp in components:
#                 existing = query_db(
#                     "SELECT id FROM shifts WHERE date=? AND shift=? AND component_type=?",
#                     (d, shift, comp),
#                     one=True
#                 )
#                 if not existing:
#                     execute_db(
#                         "INSERT INTO shifts (date, shift, component_type, tester) VALUES (?, ?, ?, ?)",
#                         (d, shift, comp, None)
#                     )

#     # Fetch all shifts
#     rows = query_db("SELECT * FROM shifts ORDER BY date, shift, component_type")

#     # Build calendar dict
#     calendar = {d: {"morning": {}, "afternoon": {}} for d in day_strs}
#     for r in rows:
#         d = r["date"]
#         shift = r["shift"]
#         comp = r["component_type"]
#         calendar[d][shift][comp] = {
#             "tester": r["tester"],
#             "id": r["id"]
#         }

#     # Assign colors
#     base_colors = ["#ffcccc", "#ccffcc", "#ccccff", "#fff0cc", "#ffccff", "#ccffff"]
#     dark_colors = ["#cc4444", "#44cc44", "#4444cc", "#ffaa00", "#aa00aa", "#00aaaa"]
#     component_colors = {}
#     for idx, comp in enumerate(components):
#         component_colors[comp] = {"open": base_colors[idx % len(base_colors)],
#                                    "staffed": dark_colors[idx % len(dark_colors)]}

#     return render_template(
#         "calendar.html",
#         calendar=calendar,
#         days=day_strs,
#         components=components,
#         component_colors=component_colors
#     )

from datetime import datetime, timedelta

@app.route("/calendar")
def calendar_page():
    # Fetch all shifts from DB
    rows = query_db(
        "SELECT * FROM shifts ORDER BY date, shift, component_type"
    )

    # Generate a week-long range (Mon–Sun) starting from today
    start_date = datetime.today().date()
    week_days = [start_date + timedelta(days=i) for i in range(7)]

    # Build calendar dict only for weekdays
    calendar = {}
    for d in week_days:
        if d.weekday() < 5:  # Monday=0, Sunday=6
            calendar[d] = {"morning": [], "afternoon": []}
        else:
            calendar[d] = {"morning": [], "afternoon": []}  # keep weekends but empty

    # Populate calendar with shifts (only for weekdays)
    for r in rows:
        d = datetime.fromisoformat(r["date"]).date()
        if d.weekday() >= 5:  # skip weekends
            continue
        shift = r["shift"]
        comp = r["component_type"]
        calendar[d][shift].append({
            "component": comp,
            "tester": r["tester"],
            "id": r["id"]
        })

    # Generate day headers as (weekday name, date)
    day_headers = [(d.strftime("%A"), d) for d in week_days]

    # Generate consistent colors for each component
    pastel_colors = ["#FFB3BA","#BAE1FF","#BAFFC9","#FFFFBA","#FFDFBA","#E2BAFF","#BAFFD9"]
    component_colors = {comp: pastel_colors[i % len(pastel_colors)] for i, comp in enumerate(components)}

    return render_template(
        "calendar.html",
        calendar=calendar,
        day_headers=day_headers,
        components=components,
        component_colors=component_colors
    )

@app.route("/shift/<int:shift_id>", methods=["GET", "POST"])
def edit_shift(shift_id):
    # Fetch the shift row from DB if it exists
    row = query_db(
        "SELECT * FROM shifts WHERE id=?",
        (shift_id,),
        one=True
    )

    if request.method == "POST":
        tester = request.form.get("tester", "").strip() or None

        if row:
            # Update existing shift
            execute_db(
                "UPDATE shifts SET tester=? WHERE id=?",
                (tester, shift_id)
            )
            message = f"Shift updated successfully for {row['component_type']} on {row['date']} ({row['shift']})"
        else:
            # Insert new shift if it didn't exist
            # Expect hidden fields to provide date, shift, component
            date_val = request.form["date"]
            shift_val = request.form["shift"]
            component_val = request.form["component"]

            execute_db(
                "INSERT INTO shifts (date, shift, component_type, tester) VALUES (?, ?, ?, ?)",
                (date_val, shift_val, component_val, tester)
            )
            message = f"Shift created successfully for {component_val} on {date_val} ({shift_val})"

        return redirect("/calendar")

    # GET request: render form
    return render_template(
        "edit_shift.html",
        shift=row,
        testers=testers,
        message=None
    )

# -------------------------
# RUN SERVER
# -------------------------

if __name__ == "__main__":
    app.run(debug=True)
