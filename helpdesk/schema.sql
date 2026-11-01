PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    code        TEXT    NOT NULL UNIQUE,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER REFERENCES companies(id) ON DELETE RESTRICT,
    role            TEXT    NOT NULL CHECK (role IN ('customer', 'agent', 'admin')),
    name            TEXT    NOT NULL,
    email           TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    phone           TEXT,
    password_hash   TEXT    NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    session_epoch   INTEGER NOT NULL DEFAULT 0,
    api_token_hash  TEXT    UNIQUE,
    api_token_expires_at TEXT,          -- F11: API tokens now expire
    created_at      TEXT    NOT NULL,
    last_login_at   TEXT,
    CHECK ((role = 'admin' AND company_id IS NULL) OR (role <> 'admin' AND company_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id, role);

CREATE TABLE IF NOT EXISTS tickets (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id         INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    number             INTEGER NOT NULL,
    customer_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assigned_agent_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    subject            TEXT    NOT NULL,
    description        TEXT    NOT NULL,
    category           TEXT    NOT NULL,
    priority           TEXT    NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
    status             TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved')),
    created_at         TEXT    NOT NULL,
    updated_at         TEXT    NOT NULL,
    UNIQUE (company_id, number)
);
CREATE INDEX IF NOT EXISTS idx_tickets_company ON tickets(company_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_tickets_customer ON tickets(customer_id, updated_at);

CREATE TABLE IF NOT EXISTS ai_drafts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    agent_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    model       TEXT    NOT NULL,
    draft       TEXT    NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS replies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id    INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    body         TEXT    NOT NULL,
    ai_draft_id  INTEGER REFERENCES ai_drafts(id) ON DELETE SET NULL,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replies_ticket ON replies(ticket_id, created_at);

CREATE TABLE IF NOT EXISTS attachments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id      INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    uploaded_by    INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    original_name  TEXT    NOT NULL,
    stored_name    TEXT    NOT NULL UNIQUE,
    content_type   TEXT    NOT NULL,
    size_bytes     INTEGER NOT NULL,
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS password_resets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT    NOT NULL UNIQUE,
    expires_at  TEXT    NOT NULL,
    used_at     TEXT,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    company_id   INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    action       TEXT    NOT NULL,
    target_type  TEXT,
    target_id    INTEGER,
    details      TEXT,
    ip_address   TEXT,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at);
CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(action, created_at);

