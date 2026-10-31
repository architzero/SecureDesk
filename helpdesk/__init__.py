"""HelpDesk: a customer support ticket system for many companies at once."""
import os
import secrets

from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from .config import Config

ERROR_TEXT = {
    400: ("Request not accepted", "Something in the request was missing or out of date. Go back, reload the page and try again."),
    403: ("No access", "Your account doesn't have access to this page."),
    404: ("Page not found", "This page doesn't exist, or your account can't see it."),
    405: ("Action not allowed", "This page doesn't accept that kind of request."),
    413: ("File too large", ""),
    429: ("Too many requests", "Wait a few minutes and try again."),
    500: ("Something went wrong", "The error was written to the terminal running the app. Try again in a moment."),
}


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning(
            "SECRET_KEY is not set in .env. Using a temporary key, "
            "so everyone is signed out whenever the app restarts."
        )

    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    from . import db, filters, security

    db.init_app(app)
    security.init_app(app)
    filters.init_app(app)

    from .admin import bp as admin_bp
    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .tickets import bp as tickets_bp

    for blueprint in (auth_bp, tickets_bp, admin_bp, api_bp):
        app.register_blueprint(blueprint)

    @app.get("/")
    def index():
        user = g.get("user")
        if user is None:
            return redirect(url_for("auth.login"))
        if user["role"] == "admin":
            return redirect(url_for("admin.companies"))
        return redirect(url_for("tickets.index"))

    _register_error_handlers(app)
    return app


def _register_error_handlers(app):
    def wants_json():
        return request.path.startswith("/api/") or request.headers.get("X-Requested-With") == "fetch"

    def handle(error):
        code = getattr(error, "code", None) or 500
        title, message = ERROR_TEXT.get(code, ERROR_TEXT[500])
        if code == 413:
            message = f"Attachments can be up to {app.config['MAX_UPLOAD_MB']} MB. Choose a smaller file and try again."
        custom = getattr(error, "description", None)
        if code == 400 and custom and not custom.startswith("The browser"):
            message = custom
        if wants_json():
            return jsonify(error=message), code
        return render_template("errors/error.html", code=code, title=title, message=message), code

    for code in ERROR_TEXT:
        app.register_error_handler(code, handle)