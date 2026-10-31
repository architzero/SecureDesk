"""JSON REST API. Authenticate with a bearer token from POST /api/v1/auth/token."""
import secrets

from flask import Blueprint, g, jsonify, request, url_for
from werkzeug.security import check_password_hash

from . import services
from .constants import PRIORITIES, STATUSES
from .db import get_db
from .security import DUMMY_HASH, hash_token, log_activity, too_many_failed_logins
from .services import ServiceError

bp = Blueprint("api", __name__, url_prefix="/api/v1")
PUBLIC_ENDPOINTS = {"api.create_token"}


def error(message, status, errors=None):
    body = {"error": message}
    if errors:
        body["errors"] = errors
    return jsonify(body), status


def _s(value):
    return value if isinstance(value, str) else ""


@bp.errorhandler(ServiceError)
def handle_service_error(exc):
    return error(exc.message, exc.status, exc.errors)


@bp.before_request
def authenticate():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return error("Send your token in the header: Authorization: Bearer <token>.", 401)
    user = get_db().execute(
        "SELECT u.* FROM users u LEFT JOIN companies c ON c.id = u.company_id "
        "WHERE u.api_token_hash = ? AND u.is_active = 1 AND (u.company_id IS NULL OR c.is_active = 1)",
        (hash_token(token),),
    ).fetchone()
    if user is None:
        return error("This token is invalid or has been revoked.", 401)
    g.user = user
    return None


def _ticket(t):
    return {
        "number": t["number"],
        "subject": t["subject"],
        "description": t["description"],
        "category": t["category"],
        "priority": t["priority"],
        "status": t["status"],
        "customer": {"name": t["customer_name"], "email": t["customer_email"]},
        "assigned_agent": t["agent_name"],
        "reply_count": t["reply_count"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "url": url_for("tickets.detail", number=t["number"], _external=True),
    }


def _reply(r):
    data = {
        "id": r["id"],
        "body": r["body"],
        "author": {"name": r["author_name"], "role": r["author_role"]},
        "created_at": r["created_at"],
    }
    if g.user["role"] == "agent":
        data["ai_assisted"] = r["ai_draft_id"] is not None
    return data


def _list(q):
    args = request.args
    result = services.list_tickets(
        g.user,
        q=q.strip()[:200],
        status=args.get("status") if args.get("status") in STATUSES else None,
        priority=args.get("priority") if args.get("priority") in PRIORITIES else None,
        assigned=args.get("assigned"),
        page=max(args.get("page", 1, type=int) or 1, 1),
    )
    return jsonify(tickets=[_ticket(t) for t in result["tickets"]], page=result["page"],
                   pages=result["pages"], total=result["total"])


@bp.post("/auth/token")
def create_token():
    data = request.get_json(silent=True) or {}
    email = _s(data.get("email")).strip().lower()
    password = _s(data.get("password"))
    if too_many_failed_logins(email):
        return error("Too many failed attempts. Wait 15 minutes and try again.", 429)
    db = get_db()
    user = db.execute(
        "SELECT u.*, c.is_active AS company_active FROM users u "
        "LEFT JOIN companies c ON c.id = u.company_id WHERE u.email = ?",
        (email,),
    ).fetchone()
    ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password)
    if not (user and ok and user["is_active"] and (user["company_id"] is None or user["company_active"])):
        log_activity("login_failed", user=user, details=email)
        return error("Email or password is incorrect, or the account is deactivated.", 401)

    token = "hd_" + secrets.token_urlsafe(32)
    db.execute("UPDATE users SET api_token_hash = ? WHERE id = ?", (hash_token(token), user["id"]))
    log_activity("api_token_created", user=user, target_type="user", target_id=user["id"], commit=False)
    db.commit()
    return jsonify(
        token=token,
        token_type="Bearer",
        user={"name": user["name"], "email": user["email"], "role": user["role"]},
        note="Store this token now. Requesting a new one replaces it.",
    ), 201


@bp.delete("/auth/token")
def revoke_token():
    db = get_db()
    db.execute("UPDATE users SET api_token_hash = NULL WHERE id = ?", (g.user["id"],))
    log_activity("api_token_revoked", user=g.user, target_type="user", target_id=g.user["id"], commit=False)
    db.commit()
    return "", 204


@bp.get("/tickets")
def list_tickets():
    return _list(request.args.get("q", ""))


@bp.get("/tickets/search")
def search_tickets():
    q = request.args.get("q", "").strip()
    if not q:
        return error("Add a search term, for example /api/v1/tickets/search?q=refund", 400)
    return _list(q)


@bp.get("/tickets/<int:number>")
def get_ticket(number):
    ticket = services.get_ticket(g.user, number)
    data = _ticket(ticket)
    data["replies"] = [_reply(r) for r in services.get_replies(ticket["id"])]
    data["attachments"] = [
        {"id": a["id"], "filename": a["original_name"], "size_bytes": a["size_bytes"],
         "content_type": a["content_type"], "uploaded_at": a["created_at"]}
        for a in services.get_attachments(ticket["id"])
    ]
    return jsonify(data)


@bp.get("/tickets/<int:number>/replies")
def list_replies(number):
    ticket = services.get_ticket(g.user, number)
    return jsonify(replies=[_reply(r) for r in services.get_replies(ticket["id"])])


@bp.post("/tickets")
def create_ticket():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("Send a JSON object with subject, description, category and priority.", 400)
    payload = {
        "subject": _s(data.get("subject")),
        "description": _s(data.get("description")),
        "category": _s(data.get("category")) or "General question",
        "priority": _s(data.get("priority")) or "medium",
    }
    number = services.create_ticket(g.user, payload)
    response = jsonify(_ticket(services.get_ticket(g.user, number)))
    response.status_code = 201
    response.headers["Location"] = url_for(".get_ticket", number=number)
    return response


@bp.post("/tickets/<int:number>/replies")
def create_reply(number):
    ticket = services.get_ticket(g.user, number)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error('Send a JSON object like {"body": "Your reply"}.', 400)
    reply_id = services.add_reply(g.user, ticket, _s(data.get("body")))
    return jsonify(_reply(services.get_reply(reply_id))), 201