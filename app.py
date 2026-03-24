import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")


app = Flask(__name__)
CORS(app)
app.config["SECRET_KEY"] = "change-this-secret-key-for-production"
app.config["DATABASE"] = DATABASE
app.config["LOW_STOCK_THRESHOLD"] = 25


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    lastrowid = cur.lastrowid
    cur.close()
    return lastrowid


def get_reports_data():
    today_str = date.today().isoformat()
    current_month = date.today().strftime("%Y-%m")

    daily_orders = query_db(
        """
        SELECT * FROM orders
        WHERE order_date = ?
        ORDER BY id DESC
        """,
        (today_str,),
    )
    monthly_summary = query_db(
        """
        SELECT product, COUNT(*) AS order_count, COALESCE(SUM(quantity), 0) AS total_quantity
        FROM orders
        WHERE substr(order_date, 1, 7) = ?
        GROUP BY product
        ORDER BY total_quantity DESC, product ASC
        """,
        (current_month,),
    )
    stock_report = query_db(
        """
        SELECT category, product_name, quantity, unit, last_updated
        FROM stock
        ORDER BY category ASC, product_name ASC
        """
    )

    return {
        "daily_orders": daily_orders,
        "monthly_summary": monthly_summary,
        "stock_report": stock_report,
        "current_month": current_month,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    cursor = db.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
            created_at TEXT NOT NULL,
            full_name TEXT,
            date_of_birth TEXT,
            gender TEXT,
            email TEXT,
            phone TEXT,
            address TEXT
        )
        """
    )

    users_table_sql = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if users_table_sql and (
        "'user'" in users_table_sql[0]
        or cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'user'").fetchone()[0] > 0
    ):
        cursor.execute("ALTER TABLE users RENAME TO users_old")
        cursor.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
                created_at TEXT NOT NULL,
                full_name TEXT,
                date_of_birth TEXT,
                gender TEXT,
                email TEXT,
                phone TEXT,
                address TEXT
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO users (id, username, password_hash, role, created_at)
            SELECT
                id,
                username,
                password_hash,
                CASE WHEN role = 'user' THEN 'staff' ELSE role END,
                created_at
            FROM users_old
            """
        )
        cursor.execute("DROP TABLE users_old")

    existing_user_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()
    }
    optional_user_columns = {
        "full_name": "TEXT",
        "date_of_birth": "TEXT",
        "gender": "TEXT",
        "email": "TEXT",
        "phone": "TEXT",
        "address": "TEXT",
    }
    for column_name, column_type in optional_user_columns.items():
        if column_name not in existing_user_columns:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('Coconut', 'Tamarind')),
            quantity REAL NOT NULL,
            unit TEXT NOT NULL CHECK(unit IN ('nos', 'kg')),
            last_updated TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            product TEXT NOT NULL,
            quantity REAL NOT NULL,
            order_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Pending', 'Completed')),
            created_by INTEGER,
            FOREIGN KEY(created_by) REFERENCES users(id)
        )
        """
    )

    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if session.get("role") != "admin":
            flash("Admin access is required for that action.", "danger")
            return redirect(url_for("dashboard"))
        return view(**kwargs)

    return wrapped_view


@app.context_processor
def inject_globals():
    profile_name = session.get("full_name") or session.get("username")
    return {
        "current_user": {
            "id": session.get("user_id"),
            "username": session.get("username"),
            "full_name": session.get("full_name"),
            "profile_name": profile_name,
            "role": session.get("role"),
        },
        "today": date.today().isoformat(),
    }


@app.route("/", methods=["GET"])
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/save", methods=["POST"])
def save():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"message": "Invalid or missing JSON data"}), 400

    print(data)
    return jsonify({"message": "Saved successfully", "data": data}), 200


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        form_type = request.form.get("form_type", "login")

        if form_type == "register":
            username = request.form.get("register_username", "").strip()
            password = request.form.get("register_password", "")
            confirm_password = request.form.get("confirm_password", "")
            role = request.form.get("role", "").strip()

            if not username:
                flash("Username is required for registration.", "danger")
            elif role not in {"admin", "staff"}:
                flash("Please choose either Admin or Staff.", "danger")
            elif len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
            elif password != confirm_password:
                flash("Passwords do not match.", "danger")
            else:
                try:
                    execute_db(
                        """
                        INSERT INTO users (username, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (username, generate_password_hash(password), role, datetime.now().isoformat()),
                    )
                    flash("Registration successful. You can now log in.", "success")
                    return render_template("login.html", active_tab="login")
                except sqlite3.IntegrityError:
                    flash("That username already exists.", "danger")

            return render_template("login.html", active_tab="register")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = query_db(
            "SELECT * FROM users WHERE username = ?", (username,), one=True
        )
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")
        return render_template("login.html", active_tab="login")

    return render_template("login.html", active_tab="login")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    coconut_total = query_db(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM stock WHERE category = 'Coconut'",
        one=True,
    )["total"]
    tamarind_total = query_db(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM stock WHERE category = 'Tamarind'",
        one=True,
    )["total"]
    orders_total = query_db(
        "SELECT COUNT(*) AS total FROM orders",
        one=True,
    )["total"]
    low_stock_items = query_db(
        """
        SELECT * FROM stock
        WHERE quantity <= ?
        ORDER BY quantity ASC, product_name ASC
        """,
        (app.config["LOW_STOCK_THRESHOLD"],),
    )
    latest_orders = query_db(
        """
        SELECT o.*, u.username AS creator_name
        FROM orders o
        LEFT JOIN users u ON u.id = o.created_by
        ORDER BY o.order_date DESC, o.id DESC
        LIMIT 5
        """
    )
    staff_total = query_db(
        "SELECT COUNT(*) AS total FROM users WHERE role = 'staff'",
        one=True,
    )["total"]

    return render_template(
        "dashboard.html",
        coconut_total=coconut_total,
        tamarind_total=tamarind_total,
        orders_total=orders_total,
        low_stock_items=low_stock_items,
        latest_orders=latest_orders,
        staff_total=staff_total,
    )


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile_user = query_db(
        """
        SELECT id, username, role, created_at, full_name, date_of_birth, gender, email, phone, address
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],),
        one=True,
    )
    if not profile_user:
        session.clear()
        flash("Your session could not be matched to a valid account.", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        date_of_birth = request.form.get("date_of_birth", "").strip()
        gender = request.form.get("gender", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username:
            flash("Username is required.", "danger")
            return redirect(url_for("profile"))

        if gender and gender not in {"Male", "Female", "Other", "Prefer not to say"}:
            flash("Please choose a valid gender option.", "danger")
            return redirect(url_for("profile"))

        if email and ("@" not in email or "." not in email):
            flash("Please enter a valid email address.", "danger")
            return redirect(url_for("profile"))

        if phone and len(phone) > 20:
            flash("Phone number should be 20 characters or fewer.", "danger")
            return redirect(url_for("profile"))

        if password and len(password) < 6:
            flash("New password must be at least 6 characters.", "danger")
            return redirect(url_for("profile"))

        if password and password != confirm_password:
            flash("New password and confirmation do not match.", "danger")
            return redirect(url_for("profile"))

        try:
            if password:
                execute_db(
                    """
                    UPDATE users
                    SET username = ?, full_name = ?, date_of_birth = ?, gender = ?, email = ?, phone = ?, address = ?, password_hash = ?
                    WHERE id = ?
                    """,
                    (
                        username,
                        full_name or None,
                        date_of_birth or None,
                        gender or None,
                        email or None,
                        phone or None,
                        address or None,
                        generate_password_hash(password),
                        session["user_id"],
                    ),
                )
            else:
                execute_db(
                    """
                    UPDATE users
                    SET username = ?, full_name = ?, date_of_birth = ?, gender = ?, email = ?, phone = ?, address = ?
                    WHERE id = ?
                    """,
                    (
                        username,
                        full_name or None,
                        date_of_birth or None,
                        gender or None,
                        email or None,
                        phone or None,
                        address or None,
                        session["user_id"],
                    ),
                )
        except sqlite3.IntegrityError:
            flash("That username already exists.", "danger")
            return redirect(url_for("profile"))

        session["username"] = username
        session["full_name"] = full_name or None
        flash("Profile updated successfully.", "success")
        return redirect(url_for("profile"))

    return render_template("profile.html", profile_user=profile_user)


@app.route("/stock", methods=["GET", "POST"])
@login_required
def stock():
    if request.method == "POST":
        action = request.form.get("action")
        product_name = request.form.get("product_name", "").strip()
        category = request.form.get("category", "").strip()
        quantity_raw = request.form.get("quantity", "").strip()
        unit = request.form.get("unit", "").strip()
        stock_id = request.form.get("stock_id")

        if action == "delete":
            if session.get("role") != "admin":
                flash("Only admins can delete stock items.", "danger")
                return redirect(url_for("stock"))
            execute_db("DELETE FROM stock WHERE id = ?", (stock_id,))
            flash("Stock item deleted.", "warning")
            return redirect(url_for("stock"))

        if not product_name or category not in {"Coconut", "Tamarind"} or unit not in {"nos", "kg"}:
            flash("Please fill in a valid stock form.", "danger")
            return redirect(url_for("stock"))

        try:
            quantity = float(quantity_raw)
            if quantity < 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a non-negative number.", "danger")
            return redirect(url_for("stock"))

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if action == "add":
            execute_db(
                """
                INSERT INTO stock (product_name, category, quantity, unit, last_updated)
                VALUES (?, ?, ?, ?, ?)
                """,
                (product_name, category, quantity, unit, now),
            )
            flash("Stock item added successfully.", "success")
        elif action == "update" and stock_id:
            execute_db(
                """
                UPDATE stock
                SET product_name = ?, category = ?, quantity = ?, unit = ?, last_updated = ?
                WHERE id = ?
                """,
                (product_name, category, quantity, unit, now, stock_id),
            )
            flash("Stock item updated successfully.", "success")

        return redirect(url_for("stock"))

    edit_id = request.args.get("edit", type=int)
    edit_item = None
    if edit_id:
        edit_item = query_db("SELECT * FROM stock WHERE id = ?", (edit_id,), one=True)

    stock_items = query_db(
        "SELECT * FROM stock ORDER BY category ASC, product_name ASC, id DESC"
    )
    coconut_items = [item for item in stock_items if item["category"] == "Coconut"]
    tamarind_items = [item for item in stock_items if item["category"] == "Tamarind"]

    return render_template(
        "stock.html",
        stock_items=stock_items,
        coconut_items=coconut_items,
        tamarind_items=tamarind_items,
        edit_item=edit_item,
    )


@app.route("/orders", methods=["GET", "POST"])
@login_required
def orders():
    if request.method == "POST":
        action = request.form.get("action")
        order_id = request.form.get("order_id")

        if action == "delete":
            if session.get("role") != "admin":
                flash("Only admins can delete orders.", "danger")
                return redirect(url_for("orders"))
            execute_db("DELETE FROM orders WHERE id = ?", (order_id,))
            flash("Order deleted.", "warning")
            return redirect(url_for("orders"))

        customer_name = request.form.get("customer_name", "").strip()
        phone = request.form.get("phone", "").strip()
        product = request.form.get("product", "").strip()
        quantity_raw = request.form.get("quantity", "").strip()
        order_date = request.form.get("order_date", "").strip()
        status = request.form.get("status", "").strip()

        if not all([customer_name, phone, product, order_date]) or status not in {"Pending", "Completed"}:
            flash("Please complete all order fields correctly.", "danger")
            return redirect(url_for("orders"))

        try:
            quantity = float(quantity_raw)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            flash("Order quantity must be greater than zero.", "danger")
            return redirect(url_for("orders"))

        if action == "add":
            execute_db(
                """
                INSERT INTO orders (customer_name, phone, product, quantity, order_date, status, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_name,
                    phone,
                    product,
                    quantity,
                    order_date,
                    status,
                    session["user_id"],
                ),
            )
            flash("Order created successfully.", "success")
        elif action == "update" and order_id:
            if session.get("role") != "admin":
                flash("Only admins can edit orders.", "danger")
                return redirect(url_for("orders"))
            execute_db(
                """
                UPDATE orders
                SET customer_name = ?, phone = ?, product = ?, quantity = ?, order_date = ?, status = ?
                WHERE id = ?
                """,
                (
                    customer_name,
                    phone,
                    product,
                    quantity,
                    order_date,
                    status,
                    order_id,
                ),
            )
            flash("Order updated successfully.", "success")

        return redirect(url_for("orders"))

    edit_id = request.args.get("edit", type=int)
    edit_order = None
    if edit_id:
        if session.get("role") != "admin":
            flash("Only admins can edit orders.", "danger")
            return redirect(url_for("orders"))
        edit_order = query_db("SELECT * FROM orders WHERE id = ?", (edit_id,), one=True)

    orders_list = query_db(
        """
        SELECT o.*, u.username AS creator_name
        FROM orders o
        LEFT JOIN users u ON u.id = o.created_by
        ORDER BY o.order_date DESC, o.id DESC
        """
    )
    product_choices = query_db(
        "SELECT product_name, category, unit FROM stock ORDER BY category, product_name"
    )

    return render_template(
        "orders.html",
        orders_list=orders_list,
        edit_order=edit_order,
        product_choices=product_choices,
    )


