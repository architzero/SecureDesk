import re

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{5,18}[0-9]$")
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,18}[A-Z0-9]$")


def escape_like(term):
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def check_name(name):
    if not 2 <= len(name) <= 100:
        return "Enter a full name between 2 and 100 characters."
    return None


def check_email(email):
    if not EMAIL_RE.match(email or ""):
        return "Enter a valid email address, like name@example.com."
    return None


def check_phone(phone, required=True):
    if not phone:
        return "Enter a phone number." if required else None
    if not PHONE_RE.match(phone):
        return "Use digits and spaces, with an optional + at the start."
    return None


def check_password(password):
    if len(password) < 8:
        return "Use at least 8 characters."
    if len(password) > 128:
        return "Use 128 characters or fewer."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Include at least one letter and one number."
    return None