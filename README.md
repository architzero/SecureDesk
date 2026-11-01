# HelpDesk

A customer support ticket system that many companies can use at the same time.
Built with Flask, SQLite and Jinja templates. Runs on Ubuntu, including WSL on Windows.

- **Customers** sign up with a company code, raise tickets (with an optional file), reply and search their own tickets.
- **Agents** see every ticket for their company, reply, change status, assign tickets to themselves,
  download attachments and draft replies with AI (Groq).
- **The admin** adds companies, creates agent accounts, deactivates users and reads the activity log.
  The admin doesn't see tickets.

## Folder structure

```
helpdesk-app/
├── README.md
├── requirements.txt
├── .env.example          copy to .env and fill in
├── .gitignore
├── run.py                python run.py starts the app
├── seed.py               resets the database with demo data
├── instance/             created on first run: helpdesk.db and uploads/
└── helpdesk/
    ├── __init__.py       app factory and error pages
    ├── config.py         settings read from .env
    ├── constants.py      statuses, priorities, categories, log labels
    ├── db.py             SQLite connection and CLI commands
    ├── schema.sql        all tables
    ├── security.py       sessions, CSRF, roles, activity log, security headers
    ├── validation.py     form field checks
    ├── filters.py        template filters and globals
    ├── services.py       ticket logic shared by web pages and the API
    ├── ai.py             Groq client for AI drafts
    ├── auth.py           signup, sign in, sign out, password reset
    ├── tickets.py        ticket pages
    ├── admin.py          companies, users, activity log
    ├── api.py            JSON REST API
    ├── static/           css/app.css, js/app.js, img/favicon.svg
    └── templates/        base, macros, auth/, tickets/, admin/, errors/
```

## Setup on Ubuntu (WSL)

Keep the project in your Linux home folder (`~/helpdesk-app`), not under `/mnt/c`.
SQLite is slower and can lock up on the Windows drive.

```bash
# 1. Install Python tools (once)
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

# 2. Go to the project
cd ~/helpdesk-app

# 3. Create and turn on a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install the packages
pip install -r requirements.txt

# 5. Create .env with a random secret key
cp .env.example .env
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')/" .env

# 6. Add your Groq key: paste it after GROQ_API_KEY=, then Ctrl+O, Enter, Ctrl+X
nano .env

# 7. Load the demo data
python seed.py --yes

# 8. Start the app
flask --app helpdesk run --debug
```

Open **http://localhost:5000** in your Windows browser. Stop the app with Ctrl+C.

Every time after that:

```bash
cd ~/helpdesk-app
source .venv/bin/activate
flask --app helpdesk run --debug
```

`python run.py` does the same thing as the `flask` command.

## Demo accounts

| Role | Company | Email | Password |
|---|---|---|---|
| Admin | – | admin@example.test | Admin@1234 |
| Agent | Acme Internet | priya.nair@acme.example.test | Demo@1234 |
| Agent | Acme Internet | daniel.brooks@acme.example.test | Demo@1234 |
| Customer | Acme Internet | rohan.mehta@example.test | Demo@1234 |
| Customer | Acme Internet | sara.lopez@example.test | Demo@1234 |
| Agent | Zest Bank | ananya.rao@zestbank.example.test | Demo@1234 |
| Agent | Zest Bank | marcus.hale@zestbank.example.test | Demo@1234 |
| Customer | Zest Bank | kabir.shah@example.test | Demo@1234 |
| Customer | Zest Bank | emily.chen@example.test | Demo@1234 |

Signup codes: **ACME-2026** and **ZEST-2026**.

## Things to try

- **Sign up as a customer:** click "Create an account" on the sign-in page and use `ACME-2026`.
- **AI draft:** sign in as Priya, open ticket #2 ("Internet drops every evening"), click
  **Draft reply with AI**, edit the draft and send it. Replies built from a draft show an
  "AI-assisted" tag to agents only.
- **Attachments:** ticket #2 at Acme has `router-log.txt`. Customers can attach one file when raising a ticket.
- **Search:** type words or a ticket number like `#2`. Search covers subjects, descriptions,
  categories, customer names and replies.
- **Forgot password:** submit your email on the "Forgot password?" page. The reset link is
  printed in the terminal running the app, because there's no email in this setup. It expires after 30 minutes.
- **Separation between companies:** Acme agents never see Zest Bank tickets, and customers only see their own.
- **Admin:** sign in as admin to add companies, create agents, deactivate users (they're signed out
  right away) and filter the activity log by action, company, person or IP.

## JSON API

Base URL: `http://localhost:5000/api/v1`. Every endpoint except the token endpoint needs
`Authorization: Bearer <token>`. Customers see their own tickets and agents see their company's.
Only customers can create tickets.