@app.route("/staff", methods=["GET", "POST"])
@login_required
@admin_required
def staff():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            user_id = request.form.get("user_id")
            user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
            if user and user["role"] == "staff":
                execute_db("DELETE FROM users WHERE id = ?", (user_id,))
                flash("Staff member removed.", "warning")
            else:
                flash("Only staff users can be removed here.", "danger")
            return redirect(url_for("staff"))

        user_id = request.form.get("user_id")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username:
            flash("Username is required.", "danger")
            return redirect(url_for("staff"))

        if action == "add":
            if len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return redirect(url_for("staff"))

            try:
                execute_db(
                    """
                    INSERT INTO users (username, password_hash, role, created_at)
                    VALUES (?, ?, 'staff', ?)
                    """,
                    (username, generate_password_hash(password), datetime.now().isoformat()),
                )
                flash("Staff user created successfully.", "success")
            except sqlite3.IntegrityError:
                flash("That username already exists.", "danger")
            return redirect(url_for("staff"))

        if action == "update":
            staff_user = query_db(
                "SELECT * FROM users WHERE id = ? AND role = 'staff'",
                (user_id,),
                one=True,
            )
            if not staff_user:
                flash("Staff user not found.", "danger")
                return redirect(url_for("staff"))

            if password and len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return redirect(url_for("staff", edit=staff_user["id"]))

            try:
                if password:
                    execute_db(
                        """
                        UPDATE users
                        SET username = ?, password_hash = ?
                        WHERE id = ? AND role = 'staff'
                        """,
                        (username, generate_password_hash(password), user_id),
                    )
                else:
                    execute_db(
                        """
                        UPDATE users
                        SET username = ?
                        WHERE id = ? AND role = 'staff'
                        """,
                        (username, user_id),
                    )
                flash("Staff user updated successfully.", "success")
            except sqlite3.IntegrityError:
                flash("That username already exists.", "danger")
                return redirect(url_for("staff", edit=staff_user["id"]))

        return redirect(url_for("staff"))

    edit_id = request.args.get("edit", type=int)
    edit_user = None
    if edit_id:
        edit_user = query_db(
            "SELECT id, username, role, created_at FROM users WHERE id = ? AND role = 'staff'",
            (edit_id,),
            one=True,
        )
        if not edit_user:
            flash("Staff user not found.", "danger")
            return redirect(url_for("staff"))

    staff_users = query_db(
        "SELECT id, username, role, created_at FROM users WHERE role = 'staff' ORDER BY username ASC"
    )
    return render_template("staff.html", staff_users=staff_users, edit_user=edit_user)


