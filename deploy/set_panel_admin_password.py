"""Seed or reset the control panel admin account.

Used by ``install/install_panel.ps1`` (first install) and by
``deploy/windows-unattended.ps1`` (hardening an existing install).

It ensures the panel database exists and the configured admin user is present
(seeded with the ``admin_password`` from ``control_panel/config.json``), and it
always keeps that user in the ``admin`` role. When the
``BCA_PANEL_ADMIN_PASSWORD`` environment variable is set, the admin's password
is set to that value and written back to ``control_panel/config.json`` so a
fresh database seeds consistently.

The new password is read from the environment variable, never from the command
line, to keep it out of the process list.

Usage:
    BCA_PANEL_ADMIN_PASSWORD=<pw> python set_panel_admin_password.py <repo_dir>
"""

import json
import os
import sys


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    cp = os.path.join(repo, "control_panel")
    sys.path.insert(0, cp)
    import auth
    import db

    cfg_path = os.path.join(cp, "config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    db_path = cfg.get("db_path", "panel.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(cp, db_path)
    username = cfg.get("admin_username", "admin")
    password = os.environ.get("BCA_PANEL_ADMIN_PASSWORD") or None

    db.init_db(db_path)
    user = db.get_user(db_path, username)

    if user is None:
        seed_pw = password or cfg.get("admin_password") or ""
        if not seed_pw:
            print("no password available to seed {!r}".format(username), file=sys.stderr)
            return 2
        db.add_user(db_path, username, auth.hash_password(seed_pw), "admin")
        print("created admin {!r} in {}".format(username, db_path))
    else:
        # The configured account is always an admin.
        db.set_user_role_guarded(db_path, user["id"], "admin")
        if password:
            db.set_user_password(db_path, user["id"], auth.hash_password(password))
            print("updated password for {!r} in {}".format(username, db_path))

    if password:
        cfg["admin_password"] = password
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
