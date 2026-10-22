"""Exercise the shipped desktop backend and native GUI lifecycle on disposable data."""
import faulthandler
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import sqlite3
import subprocess
import threading
import time

from build_config import OUT

ROOT = Path(__file__).resolve().parent
(ROOT / "manager-results.json").write_text("{}\n", encoding="utf-8")
TEST = ROOT / "test-output" / f"管理 空格路径-{time.time_ns()}"
shutil.copytree(OUT, TEST)
PYTHON = TEST / "runtime/bin/python.exe"
env = dict(os.environ, PYTHONUTF8="1", PYTHONNOUSERSITE="1")
env["PATH"] = str(PYTHON.parent) + os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32")
for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "MSYSTEM", "MINGW_PREFIX"):
    env.pop(name, None)
faulthandler.dump_traceback_later(35, repeat=True)
responses = queue.Queue()
errors = (TEST.parent / (TEST.name + ".stderr.log")).open("wb")
worker = subprocess.Popen([str(PYTHON), "-B", "-u", str(TEST / "manager.py")], cwd=TEST, env=env,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def read_replies():
    for line in worker.stdout:
        responses.put(json.loads(line))
    responses.put(None)


threading.Thread(target=read_replies, daemon=True).start()


def call(action, mode="bbsc", reject=False, **values):
    worker.stdin.write(json.dumps(dict(action=action, mode=mode, **values), ensure_ascii=True).encode() + b"\n")
    worker.stdin.flush()
    response = responses.get(timeout=25)
    assert response is not None, "Manager unexpectedly closed its pipe"
    assert response["ok"] != reject, response.get("error", "Unexpected success")
    return response.get("error") if reject else response["data"]


def native_login(name, password, mode="bbsc", expected=True):
    result = subprocess.run([str(TEST / "runtime/bin/shadnet-admin.exe"), "127.0.0.1",
                             "31413" if mode == "bbsc" else "31313", "login"],
                            input=json.dumps(dict(name=name, password=password)).encode() + b"\n",
                            capture_output=True, env=env, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert (result.returncode == 0) == expected, "Native credential interoperability failed"


def db(mode="bbsc"):
    return sqlite3.connect(TEST / mode / "db/shadnet.db")


def validate_backup(reply, expected_name):
    path = Path(reply["backup"])
    assert path.resolve().is_relative_to(TEST.resolve())
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT 1 FROM account WHERE username=?", (expected_name,)).fetchone()


def ports_released():
    for _ in range(50):
        try:
            for port, kind in ((31313, socket.SOCK_STREAM), (31314, socket.SOCK_DGRAM),
                               (31315, socket.SOCK_STREAM), (31413, socket.SOCK_STREAM),
                               (31414, socket.SOCK_DGRAM), (31415, socket.SOCK_STREAM),
                               (20443, socket.SOCK_STREAM), (20444, socket.SOCK_STREAM)):
                with socket.socket(socket.AF_INET, kind) as probe:
                    probe.bind(("127.0.0.1", port))
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("A managed service survived shutdown")


try:
    assert call("accounts") == []
    call("configure", address="0.0.0.0", reject=True)
    call("configure", address="192.0.2.123", reject=True)
    call("configure", address="127.0.0.1")
    for mode in ("normal", "bbsc"):
        assert call("start", mode)["modes"][mode]["ready"]
    call("create", "normal", name="traveler", password="ordinary pass 1", email="")
    call("create", name="traveler", password="灰烬 hunter Δ 2", email="")
    call("create", name="companion", password="another pass 3", email="")
    with db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM account_timestamp WHERE last_login IS NULL").fetchone()[0] == 0
    listed = call("accounts")
    assert len(listed) == 2 and set(listed[0]) == {"id", "name", "email", "state"}
    account_id = listed[0]["id"]
    call("verify", id=account_id, expected="traveler", password="灰烬 hunter Δ 2")
    call("verify", id=account_id, expected="traveler", password="wrong", reject=True)
    native_login("traveler", "灰烬 hunter Δ 2")
    native_login("traveler", "ordinary pass 1", mode="normal")
    for action, value in (("rename", "newname"), ("reset", "new password"), ("delete", "traveler")):
        call(action, id=account_id, expected="traveler", value=value, reject=True)
    call("configure", address="127.0.0.2", reject=True)
    print("PASS: pipe protocol, isolated modes, native UTF-8 registration/login, live-edit rejection", flush=True)

    call("stop")
    assert call("status")["modes"]["normal"]["ready"]
    call("rename", id=account_id, expected="traveler", value="companion", reject=True)
    result = call("rename", id=account_id, expected="traveler", value="wanderer")
    validate_backup(result, "traveler")
    assert call("accounts")[0]["id"] == account_id
    result = call("reset", id=account_id, expected="wanderer", value="moon ルナ Δ 4")
    validate_backup(result, "wanderer")
    call("verify", id=account_id, expected="wanderer", password="moon ルナ Δ 4")
    call("verify", id=account_id, expected="wanderer", password="灰烬 hunter Δ 2", reject=True)
    call("start")
    native_login("wanderer", "moon ルナ Δ 4")
    native_login("wanderer", "灰烬 hunter Δ 2", expected=False)
    native_login("traveler", "moon ルナ Δ 4", expected=False)
    call("stop")
    print("PASS: transactional rename, immutable ID, password reset accepted by native service, verified backups", flush=True)

    with db() as connection:
        other_id = connection.execute("SELECT user_id FROM account WHERE username='companion'").fetchone()[0]
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("INSERT INTO friendship VALUES(?,?,1,1)", tuple(sorted((account_id, other_id))))
        for value in (account_id, other_id):
            connection.execute("INSERT INTO score(communication_id,board_id,user_id,character_id,score,timestamp) VALUES('TEST',1,?,0,100,1)", (value,))
    call("delete", id=account_id, expected="old-stale-name", value="old-stale-name", reject=True)
    call("delete", id=account_id, expected="wanderer", value="wrong", reject=True)
    result = call("delete", id=account_id, expected="wanderer", value="wanderer")
    validate_backup(result, "wanderer")
    with db() as connection:
        assert not connection.execute("SELECT 1 FROM account WHERE user_id=?", (account_id,)).fetchone()
        assert not connection.execute("SELECT 1 FROM account_timestamp WHERE user_id=?", (account_id,)).fetchone()
        assert not connection.execute("SELECT 1 FROM score WHERE user_id=?", (account_id,)).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM score WHERE user_id=?", (other_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM friendship").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert [row["name"] for row in call("accounts")] == ["companion"]
    assert [row["name"] for row in call("accounts", "normal")] == ["traveler"]
    call("start")
    native_login("companion", "another pass 3")
    native_login("wanderer", "moon ルナ Δ 4", expected=False)
    print("PASS: delete confirmation, stale-row rejection, related-row cleanup, other account/profile preserved", flush=True)

    # Test the GUI worker's inherited-pipe shutdown contract with both modes active.
    worker.stdin.close()
    assert worker.wait(timeout=20) == 0
    ports_released()
    print("PASS: parent pipe closure stops owned services", flush=True)
    gui = subprocess.run([str(TEST / "Server.exe"), "--validate"], env=env, capture_output=True, timeout=15)
    assert gui.returncode == 0, "Native WPF validation failed"
    interaction = subprocess.run([str(TEST / "Server.exe"), "--test-ui"], env=env, capture_output=True, timeout=30)
    assert interaction.returncode == 0, interaction.stderr.decode("utf-8", errors="replace")
    ports_released()
    print("PASS: real WPF start/stop states, JSON account grid, protected edit controls and connection fields", flush=True)
    lifecycle = subprocess.run([str(TEST / "Server.exe"), "--test-lifecycle"], env=env, capture_output=True, timeout=25)
    assert lifecycle.returncode == 0, lifecycle.stderr.decode("utf-8", errors="replace")
    ports_released()
    print("PASS: native GUI launches worker and Job closes every service descendant", flush=True)
    (ROOT / "manager-results.json").write_text(json.dumps(dict(
        pipe_protocol_and_native_UTF8_registration=True, isolated_modes_and_account_fields=True,
        online_edits_rejected=True, transactional_rename_preserves_ID=True,
        reset_password_verified_by_native_service=True, deletion_confirmation_and_related_cleanup=True,
        verified_prechange_SQLite_backups=True, pipe_EOF_stops_owned_services=True,
        real_WPF_controls_account_grid_and_connection_fields=True, Job_releases_all_owned_processes=True), indent=2) + "\n", encoding="utf-8")
finally:
    if worker.poll() is None:
        try:
            worker.stdin.close()
            worker.wait(timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            subprocess.run(["taskkill", "/PID", str(worker.pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    errors.close()
    faulthandler.cancel_dump_traceback_later()
