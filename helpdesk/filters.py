from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import request, url_for

from .constants import (ACTION_LABELS, CATEGORIES, PRIORITIES, ROLE_LABELS, STATUS_LABELS,
                        STATUSES, TIME_FORMAT, WARNING_ACTIONS)
from .security import csrf_token, utcnow


def _parse(value):
    return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=timezone.utc)


def init_app(app):
    tz = ZoneInfo(app.config["DISPLAY_TIMEZONE"])

    @app.template_filter("dt")
    def format_dt(value, fmt="%-d %b %Y, %H:%M"):
        if not value:
            return ""
        try:
            return _parse(value).astimezone(tz).strftime(fmt)
        except ValueError:
            return value

    @app.template_filter("ago")
    def ago(value):
        if not value:
            return ""
        try:
            then = _parse(value)
        except ValueError:
            return value
        seconds = int((utcnow() - then).total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60} min ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if seconds < 7 * 86400:
            days = seconds // 86400
            return "yesterday" if days == 1 else f"{days} days ago"
        return then.astimezone(tz).strftime("%-d %b %Y")

    @app.template_filter("filesize")
    def filesize(size):
        size = int(size or 0)
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def page_url(page):
        args = request.args.to_dict()
        args["page"] = page
        return url_for(request.endpoint, **(request.view_args or {}), **args)

    def nav_active(endpoint, assigned=None):
        if request.endpoint != endpoint:
            return False
        if endpoint == "tickets.index":
            return request.args.get("assigned") == assigned
        return True

    extensions = sorted(app.config["ALLOWED_EXTENSIONS"])
    app.jinja_env.globals.update(
        csrf_token=csrf_token,
        page_url=page_url,
        nav_active=nav_active,
        STATUSES=STATUSES,
        STATUS_LABELS=STATUS_LABELS,
        PRIORITIES=PRIORITIES,
        CATEGORIES=CATEGORIES,
        ROLE_LABELS=ROLE_LABELS,
        ACTION_LABELS=ACTION_LABELS,
        WARNING_ACTIONS=WARNING_ACTIONS,
        UPLOAD_ACCEPT=",".join(f".{ext}" for ext in extensions),
        UPLOAD_TYPES_TEXT=", ".join(ext.upper() for ext in extensions),
        groq_enabled=bool(app.config.get("GROQ_API_KEY")),
    )

