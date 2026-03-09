import json
import sqlite3
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

DB = "database.db"

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

def query_db(query, args=()):

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(query, args)
    rows = cur.fetchall()

    conn.close()

    return rows


def execute_db(query, args=()):

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(query, args)
    conn.commit()

    conn.close()


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

        execute_db("""
        INSERT INTO tests
        (component_type, serial_number, tester, status, failure_mode)
        VALUES (?, ?, ?, ?, ?)
        """, (component, serial, tester, status, failure))

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
    progress = good / goal if goal else 0

    failure_counts = {}

    for r in rows:
        if r["failure_mode"]:
            failure_counts[r["failure_mode"]] = \
                failure_counts.get(r["failure_mode"], 0) + 1

    return render_template(
        "status.html",

        component=component,

        total=total,
        good=good,
        bad=bad,
        investigation=investigation,

        yield_estimate=yield_estimate,
        goal=goal,
        progress=progress,

        failures=failure_counts,
        rows=[dict(r) for r in rows]  # convert for JSON
    )

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
    # Get updated fields from form
    serial = request.form["serial"]
    status = request.form["status"]
    tester = request.form["tester"]
    failure_mode = request.form.get("failure_mode")

    # Update database
    execute_db("""
        UPDATE tests
        SET serial_number=?, status=?, tester=?, failure_mode=?
        WHERE id=?
    """, (serial, status, tester, failure_mode, test_id))

    # Redirect back to list page for the same component
    # First, fetch component type of updated row
    row = query_db("SELECT component_type FROM tests WHERE id=?", (test_id,))
    component = row[0]["component_type"] if row else "Unknown"

    return redirect(url_for("list_component", component=component))

# -------------------------
# RUN SERVER
# -------------------------

if __name__ == "__main__":
    app.run(debug=True)
