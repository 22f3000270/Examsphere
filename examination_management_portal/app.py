
# ============================================================
# EXAMINATION MANAGEMENT PORTAL
# Backend: Flask
# Database: SQLite
# Authentication: Flask-Login
# Frontend: HTML, CSS, Bootstrap and Jinja2
# ============================================================


# ============================================================
# 1. IMPORTS
# ============================================================

import os
import sqlite3

from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort
)

from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


# ============================================================
# 2. APPLICATION CONFIGURATION
# ============================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "EMP_SECRET_KEY",
    "local-demo-change-this-secret"
)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# Database file is stored in the same folder as app.py.
DB = os.path.join(
    os.path.dirname(__file__),
    "emp.sqlite3"
)


# ============================================================
# 3. DATABASE CONNECTION
# ============================================================

def conn():
    """Create and return a database connection."""

    connection = sqlite3.connect(DB)

    # Return database rows as dictionary-like objects.
    connection.row_factory = sqlite3.Row

    # Enable foreign key validation.
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ============================================================
# 4. COMMON HELPER FUNCTIONS
# ============================================================

def now():
    """Return the current date and time."""

    return datetime.now().strftime("%Y-%m-%d %H:%M")


def dt(value):
    """Convert a stored date/time string into a datetime object."""

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M"
        )

    except (ValueError, TypeError):

        try:
            return datetime.strptime(
                value,
                "%Y-%m-%d %H:%M"
            )

        except (ValueError, TypeError):
            return None


def setting(key):
    """Read a portal setting from the database."""

    connection = conn()

    result = connection.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()

    connection.close()

    return result["value"] if result else "0"


# ============================================================
# 5. BOOKING HELPER FUNCTIONS
# ============================================================

def refresh(connection, slot_id):
    """
    Update a slot's status based on its booking count.

    If all seats are booked, mark the slot as Full.
    Otherwise, mark it as Available.
    """

    result = connection.execute("""
        SELECT
            s.capacity,
            s.status,
            COUNT(b.id) AS booked_count

        FROM slots s

        LEFT JOIN bookings b
            ON b.slot_id = s.id
            AND b.status = 'Booked'

        WHERE s.id = ?

        GROUP BY s.id
    """, (slot_id,)).fetchone()

    if result and result["status"] not in (
        "Cancelled",
        "Completed"
    ):

        new_status = (
            "Full"
            if result["booked_count"] >= result["capacity"]
            else "Available"
        )

        connection.execute("""
            UPDATE slots
            SET status = ?
            WHERE id = ?
        """, (new_status, slot_id))


def active_exam_booking(
    connection,
    student_id,
    exam_id,
    exclude=None
):
    """
    Check whether a student already has
    an active booking for the same examination.
    """

    sql = """
        SELECT COUNT(*) AS total

        FROM bookings b

        JOIN slots s
            ON s.id = b.slot_id

        WHERE b.student_id = ?
          AND s.exam_id = ?
          AND b.status = 'Booked'
    """

    params = [student_id, exam_id]

    if exclude:

        sql += " AND b.id <> ?"
        params.append(exclude)

    result = connection.execute(
        sql,
        params
    ).fetchone()

    return result["total"]


# ============================================================
# 6. DATABASE INITIALIZATION
# ============================================================

def init_db():
    """Create all required database tables and default settings."""

    connection = conn()

    connection.executescript("""

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            department TEXT DEFAULT '',
            contact TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            approved INTEGER DEFAULT 1,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'Active'
        );

        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY,
            course_id INTEGER NOT NULL REFERENCES courses(id),
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            duration INTEGER NOT NULL,
            max_marks REAL NOT NULL,
            no_of_slots INTEGER NOT NULL DEFAULT 10,
            slot_start TEXT NOT NULL,
            slot_end TEXT NOT NULL,
            book_start TEXT NOT NULL,
            book_end TEXT NOT NULL,
            status TEXT DEFAULT 'Draft',
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS rubrics (
            id INTEGER PRIMARY KEY,
            exam_id INTEGER NOT NULL REFERENCES exams(id),
            criterion TEXT NOT NULL,
            max_marks REAL NOT NULL,
            weightage REAL DEFAULT 100,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS assignments (
            exam_id INTEGER REFERENCES exams(id),
            examiner_id INTEGER REFERENCES users(id),
            PRIMARY KEY(exam_id, examiner_id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY,
            exam_id INTEGER REFERENCES exams(id),
            examiner_id INTEGER REFERENCES users(id),
            day TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            status TEXT DEFAULT 'Available',
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY,
            student_id INTEGER REFERENCES users(id),
            slot_id INTEGER REFERENCES slots(id),
            booked TEXT,
            status TEXT DEFAULT 'Booked',
            updated TEXT
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY,
            booking_id INTEGER UNIQUE REFERENCES bookings(id),
            examiner_id INTEGER REFERENCES users(id),
            total REAL,
            remarks TEXT,
            published INTEGER DEFAULT 0,
            evaluated TEXT
        );

        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY,
            evaluation_id INTEGER REFERENCES evaluations(id),
            rubric_id INTEGER REFERENCES rubrics(id),
            marks REAL,
            remarks TEXT DEFAULT ''
        );

    """)

    # Migration for databases created before no_of_slots existed.
    columns = [
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(exams)"
        ).fetchall()
    ]

    if "no_of_slots" not in columns:

        connection.execute("""
            ALTER TABLE exams
            ADD COLUMN no_of_slots INTEGER NOT NULL DEFAULT 10
        """)

    # Create default portal settings.
    for key in (
        "slot_creation_open",
        "booking_open"
    ):

        connection.execute(
            "INSERT OR IGNORE INTO settings VALUES (?, '0')",
            (key,)
        )

    # Create the default administrator if no admin exists.
    admin_exists = connection.execute("""
        SELECT id
        FROM users
        WHERE role = 'admin'
    """).fetchone()

    if not admin_exists:

        connection.execute("""
            INSERT INTO users (
                name,
                email,
                password,
                role,
                department,
                active,
                approved,
                created
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "System Administrator",
            "22f3000270@ds.study.iitm.ac.in",
            generate_password_hash("Oneplus@03031991"),
            "admin",
            "Administration",
            1,
            1,
            now()
        ))

    connection.commit()
    connection.close()


# ============================================================
# 7. USER MODEL AND LOGIN MANAGEMENT
# ============================================================

class User(UserMixin):
    """Represent a logged-in portal user."""

    def __init__(self, row):

        self.id = row["id"]
        self.name = row["name"]
        self.email = row["email"]
        self.role = row["role"]
        self.active = row["active"]
        self.approved = row["approved"]
        self.department = row["department"]
        self.contact = row["contact"]


@login_manager.user_loader
def load_user(user_id):
    """Load a user from the database using their ID."""

    connection = conn()

    user = connection.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    connection.close()

    return User(user) if user else None


# ============================================================
# 8. ROLE-BASED ACCESS CONTROL
# ============================================================

def gate(*roles):
    """
    Restrict a page to selected user roles.

    Example:
    @gate("admin")
    @gate("student")
    @gate("admin", "student")
    """

    def decorator(function):

        @wraps(function)
        @login_required
        def wrapper(*args, **kwargs):

            # Check user role.
            if current_user.role not in roles:
                abort(403)

            # Check whether the account is active.
            if not current_user.active:

                logout_user()

                flash(
                    "Account inactive.",
                    "danger"
                )

                return redirect(url_for("login"))

            # Check examiner approval.
            if (
                current_user.role == "examiner"
                and not current_user.approved
            ):

                return redirect(url_for("pending"))

            return function(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================
# 9. GLOBAL TEMPLATE VARIABLES
# ============================================================

@app.context_processor
def globals():
    """Make portal settings available in all templates."""

    return {
        "slot_creation_open": setting("slot_creation_open"),
        "booking_open": setting("booking_open")
    }


# ============================================================
# 10. HOME PAGE
# ============================================================

@app.route("/")
def home():

    if current_user.is_authenticated:

        return redirect(url_for("dashboard"))

    return render_template("home.html")


# ============================================================
# 11. USER REGISTRATION
# ============================================================

@app.route("/register/<role>", methods=["GET", "POST"])
def register(role):

    # Only student and examiner registration is allowed.
    if role not in ("student", "examiner"):
        abort(404)

    if request.method == "POST":

        form = request.form

        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")

        if (
            len(password) < 8
            or not name
            or not email
        ):

            flash(
                "Name, email and password (8+ characters) are required.",
                "danger"
            )

        else:

            connection = conn()

            try:

                # New examiners require administrator approval.
                approved = 0 if role == "examiner" else 1

                connection.execute("""
                    INSERT INTO users (
                        name,
                        email,
                        password,
                        role,
                        department,
                        contact,
                        active,
                        approved,
                        created
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    name,
                    email,
                    generate_password_hash(password),
                    role,
                    form.get("department", ""),
                    form.get("contact", ""),
                    1,
                    approved,
                    now()
                ))

                connection.commit()
                connection.close()

                if role == "examiner":

                    flash(
                        "Registration complete. Examiner approval is required.",
                        "success"
                    )

                else:

                    flash(
                        "Registration complete. Sign in now.",
                        "success"
                    )

                return redirect(url_for("login"))

            except sqlite3.IntegrityError:

                connection.close()

                flash(
                    "Email already registered.",
                    "danger"
                )

    return render_template(
        "register.html",
        role=role
    )


