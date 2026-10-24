"""SQLite helpers and single-instance locks."""

import auth
import db
from utils.instance_lock import acquire_instance_lock


def _init(path):
    db.init_db(path)
    db.seed_admin(path, "admin", auth.hash_password("x"))
    return db.get_user(path, "admin")


def test_wal_and_last_admin_guard(tmp_path):
    path = str(tmp_path / "panel.db")
    admin = _init(path)
    with db.connect(path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"

    status = db.set_user_role_guarded(path, admin["id"], "operator")
    assert status == "last_admin"
    status = db.delete_user_guarded(path, admin["id"])
    assert status == "last_admin"


def test_reserved_labels_and_orphan_cleanup(tmp_path):
    path = str(tmp_path / "panel.db")
    _init(path)
    robot_one = db.add_robot(path, "r1", "10.0.0.1", 8000)
    robot_two = db.add_robot(path, "r2", "10.0.0.2", 8000)

    assert db.reserve_account(path, "label1", "mybca", robot_one) is True
    assert db.reserve_account(path, "label1", "mybca", robot_two) is False
    assert db.get_account_owner(path, "label1")["robot_id"] == robot_one

    db.delete_orphan_accounts(path, {robot_two})
    assert db.get_account_owner(path, "label1") is None


def test_instance_lock_is_exclusive(tmp_path):
    path = str(tmp_path / "instance.lock")
    first = acquire_instance_lock(path)
    assert first is not None
    try:
        assert acquire_instance_lock(path) is None
    finally:
        first.close()
    second = acquire_instance_lock(path)
    assert second is not None
    second.close()
