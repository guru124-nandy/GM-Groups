# Coconut and Tamarind Traders Management System

Internal web application built with Flask, SQLite, Bootstrap, HTML, CSS, and JavaScript.

## Features

- Admin and staff login with role-based access
- Dashboard with stock totals, order totals, and low-stock alerts
- Stock CRUD for coconut and tamarind items
- Order management with pending/completed status
- Admin-only staff management
- Daily, monthly, and stock reports
- Seeded sample data and default admin login

## Default Login

- Admin username: `admin`
- Admin password: `admin123`
- Sample staff username: `staff1`
- Sample staff password: `staff123`

## Run the Project

1. Open the folder in VS Code.
2. Open a terminal in the project root.
3. Create a virtual environment:
   - Windows: `python -m venv .venv`
4. Activate the virtual environment:
   - PowerShell: `.\.venv\Scripts\Activate.ps1`
5. Install dependencies:
   - `pip install -r requirements.txt`
6. Start the Flask app:
   - `python app.py`
7. Open the shown local URL in your browser, usually `http://127.0.0.1:5000`.

The SQLite database file `database.db` is created automatically the first time the app runs.