# ============================================================
# 12. USER LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        connection = conn()

        user = connection.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        connection.close()

        if (
            user
            and user["active"]
            and check_password_hash(
                user["password"],
                password
            )
        ):

            login_user(User(user))

            if (
                user["role"] == "examiner"
                and not user["approved"]
            ):

                return redirect(url_for("pending"))

            return redirect(url_for("dashboard"))

        flash(
            "Invalid credentials or inactive account.",
            "danger"
        )

    return render_template("login.html")


# ============================================================
# 13. EXAMINER APPROVAL PENDING PAGE
# ============================================================

@app.route("/pending")
@login_required
def pending():

    if (
        current_user.role != "examiner"
        or current_user.approved
    ):

        return redirect(url_for("dashboard"))

    return render_template("pending.html")


# ============================================================
# 14. USER LOGOUT
# ============================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(url_for("login"))


# ============================================================
# 15. ROLE-BASED DASHBOARD
# ============================================================

@app.route("/dashboard")
@gate("admin", "examiner", "student")
def dashboard():

    connection = conn()

    # --------------------------------------------------------
    # ADMIN DASHBOARD
    # --------------------------------------------------------

    if current_user.role == "admin":

        counts = {}

        # Count records in the main tables.
        for table in (
            "courses",
            "exams",
            "slots",
            "bookings"
        ):

            counts[table] = connection.execute(
                f"SELECT COUNT(*) AS total FROM {table}"
            ).fetchone()["total"]

        # Count examiners and students.
        for role in ("examiner", "student"):

            counts[role + "s"] = connection.execute("""
                SELECT COUNT(*) AS total
                FROM users
                WHERE role=?
            """, (role,)).fetchone()["total"]

        # Count examiners awaiting approval.
        pending_count = connection.execute("""
            SELECT COUNT(*) AS total
            FROM users
            WHERE role='examiner'
              AND approved=0
        """).fetchone()["total"]

        # Fetch latest bookings.
        rows = connection.execute("""
            SELECT
                b.id,
                b.status,
                u.name AS student,
                e.name AS exam,
                s.day,
                s.start

            FROM bookings b

            JOIN users u
                ON u.id = b.student_id

            JOIN slots s
                ON s.id = b.slot_id

            JOIN exams e
                ON e.id = s.exam_id

            ORDER BY b.id DESC
            LIMIT 10
        """).fetchall()

        connection.close()

        return render_template(
            "admin_dashboard.html",
            counts=counts,
            pending=pending_count,
            rows=rows
        )

    # --------------------------------------------------------
    # EXAMINER DASHBOARD
    # --------------------------------------------------------

    if current_user.role == "examiner":

        # Fetch examinations assigned to the examiner.
        exams = connection.execute("""
            SELECT e.*

            FROM exams e

            JOIN assignments a
                ON a.exam_id = e.id

            WHERE a.examiner_id = ?
        """, (current_user.id,)).fetchall()

        # Fetch examiner's slots and booking counts.
        slots = connection.execute("""
            SELECT
                s.*,
                e.name AS exam,

                (
                    SELECT COUNT(*)
                    FROM bookings b
                    WHERE b.slot_id = s.id
                      AND b.status = 'Booked'
                ) AS booked

            FROM slots s

            JOIN exams e
                ON e.id = s.exam_id

            WHERE s.examiner_id = ?

            ORDER BY s.day, s.start
        """, (current_user.id,)).fetchall()

        # Count bookings awaiting evaluation.
        pending_count = connection.execute("""
            SELECT COUNT(*) AS total

            FROM bookings b

            JOIN slots s
                ON s.id = b.slot_id

            LEFT JOIN evaluations v
                ON v.booking_id = b.id

            WHERE s.examiner_id = ?
              AND b.status = 'Booked'
              AND v.id IS NULL
        """, (current_user.id,)).fetchone()["total"]

        connection.close()

        return render_template(
            "examiner_dashboard.html",
            exams=exams,
            slots=slots,
            pend=pending_count
        )

    # --------------------------------------------------------
    # STUDENT DASHBOARD
    # --------------------------------------------------------

    # Calculate remaining available seats for each examination.
    exams = connection.execute("""
        SELECT
            e.*,
            co.code,
            co.name AS course,

            (
                SELECT COALESCE(
                    SUM(
                        s.capacity - (
                            SELECT COUNT(*)
                            FROM bookings b
                            WHERE b.slot_id = s.id
                              AND b.status = 'Booked'
                        )
                    ),
                    0
                )

                FROM slots s

                WHERE s.exam_id = e.id
                  AND s.status = 'Available'

                  AND s.capacity > (
                      SELECT COUNT(*)
                      FROM bookings b
                      WHERE b.slot_id = s.id
                        AND b.status = 'Booked'
                  )

            ) AS avail

        FROM exams e

        JOIN courses co
            ON co.id = e.course_id

        WHERE e.status <> 'Draft'

        ORDER BY e.id DESC
    """).fetchall()

    # Fetch the student's booking history.
    bookings = connection.execute("""
        SELECT
            b.*,
            s.day,
            s.start,
            s.end,
            e.name AS exam,
            u.name AS examiner,
            v.total,
            v.remarks,
            v.published

        FROM bookings b

        JOIN slots s
            ON s.id = b.slot_id

        JOIN exams e
            ON e.id = s.exam_id

        JOIN users u
            ON u.id = s.examiner_id

        LEFT JOIN evaluations v
            ON v.booking_id = b.id

        WHERE b.student_id = ?

        ORDER BY b.id DESC
    """, (current_user.id,)).fetchall()

    connection.close()

    return render_template(
        "student_dashboard.html",
        exams=exams,
        bookings=bookings
    )


