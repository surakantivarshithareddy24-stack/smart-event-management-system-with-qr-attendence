## Smart Event Management System (Flask + MySQL)

This is a beginner-friendly Smart Event Management System built with **Python Flask**, **MySQL**, **HTML**, **CSS**, and **JavaScript**.

### Features
- **User registration and login**
- **Admin panel** to create events
- **Event registration** for logged-in users
- **QR code generation** after event registration
- **Webcam-based QR scanner** (admin) to mark attendance
- **MySQL database** for users, events, registrations, and attendance

### Project Structure
- `app.py` – main Flask application
- `templates/`
  - `login.html`
  - `register.html`
  - `dashboard.html`
  - `admin.html`
  - `qr_scanner.html`
- `static/`
  - `style.css`
  - `script.js`
- `requirements.txt`

### 1. Create MySQL Database

Open MySQL (Workbench, CLI, etc.) and run:

```sql
CREATE DATABASE smart_event_db;
```

If you want a different database name, also change `DB_NAME` at the top of `app.py`.

### 2. Configure Database Credentials

In `app.py`, at the top, set your MySQL username and password:

```python
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = ""          # Put your password here
DB_NAME = "smart_event_db"
```

### 3. Install Python Dependencies

In a terminal inside the project folder:

```bash
pip install -r requirements.txt
```

### 4. Run the Application

From the project folder:

```bash
python app.py
```

Then open your browser and go to:

```text
http://127.0.0.1:5000
```

### 5. Default Admin Login

On first run, the app creates a default admin user:

- Email: `admin@example.com`
- Password: `admin123`

Use this account to log in and open the **Admin Panel** to create events and use the **QR Scanner**.

### 6. Notes

- Passwords are stored in plain text for simplicity (for learning only).  
  In real applications, always hash passwords (e.g. using `werkzeug.security`).
- The QR scanner uses the `html5-qrcode` JS library via CDN and needs **camera permission** in the browser.

