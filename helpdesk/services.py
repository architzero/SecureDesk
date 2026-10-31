"""Ticket logic shared by the web pages and the JSON API.

Every query goes through _scope(), which limits customers to their own tickets and
agents to their own company's tickets. That's what keeps companies apart.
"""
import math
import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

from . import ai
from .constants import CATEGORIES, PRIORITIES, STATUS_LABELS, STATUSES
from .db import get_db
from .security import log_activity, now_iso
from .validation import escape_like

PER_PAGE = 20

TICKET_COLUMNS = """
    t.*,
    cu.name  AS customer_name,
    cu.email AS customer_email,
    cu.phone AS customer_phone,
    ag.name  AS agent_name,
    (SELECT COUNT(*) FROM replies r WHERE r.ticket_id = t.id) AS reply_count
"""
TICKET_FROM = """
    FROM tickets t
    JOIN users cu ON cu.id = t.customer_id
    LEFT JOIN users ag ON ag.id = t.assigned_agent_id
"""
REPLY_SELECT = """
    SELECT r.*, u.name AS author_name, u.role AS author_role
    FROM replies r JOIN users u ON u.id = r.author_id
"""


class ServiceError(Exception):
    def __init__(self, message, status=400, errors=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.errors = errors or {}


def _require_agent(user):
    if user["role"] != "agent":
        raise ServiceError("Only support agents can do this.", 403)


def _scope(user):
    if user["role"] == "customer":
        return ["t.company_id = ?", "t.customer_id = ?"], [user["company_id"], user["id"]]
    if user["role"] == "agent":
        return ["t.company_id = ?"], [user["company_id"]]
    raise ServiceError("Tickets are only available to customers and agents.", 403)


def _filters(user, q="", priority=None, assigned=None):
    clauses, params = _scope(user)
    if priority in PRIORITIES:
        clauses.append("t.priority = ?")
        params.append(priority)
    if user["role"] == "agent":
        if assigned == "me":
            clauses.append("t.assigned_agent_id = ?")
            params.append(user["id"])
        elif assigned == "none":
            clauses.append("t.assigned_agent_id IS NULL")

    # Every word must match somewhere: subject, description, category, customer name or a reply.
    for term in (q or "").split()[:8]:
        like = f"%{escape_like(term)}%"
        parts = [
            "t.subject LIKE ? ESCAPE '\\'",
            "t.description LIKE ? ESCAPE '\\'",
            "t.category LIKE ? ESCAPE '\\'",
            "cu.name LIKE ? ESCAPE '\\'",
            "EXISTS (SELECT 1 FROM replies r WHERE r.ticket_id = t.id AND r.body LIKE ? ESCAPE '\\')",
        ]
        term_params = [like] * 5
        number = term.lstrip("#")
        if number.isascii() and number.isdigit() and len(number) <= 9:
            parts.append("t.number = ?")
            term_params.append(int(number))
        clauses.append("(" + " OR ".join(parts) + ")")
        params.extend(term_params)
    return clauses, params


def list_tickets(user, q="", status=None, priority=None, assigned=None, page=1, per_page=PER_PAGE):
    clauses, params = _filters(user, q, priority, assigned)
    if status in STATUSES:
        clauses.append("t.status = ?")
        params.append(status)
    where = " AND ".join(clauses)
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) {TICKET_FROM} WHERE {where}", params).fetchone()[0]
    pages = max(1, math.ceil(total / per_page))
    page = min(max(page, 1), pages)
    rows = db.execute(
        f"SELECT {TICKET_COLUMNS} {TICKET_FROM} WHERE {where} "
        "ORDER BY t.updated_at DESC, t.id DESC LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page],
    ).fetchall()
    return {"tickets": rows, "total": total, "page": page, "pages": pages}


def status_counts(user, q="", priority=None, assigned=None):
    clauses, params = _filters(user, q, priority, assigned)
    rows = get_db().execute(
        f"SELECT t.status AS status, COUNT(*) AS n {TICKET_FROM} WHERE {' AND '.join(clauses)} GROUP BY t.status",
        params,
    ).fetchall()
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row["status"]] = row["n"]
    counts["all"] = sum(counts[s] for s in STATUSES)
    return counts


def get_ticket(user, number):
    clauses, params = _scope(user)
    clauses.append("t.number = ?")
    row = get_db().execute(
        f"SELECT {TICKET_COLUMNS} {TICKET_FROM} WHERE {' AND '.join(clauses)}", params + [number]
    ).fetchone()
    if row is None:
        raise ServiceError("This ticket doesn't exist, or your account can't see it.", 404)
    return row


