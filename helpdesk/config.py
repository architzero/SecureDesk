import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

    DATABASE = os.environ.get("DATABASE_PATH") or str(BASE_DIR / "instance" / "helpdesk.db")
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or str(BASE_DIR / "instance" / "uploads")

    MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 5)
    # Whole request limit: the file plus a little room for the other form fields.
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024 + 256 * 1024
    # F13: dropped "zip" (a classic malware carrier that agents would download).
    ALLOWED_EXTENSIONS = {
        "png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log", "csv", "docx", "xlsx",
    }
    API_TOKEN_DAYS = 30  # F11: API tokens expire after this many days.

    DISPLAY_TIMEZONE = os.environ.get("DISPLAY_TIMEZONE", "Asia/Kolkata")
    RESET_TOKEN_MINUTES = 30

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # F16: secure by default. Browsers still send Secure cookies to
    # http://localhost (a secure context), so local testing is unaffected.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    GROQ_TIMEOUT = 30