# ============================================================
# 16. USER PROFILE MANAGEMENT
# ============================================================

@app.route("/profile", methods=["GET", "POST"])
@gate("student", "examiner")
def profile():

    connection = conn()

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        department = request.form.get(
            "department",
            ""
        )

        contact = request.form.get(
            "contact",
            ""
        )

        if not name:

            flash(
                "Name is required.",
                "danger"
            )

        else:

            connection.execute("""
                UPDATE users

                SET
                    name=?,
                    department=?,
                    contact=?

                WHERE id=?
            """, (
                name,
                department,
                contact,
                current_user.id
            ))

            connection.commit()
            connection.close()

            flash(
                "Profile updated.",
                "success"
            )

            return redirect(url_for("profile"))

    user = connection.execute(
        "SELECT * FROM users WHERE id=?",
        (current_user.id,)
    ).fetchone()

    connection.close()

    return render_template(
        "profile.html",
        r=user
    )


# ============================================================
# 17. COURSE, EXAM AND RUBRIC MANAGEMENT
# ============================================================

@app.route("/admin/<kind>", methods=["GET", "POST"])
@gate("admin")
def admin_crud(kind):

    # Only these three modules are supported.
    if kind not in (
        "courses",
        "exams",
        "rubrics"
    ):

        abort(404)

    connection = conn()

    # --------------------------------------------------------
    # CREATE, UPDATE OR DELETE RECORDS
    # --------------------------------------------------------

    if request.method == "POST":

        action = request.form.get("action")

        # DELETE RECORD
        if action == "delete":

            try:

                connection.execute(
                    f"DELETE FROM {kind} WHERE id=?",
                    (request.form.get("id"),)
                )

                connection.commit()

                flash(
                    "Record deleted.",
                    "success"
                )

            except sqlite3.IntegrityError:

                flash(
                    "Record has linked history and cannot be deleted.",
                    "danger"
                )

        # SAVE RECORD
        elif action == "save":

            form = request.form

            try:

                # ------------------------------------------------
                # COURSE MANAGEMENT
                # ------------------------------------------------

                if kind == "courses":

                    data = (
                        form.get("code", "").strip().upper(),
                        form.get("name", "").strip(),
                        form.get("description", ""),
                        form.get("status", "Active")
                    )

                    if not data[0] or not data[1]:

                        raise ValueError(
                            "Course code and name are required."
                        )

                    if form.get("id"):

                        connection.execute("""
                            UPDATE courses

                            SET
                                code=?,
                                name=?,
                                description=?,
                                status=?

                            WHERE id=?
                        """, data + (form["id"],))

                    else:

                        connection.execute("""
                            INSERT INTO courses (
                                code,
                                name,
                                description,
                                status
                            )
                            VALUES (?, ?, ?, ?)
                        """, data)

                # ------------------------------------------------
                # EXAM MANAGEMENT
                # ------------------------------------------------

                elif kind == "exams":

                    # Validate numeric fields.
                    try:

                        no_of_slots = int(
                            form.get("no_of_slots", 10)
                        )

                        duration = int(
                            form.get("duration", 30)
                        )

                        max_marks = float(
                            form.get("max_marks", 100)
                        )

                    except (ValueError, TypeError):

                        raise ValueError(
                            "Enter valid duration, marks and number of slots."
                        )

                    if no_of_slots < 1:

                        raise ValueError(
                            "Number of slots must be at least 1."
                        )

                    if duration < 1 or max_marks <= 0:

                        raise ValueError(
                            "Duration and maximum marks must be positive."
                        )

                    data = (
                        form.get("course_id"),
                        form.get("name", "").strip(),
                        form.get("type", "Viva"),
                        duration,
                        max_marks,
                        no_of_slots,
                        form.get("slot_start"),
                        form.get("slot_end"),
                        form.get("book_start"),
                        form.get("book_end"),
                        form.get("status", "Draft"),
                        form.get("description", "")
                    )

                    # Validate examination dates.
                    slot_start = dt(data[6])
                    slot_end = dt(data[7])
                    book_start = dt(data[8])
                    book_end = dt(data[9])

                    if (
                        not data[0]
                        or not data[1]
                        or not data[2]
                        or not all(data[6:10])
                        or not all((
                            slot_start,
                            slot_end,
                            book_start,
                            book_end
                        ))
                        or slot_start > slot_end
                        or book_start > book_end
                    ):

                        raise ValueError(
                            "Check required fields and date windows."
                        )

                    if form.get("id"):

                        connection.execute("""
                            UPDATE exams

                            SET
                                course_id=?,
                                name=?,
                                type=?,
                                duration=?,
                                max_marks=?,
                                no_of_slots=?,
                                slot_start=?,
                                slot_end=?,
                                book_start=?,
                                book_end=?,
                                status=?,
                                description=?

                            WHERE id=?
                        """, data + (form["id"],))

                    else:

                        connection.execute("""
                            INSERT INTO exams (
                                course_id,
                                name,
                                type,
                                duration,
                                max_marks,
                                no_of_slots,
                                slot_start,
                                slot_end,
                                book_start,
                                book_end,
                                status,
                                description
                            )

                            VALUES (
                                ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?
                            )
                        """, data)

                # ------------------------------------------------
                # RUBRIC MANAGEMENT
                # ------------------------------------------------

                else:

                    data = (
                        form.get("exam_id"),
                        form.get("criterion", ""),
                        form.get("max_marks", 0),
                        form.get("weightage", 100),
                        form.get("description", "")
                    )

                    if form.get("id"):

                        connection.execute("""
                            UPDATE rubrics

                            SET
                                exam_id=?,
                                criterion=?,
                                max_marks=?,
                                weightage=?,
                                description=?

                            WHERE id=?
                        """, data + (form["id"],))

                    else:

                        connection.execute("""
                            INSERT INTO rubrics (
                                exam_id,
                                criterion,
                                max_marks,
                                weightage,
                                description
                            )

                            VALUES (?, ?, ?, ?, ?)
                        """, data)

                connection.commit()

                flash(
                    "Record saved.",
                    "success"
                )

            except (
                sqlite3.IntegrityError,
                ValueError
            ) as error:

                connection.rollback()

                flash(
                    str(error) or "Please check the entered fields.",
                    "danger"
                )

        connection.close()

        return redirect(
            url_for("admin_crud", kind=kind)
        )

    # --------------------------------------------------------
    # FETCH RECORDS FOR DISPLAY
    # --------------------------------------------------------

    edit = None

    if request.args.get("edit"):

        edit = connection.execute(
            f"SELECT * FROM {kind} WHERE id=?",
            (request.args.get("edit"),)
        ).fetchone()

    rows = connection.execute(
        f"SELECT * FROM {kind} ORDER BY id DESC"
    ).fetchall()

    courses = []
    exams = []

    if kind == "exams":

        courses = connection.execute("""
            SELECT *
            FROM courses
            WHERE status='Active'
        """).fetchall()

        rows = connection.execute("""
            SELECT
                e.*,
                co.code AS course_code

            FROM exams e

            JOIN courses co
                ON co.id = e.course_id

            ORDER BY e.id DESC
        """).fetchall()

    if kind == "rubrics":

        exams = connection.execute("""
            SELECT *
            FROM exams
        """).fetchall()

        rows = connection.execute("""
            SELECT
                r.*,
                e.name AS exam_name

            FROM rubrics r

            JOIN exams e
                ON e.id = r.exam_id

            ORDER BY r.id DESC
        """).fetchall()

    connection.close()

    return render_template(
        "crud.html",
        kind=kind,
        rows=rows,
        edit=edit,
        courses=courses,
        exams=exams
    )