def get_replies(ticket_id):
    return get_db().execute(
        f"{REPLY_SELECT} WHERE r.ticket_id = ? ORDER BY r.created_at, r.id", (ticket_id,)
    ).fetchall()


def get_reply(reply_id):
    return get_db().execute(f"{REPLY_SELECT} WHERE r.id = ?", (reply_id,)).fetchone()


def get_attachments(ticket_id):
    return get_db().execute(
        "SELECT * FROM attachments WHERE ticket_id = ? ORDER BY id", (ticket_id,)
    ).fetchall()


def get_attachment(user, attachment_id):
    clauses, params = _scope(user)
    row = get_db().execute(
        "SELECT a.*, t.number AS ticket_number FROM attachments a JOIN tickets t ON t.id = a.ticket_id "
        f"WHERE a.id = ? AND {' AND '.join(clauses)}",
        [attachment_id] + params,
    ).fetchone()
    if row is None:
        raise ServiceError("This file doesn't exist, or your account can't see it.", 404)
    return row


def validate_ticket(data):
    clean = {
        "subject": " ".join((data.get("subject") or "").split()),
        "description": (data.get("description") or "").strip(),
        "category": (data.get("category") or "").strip(),
        "priority": (data.get("priority") or "").strip().lower(),
    }
    errors = {}
    if not 5 <= len(clean["subject"]) <= 150:
        errors["subject"] = "Write a short subject between 5 and 150 characters."
    if not 10 <= len(clean["description"]) <= 5000:
        errors["description"] = "Describe the problem in 10 to 5,000 characters."
    if clean["category"] not in CATEGORIES:
        errors["category"] = "Choose a category from the list."
    if clean["priority"] not in PRIORITIES:
        errors["priority"] = "Choose low, medium or high."
    return clean, errors


def _extension(filename):
    return os.path.splitext(filename or "")[1].lower().lstrip(".")


def _store_upload(upload):
    ext = _extension(upload.filename)
    original = secure_filename(upload.filename) or ""
    if not original.lower().endswith(f".{ext}"):
        original = f"attachment.{ext}"
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored_name)
    upload.save(path)
    size = os.path.getsize(path)
    max_mb = current_app.config["MAX_UPLOAD_MB"]
    if size == 0 or size > max_mb * 1024 * 1024:
        os.remove(path)
        message = "The attached file is empty." if size == 0 else f"Files can be up to {max_mb} MB."
        raise ServiceError(message, 400, {"attachment": message})
    return {
        "original_name": original[:200],
        "stored_name": stored_name,
        "size": size,
        "content_type": (upload.mimetype or "application/octet-stream")[:100],
    }


