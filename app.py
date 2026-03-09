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
# DATABASE HELPER
# -------------------------

def query_db(query, args=(), one=False):

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(query, args)
    rows = cur.fetchall()

    conn.close()

    return (rows[0] if rows else None) if one else rows


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

    return render_template(
        "index.html",
        components=components
    )


# -------------------------
# SUBMISSION PAGE
# -------------------------

@app.route("/submit", methods=["GET", "POST"])
def submit():

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

        return redirect(url_for("submit"))

    return render_template(
        "submit.html",
        components=components,
        testers=testers,
        failures=failure_modes
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

    # failure mode breakdown
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
        rows=rows
    )


# -------------------------
# RUN SERVER
# -------------------------

if __name__ == "__main__":
    app.run(debug=True)