# ============================================================
# 18. ADMIN USER MANAGEMENT
# ============================================================

@app.route("/admin/users", methods=["GET", "POST"])
@gate("admin")
def users():

    connection = conn()

    if request.method == "POST":

        user_id = request.form["id"]
        action = request.form["action"]

        if action == "approve":

            connection.execute("""
                UPDATE users
                SET approved=1
                WHERE id=?
                  AND role='examiner'
            """, (user_id,))

        elif action == "deactivate":

            connection.execute("""
                UPDATE users
                SET active=0
                WHERE id=?
                  AND role<>'admin'
            """, (user_id,))

        elif action == "activate":

            connection.execute("""
                UPDATE users
                SET active=1
                WHERE id=?
                  AND role<>'admin'
            """, (user_id,))

        connection.commit()
        connection.close()

        return redirect(url_for("users"))

    search = request.args.get("q", "")

    rows = connection.execute("""
        SELECT *

        FROM users

        WHERE role <> 'admin'

          AND (
              name LIKE ?
              OR email LIKE ?
              OR CAST(id AS TEXT) LIKE ?
          )

        ORDER BY role, name
    """, (
        f"%{search}%",
        f"%{search}%",
        f"%{search}%"
    )).fetchall()

    connection.close()

    return render_template(
        "users.html",
        rows=rows,
        q=search
    )


# ============================================================
# 19. EXAMINER ASSIGNMENT MANAGEMENT
# ============================================================

