from flask import (Blueprint, current_app, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)

from . import services
from .ai import AIError
from .constants import CATEGORIES, PRIORITIES, STATUS_LABELS, STATUSES
from .security import log_activity, roles_required
from .services import ServiceError

bp = Blueprint("tickets", __name__, url_prefix="/tickets")


@bp.errorhandler(ServiceError)
def handle_service_error(error):
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(error=error.message), error.status
    title = {403: "No access", 404: "Ticket not found"}.get(error.status, "Request not accepted")
    return render_template("errors/error.html", code=error.status, title=title, message=error.message), error.status


@bp.get("/")
@roles_required("customer", "agent")
def index():
    is_agent = g.user["role"] == "agent"
    q = request.args.get("q", "").strip()[:200]
    status = request.args.get("status") if request.args.get("status") in STATUSES else None
    priority = request.args.get("priority") if request.args.get("priority") in PRIORITIES else None
    assigned = request.args.get("assigned") if is_agent and request.args.get("assigned") in ("me", "none") else None
    page = max(request.args.get("page", 1, type=int) or 1, 1)

    result = services.list_tickets(g.user, q=q, status=status, priority=priority, assigned=assigned, page=page)
    counts = services.status_counts(g.user, q=q, priority=priority, assigned=assigned)

    base = {k: v for k, v in {"q": q, "priority": priority, "assigned": assigned}.items() if v}
    tabs = [{"label": "All", "count": counts["all"], "url": url_for(".index", **base), "active": status is None}]
    for s in STATUSES:
        tabs.append({"label": STATUS_LABELS[s], "count": counts[s],
                     "url": url_for(".index", status=s, **base), "active": status == s})

    if assigned == "me":
        heading = "Assigned to me"
    elif assigned == "none":
        heading = "Unassigned"
    else:
        heading = "All tickets" if is_agent else "My tickets"

    return render_template("tickets/list.html", result=result, tabs=tabs, q=q, status=status,
                           priority=priority, assigned=assigned, heading=heading)


@bp.route("/new", methods=["GET", "POST"])
@roles_required("customer")
def new():
    form = {"subject": "", "description": "", "category": CATEGORIES[0], "priority": "medium"}
    errors = {}
    if request.method == "POST":
        form = {key: request.form.get(key, "") for key in form}
        try:
            number = services.create_ticket(g.user, form, request.files.get("attachment"))
        except ServiceError as error:
            if error.status != 400:
                raise
            errors = error.errors or {"_form": error.message}
        else:
            flash(f"Ticket #{number} is raised. The support team will reply on this page.", "success")
            return redirect(url_for(".detail", number=number))
    return render_template("tickets/new.html", form=form, errors=errors), (400 if errors else 200)


def _render_detail(ticket, reply_body="", reply_error=None, code=200):
    return render_template(
        "tickets/detail.html",
        ticket=ticket,
        replies=services.get_replies(ticket["id"]),
        attachments=services.get_attachments(ticket["id"]),
        reply_body=reply_body,
        reply_error=reply_error,
        current_step=STATUSES.index(ticket["status"]),
    ), code


@bp.get("/<int:number>")
@roles_required("customer", "agent")
def detail(number):
    return _render_detail(services.get_ticket(g.user, number))


@bp.post("/<int:number>/reply")
@roles_required("customer", "agent")
def reply(number):
    ticket = services.get_ticket(g.user, number)
    body = request.form.get("body", "")
    try:
        services.add_reply(g.user, ticket, body, ai_draft_id=request.form.get("ai_draft_id", type=int))
    except ServiceError as error:
        if error.status != 400:
            raise
        return _render_detail(ticket, reply_body=body, reply_error=error.message, code=400)

    message = "Reply sent."
    then_status = request.form.get("then_status")
    if g.user["role"] == "agent" and then_status in STATUSES:
        ticket = services.get_ticket(g.user, number)
        if services.change_status(g.user, ticket, then_status):
            message = f"Reply sent and status set to {STATUS_LABELS[then_status]}."
    flash(message, "success")
    return redirect(url_for(".detail", number=number, _anchor="latest"))


@bp.post("/<int:number>/status")
@roles_required("agent")
def update_status(number):
    ticket = services.get_ticket(g.user, number)
    new_status = request.form.get("status", "")
    if new_status not in STATUSES:
        flash("Choose open, in progress or resolved.", "error")
    elif services.change_status(g.user, ticket, new_status):
        flash(f"Status set to {STATUS_LABELS[new_status]}.", "success")
    return redirect(url_for(".detail", number=number))


@bp.post("/<int:number>/assign")
@roles_required("agent")
def assign(number):
    ticket = services.get_ticket(g.user, number)
    action = request.form.get("action")
    try:
        if action == "assign":
            services.assign_to_self(g.user, ticket)
            flash("You're now handling this ticket.", "success")
        elif action == "unassign":
            services.unassign_self(g.user, ticket)
            flash("Ticket released to the unassigned queue.", "success")
        else:
            flash("Choose whether to take or release the ticket.", "error")
    except ServiceError as error:
        flash(error.message, "error")
    return redirect(url_for(".detail", number=number))


@bp.post("/<int:number>/ai-draft")
@roles_required("agent")
def ai_draft(number):
    ticket = services.get_ticket(g.user, number)
    try:
        draft = services.generate_ai_draft(g.user, ticket)
    except AIError as error:
        return jsonify(error=str(error)), 502
    return jsonify(id=draft["id"], draft=draft["text"], model=draft["model"])


@bp.get("/attachments/<int:attachment_id>")
@roles_required("customer", "agent")
def download(attachment_id):
    attachment = services.get_attachment(g.user, attachment_id)
    log_activity("attachment_downloaded", user=g.user, target_type="attachment", target_id=attachment["id"],
                 details=f"#{attachment['ticket_number']} {attachment['original_name']}")
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], attachment["stored_name"],
                               as_attachment=True, download_name=attachment["original_name"])

