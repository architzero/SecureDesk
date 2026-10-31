#!/usr/bin/env python3
"""Reset the HelpDesk database and fill it with demo data.

    python seed.py          asks before deleting existing data
    python seed.py --yes    deletes without asking
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

from helpdesk import create_app
from helpdesk.constants import TIME_FORMAT
from helpdesk.db import get_db, init_db

NOW = datetime.now(timezone.utc)
ADMIN_PASSWORD = "Admin@1234"
DEMO_PASSWORD = "Demo@1234"
ADMIN = ("Asha Kulkarni", "admin@example.test", "+91 90000 00001", "192.0.2.1")

# IP addresses come from the ranges reserved for documentation (192.0.2.x, 198.51.100.x, 203.0.113.x).
COMPANIES = [
    {
        "name": "Acme Internet",
        "code": "ACME-2026",
        "agents": [
            ("Priya Nair", "priya.nair@acme.example.test", "+91 98200 11001", "192.0.2.21"),
            ("Daniel Brooks", "daniel.brooks@acme.example.test", "+91 98200 11002", "192.0.2.22"),
        ],
        "customers": [
            ("Rohan Mehta", "rohan.mehta@example.test", "+91 98765 20001", "198.51.100.14"),
            ("Sara Lopez", "sara.lopez@example.test", "+91 98765 20002", "198.51.100.37"),
        ],
    },
    {
        "name": "Zest Bank",
        "code": "ZEST-2026",
        "agents": [
            ("Ananya Rao", "ananya.rao@zestbank.example.test", "+91 98200 22001", "192.0.2.41"),
            ("Marcus Hale", "marcus.hale@zestbank.example.test", "+91 98200 22002", "192.0.2.42"),
        ],
        "customers": [
            ("Kabir Shah", "kabir.shah@example.test", "+91 98765 30001", "203.0.113.8"),
            ("Emily Chen", "emily.chen@example.test", "+91 98765 30002", "203.0.113.52"),
        ],
    },
]


def router_log():
    day = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    lines = [
        f"{day} 20:58:11 SYS   Uptime 5d 02:14:09",
        f"{day} 21:04:52 WAN   PPPoE session down (LCP echo timeout)",
        f"{day} 21:04:53 DSL   Line sync lost",
        f"{day} 21:07:30 DSL   Training... SNR margin 3.1 dB",
        f"{day} 21:12:46 DSL   Line sync lost",
        f"{day} 21:19:02 DSL   Showtime. Down 98.4 Mbps / Up 19.6 Mbps",
        f"{day} 21:19:09 WAN   PPPoE session up",
    ]
    return "\n".join(lines) + "\n"


# Each reply is (author email, text, hours after the ticket was raised).
TICKETS = [
    {
        "company": "ACME-2026", "customer": "rohan.mehta@example.test",
        "subject": "Upgrade to the 300 Mbps plan", "category": "Account", "priority": "low",
        "status": "resolved", "agent": "daniel.brooks@acme.example.test", "age": timedelta(days=9),
        "description": "I'd like to move from the 100 Mbps plan to the 300 Mbps plan from this billing cycle. "
                       "Is there an installation charge, and will my current router handle the higher speed?",
        "replies": [
            ("daniel.brooks@acme.example.test",
             "Hi Rohan,\n\nThere's no installation charge for this upgrade, and your router supports up to 1 Gbps, "
             "so you're all set. I've switched your plan to 300 Mbps from today. Restart the router once so the new "
             "speed applies.\n\nDaniel", 3),
            ("rohan.mehta@example.test",
             "Restarted it and the speed test now shows around 290 Mbps. Thanks for the quick help!", 5),
            ("daniel.brooks@acme.example.test",
             "Great to hear. I'll close this ticket now. Reply here if anything changes.\n\nDaniel", 6),
        ],
    },
    {
        "company": "ACME-2026", "customer": "rohan.mehta@example.test",
        "subject": "Internet drops every evening around 9 PM", "category": "Technical issue", "priority": "high",
        "status": "in_progress", "agent": "priya.nair@acme.example.test", "age": timedelta(days=6),
        "description": "For the past week my connection drops almost every evening between 9 and 10 PM. "
                       "The router lights stay on but nothing loads for about 15 minutes, then it comes back on its own. "
                       "I work from home and this keeps cutting my calls. I've attached the router's event log from last night.",
        "attachment": ("router-log.txt", router_log()),
        "replies": [
            ("priya.nair@acme.example.test",
             "Hi Rohan,\n\nThanks for the log, it helps a lot. I can see your line losing sync several times between "
             "21:05 and 21:20 over the last five days. I've asked our field team to test the line at your building's "
             "junction box.\n\nTo narrow it down: does it also drop when a laptop is connected to the router with a cable?"
             "\n\nPriya", 24),
            ("rohan.mehta@example.test",
             "Yes, I tried a cable yesterday and it still dropped at 9:10 PM. Do you know when the field team will "
             "visit? I'd like to be home.", 28),
        ],
    },
    {
        "company": "ACME-2026", "customer": "sara.lopez@example.test",
        "subject": "Charged twice for my October bill", "category": "Billing", "priority": "medium",
        "status": "open", "agent": None, "age": timedelta(days=2),
        "description": "My bank statement shows two debits of ₹1,179 on 3 October for the same invoice "
                       "(INV-2026-10-55821). Please refund the duplicate payment to my card.",
        "replies": [],
    },
    {
        "company": "ACME-2026", "customer": "sara.lopez@example.test",
        "subject": "Can I get a static IP for my home office?", "category": "Feature request", "priority": "low",
        "status": "open", "agent": None, "age": timedelta(hours=5),
        "description": "I'm setting up a small home office and need a static IP address for remote access to a server. "
                       "Is this available on home plans, and what does it cost per month?",
        "replies": [],
    },
    {
        "company": "ZEST-2026", "customer": "kabir.shah@example.test",
        "subject": "Update my registered mobile number", "category": "Account", "priority": "low",
        "status": "resolved", "agent": "marcus.hale@zestbank.example.test", "age": timedelta(days=12),
        "description": "I changed my mobile number last month. Please update it on my savings account so I get OTPs on "
                       "the new number. I submitted the form at the Andheri branch on 14 October.",
        "replies": [
            ("marcus.hale@zestbank.example.test",
             "Hi Kabir,\n\nThanks for visiting the branch. Your form has been verified and the new number is now "
             "registered. You'll receive OTPs on it from today.\n\nMarcus", 24),
            ("kabir.shah@example.test", "Got an OTP on the new number just now. Thank you.", 26),
        ],
    },
    {
        "company": "ZEST-2026", "customer": "emily.chen@example.test",
        "subject": "UPI transfer debited but not received", "category": "Technical issue", "priority": "high",
        "status": "in_progress", "agent": "ananya.rao@zestbank.example.test", "age": timedelta(days=3),
        "description": "I sent ₹4,500 by UPI to my landlord on Wednesday. The money left my account but he still "
                       "hasn't received it. The UPI reference ends in 7731.",
        "replies": [
            ("ananya.rao@zestbank.example.test",
             "Hi Emily,\n\nI'm sorry for the worry. I found the transaction: it's pending with the receiving bank, and "
             "I've raised a dispute on it. These usually settle within 3 working days. If the transfer fails, the money "
             "comes back to your account automatically.\n\nAnanya", 5),
            ("emily.chen@example.test",
             "Thanks. Is there anything I need to do from my side? My landlord is asking when he'll get it.", 24),
        ],
    },
    {
        "company": "ZEST-2026", "customer": "emily.chen@example.test",
        "subject": "Interest certificate for FY 2025-26", "category": "General question", "priority": "medium",
        "status": "open", "agent": None, "age": timedelta(days=1, hours=6),
        "description": "Please share the interest certificate for my fixed deposit for the financial year 2025-26. "
                       "I need it for my tax filing.",
        "replies": [],
    },
    {
        "company": "ZEST-2026", "customer": "kabir.shah@example.test",
        "subject": "Debit card blocked after an international payment", "category": "Account", "priority": "high",
        "status": "open", "agent": None, "age": timedelta(hours=20),
        "description": "I'm travelling in Singapore and my debit card was blocked right after I paid at a restaurant "
                       "yesterday. I had turned on international usage in the app before leaving. I need the card "
                       "working while I'm here.",
        "replies": [],
    },
]


def stamp(dt):
    return dt.strftime(TIME_FORMAT)


def reset_storage(app):
    db_path = Path(app.config["DATABASE"])
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(str(db_path) + suffix)
        if path.exists():
            path.unlink()
    uploads = Path(app.config["UPLOAD_FOLDER"])
    uploads.mkdir(parents=True, exist_ok=True)
    for item in uploads.iterdir():
        if item.is_file():
            item.unlink()
    return uploads


def add_user(db, company_id, role, name, email, phone, password, created):
    cur = db.execute(
        "INSERT INTO users (company_id, role, name, email, phone, password_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (company_id, role, name, email, phone, generate_password_hash(password), stamp(created)),
    )
    return cur.lastrowid


def log(db, action, user, when, target_type=None, target_id=None, details=None, company_id=None):
    if company_id is None:
        company_id = user["company_id"]
    db.execute(
        "INSERT INTO activity_log (user_id, company_id, action, target_type, target_id, details, ip_address, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], company_id, action, target_type, target_id, details, user["ip"], stamp(when)),
    )


def seed(db, uploads):
    users = {}
    start = NOW - timedelta(days=30)

    name, email, phone, ip = ADMIN
    admin = {"id": add_user(db, None, "admin", name, email, phone, ADMIN_PASSWORD, start),
             "company_id": None, "role": "admin", "ip": ip}
    users[email] = admin

    companies = {}
    for company in COMPANIES:
        created = start + timedelta(hours=1)
        cid = db.execute("INSERT INTO companies (name, code, created_at) VALUES (?, ?, ?)",
                         (company["name"], company["code"], stamp(created))).lastrowid
        companies[company["code"]] = cid
        log(db, "company_created", admin, created, "company", cid, company["name"], company_id=cid)

        for name, email, phone, ip in company["agents"]:
            created = start + timedelta(hours=2)
            uid = add_user(db, cid, "agent", name, email, phone, DEMO_PASSWORD, created)
            users[email] = {"id": uid, "company_id": cid, "role": "agent", "ip": ip}
            log(db, "agent_created", admin, created, "user", uid, f"{name} ({email})", company_id=cid)

        for name, email, phone, ip in company["customers"]:
            created = NOW - timedelta(days=20)
            uid = add_user(db, cid, "customer", name, email, phone, DEMO_PASSWORD, created)
            users[email] = {"id": uid, "company_id": cid, "role": "customer", "ip": ip}
            log(db, "signup", users[email], created, "user", uid, company["name"])

    # Tickets are numbered per company, oldest first.
    numbers = {}
    for t in sorted(TICKETS, key=lambda item: item["age"], reverse=True):
        cid = companies[t["company"]]
        numbers[cid] = numbers.get(cid, 0) + 1
        number = numbers[cid]
        created = NOW - t["age"]
        customer = users[t["customer"]]
        agent = users[t["agent"]] if t["agent"] else None
        replies = t["replies"]
        updated = created + timedelta(hours=replies[-1][2]) if replies else created
        if t["status"] == "resolved":
            updated += timedelta(minutes=2)

        tid = db.execute(
            "INSERT INTO tickets (company_id, number, customer_id, assigned_agent_id, subject, description, "
            "category, priority, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, number, customer["id"], agent["id"] if agent else None, t["subject"], t["description"],
             t["category"], t["priority"], t["status"], stamp(created), stamp(updated)),
        ).lastrowid
        log(db, "ticket_created", customer, created, "ticket", tid, f"#{number}")

        if t.get("attachment"):
            filename, content = t["attachment"]
            data = content.encode("utf-8")
            stored = f"{uuid.uuid4().hex}.txt"
            (uploads / stored).write_bytes(data)
            db.execute(
                "INSERT INTO attachments (ticket_id, uploaded_by, original_name, stored_name, content_type, "
                "size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tid, customer["id"], filename, stored, "text/plain", len(data), stamp(created)),
            )

        first_agent_reply = True
        for author_email, body, hours in replies:
            author = users[author_email]
            when = created + timedelta(hours=hours)
            if author["role"] == "agent" and first_agent_reply:
                first_agent_reply = False
                log(db, "login", author, when - timedelta(minutes=20))
                log(db, "ticket_assigned", author, when - timedelta(minutes=12), "ticket", tid, f"#{number}")
                log(db, "status_changed", author, when - timedelta(minutes=10), "ticket", tid,
                    f"#{number}: Open to In progress")
            db.execute("INSERT INTO replies (ticket_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
                       (tid, author["id"], body, stamp(when)))
            log(db, "reply_added", author, when, "ticket", tid, f"#{number}")

        if t["status"] == "resolved" and agent:
            log(db, "status_changed", agent, updated, "ticket", tid, f"#{number}: In progress to Resolved")

    # Recent sign-ins so the Users page and activity log have something to show.
    for i, user in enumerate(users.values()):
        when = NOW - timedelta(hours=1 + i % 4, minutes=7 * i)
        log(db, "login", user, when)
        db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (stamp(when), user["id"]))

    rohan = users["rohan.mehta@example.test"]
    log(db, "login_failed", rohan, NOW - timedelta(days=2, hours=3), details="rohan.mehta@example.test")

    db.commit()


def main():
    app = create_app()
    db_path = Path(app.config["DATABASE"])
    if db_path.exists() and "--yes" not in sys.argv:
        answer = input(f"This deletes everything in {db_path} and all uploaded files. Continue? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was changed.")
            return

    uploads = reset_storage(app)
    with app.app_context():
        init_db()
        seed(get_db(), uploads)

    print("\nDemo data is ready.\n")
    print(f"  Admin       admin@example.test                 {ADMIN_PASSWORD}")
    for company in COMPANIES:
        print(f"\n  {company['name']} (signup code {company['code']})")
        for name, email, _, _ in company["agents"]:
            print(f"  Agent       {email:<34} {DEMO_PASSWORD}")
        for name, email, _, _ in company["customers"]:
            print(f"  Customer    {email:<34} {DEMO_PASSWORD}")
    print("\nStart the app with: flask --app helpdesk run --debug\n")


if __name__ == "__main__":
    main()