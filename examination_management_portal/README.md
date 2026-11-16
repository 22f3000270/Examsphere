# Examination Management Portal (EMP)

## Run in VS Code
1. Install Python 3.10+ and VS Code's Python extension.
2. Extract this ZIP and open the `examination_management_portal` folder.
3. Open **Terminal → New Terminal**.
4. Create a virtual environment: `py -m venv .venv` (Windows) or `python3 -m venv .venv` (macOS/Linux).
5. Activate it: `\.venv\Scripts\Activate.ps1` on Windows PowerShell, or `source .venv/bin/activate` on macOS/Linux.
6. Install packages: `python -m pip install -r requirements.txt`
7. Start: `python app.py`
8. Browse to http://127.0.0.1:5000
9. Admin credentials: `admin@emp.local` / `Admin@123`. Change these before any non-demo use.
10. Register examiner and student accounts. Approve the examiner using Admin → Users.

SQLite is created automatically as `emp.sqlite3` by Python on first run. No manual database setup is needed.

## Suggested demo
Admin: add course, add examination and rubric, approve examiner, assign examiner, open slot and booking windows. Examiner: create a slot and evaluate a booked student. Student: book a slot and view a published result. Admin can search users, exams and bookings, review all slots/bookings, reschedule bookings, and reassign examiners.

## Features / safeguards
Role-based authentication; examiner approval; admin dashboards and CRUD; slot and booking windows; capacity/overbooking prevention; one active booking per student per exam; cancellation before deadline; rubric-based evaluation; result publishing; historical booking records; profile editing; search; programmatic SQLite schema.

This is an educational local demo, not production-hardened. For production add CSRF protection, stronger secret management, HTTPS, rate limiting, audit logging and database backups. Core actions use server-rendered HTML forms rather than JavaScript.
