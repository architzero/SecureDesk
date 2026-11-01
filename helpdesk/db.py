import sqlite3
from pathlib import Path

import click
from flask import current_app, g
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    db.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Create the tables (safe to run more than once)."""
    init_db()
    click.echo(f"Database ready: {current_app.config['DATABASE']}")


@click.command("create-admin")
@click.option("--name", prompt="Full name")
@click.option("--email", prompt="Email")
@click.password_option(prompt="Password")
@with_appcontext
def create_admin_command(name, email, password):
    """Create a platform admin account."""
    from .security import now_iso
    from .validation import check_email, check_name, check_password

    name, email = name.strip(), email.strip().lower()
    for problem in (check_name(name), check_email(email), check_password(password)):
        if problem:
            raise click.ClickException(problem)

    init_db()
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise click.ClickException("A user with this email already exists.")
    db.execute(
        "INSERT INTO users (company_id, role, name, email, password_hash, created_at) "
        "VALUES (NULL, 'admin', ?, ?, ?, ?)",
        (name, email, generate_password_hash(password), now_iso()),
    )
    db.commit()
    click.echo(f"Admin account created for {email}.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_admin_command)