@app.route("/admin/assignments", methods=["GET", "POST"])
@gate("admin")
def assignments():

    connection = conn()

    if request.method == "POST":

        action = request.form.get("action")
        exam_id = request.form.get("exam_id")
        examiner_id = request.form.get("examiner_id")

        try:

            if not exam_id or not examiner_id:

                raise ValueError(
                    "Please select both an exam and an examiner."
                )

            # Check that examination exists.
            exam = connection.execute("""
                SELECT id, name
                FROM exams
                WHERE id=?
            """, (exam_id,)).fetchone()

            # Check that examiner exists, is approved and active.
            examiner = connection.execute("""
                SELECT id, name

                FROM users

                WHERE id=?
                  AND role='examiner'
                  AND approved=1
                  AND active=1
            """, (examiner_id,)).fetchone()

            if not exam:

                raise ValueError(
                    "Selected examination does not exist."
                )

            if not examiner:

                raise ValueError(
                    "Examiner is not approved or active."
                )

            # ASSIGN EXAMINER
            if action == "assign":

                existing = connection.execute("""
                    SELECT 1

                    FROM assignments

                    WHERE exam_id=?
                      AND examiner_id=?
                """, (
                    exam_id,
                    examiner_id
                )).fetchone()

                if existing:

                    flash(
                        "This examiner is already assigned to this exam.",
                        "warning"
                    )

                else:

                    connection.execute("""
                        INSERT INTO assignments (
                            exam_id,
                            examiner_id
                        )

                        VALUES (?, ?)
                    """, (
                        exam_id,
                        examiner_id
                    ))

                    connection.commit()

                    flash(
                        f"{examiner['name']} assigned to {exam['name']} successfully.",
                        "success"
                    )

            # REMOVE EXAMINER
            elif action == "remove":

                connection.execute("""
                    DELETE FROM assignments

                    WHERE exam_id=?
                      AND examiner_id=?
                """, (
                    exam_id,
                    examiner_id
                ))

                connection.commit()

                flash(
                    "Assignment removed successfully.",
                    "success"
                )

            else:

                raise ValueError(
                    "Invalid assignment action."
                )

        except (
            sqlite3.IntegrityError,
            ValueError
        ) as error:

            connection.rollback()

            flash(
                str(error),
                "danger"
            )

        connection.close()

        return redirect(url_for("assignments"))

    # Fetch examinations.
    exams = connection.execute("""
        SELECT id, name
        FROM exams
        ORDER BY name
    """).fetchall()

    # Fetch approved and active examiners.
    examiners = connection.execute("""
        SELECT id, name, email

        FROM users

        WHERE role='examiner'
          AND approved=1
          AND active=1

        ORDER BY name
    """).fetchall()

    # Fetch existing assignments.
    rows = connection.execute("""
        SELECT
            a.*,
            e.name AS exam,
            u.name AS examiner

        FROM assignments a

        JOIN exams e
            ON e.id = a.exam_id

        JOIN users u
            ON u.id = a.examiner_id

        ORDER BY e.name, u.name
    """).fetchall()

    connection.close()

    return render_template(
        "assignments.html",
        exams=exams,
        examiners=examiners,
        rows=rows
    )


# ============================================================
# 20. PORTAL SETTINGS
# ============================================================

@app.route("/admin/settings", methods=["GET", "POST"])
@gate("admin")
def settings():

    connection = conn()

    if request.method == "POST":

        # Update slot creation and booking controls.
        for key in (
            "slot_creation_open",
            "booking_open"
        ):

            value = (
                "1"
                if request.form.get(key)
                else "0"
            )

            connection.execute("""
                INSERT INTO settings (key, value)

                VALUES (?, ?)

                ON CONFLICT(key)
                DO UPDATE SET value=excluded.value
            """, (
                key,
                value
            ))

        connection.commit()
        connection.close()

        flash(
            "Portal windows updated.",
            "success"
        )

        return redirect(url_for("settings"))

    connection.close()

    return render_template("settings.html")


# ============================================================
# 21. SLOT LISTING
# ============================================================

@app.route("/slots")
@gate("examiner", "student")
def slots():

    connection = conn()

    search = request.args.get("q", "")

    # EXAMINER VIEW
    if current_user.role == "examiner":

        rows = connection.execute("""
            SELECT
                s.*,
                e.name AS exam,

                (
                    SELECT COUNT(*)
                    FROM bookings b
                    WHERE b.slot_id = s.id
                      AND b.status = 'Booked'
                ) AS booked

            FROM slots s

            JOIN exams e
                ON e.id = s.exam_id

            WHERE s.examiner_id = ?

            ORDER BY s.day, s.start
        """, (current_user.id,)).fetchall()

        connection.close()

        return render_template(
            "slots.html",
            rows=rows,
            mode="examiner",
            q=search
        )

    # STUDENT VIEW
    rows = connection.execute("""
        SELECT
            s.*,
            e.name AS exam,
            co.code,

            (
                SELECT COUNT(*)
                FROM bookings b
                WHERE b.slot_id = s.id
                  AND b.status = 'Booked'
            ) AS booked,

            u.name AS examiner

        FROM slots s

        JOIN exams e
            ON e.id = s.exam_id

        JOIN courses co
            ON co.id = e.course_id

        JOIN users u
            ON u.id = s.examiner_id

        WHERE s.status = 'Available'
          AND e.name LIKE ?

        ORDER BY s.day, s.start
    """, (f"%{search}%",)).fetchall()

    connection.close()

    return render_template(
        "slots.html",
        rows=rows,
        mode="student",
        q=search
    )


# ============================================================
# 22. CREATE EXAMINATION SLOT
# ============================================================