def create_ticket(user, data, upload=None):
    if user["role"] != "customer":
        raise ServiceError("Only customers can raise tickets.", 403)
    clean, errors = validate_ticket(data)
    has_file = upload is not None and bool(upload.filename)
    allowed = current_app.config["ALLOWED_EXTENSIONS"]
    if has_file and _extension(upload.filename) not in allowed:
        errors["attachment"] = "This file type isn't allowed. Use " + ", ".join(sorted(allowed)).upper() + "."
    if errors:
        raise ServiceError("Some fields need attention.", 400, errors)

    db = get_db()
    now = now_iso()
    stored = None
    try:
        if has_file:
            stored = _store_upload(upload)
        cur = db.execute(
            """INSERT INTO tickets (company_id, number, customer_id, subject, description, category,
                                    priority, status, created_at, updated_at)
               VALUES (?, (SELECT COALESCE(MAX(number), 0) + 1 FROM tickets WHERE company_id = ?),
                       ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (user["company_id"], user["company_id"], user["id"], clean["subject"], clean["description"],
             clean["category"], clean["priority"], now, now),
        )
        ticket_id = cur.lastrowid
        number = db.execute("SELECT number FROM tickets WHERE id = ?", (ticket_id,)).fetchone()[0]
        if stored:
            db.execute(
                "INSERT INTO attachments (ticket_id, uploaded_by, original_name, stored_name, content_type, size_bytes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticket_id, user["id"], stored["original_name"], stored["stored_name"],
                 stored["content_type"], stored["size"], now),
            )
        log_activity("ticket_created", user=user, target_type="ticket", target_id=ticket_id,
                     details=f"#{number}", commit=False)
        db.commit()
    except Exception:
        db.rollback()
        if stored:
            try:
                os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], stored["stored_name"]))
            except OSError:
                pass
        raise
    return number


def add_reply(user, ticket, body, ai_draft_id=None):
    if user["role"] not in ("customer", "agent"):
        raise ServiceError("Only customers and agents can reply.", 403)
    body = (body or "").strip()
    if not body:
        raise ServiceError("Write a reply before sending.", 400, {"body": "Write a reply before sending."})
    if len(body) > 5000:
        raise ServiceError("Replies can be up to 5,000 characters.", 400, {"body": "Replies can be up to 5,000 characters."})

    db = get_db()
    now = now_iso()
    if ai_draft_id and user["role"] == "agent":
        row = db.execute(
            "SELECT id FROM ai_drafts WHERE id = ? AND ticket_id = ? AND agent_id = ?",
            (ai_draft_id, ticket["id"], user["id"]),
        ).fetchone()
        ai_draft_id = row["id"] if row else None
    else:
        ai_draft_id = None

    cur = db.execute(
        "INSERT INTO replies (ticket_id, author_id, body, ai_draft_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket["id"], user["id"], body, ai_draft_id, now),
    )
    db.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, ticket["id"]))
    if ai_draft_id:
        db.execute("UPDATE ai_drafts SET used = 1 WHERE id = ?", (ai_draft_id,))
    log_activity("reply_added", user=user, target_type="ticket", target_id=ticket["id"],
                 details=f"#{ticket['number']}" + (" (AI-assisted)" if ai_draft_id else ""), commit=False)

    # A customer replying to a resolved ticket reopens it.
    if user["role"] == "customer" and ticket["status"] == "resolved":
        db.execute("UPDATE tickets SET status = 'open' WHERE id = ?", (ticket["id"],))
        log_activity("status_changed", user=user, target_type="ticket", target_id=ticket["id"],
                     details=f"#{ticket['number']}: Resolved to Open (customer replied)", commit=False)
    db.commit()
    return cur.lastrowid


def change_status(user, ticket, status):
    _require_agent(user)
    if status not in STATUSES:
        raise ServiceError("Choose open, in progress or resolved.", 400)
    if status == ticket["status"]:
        return False
    db = get_db()
    db.execute("UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), ticket["id"]))
    log_activity("status_changed", user=user, target_type="ticket", target_id=ticket["id"],
                 details=f"#{ticket['number']}: {STATUS_LABELS[ticket['status']]} to {STATUS_LABELS[status]}",
                 commit=False)
    db.commit()
    return True


def assign_to_self(user, ticket):
    _require_agent(user)
    if ticket["assigned_agent_id"] == user["id"]:
        return False
    db = get_db()
    db.execute("UPDATE tickets SET assigned_agent_id = ?, updated_at = ? WHERE id = ?",
               (user["id"], now_iso(), ticket["id"]))
    details = f"#{ticket['number']}"
    if ticket["agent_name"]:
        details += f" (taken over from {ticket['agent_name']})"
    log_activity("ticket_assigned", user=user, target_type="ticket", target_id=ticket["id"],
                 details=details, commit=False)
    db.commit()
    return True


def unassign_self(user, ticket):
    _require_agent(user)
    if ticket["assigned_agent_id"] != user["id"]:
        raise ServiceError("You can only release tickets assigned to you.", 400)
    db = get_db()
    db.execute("UPDATE tickets SET assigned_agent_id = NULL, updated_at = ? WHERE id = ?",
               (now_iso(), ticket["id"]))
    log_activity("ticket_unassigned", user=user, target_type="ticket", target_id=ticket["id"],
                 details=f"#{ticket['number']}", commit=False)
    db.commit()


def generate_ai_draft(user, ticket):
    _require_agent(user)
    db = get_db()
    company = db.execute("SELECT name FROM companies WHERE id = ?", (ticket["company_id"],)).fetchone()
    text, model = ai.draft_reply(company["name"], user["name"], ticket, get_replies(ticket["id"]))
    cur = db.execute(
        "INSERT INTO ai_drafts (ticket_id, agent_id, model, draft, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket["id"], user["id"], model, text, now_iso()),
    )
    log_activity("ai_draft_generated", user=user, target_type="ticket", target_id=ticket["id"],
                 details=f"#{ticket['number']}", commit=False)
    db.commit()
    return {"id": cur.lastrowid, "text": text, "model": model}