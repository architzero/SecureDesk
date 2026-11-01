import re

# F18: only ordinary email characters, so values like "x@y.com?subject=..&body=.."
# can't pass validation and later become a pre-filled mailto link.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{5,18}[0-9]$")
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,18}[A-Z0-9]$")

# F10: a small blocklist of the most common weak passwords. A production app
# would check a breached-password corpus (e.g. HaveIBeenPwned) instead.
COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwerty123", "qwertyuiop", "admin123", "welcome1", "letmein123", "iloveyou1",
    "abc12345", "password@123", "changeme123",
}


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
    # F10: NIST SP 800-63B Rev 4 asks for at least a 15-character minimum when
    # a password is the only factor; 12 is used here as a lab-practical minimum.
    if len(password) < 12:
        return "Use at least 12 characters."
    if len(password) > 128:
        return "Use 128 characters or fewer."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Include at least one letter and one number."
    if password.lower() in COMMON_PASSWORDS:
        return "This password is too common. Choose a less predictable one."
    return None