@app.route("/slots/create", methods=["GET", "POST"])
@gate("examiner")
def create_slot():

    # Check whether administrator has opened slot creation.
    if setting("slot_creation_open") != "1":

        flash(
            "Admin has closed slot creation.",
            "warning"
        )

        return redirect(url_for("slots"))

    connection = conn()

    if request.method == "POST":

        form = request.form
        exam_id = form.get("exam_id")

        # Check whether this examiner is assigned to the exam.
        exam = connection.execute("""
            SELECT e.*

            FROM exams e

            JOIN assignments a
                ON a.exam_id = e.id

            WHERE e.id = ?
              AND a.examiner_id = ?
        """, (
            exam_id,
            current_user.id
        )).fetchone()

        if not exam:

            flash(
                "You are not assigned to this examination.",
                "danger"
            )

        else:

            # Check maximum permitted slots.
            existing_slots = connection.execute("""
                SELECT COUNT(*) AS total

                FROM slots

                WHERE exam_id = ?
            """, (exam_id,)).fetchone()["total"]

            if existing_slots >= exam["no_of_slots"]:

                flash(
                    "Maximum number of slots for this examination reached.",
                    "danger"
                )

            else:

                # Validate seat capacity.
                try:

                    capacity = int(
                        form.get("capacity", 0)
                    )

                except (ValueError, TypeError):

                    capacity = 0

                start_date = dt(exam["slot_start"])
                end_date = dt(exam["slot_end"])

                # Validate selected date.
                try:

                    selected_day = datetime.strptime(
                        form.get("day", ""),
                        "%Y-%m-%d"
                    ).date()

                except (ValueError, TypeError):

                    selected_day = None

                if (
                    not start_date
                    or not end_date
                    or not selected_day
                    or not (
                        start_date.date()
                        <= selected_day
                        <= end_date.date()
                    )
                    or not form.get("start")
                    or not form.get("end")
                    or form.get("start") >= form.get("end")
                    or capacity <= 0
                ):

                    flash(
                        "Check examination dates, time range or capacity.",
                        "danger"
                    )

                else:

                    # Create examination slot.
                    connection.execute("""
                        INSERT INTO slots (
                            exam_id,
                            examiner_id,
                            day,
                            start,
                            end,
                            capacity,
                            status,
                            created
                        )

                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        exam_id,
                        current_user.id,
                        form["day"],
                        form["start"],
                        form["end"],
                        capacity,
                        "Available",
                        now()
                    ))

                    connection.commit()
                    connection.close()

                    flash(
                        "Slot created successfully.",
                        "success"
                    )

                    return redirect(url_for("slots"))

    # Fetch examinations assigned to this examiner.
    exams = connection.execute("""
        SELECT e.*

        FROM exams e

        JOIN assignments a
            ON a.exam_id = e.id

        WHERE a.examiner_id = ?
    """, (current_user.id,)).fetchall()

    connection.close()

    return render_template(
        "create_slot.html",
        exams=exams
    )


# ============================================================
# 23. EDIT EXAMINATION SLOT
# ============================================================

@app.route("/slots/<int:sid>/edit", methods=["GET", "POST"])
@gate("examiner")
def edit_slot(sid):

    connection = conn()

    # Fetch only the slot belonging to the logged-in examiner.
    slot = connection.execute("""
        SELECT *

        FROM slots

        WHERE id=?
          AND examiner_id=?
    """, (
        sid,
        current_user.id
    )).fetchone()

    if not slot:

        connection.close()
        abort(404)

    # Check booking history.
    booking_count = connection.execute("""
        SELECT COUNT(*) AS total

        FROM bookings

        WHERE slot_id=?
    """, (sid,)).fetchone()["total"]

    if (
        setting("booking_open") == "1"
        or booking_count
    ):

        connection.close()

        flash(
            "Cannot edit after booking opens or booking history exists.",
            "danger"
        )

        return redirect(url_for("slots"))

    if request.method == "POST":

        form = request.form

        capacity = int(
            form.get("capacity", 0) or 0
        )

        if (
            form.get("start")
            and form.get("end")
            and form.get("start") < form.get("end")
            and capacity > 0
        ):

            connection.execute("""
                UPDATE slots

                SET
                    day=?,
                    start=?,
                    end=?,
                    capacity=?

                WHERE id=?
            """, (
                form["day"],
                form["start"],
                form["end"],
                capacity,
                sid
            ))

            connection.commit()
            connection.close()

            flash(
                "Slot updated successfully.",
                "success"
            )

            return redirect(url_for("slots"))

        flash(
            "Check time and capacity.",
            "danger"
        )

    connection.close()

    return render_template(
        "edit_slot.html",
        s=slot
    )


# ============================================================
# 24. DELETE EXAMINATION SLOT
# ============================================================

@app.route("/slots/<int:sid>/delete", methods=["POST"])
@gate("examiner")
def delete_slot(sid):

    connection = conn()

    slot = connection.execute("""
        SELECT *

        FROM slots

        WHERE id=?
          AND examiner_id=?
    """, (
        sid,
        current_user.id
    )).fetchone()

    booking_count = connection.execute("""
        SELECT COUNT(*) AS total

        FROM bookings

        WHERE slot_id=?
    """, (sid,)).fetchone()["total"]

    if (
        slot
        and not booking_count
        and setting("booking_open") != "1"
    ):

        connection.execute(
            "DELETE FROM slots WHERE id=?",
            (sid,)
        )

        connection.commit()

        flash(
            "Slot deleted successfully.",
            "success"
        )

    else:

        flash(
            "Cannot delete a slot once booking opens or booking history exists.",
            "danger"
        )

    connection.close()

    return redirect(url_for("slots"))


# ============================================================
# 25. STUDENT SLOT BOOKING
# ============================================================

@app.route("/slots/<int:sid>/book", methods=["POST"])
@gate("student")
def book(sid):

    connection = conn()

    # Fetch selected slot and examination booking window.
    slot = connection.execute("""
        SELECT
            s.*,
            e.book_start,
            e.book_end,
            e.status AS exam_status

        FROM slots s

        JOIN exams e
            ON e.id = s.exam_id

        WHERE s.id=?
    """, (sid,)).fetchone()

    start = dt(slot["book_start"]) if slot else None
    end = dt(slot["book_end"]) if slot else None

    # Validate booking window and slot status.
    if not slot:

        flash(
            "Selected slot does not exist.",
            "danger"
        )

    elif setting("booking_open") != "1":

        flash(
            "Booking is currently closed by the administrator.",
            "danger"
        )

    elif not start or not end or not start <= datetime.now() <= end:

        flash(
            "Booking is outside the permitted booking window.",
            "danger"
        )

    elif slot["status"] != "Available":

        flash(
            "This slot is no longer available.",
            "danger"
        )

    elif slot["exam_status"] in (
        "Draft",
        "Closed",
        "Completed"
    ):

        flash(
            "This examination is not open for booking.",
            "danger"
        )

    # Prevent duplicate active bookings for the same exam.
    elif active_exam_booking(
        connection,
        current_user.id,
        slot["exam_id"]
    ):

        flash(
            "You already have an active booking for this exam.",
            "warning"
        )

    else:

        booked_count = connection.execute("""
            SELECT COUNT(*) AS total

            FROM bookings

            WHERE slot_id=?
              AND status='Booked'
        """, (sid,)).fetchone()["total"]

        if booked_count >= slot["capacity"]:

            flash(
                "Slot is full.",
                "danger"
            )

        else:

            # Create student booking.
            connection.execute("""
                INSERT INTO bookings (
                    student_id,
                    slot_id,
                    booked,
                    status,
                    updated
                )

                VALUES (?, ?, ?, ?, ?)
            """, (
                current_user.id,
                sid,
                now(),
                "Booked",
                now()
            ))

            refresh(connection, sid)

            connection.commit()

            flash(
                "Slot booked successfully.",
                "success"
            )

    connection.close()

    return redirect(url_for("slots"))


# ============================================================
# 26. CANCEL STUDENT BOOKING
# ============================================================

@app.route("/bookings/<int:bid>/cancel", methods=["POST"])
@gate("student")
def cancel(bid):

    connection = conn()

    booking = connection.execute("""
        SELECT
            b.*,
            s.id AS slot_id,
            e.book_end

        FROM bookings b

        JOIN slots s
            ON s.id = b.slot_id

        JOIN exams e
            ON e.id = s.exam_id

        WHERE b.id=?
          AND b.student_id=?
    """, (
        bid,
        current_user.id
    )).fetchone()

    end = dt(booking["book_end"]) if booking else None

    if not booking:

        flash(
            "Booking not found.",
            "danger"
        )

    elif booking["status"] != "Booked":

        flash(
            "This booking is no longer active.",
            "danger"
        )

    elif not end or datetime.now() > end:

        flash(
            "Booking cancellation deadline has passed.",
            "danger"
        )

    else:

        connection.execute("""
            UPDATE bookings

            SET
                status='Cancelled',
                updated=?

            WHERE id=?
        """, (
            now(),
            bid
        ))

        refresh(
            connection,
            booking["slot_id"]
        )

        connection.commit()

        flash(
            "Booking cancelled successfully.",
            "success"
        )

    connection.close()

    return redirect(url_for("dashboard"))


# ============================================================
# 27. ADMIN SLOT MANAGEMENT
# ============================================================

@app.route("/admin/slots")
@gate("admin")
def all_slots():

    search = request.args.get("q", "")

    connection = conn()

    rows = connection.execute("""
        SELECT
            s.*,
            e.name AS exam,
            u.name AS examiner,

            (
                SELECT COUNT(*)
                FROM bookings b
                WHERE b.slot_id = s.id
                  AND b.status = 'Booked'
            ) AS booked

        FROM slots s

        JOIN exams e
            ON e.id = s.exam_id

        JOIN users u
            ON u.id = s.examiner_id

        WHERE e.name LIKE ?
           OR u.name LIKE ?
           OR CAST(s.id AS TEXT) LIKE ?

        ORDER BY s.day DESC
    """, (
        f"%{search}%",
        f"%{search}%",
        f"%{search}%"
    )).fetchall()

    connection.close()

    return render_template(
        "admin_slots.html",
        rows=rows,
        q=search
    )


# ============================================================
# 28. ADMIN BOOKING MANAGEMENT
# ============================================================

@app.route("/admin/bookings", methods=["GET", "POST"])
@gate("admin")
def all_bookings():

    connection = conn()

    if request.method == "POST":

        booking_id = request.form["booking_id"]
        action = request.form["action"]

        booking = connection.execute("""
            SELECT
                b.*,
                s.exam_id,
                s.id AS oldslot

            FROM bookings b

            JOIN slots s
                ON s.id = b.slot_id

            WHERE b.id=?
        """, (booking_id,)).fetchone()

        if booking and action == "cancel":

            connection.execute("""
                UPDATE bookings

                SET
                    status='Cancelled',
                    updated=?

                WHERE id=?
            """, (
                now(),
                booking_id
            ))

            refresh(
                connection,
                booking["oldslot"]
            )

            connection.commit()

            flash(
                "Booking cancelled by Admin.",
                "success"
            )

        elif booking and action == "reschedule":

            new_slot = connection.execute("""
                SELECT *

                FROM slots

                WHERE id=?
            """, (
                request.form.get("slot_id"),
            )).fetchone()

            if (
                not new_slot
                or new_slot["exam_id"] != booking["exam_id"]
                or new_slot["status"] in (
                    "Full",
                    "Cancelled",
                    "Completed"
                )
                or active_exam_booking(
                    connection,
                    booking["student_id"],
                    booking["exam_id"],
                    booking["id"]
                )
            ):

                flash(
                    "Choose an available slot for the same exam; duplicate active bookings are not allowed.",
                    "danger"
                )

            else:

                booked_count = connection.execute("""
                    SELECT COUNT(*) AS total

                    FROM bookings

                    WHERE slot_id=?
                      AND status='Booked'
                """, (
                    new_slot["id"],
                )).fetchone()["total"]

                if booked_count >= new_slot["capacity"]:

                    flash(
                        "Target slot is full.",
                        "danger"
                    )

                else:

                    connection.execute("""
                        UPDATE bookings

                        SET
                            slot_id=?,
                            updated=?

                        WHERE id=?
                    """, (
                        new_slot["id"],
                        now(),
                        booking_id
                    ))

                    refresh(
                        connection,
                        booking["oldslot"]
                    )

                    refresh(
                        connection,
                        new_slot["id"]
                    )

                    connection.commit()

                    flash(
                        "Booking rescheduled successfully.",
                        "success"
                    )

        connection.close()

        return redirect(url_for("all_bookings"))

    # Fetch booking history.
    search = request.args.get("q", "")

    rows = connection.execute("""
        SELECT
            b.*,
            stu.name AS student,
            stu.email,
            e.name AS exam,
            s.day,
            s.start,
            s.end,
            u.name AS examiner,
            s.exam_id

        FROM bookings b

        JOIN users stu
            ON stu.id = b.student_id

        JOIN slots s
            ON s.id = b.slot_id

        JOIN exams e
            ON e.id = s.exam_id

        JOIN users u
            ON u.id = s.examiner_id

        WHERE stu.name LIKE ?
           OR stu.email LIKE ?
           OR e.name LIKE ?
           OR CAST(b.id AS TEXT) LIKE ?

        ORDER BY b.id DESC
    """, (
        f"%{search}%",
        f"%{search}%",
        f"%{search}%",
        f"%{search}%"
    )).fetchall()

    # Fetch slots that may be used for rescheduling.
    available = connection.execute("""
        SELECT
            s.*,
            e.name AS exam,
            u.name AS examiner,

            (
                SELECT COUNT(*)
                FROM bookings b
                WHERE b.slot_id = s.id
                  AND b.status = 'Booked'
            ) AS booked

        FROM slots s

        JOIN exams e
            ON e.id = s.exam_id

        JOIN users u
            ON u.id = s.examiner_id

        WHERE s.status = 'Available'
    """).fetchall()

    connection.close()

    return render_template(
        "admin_bookings.html",
        rows=rows,
        available=available,
        q=search
    )


# ============================================================
# 29. EXAMINER EVALUATION LIST
# ============================================================

@app.route("/evaluate")
@gate("examiner")
def evaluations():

    connection = conn()

    rows = connection.execute("""
        SELECT
            b.id AS bid,
            b.status,
            stu.name AS student,
            e.name AS exam,
            s.day,
            s.start,
            v.id AS evid,
            v.total,
            v.published

        FROM bookings b

        JOIN slots s
            ON s.id = b.slot_id

        JOIN exams e
            ON e.id = s.exam_id

        JOIN users stu
            ON stu.id = b.student_id

        LEFT JOIN evaluations v
            ON v.booking_id = b.id

        WHERE s.examiner_id = ?
          AND b.status IN ('Booked', 'Completed')

        ORDER BY s.day, s.start
    """, (current_user.id,)).fetchall()

    connection.close()

    return render_template(
        "evaluations.html",
        rows=rows
    )


# ============================================================
# 30. STUDENT EXAMINATION EVALUATION
# ============================================================

@app.route("/evaluate/<int:bid>", methods=["GET", "POST"])
@gate("examiner")
def evaluate(bid):

    connection = conn()

    # Fetch booking assigned to the logged-in examiner.
    booking = connection.execute("""
        SELECT
            b.*,
            stu.name AS student,
            s.exam_id,
            s.day,
            s.start,
            e.name AS exam,
            e.max_marks

        FROM bookings b

        JOIN slots s
            ON s.id = b.slot_id

        JOIN exams e
            ON e.id = s.exam_id

        JOIN users stu
            ON stu.id = b.student_id

        WHERE b.id=?
          AND s.examiner_id=?
    """, (
        bid,
        current_user.id
    )).fetchone()

    if not booking:

        connection.close()
        abort(403)

    # Fetch examination evaluation rubrics.
    rubrics = connection.execute("""
        SELECT *

        FROM rubrics

        WHERE exam_id=?
    """, (
        booking["exam_id"],
    )).fetchall()

    # Check whether evaluation already exists.
    evaluation = connection.execute("""
        SELECT *

        FROM evaluations

        WHERE booking_id=?
    """, (
        bid,
    )).fetchone()

    scoremap = {}

    if evaluation:

        scores = connection.execute("""
            SELECT *

            FROM scores

            WHERE evaluation_id=?
        """, (
            evaluation["id"],
        )).fetchall()

        scoremap = {
            score["rubric_id"]: score
            for score in scores
        }

    # --------------------------------------------------------
    # SAVE EVALUATION
    # --------------------------------------------------------

    if request.method == "POST":

        total = 0
        scoredata = []

        for rubric in rubrics:

            try:

                mark = float(
                    request.form.get(
                        "mark_" + str(rubric["id"]),
                        0
                    )
                )

            except ValueError:

                mark = -1

            if (
                mark < 0
                or mark > rubric["max_marks"]
            ):

                connection.close()

                flash(
                    "A rubric score is outside its allowed range.",
                    "danger"
                )

                return redirect(
                    url_for("evaluate", bid=bid)
                )

            total += mark

            remark = request.form.get(
                "remark_" + str(rubric["id"]),
                ""
            )

            scoredata.append((
                rubric,
                mark,
                remark
            ))

        # Check maximum examination marks.
        if total > booking["max_marks"]:

            connection.close()

            flash(
                "Total marks exceed exam maximum.",
                "danger"
            )

            return redirect(
                url_for("evaluate", bid=bid)
            )

        published = (
            1
            if request.form.get("published")
            else 0
        )

        remarks = request.form.get(
            "remarks",
            ""
        )

        # Update existing evaluation.
        if evaluation:

            connection.execute("""
                UPDATE evaluations

                SET
                    total=?,
                    remarks=?,
                    published=?,
                    evaluated=?

                WHERE id=?
            """, (
                total,
                remarks,
                published,
                now(),
                evaluation["id"]
            ))

            evaluation_id = evaluation["id"]

            # Replace previous rubric scores.
            connection.execute("""
                DELETE FROM scores

                WHERE evaluation_id=?
            """, (
                evaluation_id,
            ))

        # Create new evaluation.
        else:

            cursor = connection.execute("""
                INSERT INTO evaluations (
                    booking_id,
                    examiner_id,
                    total,
                    remarks,
                    published,
                    evaluated
                )

                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                bid,
                current_user.id,
                total,
                remarks,
                published,
                now()
            ))

            evaluation_id = cursor.lastrowid

        # Save rubric-wise marks.
        for rubric, mark, remark in scoredata:

            connection.execute("""
                INSERT INTO scores (
                    evaluation_id,
                    rubric_id,
                    marks,
                    remarks
                )

                VALUES (?, ?, ?, ?)
            """, (
                evaluation_id,
                rubric["id"],
                mark,
                remark
            ))

        # Mark the booking as completed.
        connection.execute("""
            UPDATE bookings

            SET
                status='Completed',
                updated=?

            WHERE id=?
        """, (
            now(),
            bid
        ))

        connection.commit()
        connection.close()

        flash(
            "Evaluation saved successfully.",
            "success"
        )

        return redirect(
            url_for("evaluations")
        )

    connection.close()

    return render_template(
        "evaluate.html",
        b=booking,
        rubrics=rubrics,
        ev=evaluation,
        scoremap=scoremap
    )


