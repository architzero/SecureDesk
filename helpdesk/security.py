import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, g, has_request_context, redirect, request, session, url_for
from werkzeug.security import generate_password_hash

from .constants import TIME_FORMAT
from .db import get_db

# Used to keep login timing the same whether or not the email exists.
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))

CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; connect-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
)


def utcnow():
    return datetime.now(timezone.utc)


def to_iso(dt):
    return dt.astimezone(timezone.utc).strftime(TIME_FORMAT)


def now_iso():
    return to_iso(utcnow())


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def client_ip():
    if not has_request_context():
        return "cli"
    # Behind a reverse proxy, wrap the app with werkzeug's ProxyFix so this is the real client IP.
    return request.remote_addr or "unknown"


def log_activity(action, user=None, target_type=None, target_id=None, details=None,
                 company_id=None, commit=True):
    if company_id is None and user is not None:
        company_id = user["company_id"]
    db = get_db()
    db.execute(
        "INSERT INTO activity_log (user_id, company_id, action, target_type, target_id, details, ip_address, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"] if user is not None else None, company_id, action, target_type,
         target_id, details, client_ip(), now_iso()),
    )
    if commit:
        db.commit()


def too_many_failed_logins(email):
    """Simple brute-force guard that reads failed attempts from the activity log."""
    since = to_iso(utcnow() - timedelta(minutes=15))
    db = get_db()
    by_ip = db.execute(
        "SELECT COUNT(*) FROM activity_log WHERE action = 'login_failed' AND ip_address = ? AND created_at >= ?",
        (client_ip(), since),
    ).fetchone()[0]
    by_email = db.execute(
        "SELECT COUNT(*) FROM activity_log WHERE action = 'login_failed' AND details = ? AND created_at >= ?",
        (email, since),
    ).fetchone()[0]
    return by_ip >= 20 or by_email >= 8


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def is_safe_next(target):
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc


def start_session(user):
    session.clear()
    session["user_id"] = user["id"]
    session["epoch"] = user["session_epoch"]
    session.permanent = True


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                next_url = request.full_path.rstrip("?") if request.method == "GET" else None
                return redirect(url_for("auth.login", next=next_url))
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _load_user():
    g.user = None
    if request.endpoint == "static" or request.blueprint == "api":
        return
    user_id = session.get("user_id")
    if user_id is None:
        return
    user = get_db().execute(
        "SELECT u.*, c.name AS company_name, c.is_active AS company_active "
        "FROM users u LEFT JOIN companies c ON c.id = u.company_id WHERE u.id = ?",
        (user_id,),
    ).fetchone()
    if (
        user is None
        or not user["is_active"]
        or user["session_epoch"] != session.get("epoch")
        or (user["company_id"] is not None and not user["company_active"])
    ):
        session.clear()
        return
    g.user = user


def _csrf_protect():
    if request.method in ("GET", "HEAD", "OPTIONS") or request.blueprint == "api":
        return
    expected = session.get("_csrf_token")
    sent = request.headers.get("X-CSRFToken") or request.form.get("csrf_token", "")
    if not expected or not hmac.compare_digest(str(sent), expected):
        abort(400, description="This form expired. Reload the page and try again.")


def _security_headers(response):
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if g.get("user") is not None and request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


def init_app(app):
    app.before_request(_load_user)
    app.before_request(_csrf_protect)
    app.after_request(_security_headers)