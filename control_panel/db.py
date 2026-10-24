"""SQLite helpers for the control panel (users + robots)."""

import sqlite3
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator'
);
CREATE TABLE IF NOT EXISTS robots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    token TEXT NOT NULL DEFAULT '',
    default_proxy_ip TEXT NOT NULL DEFAULT '',
    default_proxy_port TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS accounts (
    label TEXT PRIMARY KEY,
    bank TEXT NOT NULL DEFAULT '',
    robot_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    port INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def init_db(db_path):
    with closing(connect(db_path)) as conn:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            pass
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()


def _migrate(conn):
    """Bring older databases up to the current schema."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "role" not in cols:
        # Databases created before roles only ever held the seeded admin.
        conn.execute(
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'"
        )


def get_user(db_path, username):
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(db_path, user_id):
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def list_users(db_path):
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT id, username, role FROM users ORDER BY username"
        ).fetchall()
        return [dict(r) for r in rows]


def add_user(db_path, username, password_hash, role="operator"):
    """Insert a user; returns the new id, or None if the username is taken."""
    try:
        with closing(connect(db_path)) as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
            conn.commit()
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def set_user_password(db_path, user_id, password_hash):
    with closing(connect(db_path)) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()


def _guarded_write(db_path, user_id, mutate):
    """Run *mutate(conn, row)* atomically, blocking last-admin removal.

    Returns ``"ok"``, ``"missing"`` or ``"last_admin"``.
    """
    conn = connect(db_path)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return "missing"
        if row["role"] == "admin":
            remaining = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin'"
            ).fetchone()["n"]
            if remaining <= 1:
                conn.execute("ROLLBACK")
                return "last_admin"
        mutate(conn, row)
        conn.execute("COMMIT")
        return "ok"
    finally:
        conn.close()


def set_user_role_guarded(db_path, user_id, role):
    """Set *role*, refusing to demote the last admin. Returns a status string."""

    def mutate(conn, row):
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, row["id"]))

    return _guarded_write(db_path, user_id, mutate)


def delete_user_guarded(db_path, user_id):
    """Delete *user_id*, refusing to remove the last admin. Returns a status."""

    def mutate(conn, row):
        conn.execute("DELETE FROM users WHERE id = ?", (row["id"],))

    return _guarded_write(db_path, user_id, mutate)


def seed_admin(db_path, username, password_hash):
    with closing(connect(db_path)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) "
            "VALUES (?, ?, 'admin')",
            (username, password_hash),
        )
        # Keep the configured account as an admin even if it already existed.
        conn.execute(
            "UPDATE users SET role = 'admin' WHERE username = ?", (username,)
        )
        conn.commit()


def list_robots(db_path):
    with closing(connect(db_path)) as conn:
        rows = conn.execute("SELECT * FROM robots ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_robot(db_path, robot_id):
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM robots WHERE id = ?", (robot_id,)
        ).fetchone()
        return dict(row) if row else None


def add_robot(db_path, name, host, port, token="", proxy_ip="", proxy_port=""):
    with closing(connect(db_path)) as conn:
        cur = conn.execute(
            "INSERT INTO robots "
            "(name, host, port, token, default_proxy_ip, default_proxy_port) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, host, int(port), token, proxy_ip, proxy_port),
        )
        conn.commit()
        return cur.lastrowid


def update_robot(db_path, robot_id, **fields):
    allowed = {"name", "host", "port", "token", "default_proxy_ip", "default_proxy_port"}
    sets = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "port":
            value = int(value)
        sets.append("{} = ?".format(key))
        values.append(value)
    if not sets:
        return
    values.append(robot_id)
    with closing(connect(db_path)) as conn:
        conn.execute(
            "UPDATE robots SET {} WHERE id = ?".format(", ".join(sets)), values
        )
        conn.commit()


def delete_robot(db_path, robot_id):
    with closing(connect(db_path)) as conn:
        conn.execute("DELETE FROM robots WHERE id = ?", (robot_id,))
        conn.execute("DELETE FROM accounts WHERE robot_id = ?", (robot_id,))
        conn.commit()


# ------------------------------------------------------------------- accounts
def upsert_account(db_path, label, bank, robot_id):
    """Assign *label* to *robot_id* (global uniqueness enforced by label PK)."""
    with closing(connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO accounts (label, bank, robot_id) VALUES (?, ?, ?) "
            "ON CONFLICT(label) DO UPDATE SET bank = excluded.bank, "
            "robot_id = excluded.robot_id",
            (label, bank or "", int(robot_id)),
        )
        conn.commit()


def reserve_account(db_path, label, bank, robot_id):
    """Claim *label* for *robot_id* atomically; returns False if already taken."""
    try:
        with closing(connect(db_path)) as conn:
            conn.execute(
                "INSERT INTO accounts (label, bank, robot_id) VALUES (?, ?, ?)",
                (label, bank or "", int(robot_id)),
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def prune_robot_accounts(db_path, robot_id, labels):
    """Drop registry rows for *robot_id* whose labels are no longer present."""
    with closing(connect(db_path)) as conn:
        if labels:
            placeholders = ",".join("?" for _ in labels)
            conn.execute(
                "DELETE FROM accounts WHERE robot_id = ? AND label NOT IN ({})".format(
                    placeholders
                ),
                [int(robot_id)] + list(labels),
            )
        else:
            conn.execute("DELETE FROM accounts WHERE robot_id = ?", (int(robot_id),))
        conn.commit()


def delete_orphan_accounts(db_path, robot_ids):
    """Remove registry rows whose robot was deleted from the panel."""
    ids = [int(rid) for rid in robot_ids]
    with closing(connect(db_path)) as conn:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                "DELETE FROM accounts WHERE robot_id NOT IN ({})".format(
                    placeholders
                ),
                ids,
            )
        else:
            conn.execute("DELETE FROM accounts")
        conn.commit()


def delete_account(db_path, label):
    with closing(connect(db_path)) as conn:
        conn.execute("DELETE FROM accounts WHERE label = ?", (label,))
        conn.commit()


def get_account_owner(db_path, label):
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT a.label, a.bank, a.robot_id, r.name AS robot_name "
            "FROM accounts a LEFT JOIN robots r ON r.id = a.robot_id "
            "WHERE a.label = ?",
            (label,),
        ).fetchone()
        return dict(row) if row else None


def list_accounts(db_path):
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT a.label, a.bank, a.robot_id, r.name AS robot_name "
            "FROM accounts a LEFT JOIN robots r ON r.id = a.robot_id "
            "ORDER BY a.label"
        ).fetchall()
        return [dict(r) for r in rows]


# -------------------------------------------------------------------- proxies
def list_proxies(db_path):
    with closing(connect(db_path)) as conn:
        rows = conn.execute("SELECT * FROM proxies ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_proxy(db_path, proxy_id):
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM proxies WHERE id = ?", (proxy_id,)
        ).fetchone()
        return dict(row) if row else None


def add_proxy(db_path, ip, port, note=""):
    with closing(connect(db_path)) as conn:
        cur = conn.execute(
            "INSERT INTO proxies (ip, port, note) VALUES (?, ?, ?)",
            (ip, int(port), note),
        )
        conn.commit()
        return cur.lastrowid


def delete_proxy(db_path, proxy_id):
    with closing(connect(db_path)) as conn:
        conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
        conn.commit()
