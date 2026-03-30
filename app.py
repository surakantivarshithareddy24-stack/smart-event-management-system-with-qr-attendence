from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import sqlite3
import qrcode
from io import BytesIO
from datetime import datetime
import os
import re

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

app.url_map.strict_slashes = False

# ---------------------- DATABASE ----------------------

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'student'
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        date TEXT,
        event_time TEXT,
        location TEXT,
        description TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        event_id INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        event_id INTEGER,
        status TEXT,
        attendance_time TEXT
    )
    """)

    cursor.execute("""
    INSERT OR IGNORE INTO users (id, name, email, password, role)
    VALUES (1, 'Admin', 'admin@example.com', 'admin123', 'admin')
    """)

    conn.commit()
    conn.close()

# ---------------------- AUTH ----------------------

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper

# ---------------------- ROUTES ----------------------

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            flash("Email already exists")
            return redirect(url_for("register"))

        cursor.execute("INSERT INTO users (name,email,password) VALUES (?,?,?)",
                       (name, email, password))
        conn.commit()
        conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE email=? AND password=?",
                       (email, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM events")
    events = cursor.fetchall()

    conn.close()

    return render_template("dashboard.html", events=events)

@app.route("/create_event", methods=["POST"])
@admin_required
def create_event():
    title = request.form.get("title")
    date = request.form.get("date")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO events (title,date) VALUES (?,?)",
                   (title, date))
    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))

@app.route("/register_event/<int:event_id>")
@login_required
def register_event(event_id):
    user_id = session["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO registrations (user_id,event_id) VALUES (?,?)",
                   (user_id, event_id))
    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))

@app.route("/qr/<int:event_id>")
@login_required
def qr(event_id):
    user_id = session["user_id"]
    data = f"{user_id}:{event_id}"

    img = qrcode.make(data)
    buffer = BytesIO()
    img.save(buffer)
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png")

@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    data = request.json.get("qr")
    user_id, event_id = data.split(":")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO attendance (user_id,event_id,status,attendance_time) VALUES (?,?,?,?)",
                   (user_id, event_id, "Present", datetime.now()))
    conn.commit()
    conn.close()

    return jsonify({"status": "success"})

# ---------------------- MAIN ----------------------

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))