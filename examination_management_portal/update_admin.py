
import os
import sqlite3
from getpass import getpass
from werkzeug.security import generate_password_hash

DB = os.path.join(os.path.dirname(__file__), "emp.sqlite3")

old_email = input("Enter existing admin email: ").strip().lower()
new_email = input("Enter new admin email: ").strip().lower()
new_password = getpass("Enter new admin password: ")

if len(new_password) < 8:
    print("Password must contain at least 8 characters.")
else:
    conn = sqlite3.connect(DB)

    cursor = conn.execute(
        """
        UPDATE users
        SET email=?, password=?
        WHERE email=? AND role='admin'
        """,
        (
            new_email,
            generate_password_hash(new_password),
            old_email
        )
    )

    conn.commit()

    if cursor.rowcount == 1:
        print("Admin credentials updated successfully!")
    else:
        print("Admin not found. Check the existing email.")

    conn.close()
