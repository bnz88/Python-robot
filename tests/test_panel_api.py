"""Panel routes, auth, token preservation, and account-registry safety."""

import pytest

import auth
import db


@pytest.fixture()
def panel(tmp_path, monkeypatch):
    import app

    db_path = str(tmp_path / "panel.db")
    db.init_db(db_path)
    db.seed_admin(db_path, "admin", auth.hash_password("admin-pass"))
    operator_id = db.add_user(
        db_path, "operator", auth.hash_password("operator-pass"), "operator"
    )
    admin = db.get_user(db_path, "admin")

    monkeypatch.setattr(app, "DB_PATH", db_path)
    app.app.config.update(TESTING=True)
    client = app.app.test_client()
    return {
        "app": app,
        "client": client,
        "db_path": db_path,
        "admin_id": admin["id"],
        "operator_id": operator_id,
    }


def login(client, user_id, role):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["role"] = role


def test_api_without_session_is_json_401(panel):
    response = panel["client"].get("/api/robots")
    assert response.status_code == 401
    assert response.is_json


def test_operator_cannot_open_robot_page(panel):
    login(panel["client"], panel["operator_id"], "operator")
    response = panel["client"].get("/robot")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_edit_robot_keeps_token_when_blank(panel):
    client = panel["client"]
    app = panel["app"]
    login(client, panel["admin_id"], "admin")
    robot_id = db.add_robot(panel["db_path"], "r1", "10.0.0.5", 8000, token="secret")

    response = client.post(
        "/api/robots/{}/edit".format(robot_id), json={"name": "renamed"}
    )
    assert response.status_code == 200
    robot = db.get_robot(panel["db_path"], robot_id)
    assert robot["name"] == "renamed"
    assert robot["token"] == "secret"

    response = client.post(
        "/api/robots/{}/edit".format(robot_id), json={"token": "new-secret"}
    )
    assert response.status_code == 200
    assert db.get_robot(panel["db_path"], robot_id)["token"] == "new-secret"

    response = client.post(
        "/api/robots/{}/edit".format(robot_id), json={"port": "not-a-port"}
    )
    assert response.status_code == 400


def test_hidden_bank_statement_is_forbidden_for_operator(panel, monkeypatch):
    app = panel["app"]
    login(panel["client"], panel["operator_id"], "operator")
    robot_id = db.add_robot(panel["db_path"], "r1", "10.0.0.5", 8000)
    monkeypatch.setattr(app, "HIDDEN_BANKS", {"permata"})

    def fail_relay(*args, **kwargs):
        raise AssertionError("hidden statement must not reach the robot")

    monkeypatch.setattr(app, "relay", fail_relay)
    response = panel["client"].get(
        "/api/robots/{}/statement/label1?bank=permata".format(robot_id)
    )
    assert response.status_code == 403


def test_robot_error_does_not_wipe_registry(panel, monkeypatch):
    app = panel["app"]
    robot_id = db.add_robot(panel["db_path"], "r1", "10.0.0.5", 8000)
    db.upsert_account(panel["db_path"], "label1", "mybca", robot_id)

    monkeypatch.setattr(
        app,
        "relay_json",
        lambda *args, **kwargs: {
            "ok": True,
            "status": 500,
            "http_ok": False,
            "data": {"error": "accounts.json unreadable"},
        },
    )
    info = app._poll_one_robot({"id": robot_id, "host": "x", "port": 1})[1]
    assert info["ok"] is False

    monkeypatch.setattr(app, "poll_accounts_all", lambda: {robot_id: info})
    app.reconcile_accounts({robot_id: info})
    owner = db.get_account_owner(panel["db_path"], "label1")
    assert owner is not None
    assert owner["robot_id"] == robot_id


def test_account_label_is_validated(panel):
    client = panel["client"]
    login(client, panel["admin_id"], "admin")
    robot_id = db.add_robot(panel["db_path"], "r1", "10.0.0.5", 8000)
    response = client.post(
        "/api/accounts",
        json={
            "robot_id": robot_id,
            "label": "../bad label",
            "bank": "mybca",
            "username": "u",
            "password": "p",
        },
    )
    assert response.status_code == 400
    assert "label" in response.get_json()["error"]


def test_admin_pages_render(panel):
    client = panel["client"]
    login(client, panel["admin_id"], "admin")
    for path in ("/", "/robot", "/accounts", "/proxies", "/live", "/logs", "/settings", "/users"):
        response = client.get(path)
        assert response.status_code == 200, path
