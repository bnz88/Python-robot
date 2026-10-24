"""Central control panel: a Flask app managing many BCA robot servers.

Run:
    python app.py

Serves the login page + dashboard and a JSON API that relays requests to each
robot over token-authed HTTP. See config.json for the panel host/port, the
admin credentials, the secret key, and the SQLite database path.
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from waitress import serve

import auth
import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise SystemExit("config.json not found at {}".format(CONFIG_PATH))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


config = load_config()


def resolve_db_path():
    path = config.get("db_path", "panel.db")
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    return path


DB_PATH = resolve_db_path()

# Banks the panel knows about, in display order.
BANK_ORDER = ["mybca", "klikbca", "cimb", "permata"]


def _hidden_banks():
    """Banks hidden from operators (config ``hidden_banks``).

    Admins still see and manage them, so the data is untouched and the bank can
    be re-exposed by editing the config; operators cannot see, add, edit, ban or
    start those accounts.
    """
    raw = config.get("hidden_banks") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return {str(bank).strip().lower() for bank in raw if str(bank).strip()}


HIDDEN_BANKS = _hidden_banks()


def _is_admin():
    """True for an admin session (False outside a request, e.g. background work)."""
    try:
        user = auth.current_user()
    except RuntimeError:
        return False
    return bool(user and user.get("role") == "admin")


def _bank_hidden(bank):
    return str(bank or "").strip().lower() in HIDDEN_BANKS


def _visible_banks():
    if _is_admin():
        return list(BANK_ORDER)
    return [bank for bank in BANK_ORDER if bank not in HIDDEN_BANKS]


LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _valid_label(label):
    """Labels double as output filenames, so keep them filesystem-safe."""
    return bool(LABEL_RE.match(str(label or "")))


def _label_collision(label):
    """Existing label that collides case-insensitively, or None."""
    folded = str(label or "").casefold()
    for row in db.list_accounts(DB_PATH):
        existing = row["label"]
        if existing != label and existing.casefold() == folded:
            return existing
    return None


def _account_hidden(label):
    """True when *label* belongs to a hidden bank (for operator guards)."""
    owner = db.get_account_owner(DB_PATH, label)
    return bool(owner and _bank_hidden(owner.get("bank")))


# Let auth re-read the role from the DB so demotions/deletions take effect
# without waiting for the affected session to expire.
auth.set_user_loader(lambda user_id: db.get_user_by_id(DB_PATH, user_id))

app = Flask(__name__)
app.secret_key = config.get("secret_key") or os.urandom(24)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# In-memory status cache so JS polling does not hammer every robot each tick.
_status_cache = {"ts": 0.0, "data": None}


@app.context_processor
def inject_user():
    """Expose the signed-in user (with role) to every template."""
    return {"user": auth.current_user()}
_accounts_cache = {}  # visibility (bool) -> {"ts": float, "data": dict}


def invalidate_cache():
    _status_cache["ts"] = 0.0
    _status_cache["data"] = None
    _accounts_cache.clear()


# --------------------------------------------------------------------- relay
def robot_url(robot, path):
    return "http://{}:{}{}".format(robot["host"], robot["port"], path)


def relay(robot, method, path, timeout=4.0, **kwargs):
    headers = {"X-Robot-Token": robot.get("token") or ""}
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))
    try:
        resp = requests.request(
            method, robot_url(robot, path), timeout=timeout, headers=headers, **kwargs
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": "unreachable: {}".format(exc)}
    if resp.status_code == 401:
        return {"ok": False, "error": "auth failed (wrong robot token)"}
    return {"ok": True, "status": resp.status_code, "body": resp.text}


def relay_json(robot, method, path, **kwargs):
    result = relay(robot, method, path, **kwargs)
    if not result["ok"]:
        return result
    result["http_ok"] = 200 <= result.get("status", 0) < 300
    try:
        result["data"] = json.loads(result["body"])
    except ValueError:
        result["data"] = None
    return result


def relay_payload(result, default_status=502):
    """Turn a relay result into a Flask response, preserving robot 4xx errors."""
    if not result.get("ok"):
        return jsonify(result), default_status
    status = result.get("status") or default_status
    data = result.get("data")
    if 200 <= status < 300:
        return jsonify(data if data is not None else {})
    if 400 <= status < 500 and isinstance(data, dict):
        return jsonify(data), status
    message = None
    if isinstance(data, dict):
        message = data.get("error")
    return _json_error(message or result.get("error") or "robot error", 502)


def relay_bytes(robot, path, timeout=4.0):
    """Fetch a binary resource (e.g. the live frame) from a robot.

    Mirrors relay() but keeps the response body as bytes instead of text, so
    images are not corrupted by decoding.
    """
    headers = {"X-Robot-Token": robot.get("token") or ""}
    try:
        resp = requests.get(robot_url(robot, path), timeout=timeout, headers=headers)
    except requests.RequestException as exc:
        return {"ok": False, "error": "unreachable: {}".format(exc)}
    if resp.status_code == 401:
        return {"ok": False, "status": 401, "error": "auth failed (wrong robot token)"}
    return {
        "ok": True,
        "status": resp.status_code,
        "body": resp.content,
        "ctype": resp.headers.get("Content-Type", "application/octet-stream"),
    }


def fetch_status(robot):
    result = relay_json(robot, "GET", "/control/status", timeout=2.0)
    if not result["ok"]:
        error = result.get("error", "")
        return {
            "online": False,
            "running": False,
            "stopping": False,
            "pid": None,
            "current_account": None,
            "next_account": None,
            "error": error,
            "auth_error": error.startswith("auth failed"),
        }
    data = result.get("data") or {}
    if not result.get("http_ok"):
        error = data.get("error") if isinstance(data, dict) else None
        return {
            "online": False,
            "running": False,
            "stopping": False,
            "pid": None,
            "current_account": None,
            "next_account": None,
            "error": error or "robot status request failed",
            "auth_error": False,
        }
    return {
        "online": True,
        "running": bool(data.get("running")),
        "stopping": bool(data.get("stopping")),
        "pid": data.get("pid"),
        "current_account": data.get("current_account"),
        "next_account": data.get("next_account"),
        "error": None,
        "auth_error": False,
    }


def _get_robot_or_none(robot_id):
    return db.get_robot(DB_PATH, robot_id)


def _json_error(message, status):
    return jsonify({"error": message}), status


def proxy_defaults(data):
    """Return (proxy_ip, proxy_port) from an optional proxy_id or explicit fields."""
    proxy_id = data.get("proxy_id")
    if proxy_id not in (None, ""):
        try:
            proxy = db.get_proxy(DB_PATH, int(proxy_id))
        except (TypeError, ValueError):
            proxy = None
        if proxy:
            return proxy["ip"], str(proxy["port"])
    return (
        (data.get("default_proxy_ip") or "").strip(),
        (data.get("default_proxy_port") or "").strip(),
    )


# --------------------------------------------------------------------- pages
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = db.get_user(DB_PATH, username)
        if user and auth.verify_password(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user.get("role") or auth.DEFAULT_ROLE
            return redirect(url_for("dashboard"))
        error = "Invalid username or password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def _live_refresh_ms():
    """Panel live-view refresh interval in milliseconds (min 200)."""
    try:
        value = int(float(config.get("live_refresh_ms", 1000)))
    except (TypeError, ValueError):
        value = 1000
    return max(200, value)


@app.route("/")
@auth.login_required
def dashboard():
    return render_template(
        "dashboard.html", banks=_visible_banks(), refresh_ms=_live_refresh_ms()
    )


@app.route("/robot")
@auth.admin_required
def robot_page():
    return render_template("robot.html")


@app.route("/accounts")
@auth.login_required
def accounts_page():
    return render_template("accounts.html", banks=_visible_banks())


@app.route("/logs")
@auth.login_required
def logs_page():
    return render_template("logs.html")


@app.route("/proxies")
@auth.login_required
def proxies_page():
    return render_template("proxies.html")


@app.route("/settings")
@auth.admin_required
def settings_page():
    return render_template("settings.html")


@app.route("/users")
@auth.admin_required
def users_page():
    return render_template("users.html")


@app.route("/live")
@auth.login_required
def live_page():
    return render_template("live.html", refresh_ms=_live_refresh_ms())


# ------------------------------------------------------------------ robot list
@app.route("/api/robots")
@auth.login_required
def api_robots():
    now = time.time()
    if _status_cache["data"] is not None and (now - _status_cache["ts"]) < 1.5:
        return jsonify(_status_cache["data"])

    robots = db.list_robots(DB_PATH)
    out = []
    if robots:
        workers = max(1, min(8, len(robots)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            statuses = list(executor.map(fetch_status, robots))
    else:
        statuses = []
    for robot, status in zip(robots, statuses):
        item = {
            "id": robot["id"],
            "name": robot["name"],
            "host": robot["host"],
            "port": robot["port"],
            "default_proxy_ip": robot.get("default_proxy_ip", ""),
            "default_proxy_port": robot.get("default_proxy_port", ""),
        }
        item.update(status)
        item["last_seen"] = now if item["online"] else None
        out.append(item)

    _status_cache["ts"] = now
    _status_cache["data"] = out
    return jsonify(out)


# ------------------------------------------------------------------ robot CRUD
def _parse_port(value):
    """Return a valid TCP port as int, or None."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 0 < port < 65536 else None


