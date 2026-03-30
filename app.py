from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import mysql.connector
from mysql.connector import Error
import qrcode
from io import BytesIO
from datetime import datetime
import os
import re

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Change this in production

# Avoid 404 for /page vs /page/ on common routes
app.url_map.strict_slashes = False

# ---------------------- DATABASE CONFIG ----------------------

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "root"          # Put your MySQL password here
DB_NAME = "smart_event_db"


def get_db_connection():
    """
    Create and return a new database connection.
    """
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        return conn
    except Error as e:
        print("Error while connecting to MySQL:", e)
        return None


def get_table_columns(conn, table_name: str) -> set:
    """
    Return a set of column names for the given table.
    If the table does not exist (or any error), return empty set.
    """
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
        cols = {row[0] for row in cur.fetchall()}
        cur.close()
        return cols
    except Exception:
        return set()

def get_column_type(conn, table_name: str, column_name: str) -> str:
    """
    Returns the MySQL column type string from SHOW COLUMNS, e.g. "enum('user','admin')".
    Returns empty string on error.
    """
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{table_name}` LIKE %s", (column_name,))
        row = cur.fetchone()
        cur.close()
        return row[1] if row else ""
    except Exception:
        return ""


def init_db():
    """
    Initialize the database tables if they do not exist.
    Run once at startup.
    """
    conn = get_db_connection()
    if conn is None:
        return

    cursor = conn.cursor()

    # Users table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            role ENUM('admin', 'student') DEFAULT 'student'
        )
        """
    )

    # Events table (now includes location and time)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(200) NOT NULL,
            date DATE NOT NULL,
            event_time TIME NULL,
            location VARCHAR(255) NULL,
            description TEXT
        )
        """
    )

    # Registrations table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS registrations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            event_id INT NOT NULL,
            UNIQUE KEY uniq_user_event (user_id, event_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
        """
    )

    # Attendance table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            event_id INT NOT NULL,
            status VARCHAR(20) NOT NULL,
            attendance_time DATETIME NOT NULL,
            UNIQUE KEY uniq_attendance (user_id, event_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
        """
    )

    # --- Simple schema migrations for older databases ---

    # Ensure users.role enum includes both admin and student
    try:
        cursor.execute(
            "ALTER TABLE users MODIFY role ENUM('admin','student') NOT NULL DEFAULT 'student'"
        )
    except Exception:
        pass

    # Ensure events table has event_time and location columns
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN event_time TIME NULL")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE events ADD COLUMN location VARCHAR(255) NULL")
    except Exception:
        pass

    # Create a default admin user if not exists
    cursor.execute(
        """
        INSERT IGNORE INTO users (id, name, email, password, role)
        VALUES (1, 'Admin', 'admin@example.com', 'admin123', 'admin')
        """
    )

    conn.commit()
    cursor.close()
    conn.close()


# ---------------------- AUTH HELPERS ----------------------

def login_required(f):
    """
    Simple decorator to protect routes that require login.
    """
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """
    Decorator to protect admin-only routes.
    """
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session or session.get("role") != "admin":
            # For AJAX calls (like QR scanning), return JSON instead of an HTML redirect.
            if request.path == "/mark_attendance" or request.headers.get("Content-Type", "").startswith("application/json"):
                return jsonify({"status": "error", "message": "You are not authorized to mark attendance."}), 401

            flash("You are not authorized to view this page.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


# ---------------------- ROUTES ----------------------


@app.errorhandler(404)
def page_not_found(_e):
    """Friendly page when URL is wrong (typos, old bookmarks)."""
    return render_template("404.html"), 404


@app.route("/scanner")
def scanner_alias():
    """Common mistake: /scanner instead of /qr_scanner"""
    return redirect(url_for("qr_scanner"))


@app.route("/qr-scanner")
def qr_scanner_hyphen():
    """Common mistake: hyphen instead of underscore"""
    return redirect(url_for("qr_scanner"))


@app.route("/student_dashboard")
def student_dashboard_alias():
    return redirect(url_for("dashboard"))


@app.route("/admin_dashboard")
def admin_dashboard_alias():
    return redirect(url_for("dashboard"))


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        role = (request.form.get("role") or "student").strip().lower()

        if not name or not email or not password or not role:
            flash("Please fill all fields", "danger")
            return redirect(url_for("register"))

        if role not in {"admin", "student"}:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("register"))

        conn = get_db_connection()
        if conn is None:
            flash("Database connection error.", "danger")
            return redirect(url_for("register"))

        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM users WHERE email = %s", (email,))
            result = cursor.fetchone()
            if result and result[0] > 0:
                flash("Email already registered", "danger")
                return redirect(url_for("register"))

            # Support older schemas where role enum is ('user','admin')
            role_type = get_column_type(conn, "users", "role").lower()
            db_role = role
            if "enum" in role_type and "student" not in role_type and "user" in role_type:
                if role == "student":
                    db_role = "user"

            cursor.execute(
                "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s)",
                (name, email, password, db_role),
            )
            conn.commit()
            flash("Registration successful. Please login.", "success")
            return redirect(url_for("login"))
        except Error as e:
            print("Error while registering user:", e)
            flash("Registration failed. Please try again.", "danger")
        finally:
            cursor.close()
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = get_db_connection()
        if conn is None:
            flash("Database connection error.", "danger")
            return redirect(url_for("login"))

        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM users WHERE email = %s AND password = %s",
            (email, password),
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            # Support older DB role value 'user' as student
            session["role"] = "student" if user["role"] == "user" else user["role"]
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """
    Admin-only login page.
    Only allows users with role admin.
    """
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()

        if not email or not password:
            flash("Please fill all fields", "danger")
            return redirect(url_for("admin_login"))

        conn = get_db_connection()
        if conn is None:
            flash("Database connection error.", "danger")
            return redirect(url_for("admin_login"))

        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM users WHERE email = %s AND password = %s",
            (email, password),
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("admin_login"))

        if user.get("role") != "admin":
            flash("This login is for Admin only.", "danger")
            return redirect(url_for("admin_login"))

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["role"] = "admin"
        flash("Admin login successful.", "success")
        return redirect(url_for("dashboard"))

    return render_template("admin_login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    """
    Dashboard: shows Admin or Student view based on role.
    """
    user_id = session["user_id"]

    conn = get_db_connection()
    if conn is None:
        flash("Database connection error.", "danger")
        return redirect(url_for("login"))

    cursor = conn.cursor(dictionary=True)

    # Always load role from DB (prevents wrong dashboard due to old session role values)
    cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
    role_row = cursor.fetchone()
    db_role = (role_row.get("role") if role_row else "") or ""
    role = "student" if db_role == "user" else db_role
    session["role"] = role

    # All events
    cursor.execute("SELECT * FROM events ORDER BY date ASC")
    events = cursor.fetchall()

    if role == "admin":
        # Admin: registrations per event
        cursor.execute(
            """
            SELECT e.id AS event_id,
                   e.title,
                   e.date,
                   e.description,
                   COUNT(r.id) AS registrations_count
            FROM events e
            LEFT JOIN registrations r ON r.event_id = e.id
            GROUP BY e.id
            ORDER BY e.date ASC
            """
        )
        event_stats = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            "admin_dashboard.html",
            events=event_stats,
            user_name=session.get("user_name"),
        )

    # Student: registered events separately
    cursor.execute(
        """
        SELECT e.*
        FROM registrations r
        JOIN events e ON r.event_id = e.id
        WHERE r.user_id = %s
        ORDER BY e.date ASC
        """,
        (user_id,),
    )
    registered_events = cursor.fetchall()

    registered_event_ids = {e["id"] for e in registered_events}

    cursor.close()
    conn.close()

    return render_template(
        "student_dashboard.html",
        events=events,
        registered_events=registered_events,
        registered_event_ids=registered_event_ids,
        user_name=session.get("user_name"),
    )


@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin_panel():
    """
    Admin route to create events (then redirect to dashboard).
    """
    conn = get_db_connection()
    if conn is None:
        flash("Database connection error.", "danger")
        return redirect(url_for("dashboard"))

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        # Create new event
        title = request.form.get("title")
        date_str = request.form.get("date")
        time_str = request.form.get("time")
        location = request.form.get("location")
        description = request.form.get("description")

        title = (title or "").strip()
        date_str = (date_str or "").strip()
        time_str = (time_str or "").strip()
        location = (location or "").strip()
        description = (description or "").strip()

        if not title or not date_str or not time_str or not location:
            flash("Please fill all fields", "danger")
            cursor.close()
            conn.close()
            return redirect(url_for("dashboard"))

        try:
            cursor.execute(
                """
                INSERT INTO events (title, date, event_time, location, description)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (title, date_str, time_str, location, description),
            )
            conn.commit()
            flash("Event created successfully.", "success")
        except Error as e:
            print("Error while creating event:", e)
            flash("Could not create event.", "danger")

    # Fetch events and registration counts
    cursor.execute(
        """
        SELECT e.*, COUNT(r.id) AS registrations_count
        FROM events e
        LEFT JOIN registrations r ON e.id = r.event_id
        GROUP BY e.id
        ORDER BY e.date ASC
        """
    )
    events = cursor.fetchall()

    cursor.close()
    conn.close()

    return redirect(url_for("dashboard"))


@app.route("/admin/event/edit/<int:event_id>", methods=["GET", "POST"])
@admin_required
def edit_event(event_id):
    """
    Admin can edit an event.
    """
    conn = get_db_connection()
    if conn is None:
        flash("Database connection error.", "danger")
        return redirect(url_for("admin_panel"))

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        date_str = request.form.get("date")
        time_str = request.form.get("time")
        location = request.form.get("location")

        title = (title or "").strip()
        date_str = (date_str or "").strip()
        time_str = (time_str or "").strip()
        location = (location or "").strip()
        description = (description or "").strip()

        if not title or not date_str or not time_str or not location:
            flash("Please fill all fields", "danger")
            return redirect(url_for("edit_event", event_id=event_id))

        cursor.execute(
            """
            UPDATE events
            SET title = %s, date = %s, event_time = %s, location = %s, description = %s
            WHERE id = %s
            """,
            (title, date_str, time_str, location, description, event_id),
        )
        conn.commit()
        flash("Event updated successfully.", "success")
        cursor.close()
        conn.close()
        return redirect(url_for("dashboard"))

    # GET: load event data
    cursor.execute("SELECT * FROM events WHERE id = %s", (event_id,))
    event = cursor.fetchone()
    cursor.close()
    conn.close()

    if not event:
        flash("Event not found.", "danger")
        return redirect(url_for("dashboard"))

    return render_template("event.html", event=event, edit_mode=True)


@app.route("/admin/event/delete/<int:event_id>", methods=["POST"])
@admin_required
def delete_event(event_id):
    """
    Admin can delete an event.
    """
    conn = get_db_connection()
    if conn is None:
        flash("Database connection error.", "danger")
        return redirect(url_for("admin_panel"))

    cursor = conn.cursor()
    cursor.execute("DELETE FROM registrations WHERE event_id = %s", (event_id,))
    cursor.execute("DELETE FROM attendance WHERE event_id = %s", (event_id,))
    cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
    conn.commit()
    cursor.close()
    conn.close()

    flash("Event deleted successfully.", "info")
    return redirect(url_for("dashboard"))


@app.route("/admin/event/<int:event_id>/registrations")
@admin_required
def view_event_registrations(event_id):
    """
    Admin can view students registered for a specific event.
    """
    conn = get_db_connection()
    if conn is None:
        flash("Database connection error.", "danger")
        return redirect(url_for("admin_panel"))

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM events WHERE id = %s", (event_id,))
    event = cursor.fetchone()

    cursor.execute(
        """
        SELECT u.id AS user_id,
               u.name,
               u.email
        FROM registrations r
        JOIN users u ON r.user_id = u.id
        WHERE r.event_id = %s
        ORDER BY u.name ASC
        """,
        (event_id,),
    )
    registrations = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("event.html", event=event, registrations=registrations)


@app.route("/admin/attendance")
@admin_required
def view_attendance():
    """
    Admin can view all attendance records.
    """
    conn = get_db_connection()
    if conn is None:
        flash("Database connection error.", "danger")
        return redirect(url_for("admin_panel"))

    cursor = conn.cursor(dictionary=True)

    att_cols = get_table_columns(conn, "attendance")

    if "registration_id" in att_cols:
        # Older schema: attendance(registration_id, attended_at)
        cursor.execute(
            """
            SELECT a.id,
                   'Present' AS status,
                   a.attended_at AS attendance_time,
                   u.name AS user_name,
                   u.email AS user_email,
                   e.title AS event_title
            FROM attendance a
            JOIN registrations r ON a.registration_id = r.id
            JOIN users u ON r.user_id = u.id
            JOIN events e ON r.event_id = e.id
            ORDER BY a.attended_at DESC
            """
        )
        records = cursor.fetchall()
    else:
        # New schema: attendance(user_id, event_id, status, attendance_time)
        status_expr = "a.status" if "status" in att_cols else "'Present'"
        time_expr = "a.attendance_time" if "attendance_time" in att_cols else "NULL"
        cursor.execute(
            f"""
            SELECT a.id,
                   {status_expr} AS status,
                   {time_expr} AS attendance_time,
                   u.name AS user_name,
                   u.email AS user_email,
                   e.title AS event_title
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            JOIN events e ON a.event_id = e.id
            ORDER BY a.id DESC
            """
        )
        records = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("admin_attendance.html", records=records)


@app.route("/register_event/<int:event_id>", methods=["GET", "POST"])
@login_required
def register_event(event_id):
    """
    Student registers for an event (prevents duplicate).
    """
    user_id = session["user_id"]

    conn = get_db_connection()
    if conn is None:
        flash("Database connection error.", "danger")
        return redirect(url_for("dashboard"))

    cursor = conn.cursor(dictionary=True)

    # Load event details
    cursor.execute("SELECT * FROM events WHERE id = %s", (event_id,))
    event = cursor.fetchone()

    if not event:
        cursor.close()
        conn.close()
        flash("Event not found.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            # Prevent duplicate registration
            cursor.execute(
                "SELECT id FROM registrations WHERE user_id = %s AND event_id = %s",
                (user_id, event_id),
            )
            existing = cursor.fetchone()
            if existing:
                flash("You are already registered for this event.", "warning")
                cursor.close()
                conn.close()
                return redirect(url_for("dashboard"))

            # Work with both old/new registrations table schemas
            reg_cols = get_table_columns(conn, "registrations")

            # Always generate token if column exists (many older schemas require it)
            qr_token = f"{user_id}:{event_id}"

            insert_cols = ["user_id", "event_id"]
            insert_vals = [user_id, event_id]

            # Optional student fields (if your table has them)
            name = (request.form.get("name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            phone = (request.form.get("phone") or "").strip()

            if "name" in reg_cols:
                if not name:
                    flash("Please fill all fields", "danger")
                    cursor.close()
                    conn.close()
                    return redirect(url_for("register_event", event_id=event_id))
                insert_cols.append("name")
                insert_vals.append(name)

            if "email" in reg_cols:
                if not email:
                    flash("Please fill all fields", "danger")
                    cursor.close()
                    conn.close()
                    return redirect(url_for("register_event", event_id=event_id))
                insert_cols.append("email")
                insert_vals.append(email)

            if "phone" in reg_cols:
                if not phone:
                    flash("Please fill all fields", "danger")
                    cursor.close()
                    conn.close()
                    return redirect(url_for("register_event", event_id=event_id))
                insert_cols.append("phone")
                insert_vals.append(phone)

            if "qr_token" in reg_cols:
                insert_cols.append("qr_token")
                insert_vals.append(qr_token)

            if "registered_at" in reg_cols:
                insert_cols.append("registered_at")
                insert_vals.append(datetime.utcnow())

            placeholders = ", ".join(["%s"] * len(insert_cols))
            columns_sql = ", ".join(insert_cols)
            cursor.execute(
                f"INSERT INTO registrations ({columns_sql}) VALUES ({placeholders})",
                tuple(insert_vals),
            )
            conn.commit()

            registration_id = cursor.lastrowid
            flash("Event registration successful.", "success")
            cursor.close()
            conn.close()
            return redirect(url_for("qr_display", registration_id=registration_id))
        except Error as e:
            print("Error while registering for event:", e)
            flash("Registration failed. Please try again.", "danger")
        finally:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass

        return redirect(url_for("dashboard"))

    # GET: show registration form (auto-fill name/email from users table)
    cursor.execute("SELECT name, email FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template("event_registration.html", event=event, user=user)


@app.route("/qr/<int:registration_id>")
@login_required
def qr_display(registration_id):
    """
    Display QR after registration.
    QR contains user_id and event_id.
    Saves QR image into static/qr_codes/.
    """
    conn = get_db_connection()
    if conn is None:
        flash("Database connection error.", "danger")
        return redirect(url_for("dashboard"))

    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT r.id, r.user_id, r.event_id, e.title
        FROM registrations r
        JOIN events e ON r.event_id = e.id
        WHERE r.id = %s
        """,
        (registration_id,),
    )
    reg = cursor.fetchone()
    cursor.close()
    conn.close()

    if not reg:
        flash("Registration not found.", "danger")
        return redirect(url_for("dashboard"))

    # Only allow owner or admin to view QR
    if session.get("role") != "admin" and session.get("user_id") != reg["user_id"]:
        flash("Not authorized.", "danger")
        return redirect(url_for("dashboard"))

    qr_text = f"{reg['user_id']}:{reg['event_id']}"

    qr_dir = os.path.join(app.root_path, "static", "qr_codes")
    os.makedirs(qr_dir, exist_ok=True)
    filename = f"qr_{reg['user_id']}_{reg['event_id']}.png"
    file_path = os.path.join(qr_dir, filename)

    # Simpler QR pattern (L error correction) scans more reliably from phone/webcam than dense H-level codes
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=14,
        border=4,
    )
    qr.add_data(qr_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(file_path)

    qr_url = url_for("static", filename=f"qr_codes/{filename}")
    # Cache-busting so the browser refreshes the latest regenerated QR.
    cache_bust = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    qr_url = f"{qr_url}?v={cache_bust}"
    return render_template("qr_display.html", qr_url=qr_url, event_title=reg["title"])


@app.route("/qr/<string:qr_token>")
@login_required
def generate_qr(qr_token):
    """
    Generate a QR code image for a registration token.
    The image is generated in memory.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=14,
        border=4,
    )
    qr.add_data(qr_token)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")


@app.route("/qr_scanner")
@admin_required
def qr_scanner():
    """
    Admin-only page with webcam-based QR scanner.
    """
    return render_template("qr_scanner.html")


@app.route("/mark_attendance", methods=["POST"])
@admin_required
def mark_attendance():
    """
    AJAX endpoint called by the QR scanner when a QR token is detected.
    It records attendance for the student (user) and event encoded in the token.
    """
    data = request.get_json(silent=True) or {}
    # Remove spaces/newlines from scanned text (phones often add line breaks)
    qr_token = re.sub(r"\s+", "", (data.get("qr_token") or ""))
    if not qr_token:
        return jsonify({"status": "error", "message": "Missing QR data."}), 400

    # Expected format: "<user_id>:<event_id>" (first two colon-separated parts)
    try:
        parts = qr_token.split(":")
        if len(parts) < 2:
            raise ValueError("bad")
        user_id = int(parts[0])
        event_id = int(parts[1])
    except Exception:
        return jsonify({"status": "error", "message": "Invalid QR code format. Use user_id:event_id (e.g. 3:1)."}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"status": "error", "message": "Database connection error."}), 500

    cursor = conn.cursor(dictionary=True)

    reg_cols = get_table_columns(conn, "registrations")
    att_cols = get_table_columns(conn, "attendance")

    # Verify registration exists
    cursor.execute(
        "SELECT id FROM registrations WHERE user_id = %s AND event_id = %s",
        (user_id, event_id),
    )
    reg_row = cursor.fetchone()
    if not reg_row:
        cursor.close()
        conn.close()
        return jsonify({"status": "error", "message": "No registration found for this QR."}), 404

    if "registration_id" in att_cols:
        # Old attendance schema: attendance(registration_id, attended_at)
        cursor.execute(
            """
            SELECT a.id
            FROM attendance a
            JOIN registrations r ON a.registration_id = r.id
            WHERE r.user_id = %s AND r.event_id = %s
            """,
            (user_id, event_id),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.close()
            conn.close()
            return jsonify({"status": "ok", "message": "Attendance already marked."}), 200

        cursor.execute(
            "INSERT INTO attendance (registration_id, attended_at) VALUES (%s, %s)",
            (reg_row["id"], datetime.utcnow()),
        )
        conn.commit()
    else:
        # New attendance schema: attendance(user_id, event_id, status, attendance_time)
        cursor.execute(
            "SELECT id FROM attendance WHERE user_id = %s AND event_id = %s",
            (user_id, event_id),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.close()
            conn.close()
            return jsonify({"status": "ok", "message": "Attendance already marked."}), 200

        cursor.execute(
            """
            INSERT INTO attendance (user_id, event_id, status, attendance_time)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, event_id, "Present", datetime.utcnow()),
        )
        conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status": "ok", "message": "Attendance marked successfully."}), 200


if __name__ == "__main__":
    # Initialize database tables on first run
    init_db()
    # Run Flask development server
    app.run(host="0.0.0.0", port=5000, debug=True)

