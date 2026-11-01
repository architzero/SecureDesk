import math
import secrets

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .constants import ACTION_LABELS, ROLE_LABELS
from .db import get_db
from .security import is_safe_next, log_activity, now_iso
from .validation import (CODE_RE, check_email, check_name, check_password, check_phone,
                         escape_like)

bp = Blueprint("admin", __name__, url_prefix="/admin")
PER_PAGE = 50
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I mix-ups


@bp.before_request
def require_admin():
    if g.user is None:
        next_url = request.full_path.rstrip("?") if request.method == "GET" else None
        return redirect(url_for("auth.login", next=next_url))
    if g.user["role"] != "admin":
        abort(403)
    return None


def _companies():
    return get_db().execute("SELECT id, name FROM companies ORDER BY name").fetchall()


def _paginate(total, page):
    pages = max(1, math.ceil(total / PER_PAGE))
    page = min(max(page, 1), pages)
    return page, pages


# ---------- Companies ----------

def _render_companies(form=None, errors=None, code=200):
    rows = get_db().execute(
        """SELECT c.*,
                  (SELECT COUNT(*) FROM users u WHERE u.company_id = c.id AND u.role = 'agent') AS agents,
                  (SELECT COUNT(*) FROM users u WHERE u.company_id = c.id AND u.role = 'customer') AS customers,
                  (SELECT COUNT(*) FROM tickets t WHERE t.company_id = c.id AND t.status <> 'resolved') AS open_tickets
           FROM companies c ORDER BY c.name"""
    ).fetchall()
    return render_template("admin/companies.html", companies=rows,
                           form=form or {"name": "", "code": ""}, errors=errors or {}), code


@bp.get("/")
def companies():
    return _render_companies()


@bp.post("/companies")
def create_company():
    name = " ".join(request.form.get("name", "").split())
    code = request.form.get("code", "").strip().upper()
    errors = {}
    db = get_db()

    if not 2 <= len(name) <= 100:
        errors["name"] = "Enter a company name between 2 and 100 characters."
    elif db.execute("SELECT 1 FROM companies WHERE name = ?", (name,)).fetchone():
        errors["name"] = "A company with this name already exists."

    if code:
        if not CODE_RE.match(code):
            errors["code"] = "Use 4 to 20 capital letters, numbers or hyphens."
        elif db.execute("SELECT 1 FROM companies WHERE code = ?", (code,)).fetchone():
            errors["code"] = "Another company already uses this code."

    if errors:
        return _render_companies({"name": name, "code": code}, errors, 400)

    if not code:
        prefix = "".join(ch for ch in name.upper() if ch.isascii() and ch.isalnum())[:4] or "CO"
        while True:
            code = f"{prefix}-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))  # F3: 10 random chars
            if not db.execute("SELECT 1 FROM companies WHERE code = ?", (code,)).fetchone():
                break

    cur = db.execute("INSERT INTO companies (name, code, created_at) VALUES (?, ?, ?)", (name, code, now_iso()))
    log_activity("company_created", user=g.user, target_type="company", target_id=cur.lastrowid,
                 details=name, company_id=cur.lastrowid, commit=False)
    db.commit()
    flash(f"{name} is added. Customers sign up with the code {code}.", "success")
    return redirect(url_for(".companies"))


# ---------- Users ----------

def _render_users(form=None, errors=None, code=200):
    role = request.args.get("role") if request.args.get("role") in ROLE_LABELS else None
    company_id = request.args.get("company", type=int)
    q = request.args.get("q", "").strip()[:100]
    page = request.args.get("page", 1, type=int) or 1

    clauses, params = [], []
    if role:
        clauses.append("u.role = ?")
        params.append(role)
    if company_id:
        clauses.append("u.company_id = ?")
        params.append(company_id)
    if q:
        like = f"%{escape_like(q)}%"
        clauses.append("(u.name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')")
        params += [like, like]
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM users u {where}", params).fetchone()[0]
    page, pages = _paginate(total, page)
    rows = db.execute(
        f"""SELECT u.id, u.name, u.email, u.phone, u.role, u.is_active, u.created_at, u.last_login_at,
                   c.name AS company_name
            FROM users u LEFT JOIN companies c ON c.id = u.company_id {where}
            ORDER BY u.role = 'admin' DESC, c.name, u.role, u.name LIMIT ? OFFSET ?""",
        params + [PER_PAGE, (page - 1) * PER_PAGE],
    ).fetchall()
    blank = {"name": "", "email": "", "phone": "", "company_id": None}
    return render_template("admin/users.html", users=rows, companies=_companies(),
                           filters={"role": role, "company": company_id, "q": q},
                           form=form or blank, errors=errors or {},
                           page=page, pages=pages, total=total), code


