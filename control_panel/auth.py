"""Login session + password hashing for the control panel."""

import functools

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = ("admin", "operator")
DEFAULT_ROLE = "operator"

_user_loader = None


def set_user_loader(loader):
    """Register ``loader(user_id) -> user dict | None`` for live role lookups."""
    global _user_loader
    _user_loader = loader


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def current_user():
    """Return the signed-in user as a dict, or None.

    When a loader is registered the role is re-read from the database so a
    demotion or deletion takes effect without waiting for the user to log out.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None
    if _user_loader is not None:
        row = _user_loader(user_id)
        if not row:
            session.clear()
            return None
        role = row.get("role") or DEFAULT_ROLE
        if role != session.get("role"):
            session["role"] = role
        return {
            "id": user_id,
            "username": row.get("username") or session.get("username"),
            "role": role,
        }
    return {
        "id": user_id,
        "username": session.get("username"),
        "role": session.get("role") or DEFAULT_ROLE,
    }


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("login"))
        if _user_loader is not None and _user_loader(user_id) is None:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Require an admin session; JSON 403 for API calls, redirect for pages."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("login"))
        if user["role"] != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "admin role required"}), 403
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped


