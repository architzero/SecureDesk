import os
import secrets
import sqlite3
from datetime import timedelta

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .security import (DUMMY_HASH, hash_token, is_safe_next, log_activity, now_iso, start_session,
                       to_iso, too_many, too_many_failed_logins, utcnow)
from .validation import check_email, check_name, check_password, check_phone

bp = Blueprint("auth", __name__)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("index"))
    form = {"name": "", "email": "", "phone": "", "company_code": ""}
    errors = {}
    if request.method == "POST":
        # F3/F9: cap company-code guessing per IP so codes can't be brute-forced.
        if too_many("signup_bad_code", 10, 60):
            return render_template("auth/signup.html", form=form,
                                   errors={"company_code": "Too many attempts. Please wait and try again."}), 429
        form = {key: request.form.get(key, "").strip() for key in form}
        form["email"] = form["email"].lower()
        form["company_code"] = form["company_code"].upper()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        checks = {
            "name": check_name(form["name"]),
            "email": check_email(form["email"]),
            "phone": check_phone(form["phone"]),
            "password": check_password(password),
        }
        errors = {field: msg for field, msg in checks.items() if msg}
        if "password" not in errors and password != confirm:
            errors["confirm_password"] = "The two passwords don't match."

        db = get_db()
        company = None
        if not form["company_code"]:
            errors["company_code"] = "Enter the company code you were given."
        else:
            company = db.execute(
                "SELECT id, name FROM companies WHERE code = ? AND is_active = 1", (form["company_code"],)
            ).fetchone()
            if company is None:
                errors["company_code"] = "No company uses this code. Check it with the company you're contacting."
                log_activity("signup_bad_code", details=form["company_code"])

        if "email" not in errors and db.execute("SELECT 1 FROM users WHERE email = ?", (form["email"],)).fetchone():
            errors["email"] = "An account with this email already exists. Sign in instead."

        if not errors:
            try:
                cur = db.execute(
                    "INSERT INTO users (company_id, role, name, email, phone, password_hash, created_at) "
                    "VALUES (?, 'customer', ?, ?, ?, ?, ?)",
                    (company["id"], form["name"], form["email"], form["phone"],
                     generate_password_hash(password), now_iso()),
                )
            except sqlite3.IntegrityError:
                db.rollback()
                errors["email"] = "An account with this email already exists. Sign in instead."
            else:
                user = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
                log_activity("signup", user=user, target_type="user", target_id=user["id"],
                             details=company["name"], commit=False)
                db.commit()
                start_session(user)
                flash(f"Your account is ready. Raise tickets with {company['name']} from here.", "success")
                return redirect(url_for("tickets.index"))
    return render_template("auth/signup.html", form=form, errors=errors), (400 if errors else 200)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    email, error, status = "", None, 200
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if too_many_failed_logins(email):
            error, status = "Too many failed sign-in attempts. Wait 15 minutes and try again.", 429
        else:
            db = get_db()
            user = db.execute(
                "SELECT u.*, c.is_active AS company_active FROM users u "
                "LEFT JOIN companies c ON c.id = u.company_id WHERE u.email = ?",
                (email,),
            ).fetchone()
            password_ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password)
            if user and password_ok:
                if not user["is_active"] or (user["company_id"] and not user["company_active"]):
                    log_activity("login_blocked", user=user, details=email)
                    error, status = "This account is deactivated. Contact the support team that set it up.", 403
                else:
                    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), user["id"]))
                    log_activity("login", user=user, commit=False)
                    db.commit()
                    start_session(user)
                    target = request.args.get("next", "")
                    return redirect(target if is_safe_next(target) else url_for("index"))
            else:
                log_activity("login_failed", user=user, details=email)
                error, status = "That email and password don't match an account.", 401
    return render_template("auth/login.html", email=email, error=error), status


@bp.post("/logout")
def logout():
    if g.user:
        # F1: raise the session epoch so any copy of this session cookie
        # (on another device or captured earlier) stops working immediately.
        db = get_db()
        db.execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?", (g.user["id"],))
        log_activity("logout", user=g.user, commit=False)
        db.commit()
    session.clear()
    flash("You're signed out.", "info")
    return redirect(url_for("auth.login"))


def _save_reset_link(email, link, minutes):
    # F4: write the reset link to a restricted file instead of stdout. On a
    # server, stdout flows into shared logs that many people can read, so
    # printing the link there effectively lets any log reader reset any account.
    instance_dir = os.path.dirname(current_app.config["DATABASE"])
    path = os.path.join(instance_dir, "reset_links.txt")
    entry = (f"{now_iso()}  reset link for {email}\n  {link}\n"
             f"  expires in {minutes} minutes\n\n")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as handle:
        handle.write(entry)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    sent = False
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        # F9: cap reset requests per IP. Each new link also cancels the user's
        # previous valid one, so unlimited requests could be used to grief them.
        if too_many("password_reset_requested", 5, 60):
            return render_template("auth/forgot.html", sent=True)
        user = db.execute("SELECT * FROM users WHERE email = ? AND is_active = 1", (email,)).fetchone()
        # Log every attempt (including unknown emails) so the rate limit counts them.
        log_activity("password_reset_requested", user=user, details=email, commit=False)
        if user:
            minutes = current_app.config["RESET_TOKEN_MINUTES"]
            token = secrets.token_urlsafe(32)
            now = now_iso()
            db.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (now, user["id"]))
            db.execute(
                "INSERT INTO password_resets (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], hash_token(token), to_iso(utcnow() + timedelta(minutes=minutes)), now),
            )
            _save_reset_link(user["email"], url_for("auth.reset_password", token=token, _external=True), minutes)
        db.commit()
        # Same response either way, so the form doesn't reveal which emails have accounts.
        sent = True
    return render_template("auth/forgot.html", sent=sent)


def _find_reset(token):
    return get_db().execute(
        "SELECT pr.id, pr.user_id FROM password_resets pr JOIN users u ON u.id = pr.user_id "
        "WHERE pr.token_hash = ? AND pr.used_at IS NULL AND pr.expires_at > ? AND u.is_active = 1",
        (hash_token(token), now_iso()),
    ).fetchone()


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    reset = _find_reset(token)
    if reset is None:
        # F23: pass "expired", not "invalid" — the template imports a macro
        # called invalid(), which used to shadow this flag and make every page
        # (even a brand-new link) say "Link expired".
        return render_template("auth/reset.html", expired=True, errors={})
    errors = {}
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        problem = check_password(password)
        if problem:
            errors["password"] = problem
        elif password != confirm:
            errors["confirm_password"] = "The two passwords don't match."
        if not errors:
            db = get_db()
            db.execute(
                "UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1, api_token_hash = NULL WHERE id = ?",
                (generate_password_hash(password), reset["user_id"]),
            )
            db.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
                       (now_iso(), reset["user_id"]))
            user = db.execute("SELECT * FROM users WHERE id = ?", (reset["user_id"],)).fetchone()
            log_activity("password_reset", user=user, commit=False)
            db.commit()
            session.clear()
            flash("Your password is updated. Sign in with the new one.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", expired=False, token=token, errors=errors), (400 if errors else 200)