# ============================================================
# 31. VIEW PUBLISHED EXAMINATION RESULTS
# ============================================================

@app.route("/results/<int:bid>")
@gate("student", "admin")
def result(bid):

    connection = conn()

    sql = """
        SELECT
            v.*,
            b.student_id,
            stu.name AS student,
            e.name AS exam

        FROM evaluations v

        JOIN bookings b
            ON b.id = v.booking_id

        JOIN users stu
            ON stu.id = b.student_id

        JOIN slots s
            ON s.id = b.slot_id

        JOIN exams e
            ON e.id = s.exam_id

        WHERE b.id=?
    """

    params = [bid]

    # Students can only view their own published results.
    if current_user.role == "student":

        sql += """
            AND b.student_id=?
            AND v.published=1
        """

        params.append(current_user.id)

    evaluation = connection.execute(
        sql,
        params
    ).fetchone()

    if not evaluation:

        connection.close()
        abort(404)

    # Fetch rubric-wise scores.
    scores = connection.execute("""
        SELECT
            sc.*,
            r.criterion,
            r.max_marks

        FROM scores sc

        JOIN rubrics r
            ON r.id = sc.rubric_id

        WHERE sc.evaluation_id=?
    """, (
        evaluation["id"],
    )).fetchall()

    connection.close()

    return render_template(
        "result.html",
        ev=evaluation,
        scores=scores
    )


# ============================================================
# 32. ERROR HANDLING
# ============================================================

@app.errorhandler(403)
def forbidden(error):

    return render_template(
        "error.html",
        code=403,
        message="You do not have permission to access this page."
    ), 403


@app.errorhandler(404)
def missing(error):

    return render_template(
        "error.html",
        code=404,
        message="The requested record was not found."
    ), 404


# ============================================================
# 33. APPLICATION STARTUP
# ============================================================

if __name__ == "__main__":

    # Create database tables if they do not exist.
    init_db()

    # Start the Flask development server.
    app.run(debug=True)
