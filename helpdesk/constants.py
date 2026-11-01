STATUSES = ("open", "in_progress", "resolved")
STATUS_LABELS = {"open": "Open", "in_progress": "In progress", "resolved": "Resolved"}

PRIORITIES = ("low", "medium", "high")

CATEGORIES = ("General question", "Billing", "Technical issue", "Account", "Feature request")

ROLE_LABELS = {"customer": "Customer", "agent": "Agent", "admin": "Admin"}

ACTION_LABELS = {
    "signup": "Signed up",
    "login": "Signed in",
    "login_failed": "Failed sign-in",
    "login_blocked": "Sign-in blocked (deactivated)",
    "logout": "Signed out",
    "password_reset_requested": "Requested password reset",
    "password_reset": "Reset password",
    "api_token_created": "Created API token",
    "api_token_revoked": "Revoked API token",
    "ticket_created": "Raised ticket",
    "reply_added": "Replied on ticket",
    "status_changed": "Changed ticket status",
    "ticket_assigned": "Took ticket",
    "ticket_unassigned": "Released ticket",
    "attachment_downloaded": "Downloaded attachment",
    "ai_draft_generated": "Generated AI draft",
    "company_created": "Added company",
    "agent_created": "Created agent account",
    "user_deactivated": "Deactivated user",
    "user_reactivated": "Reactivated user",
}

WARNING_ACTIONS = {"login_failed", "login_blocked", "user_deactivated"}

# All timestamps are stored as UTC text in this format so they sort correctly.
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