@app.route("/api/robots", methods=["POST"])
@auth.admin_required
def api_robot_add():
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    host = (data.get("host") or "").strip()
    port = _parse_port(data.get("port"))
    if not name or not host or port is None:
        return _json_error("name, host and a valid port are required", 400)
    proxy_ip, proxy_port = proxy_defaults(data)
    robot_id = db.add_robot(
        DB_PATH,
        name,
        host,
        port,
        token=(data.get("token") or "").strip(),
        proxy_ip=proxy_ip,
        proxy_port=proxy_port,
    )
    invalidate_cache()
    return jsonify({"id": robot_id, "ok": True})


@app.route("/api/robots/<int:robot_id>/edit", methods=["POST"])
@auth.admin_required
def api_robot_edit(robot_id):
    if not _get_robot_or_none(robot_id):
        return _json_error("unknown robot", 404)
    data = request.get_json(silent=True) or request.form
    fields = {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return _json_error("name cannot be empty", 400)
        fields["name"] = name
    if "host" in data:
        host = (data.get("host") or "").strip()
        if not host:
            return _json_error("host cannot be empty", 400)
        fields["host"] = host
    if "port" in data:
        port = _parse_port(data.get("port"))
        if port is None:
            return _json_error("port must be a number between 1 and 65535", 400)
        fields["port"] = port
    # The edit dialog cannot show the stored token, so an empty field means
    # "keep the current token" rather than "clear it".
    token = (data.get("token") or "").strip()
    if token:
        fields["token"] = token
    if any(k in data for k in ("proxy_id", "default_proxy_ip", "default_proxy_port")):
        proxy_ip, proxy_port = proxy_defaults(data)
        fields["default_proxy_ip"] = proxy_ip
        fields["default_proxy_port"] = proxy_port
    db.update_robot(DB_PATH, robot_id, **fields)
    invalidate_cache()
    return jsonify({"ok": True})


@app.route("/api/robots/<int:robot_id>/delete", methods=["POST"])
@auth.admin_required
def api_robot_delete(robot_id):
    db.delete_robot(DB_PATH, robot_id)
    invalidate_cache()
    return jsonify({"ok": True})


# --------------------------------------------------------------- start / stop
@app.route("/api/robots/<int:robot_id>/start", methods=["POST"])
@auth.login_required
def api_robot_start(robot_id):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    data = request.get_json(silent=True) or request.form
    account = (data.get("account") or "").strip()
    if account and _bank_hidden(account) and not _is_admin():
        return _json_error("bank '{}' is not available".format(account), 403)

    mode = (data.get("proxy") or "").strip().lower()
    payload = {}
    if account:
        payload["account"] = account

    if mode == "auto":
        proxies = db.list_proxies(DB_PATH)
        if not proxies:
            return _json_error(
                "no proxies configured - Auto needs at least one proxy", 400
            )
        payload["proxy"] = "auto"
        payload["proxies"] = [
            {"ip": p["ip"], "port": p["port"]} for p in proxies
        ]
    else:
        proxy_ip = str(
            data.get("proxy_ip") or robot.get("default_proxy_ip") or ""
        ).strip()
        proxy_port = str(
            data.get("proxy_port") or robot.get("default_proxy_port") or ""
        ).strip()
        if proxy_ip and proxy_port:
            payload["proxy"] = "manual"
            payload["proxy_ip"] = proxy_ip
            payload["proxy_port"] = proxy_port

    result = relay_json(robot, "POST", "/control/start", json=payload)
    if not result["ok"]:
        return jsonify(result), 502
    invalidate_cache()
    return relay_payload(result)


@app.route("/api/robots/<int:robot_id>/stop", methods=["POST"])
@auth.login_required
def api_robot_stop(robot_id):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    result = relay_json(robot, "POST", "/control/stop", timeout=8.0)
    if not result["ok"]:
        return jsonify(result), 502
    invalidate_cache()
    return relay_payload(result)


@app.route("/api/robots/<int:robot_id>/next", methods=["POST"])
@auth.login_required
def api_robot_next(robot_id):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    data = request.get_json(silent=True) or request.form
    label = (data.get("label") or "").strip()
    if not label:
        return _json_error("label is required", 400)
    if not _is_admin() and _account_hidden(label):
        return _json_error("account '{}' is not available".format(label), 403)
    path = "/next?label={}".format(quote(label, safe=""))
    result = relay_json(robot, "POST", path, timeout=6.0)
    if not result["ok"]:
        return jsonify(result), 502
    invalidate_cache()
    return relay_payload(result)


# ------------------------------------------------------------------ accounts
@app.route("/api/robots/<int:robot_id>/accounts")
@auth.login_required
def api_robot_accounts(robot_id):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    result = relay_json(robot, "GET", "/accounts")
    if not result["ok"]:
        return jsonify(result), 502
    accounts = result.get("data")
    if not result.get("http_ok") or not isinstance(accounts, list):
        return _json_error("robot did not return an account list", 502)
    if not _is_admin():
        accounts = [acc for acc in accounts if not _bank_hidden(acc.get("bank"))]
    return jsonify(accounts)


@app.route("/api/robots/<int:robot_id>/accounts/<label>/ban", methods=["POST"])
@auth.login_required
def api_robot_ban(robot_id, label):
    return _toggle_account(robot_id, label, "ban")


@app.route("/api/robots/<int:robot_id>/accounts/<label>/unban", methods=["POST"])
@auth.login_required
def api_robot_unban(robot_id, label):
    return _toggle_account(robot_id, label, "unban")


def _toggle_account(robot_id, label, action):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    if not _is_admin() and _account_hidden(label):
        return _json_error("account '{}' is not available".format(label), 403)
    path = "/accounts/{}/{}".format(quote(label, safe=""), action)
    result = relay_json(robot, "POST", path)
    if not result["ok"]:
        return jsonify(result), 502
    return relay_payload(result)


@app.route("/api/robots/<int:robot_id>/accounts/<label>/update", methods=["POST"])
@auth.login_required
def api_account_update(robot_id, label):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    data = request.get_json(silent=True) or request.form
    if "bank" in data and str(data.get("bank") or "") not in BANK_ORDER:
        return _json_error("unknown bank", 400)
    if not _is_admin():
        if _bank_hidden(data.get("bank")) or _account_hidden(label):
            return _json_error("account '{}' is not available".format(label), 403)
    payload = {
        k: data[k]
        for k in ("bank", "unique_id", "bank_shortname", "enabled", "username", "password", "omitted_rows")
        if k in data
    }
    path = "/accounts/{}/update".format(quote(label, safe=""))
    result = relay_json(robot, "POST", path, json=payload, timeout=6.0)
    if not result["ok"]:
        return jsonify(result), 502
    invalidate_cache()
    return relay_payload(result)


# ---------------------------------------------------------- global accounts
def _poll_one_robot(robot):
    res = relay_json(robot, "GET", "/accounts", timeout=4.0)
    accounts = res.get("data") if res.get("ok") and res.get("http_ok") else None
    if not isinstance(accounts, list):
        accounts = None
    ok = accounts is not None
    return robot["id"], {"robot": robot, "ok": ok, "accounts": accounts}


def poll_accounts_all():
    """Poll every robot's /accounts in parallel -> {robot_id: {robot, ok, accounts}}."""
    robots = db.list_robots(DB_PATH)
    with ThreadPoolExecutor(max_workers=max(1, len(robots))) as executor:
        results = list(executor.map(_poll_one_robot, robots))
    return dict(results)


def reconcile_accounts(polled):
    """Refresh the ownership registry from live robots; return conflicting labels."""
    counts = {}
    existing = {
        (row["robot_id"], row["label"]): row.get("bank") or ""
        for row in db.list_accounts(DB_PATH)
    }
    for rid, info in polled.items():
        if not info["ok"]:
            continue
        labels = []
        for acc in info["accounts"]:
            label = acc.get("label")
            if not label:
                continue
            labels.append(label)
            bank = acc.get("bank") or ""
            if existing.get((rid, label)) != bank:
                db.upsert_account(DB_PATH, label, bank, rid)
            counts.setdefault(label, set()).add(rid)
        wanted = set(labels)
        stale = [
            label
            for (robot_id, label) in existing
            if robot_id == rid and label not in wanted
        ]
        if stale:
            db.prune_robot_accounts(DB_PATH, rid, labels)
    valid_ids = {r["id"] for r in db.list_robots(DB_PATH)}
    if any(robot_id not in valid_ids for (robot_id, _label) in existing):
        db.delete_orphan_accounts(DB_PATH, valid_ids)
    return sorted(label for label, rids in counts.items() if len(rids) > 1)


@app.route("/api/accounts")
@auth.login_required
def api_accounts():
    now = time.time()
    show_hidden = _is_admin()
    cached = _accounts_cache.get(show_hidden)
    if cached and cached["data"] is not None and (now - cached["ts"]) < 2.5:
        return jsonify(cached["data"])

    polled = poll_accounts_all()
    conflicts = reconcile_accounts(polled)
    rows = []
    seen = set()
    for rid, info in polled.items():
        if not info["ok"]:
            continue
        for acc in info["accounts"]:
            label = acc.get("label")
            if not label:
                continue
            if not show_hidden and _bank_hidden(acc.get("bank")):
                continue
            seen.add((rid, label))
            rows.append(
                {
                    "robot_id": rid,
                    "robot_name": info["robot"]["name"],
                    "reachable": True,
                    "label": label,
                    "bank": acc.get("bank"),
                    "enabled": bool(acc.get("enabled", True)),
                    "unique_id": acc.get("unique_id"),
                    "bank_shortname": acc.get("bank_shortname"),
                    "output_exists": acc.get("output_exists"),
                    "last_scrape": acc.get("last_scrape"),
                    "conflict": label in conflicts,
                }
            )
    for a in db.list_accounts(DB_PATH):
        if (a["robot_id"], a["label"]) not in seen:
            if not show_hidden and _bank_hidden(a.get("bank")):
                continue
            rows.append(
                {
                    "robot_id": a["robot_id"],
                    "robot_name": a.get("robot_name") or "",
                    "reachable": False,
                    "label": a["label"],
                    "bank": a.get("bank"),
                    "enabled": None,
                    "unique_id": None,
                    "bank_shortname": None,
                    "output_exists": None,
                    "last_scrape": None,
                    "conflict": a["label"] in conflicts,
                }
            )
    rows.sort(key=lambda r: (r.get("label") or ""))
    result = {"accounts": rows, "conflicts": conflicts}
    _accounts_cache[show_hidden] = {"ts": now, "data": result}
    return jsonify(result)


@app.route("/api/accounts", methods=["POST"])
@auth.login_required
def api_account_add():
    data = request.get_json(silent=True) or request.form
    robot_id = data.get("robot_id")
    label = (data.get("label") or "").strip()
    bank = (data.get("bank") or "").strip()
    username = data.get("username") or ""
    password = data.get("password") or ""
    if not robot_id or not label or not bank or not username or not password:
        return _json_error(
            "robot_id, label, bank, username and password are required", 400
        )
    if not _valid_label(label):
        return _json_error(
            "label may only contain letters, numbers, dots, dashes and "
            "underscores (max 64 characters, must start with a letter or number)",
            400,
        )
    if _bank_hidden(bank) and not _is_admin():
        return _json_error("bank '{}' is not available".format(bank), 403)
    collision = _label_collision(label)
    if collision:
        return _json_error(
            "label '{}' collides with existing label '{}'".format(label, collision),
            409,
        )
    try:
        robot_id = int(robot_id)
    except (TypeError, ValueError):
        return _json_error("robot_id must be an integer", 400)
    robot = db.get_robot(DB_PATH, robot_id)
    if not robot:
        return _json_error("unknown robot", 404)

    owner = db.get_account_owner(DB_PATH, label)
    if owner:
        return _json_error(
            "account '{}' is already assigned to robot '{}'".format(
                label, owner.get("robot_name") or owner["robot_id"]
            ),
            409,
        )

    polled = poll_accounts_all()
    reconcile_accounts(polled)
    for rid, info in polled.items():
        if not info["ok"] or rid == robot_id:
            continue
        if any(a.get("label") == label for a in info["accounts"]):
            return _json_error(
                "account '{}' already exists on robot '{}'".format(
                    label, info["robot"]["name"]
                ),
                409,
            )

    # Atomically claim the label so a concurrent add cannot double-assign it.
    if not db.reserve_account(DB_PATH, label, bank, robot_id):
        return _json_error(
            "account '{}' is already assigned to another robot".format(label), 409
        )

    payload = {
        "bank": bank,
        "label": label,
        "username": username,
        "password": password,
        "unique_id": data.get("unique_id"),
        "bank_shortname": data.get("bank_shortname"),
    }
    result = relay_json(robot, "POST", "/accounts", json=payload, timeout=6.0)
    if not result["ok"] or result["status"] != 200:
        # Release the reservation; the account was not actually added.
        db.delete_account(DB_PATH, label)
        invalidate_cache()
        if not result["ok"]:
            return jsonify(result), 502
        if result["status"] == 409:
            return _json_error("label already exists on this robot", 409)
        return _json_error(
            (result.get("data") or {}).get("error", "robot rejected the account"),
            result["status"],
        )
    invalidate_cache()
    return jsonify({"ok": True, "label": label, "robot_id": robot_id})


@app.route("/api/accounts/remove", methods=["POST"])
@auth.login_required
def api_account_remove():
    data = request.get_json(silent=True) or request.form
    robot_id = data.get("robot_id")
    label = (data.get("label") or "").strip()
    if not robot_id or not label:
        return _json_error("robot_id and label are required", 400)
    try:
        robot_id = int(robot_id)
    except (TypeError, ValueError):
        return _json_error("robot_id must be an integer", 400)
    robot = db.get_robot(DB_PATH, robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    if not _is_admin() and (
        _bank_hidden(data.get("bank")) or _account_hidden(label)
    ):
        return _json_error("account '{}' is not available".format(label), 403)

    result = relay_json(
        robot,
        "POST",
        "/accounts/{}/remove".format(quote(label, safe="")),
        timeout=6.0,
    )
    if not result["ok"]:
        return jsonify(result), 502
    if result["status"] not in (200, 404):
        return _json_error(
            (result.get("data") or {}).get("error", "robot rejected removal"),
            result["status"],
        )
    db.delete_account(DB_PATH, label)
    invalidate_cache()
    return jsonify({"ok": True, "label": label})


# -------------------------------------------------------------------- proxies
@app.route("/api/proxies")
@auth.login_required
def api_proxies():
    return jsonify(db.list_proxies(DB_PATH))


@app.route("/api/proxies", methods=["POST"])
@auth.login_required
def api_proxy_add():
    if not _is_admin():
        return _json_error("only admins can add proxies", 403)
    data = request.get_json(silent=True) or request.form
    ip = (data.get("ip") or "").strip()
    port = data.get("port")
    if not ip or port in (None, ""):
        return _json_error("ip and port are required", 400)
    try:
        port = int(port)
    except (TypeError, ValueError):
        return _json_error("port must be an integer", 400)
    pid = db.add_proxy(DB_PATH, ip, port, (data.get("note") or "").strip())
    invalidate_cache()
    return jsonify({"id": pid, "ok": True})


@app.route("/api/proxies/<int:pid>/delete", methods=["POST"])
@auth.login_required
def api_proxy_delete(pid):
    if not _is_admin():
        return _json_error("only admins can remove proxies", 403)
    db.delete_proxy(DB_PATH, pid)
    invalidate_cache()
    return jsonify({"ok": True})


@app.route("/api/proxies/test", methods=["POST"])
@auth.login_required
def api_proxy_test():
    """Measure robot -> proxy -> bank-login latency on the chosen robot."""
    data = request.get_json(silent=True) or {}
    robot_id = data.get("robot_id")
    robot = db.get_robot(DB_PATH, robot_id) if robot_id else None
    if not robot:
        return _json_error("unknown robot", 404)
    proxies = db.list_proxies(DB_PATH)
    if not proxies:
        return _json_error("no proxies configured", 400)

    payload = {
        "proxies": [
            {"id": p["id"], "ip": p["ip"], "port": p["port"]} for p in proxies
        ]
    }
    result = relay_json(
        robot,
        "POST",
        "/control/test_connections",
        json=payload,
        timeout=60.0,
    )
    if not result["ok"]:
        return _json_error(result.get("error") or "robot unreachable", 502)
    body = result.get("data")
    if not isinstance(body, dict):
        return _json_error("invalid response from robot", 502)
    if body.get("error"):
        return _json_error(body["error"], 400)
    notes = {
        "{}:{}".format(p["ip"], p["port"]): (p.get("note") or "")
        for p in proxies
    }
    for row in body.get("proxies") or []:
        if isinstance(row, dict):
            row["note"] = notes.get(row.get("host"), "")
    return jsonify(body)


# --------------------------------------------------------------- statement
@app.route("/api/robots/<int:robot_id>/statement/<label>")
@auth.login_required
def api_robot_statement(robot_id, label):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    bank = request.args.get("bank", "mybca")
    if not _is_admin() and (_bank_hidden(bank) or _account_hidden(label)):
        return _json_error("account '{}' is not available".format(label), 403)
    path = "/{}/{}".format(quote(bank, safe=""), quote(label, safe=""))
    result = relay(robot, "GET", path)
    if not result["ok"]:
        return jsonify(result), 502
    if result["status"] == 404:
        return jsonify({"ok": False, "text": None, "error": "no output yet"}), 404
    if result["status"] != 200:
        return _json_error("robot rejected the statement request", 502)
    return jsonify({"ok": True, "text": result["body"]})


# --------------------------------------------------------------- live image
@app.route("/api/robots/<int:robot_id>/live")
@auth.login_required
def api_robot_live(robot_id):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    result = relay_bytes(robot, "/live/image")
    if not result.get("ok") or result.get("status") != 200:
        return jsonify({"ok": False}), 502
    return Response(result["body"], mimetype=result.get("ctype") or "image/jpeg")


# ------------------------------------------------------------------ log tail
@app.route("/api/robots/<int:robot_id>/log")
@auth.login_required
def api_robot_log(robot_id):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    lines = request.args.get("lines", "200")
    result = relay(robot, "GET", "/control/log?lines={}".format(quote(lines, safe="")))
    if not result["ok"]:
        return jsonify(result), 502
    return jsonify({"ok": True, "text": result["body"]})


# --------------------------------------------------------------------- config
@app.route("/api/robots/<int:robot_id>/config")
@auth.admin_required
def api_robot_config(robot_id):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    result = relay_json(robot, "GET", "/config", timeout=6.0)
    if not result["ok"]:
        return jsonify(result), 502
    return jsonify(result.get("data") or {})


@app.route("/api/robots/<int:robot_id>/config", methods=["POST"])
@auth.admin_required
def api_robot_config_save(robot_id):
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error("unknown robot", 404)
    payload = request.get_json(silent=True) or {}
    result = relay_json(robot, "POST", "/config", json=payload, timeout=8.0)
    if not result["ok"] or (result.get("data") or {}).get("error"):
        if result["ok"] and result["data"]:
            return jsonify(result["data"]), (result.get("status") or 400)
        return jsonify(result), 502
    return jsonify(result.get("data") or {})


# ---------------------------------------------------------------------- users
def _valid_role(role):
    return role in auth.ROLES


@app.route("/api/users")
@auth.admin_required
def api_users():
    return jsonify(db.list_users(DB_PATH))


@app.route("/api/users", methods=["POST"])
@auth.admin_required
def api_user_add():
    data = request.get_json(silent=True) or request.form
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or auth.DEFAULT_ROLE).strip()
    if not username or not password:
        return _json_error("username and password are required", 400)
    if not _valid_role(role):
        return _json_error("invalid role", 400)
    if db.get_user(DB_PATH, username):
        return _json_error("username already exists", 409)
    user_id = db.add_user(DB_PATH, username, auth.hash_password(password), role)
    if user_id is None:
        return _json_error("username already exists", 409)
    return jsonify({"id": user_id, "ok": True})


@app.route("/api/users/<int:user_id>/update", methods=["POST"])
@auth.admin_required
def api_user_update(user_id):
    target = db.get_user_by_id(DB_PATH, user_id)
    if not target:
        return _json_error("unknown user", 404)
    data = request.get_json(silent=True) or request.form
    role = data.get("role")
    password = data.get("password") or None
    if role is not None and not _valid_role(role):
        return _json_error("invalid role", 400)
    if role is not None:
        status = db.set_user_role_guarded(DB_PATH, user_id, role)
        if status == "missing":
            return _json_error("unknown user", 404)
        if status == "last_admin":
            return _json_error("cannot remove the last admin", 400)
        if user_id == session.get("user_id"):
            session["role"] = role
    if password:
        db.set_user_password(DB_PATH, user_id, auth.hash_password(password))
    return jsonify({"ok": True})


@app.route("/api/users/<int:user_id>/delete", methods=["POST"])
@auth.admin_required
def api_user_delete(user_id):
    if user_id == session.get("user_id"):
        return _json_error("cannot delete your own account", 400)
    status = db.delete_user_guarded(DB_PATH, user_id)
    if status == "missing":
        return _json_error("unknown user", 404)
    if status == "last_admin":
        return _json_error("cannot remove the last admin", 400)
    return jsonify({"ok": True})


def _warn_label_collisions():
    """Print labels that would share the same output file on disk."""
    groups = {}
    for row in db.list_accounts(DB_PATH):
        label = row["label"]
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(label)).strip("._-")
        stem = (stem or "account").casefold()
        groups.setdefault(stem, set()).add(label)
    for stem, labels in groups.items():
        if len(labels) > 1:
            print(
                "WARNING: labels {} all map to output file {!r}; "
                "rename them to avoid overwriting statements.".format(
                    ", ".join(sorted(labels)), stem + ".txt"
                )
            )


def main():
    root = os.path.dirname(BASE_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    from utils.instance_lock import acquire_instance_lock

    instance_lock = acquire_instance_lock(
        os.path.join(root, "output", "panel.lock")
    )
    if instance_lock is None:
        print(
            "another control panel is already running (output/panel.lock) - "
            "exiting so it keeps serving."
        )
        raise SystemExit(1)

    db.init_db(DB_PATH)
    admin_user = config.get("admin_username", "admin")
    admin_pass = config.get("admin_password", "")
    db.seed_admin(DB_PATH, admin_user, auth.hash_password(admin_pass))
    _warn_label_collisions()

    host = config.get("panel_host", "127.0.0.1")
    port = int(config.get("panel_port", 5000))
    try:
        threads = int(config.get("panel_threads", 8))
    except (TypeError, ValueError):
        threads = 8
    threads = min(32, max(4, threads))
    print("control panel listening on http://{}:{}".format(host, port))
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