| Method | Path | What it does |
|---|---|---|
| POST | `/auth/token` | Get a token: `{"email", "password"}`. A new token replaces the old one. |
| DELETE | `/auth/token` | Revoke your token |
| GET | `/tickets` | List tickets. Optional: `q`, `status`, `priority`, `assigned` (agents: `me` or `none`), `page` |
| GET | `/tickets/search?q=...` | Keyword search (same filters) |
| GET | `/tickets/<number>` | One ticket with its replies and attachment details |
| GET | `/tickets/<number>/replies` | Replies only |
| POST | `/tickets` | Create: `{"subject", "description", "category", "priority"}` |
| POST | `/tickets/<number>/replies` | Reply: `{"body"}` |

Categories: `General question`, `Billing`, `Technical issue`, `Account`, `Feature request`.
Priorities: `low`, `medium`, `high`. Statuses: `open`, `in_progress`, `resolved`.

Try it in a second terminal while the app runs:

```bash
BASE=http://localhost:5000/api/v1

TOKEN=$(curl -s -X POST $BASE/auth/token \
  -H "Content-Type: application/json" \
  -d '{"email":"rohan.mehta@example.test","password":"Demo@1234"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")

curl -s $BASE/tickets -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

curl -s "$BASE/tickets/search?q=router" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

curl -s $BASE/tickets/2 -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

curl -s -X POST $BASE/tickets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"subject":"Change my Wi-Fi password","description":"I cannot find where to change the Wi-Fi password in the app.","category":"Technical issue","priority":"low"}' \
  | python3 -m json.tool

curl -s -X POST $BASE/tickets/2/replies \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"body":"I will be home all day on Saturday if the team can visit then."}' \
  | python3 -m json.tool
```

Errors come back as `{"error": "..."}`. Validation errors also include `"errors": {"field": "..."}`.

## Settings (.env)

| Name | Default | What it does |
|---|---|---|
| `SECRET_KEY` | none | Signs session cookies. Without it, everyone is signed out on every restart. |
| `GROQ_API_KEY` | none | Turns on AI drafts. Without it, the button is disabled. |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Groq model for drafts. Groq retires models over time; see https://console.groq.com/docs/models |
| `MAX_UPLOAD_MB` | `5` | Largest attachment size |
| `DISPLAY_TIMEZONE` | `Asia/Kolkata` | Time zone for dates on screen. The database stores UTC. |
| `SESSION_COOKIE_SECURE` | `0` | Set to `1` when serving over HTTPS |

Restart the app after you change `.env`.

## Useful commands

```bash
python seed.py                         # reset everything to demo data (asks first)
python seed.py --yes                   # same, without asking
flask --app helpdesk init-db           # create empty tables (keeps existing data)
flask --app helpdesk create-admin      # add an admin account (asks for name, email, password)
```

To start with an empty platform instead of demo data:

```bash
rm -rf instance
flask --app helpdesk init-db
flask --app helpdesk create-admin
```

## Troubleshooting

- **`ModuleNotFoundError: No module named 'flask'`** – turn on the virtual environment: `source .venv/bin/activate`.
- **"AI drafts are turned off"** – `GROQ_API_KEY` is empty in `.env`, or the app wasn't restarted after you added it.
- **"Groq can't use the model"** – that model was retired. Pick a current one from Groq's models page, put it in `GROQ_MODEL` and restart.
- **"Groq rejected the API key"** – check the key in `.env` for missing characters, spaces or quotes.
- **Port 5000 already in use** – run on another port: `flask --app helpdesk run --debug --port 5001`.
- **"Too many failed sign-in attempts"** – wait 15 minutes, or run `python seed.py --yes` to reset.
- **`$'\r': command not found` when running a script** – the file has Windows line endings: `sed -i 's/\r$//' file.sh`.
- **The page looks unstyled** – make sure `helpdesk/static/css/app.css` exists, then hard-refresh with Ctrl+Shift+R.

## Security notes

- Passwords are hashed (scrypt). Reset links and API tokens are stored only as SHA-256 hashes.
- Every form has a CSRF token. Pages send a strict Content-Security-Policy and other security headers.
- Each ticket query is limited to the signed-in user's company (and to the customer's own tickets),
  in `services.py`. Both the web pages and the API go through it.
- Uploads are limited by type and size, saved under random names outside `static/`, and always downloaded rather than opened in the browser.
- Failed sign-ins are rate limited using the activity log.
- Deactivating a user or resetting a password signs that user out everywhere and revokes their API token.
- This setup is for running on your laptop. To put it online, run it with a production server
  such as gunicorn behind HTTPS, set `SESSION_COOKIE_SECURE=1`, and add werkzeug's `ProxyFix`
  so the activity log records real client IPs.