@app.route("/reports")
@login_required
def reports():
    return render_template("reports.html", **get_reports_data())


@app.route("/reports/print")
@login_required
def reports_print():
    auto_print = request.args.get("auto_print") == "1"
    download_mode = request.args.get("download") == "pdf"
    return render_template(
        "reports_print.html",
        auto_print=auto_print,
        download_mode=download_mode,
        **get_reports_data(),
    )


@app.route("/about")
@login_required
def about():
    admin_user = query_db(
        """
        SELECT full_name, username, email, phone, address
        FROM users
        WHERE role = 'admin'
        ORDER BY id ASC
        """,
        one=True,
    )

    admin_contact = {
        "name": (
            admin_user["full_name"]
            if admin_user and admin_user["full_name"]
            else (admin_user["username"] if admin_user else "Main Admin")
        ),
        "email": (
            admin_user["email"]
            if admin_user and admin_user["email"]
            else "admin@gmgroups.local"
        ),
        "phone": (
            admin_user["phone"]
            if admin_user and admin_user["phone"]
            else "+91 00000 00000"
        ),
        "address": (
            admin_user["address"]
            if admin_user and admin_user["address"]
            else "GM Groups Main Office"
        ),
    }

    company_info = {
        "name": "GM Groups",
        "tagline": "Tamarind & Coconut Traders",
        "description": (
            "GM Groups supplies fresh coconuts and quality tamarind with a strong focus "
            "on dependable service, accurate stock handling, and smooth customer order management."
        ),
        "highlights": [
            {
                "emoji": "&#129381;",
                "title": "Coconut Trading",
                "text": "Fresh coconut stock is tracked carefully to support daily trading and delivery needs.",
            },
            {
                "emoji": "&#127807;",
                "title": "Tamarind Supply",
                "text": "Quality tamarind products are managed with clear quantity records and fast order updates.",
            },
            {
                "emoji": "&#128230;",
                "title": "Stock Control",
                "text": "The team monitors inventory, low-stock alerts, and product movement in one place.",
            },
            {
                "emoji": "&#129309;",
                "title": "Customer Service",
                "text": "Admin and staff work together to keep orders organized and customers informed.",
            },
        ],
    }
    return render_template(
        "about.html",
        company_info=company_info,
        admin_contact=admin_contact,
    )


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)

