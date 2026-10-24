"""Stop-flag and ProcessManager behavior."""

import json
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import api
import db
import auth
from utils import stop as stop_mod


def _config(tmp_path, script, grace=1):
    return {
        "output_dir": str(tmp_path / "output"),
        "scraper_script": str(script),
        "python_exe": sys.executable,
        "stop_grace_seconds": grace,
        "scraper_console": False,
        "log_file": str(tmp_path / "scraper.log"),
    }


def _wait_until(predicate, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_stop_flag_roundtrip(tmp_path):
    config = {"output_dir": str(tmp_path / "out")}
    path = stop_mod.stop_flag_path(config)
    assert not Path(path).exists()
    stop_mod.request_stop(config)
    assert Path(path).is_file()
    stop_mod.clear_stop(config)
    assert not Path(path).exists()


def test_watcher_raises_on_request(tmp_path, monkeypatch):
    monkeypatch.setattr(stop_mod, "_watcher", None)
    config = {"output_dir": str(tmp_path / "out")}
    stop_mod.start_watching(config)
    assert not stop_mod.should_stop()
    stop_mod.request_stop(config)
    assert _wait_until(stop_mod.should_stop, timeout=2.0)
    with pytest.raises(stop_mod.StopRequested):
        stop_mod.check()
    stop_mod.clear_stop(config)


def test_manager_graceful_stop(tmp_path):
    flag = tmp_path / "output" / "stop.request"
    script = tmp_path / "dummy_watch.py"
    script.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "flag = Path(sys.argv[1])\n"
        "while not flag.exists():\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    config = _config(tmp_path, script, grace=3)
    manager = api.ProcessManager(str(tmp_path), config)
    try:
        started = manager.start([str(flag)])
        assert started["started"] is True
        assert manager.status()["running"] is True
        assert Path(config["output_dir"], "scraper.pid").is_file()

        began = time.time()
        outcome = manager.stop()
        assert outcome["stopping"] is True
        assert time.time() - began < 1.0
        assert _wait_until(
            lambda: not manager.status()["running"]
            and not manager.status()["stopping"],
            timeout=6.0,
        )
        assert time.time() - began < 4.0
        assert not Path(config["output_dir"], "scraper.pid").exists()
        assert not flag.exists()
    finally:
        manager.stop_now()


def test_manager_force_kills_unresponsive_scraper(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "cleanup_stale_profiles", lambda **kwargs: 0)
    script = tmp_path / "dummy_sleep.py"
    script.write_text(
        "import time\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    config = _config(tmp_path, script, grace=1)
    manager = api.ProcessManager(str(tmp_path), config)
    try:
        started = manager.start([])
        assert started["started"] is True
        pid = started["pid"]
        began = time.time()
        manager.stop()
        assert _wait_until(lambda: manager.status()["running"] is False, timeout=8.0)
        assert time.time() - began < 6.0
        assert api.process_alive(pid) is False
    finally:
        manager.stop_now()


def test_start_refused_while_stopping(tmp_path):
    script = tmp_path / "dummy_sleep.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    config = _config(tmp_path, script, grace=3)
    manager = api.ProcessManager(str(tmp_path), config)
    try:
        assert manager.start([])["started"] is True
        assert manager.stop()["stopping"] is True
        again = manager.start([])
        assert again["started"] is False
        assert again["stopping"] is True
    finally:
        manager.stop_now()


def test_api_restart_adopts_running_scraper(tmp_path):
    script = tmp_path / "dummy_sleep.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    config = _config(tmp_path, script, grace=1)
    first = api.ProcessManager(str(tmp_path), config)
    try:
        started = first.start([])
        assert started["started"] is True
        second = api.ProcessManager(str(tmp_path), config)
        status = second.status()
        assert status["running"] is True
        assert status["pid"] == started["pid"]
        second.stop()
        assert _wait_until(
            lambda: second.status()["running"] is False, timeout=8.0
        )
    finally:
        first.stop_now()


def test_control_stop_endpoint_returns_202(monkeypatch):
    class FakeManager:
        def stop(self):
            return {
                "stopped": False,
                "stopping": True,
                "running": True,
                "pid": 1234,
                "message": "stopping",
            }

        def status(self):
            return {"running": True, "stopping": True, "pid": 1234}

    monkeypatch.setattr(api.StatementHandler, "config", {"robot_token": ""})
    monkeypatch.setattr(api.StatementHandler, "manager", FakeManager())
    server = ThreadingHTTPServer(("127.0.0.1", 0), api.StatementHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = "http://127.0.0.1:{}/control/stop".format(server.server_port)
        request = urllib.request.Request(url, data=b"{}", method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 202
            body = json.loads(response.read().decode("utf-8"))
            assert body["stopping"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_agent_db_helpers(tmp_path):
    path = str(tmp_path / "panel.db")
    db.init_db(path)
    db.seed_admin(path, "admin", auth.hash_password("x"))
    with db.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