@bp.get("/users")
def users():
    return _render_users()


@bp.post("/agents")
def create_agent():
    form = {
        "name": " ".join(request.form.get("name", "").split()),
        "email": request.form.get("email", "").strip().lower(),
        "phone": request.form.get("phone", "").strip(),
        "company_id": request.form.get("company_id", type=int),
    }
    password = request.form.get("password", "")
    checks = {
        "name": check_name(form["name"]),
        "email": check_email(form["email"]),
        "phone": check_phone(form["phone"], required=False),
        "password": check_password(password),
    }
    errors = {field: msg for field, msg in checks.items() if msg}

    db = get_db()
    company = None
    if form["company_id"]:
        company = db.execute("SELECT id, name FROM companies WHERE id = ?", (form["company_id"],)).fetchone()
    if company is None:
        errors["company_id"] = "Choose the company this agent works for."
    if "email" not in errors and db.execute("SELECT 1 FROM users WHERE email = ?", (form["email"],)).fetchone():
        errors["email"] = "An account with this email already exists."
    if errors:
        return _render_users(form, errors, 400)

    cur = db.execute(
        "INSERT INTO users (company_id, role, name, email, phone, password_hash, created_at) "
        "VALUES (?, 'agent', ?, ?, ?, ?, ?)",
        (company["id"], form["name"], form["email"], form["phone"] or None,
         generate_password_hash(password), now_iso()),
    )
    log_activity("agent_created", user=g.user, target_type="user", target_id=cur.lastrowid,
                 details=f"{form['name']} ({form['email']})", company_id=company["id"], commit=False)
    db.commit()
    flash(f"Agent account created for {form['name']} at {company['name']}. "
          "Share the password privately; they can change it with Forgot password.", "success")
    return redirect(url_for(".users", company=company["id"]))


@bp.post("/users/<int:user_id>/toggle")
def toggle_user(user_id):
    back = request.form.get("next", "")
    back = back if is_safe_next(back) else url_for(".users")
    if user_id == g.user["id"]:
        flash("You can't deactivate your own account.", "error")
        return redirect(back)

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    if user["is_active"]:
        db.execute("UPDATE users SET is_active = 0, session_epoch = session_epoch + 1, api_token_hash = NULL WHERE id = ?",
                   (user_id,))
        action, message = "user_deactivated", f"{user['name']} is deactivated and signed out everywhere."
    else:
        db.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user_id,))
        action, message = "user_reactivated", f"{user['name']} can sign in again."
    log_activity(action, user=g.user, target_type="user", target_id=user_id,
                 details=f"{user['name']} ({user['email']})", company_id=user["company_id"], commit=False)
    db.commit()
    flash(message, "success")
    return redirect(back)


# ---------- Activity log ----------

@bp.get("/activity")
def activity():
    action = request.args.get("action") if request.args.get("action") in ACTION_LABELS else None
    company_id = request.args.get("company", type=int)
    q = request.args.get("q", "").strip()[:100]
    page = request.args.get("page", 1, type=int) or 1

    clauses, params = [], []
    if action:
        clauses.append("a.action = ?")
        params.append(action)
    if company_id:
        clauses.append("a.company_id = ?")
        params.append(company_id)
    if q:
        like = f"%{escape_like(q)}%"
        clauses.append("(u.name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\' "
                       "OR a.ip_address LIKE ? ESCAPE '\\' OR a.details LIKE ? ESCAPE '\\')")
        params += [like] * 4
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    joins = "FROM activity_log a LEFT JOIN users u ON u.id = a.user_id LEFT JOIN companies c ON c.id = a.company_id"

    db = get_db()
    total = db.execute(f"SELECT COUNT(*) {joins} {where}", params).fetchone()[0]
    page, pages = _paginate(total, page)
    rows = db.execute(
        f"""SELECT a.*, u.name AS user_name, u.email AS user_email, u.role AS user_role, c.name AS company_name
            {joins} {where} ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?""",
        params + [PER_PAGE, (page - 1) * PER_PAGE],
    ).fetchall()
    return render_template("admin/activity.html", entries=rows, companies=_companies(),
                           filters={"action": action, "company": company_id, "q": q},
                           page=page, pages=pages, total=total)

