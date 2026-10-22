"""Exercise the packed native services on loopback using disposable state."""
import base64
import faulthandler
import configparser
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
from build_config import OUT as PACK
TEST = ROOT / "test-output" / f"原生 空格路径-{time.time_ns()}"
if TEST.exists():
    raise ValueError("Test output already exists; preserve it and choose a fresh path.")
shutil.copytree(PACK, TEST)
PYTHON = TEST / "runtime" / "bin" / "python.exe"
env = os.environ.copy()
env["PATH"] = str(PYTHON.parent) + os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32")
for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "MSYSTEM", "MINGW_PREFIX"):
    env.pop(name, None)
env["PYTHONUTF8"] = "1"
env["PYTHONNOUSERSITE"] = "1"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
results, running = {}, []
faulthandler.dump_traceback_later(20, repeat=True)


def http(port, path, body=None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=2) as response:
        return response.read()


def launch(mode):
    log = (TEST.parent / f"runner-{mode}-{time.time_ns()}.log").open("wb")
    command = [str(PYTHON), "-B", "-u", "-c",
               "import sys, threading, _thread; sys.path.insert(0, sys.argv[1]); import server; "
               "threading.Thread(target=lambda: (sys.stdin.readline(), _thread.interrupt_main()), daemon=True).start(); "
               "server.start(sys.argv[2])", str(TEST), mode]
    process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=log,
                               stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    running.append((process, log))
    port = 31315 if mode == "normal" else 31415
    for _ in range(80):
        if process.poll() is not None:
            raise AssertionError(f"{mode} runner exited: see {log.name}")
        try:
            assert json.loads(http(port, "/status"))["ok"] is True
            # Health can become ready just before the runner prints the copyable addresses.
            text = Path(log.name).read_text(encoding="utf-8", errors="replace")
            tcp = 31313 if mode == "normal" else 31413
            expected = ["客户端填写信息（可复制）", f"127.0.0.1:{tcp}",
                        f"http://127.0.0.1:{port}", "各自使用不同的联机账号", "当前仅限本机连接"]
            if mode == "bbsc":
                expected += ["http://127.0.0.1:20443", "127.0.0.1:20444"]
            if all(value in text for value in expected):
                results[mode + "_copyable_client_addresses"] = True
                return process, log
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError(f"{mode} failed to become ready")


def stop(item):
    process, log = item
    if process.poll() is None:
        process.stdin.write(b"stop\n")
        process.stdin.flush()
    assert process.wait(timeout=15) == 0
    log.close()
    running.remove(item)


def sample(mode, action, *values):
    port = "31313" if mode == "normal" else "31413"
    result = subprocess.run([str(TEST / "runtime" / "bin" / "shadnet-sample.exe"),
                             "127.0.0.1", port, action, *values], env=env, capture_output=True,
                            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, "Sample did not receive a response"
    return result.stdout


def stun(port, prefix):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.bind(("127.0.0.1", 0))
        connection.settimeout(2)
        expected = socket.inet_aton("127.0.0.1") + struct.pack("!H", connection.getsockname()[1])
        connection.sendto(prefix + b"\x01" + b"native-test".ljust(16, b"\0") + socket.inet_aton("127.0.0.1"),
                          ("127.0.0.1", port))
        reply, _ = connection.recvfrom(1024)
        assert reply == prefix + expected, reply.hex()


def recv_exact(connection, count):
    value = b""
    while len(value) < count:
        chunk = connection.recv(count - len(value))
        assert chunk, "Relay disconnected"
        value += chunk
    return value


def frame(connection):
    return recv_exact(connection, struct.unpack("<I", recv_exact(connection, 4))[0])


try:
    runtime = subprocess.check_output([str(PYTHON), "-I", "-c",
        "import sys, socket, ssl, sqlite3, json, http.server, hashlib; print(json.dumps(sys.prefix))"], env=env)
    assert str(TEST / "runtime").lower() == json.loads(runtime.decode("ascii")).lower()
    results["relocated_runtime_without_dev_PATH"] = True
    print("Packed Python runtime: OK", flush=True)
    normal, bbsc = launch("normal"), launch("bbsc")
    results["both_modes_simultaneous_status"] = True
    print("Both service profiles: OK", flush=True)
    password = secrets.token_hex(16)
    for mode, name in (("normal", "normal01"), ("bbsc", "seamless01")):
        print(f"Testing {mode} account registration", flush=True)
        config = configparser.ConfigParser(interpolation=None)
        config.read(TEST / mode / "shadnet.cfg", encoding="utf-8")
        output = sample(mode, "register", name, password, f"{name}@native.invalid",
                        config["General"]["RegistrationSecretKey"])
        assert b"[create] Account created successfully." in output
        assert b"[login] OK userId=" in sample(mode, "login", name, password)
    assert b"[login] OK userId=" not in sample("normal", "login", "seamless01", password)
    assert b"[login] OK userId=" not in sample("bbsc", "login", "normal01", password)
    results["registration_login_database_isolation"] = True
    print("Accounts and isolation: OK", flush=True)

    for port in (31314, 31414):
        for prefix in (bytes.fromhex("ffffffff"), bytes.fromhex("ff83ffffffff")):
            stun(port, prefix)
    results["both_profiles_STUN_4_and_6_byte_framing"] = True
    print("UDP STUN: OK", flush=True)

    advert = dict(MessageId="SummonDataCreateRequest", SessionId="native-session", UserId=2465,
                  CharaId=9223372036854775808, AreaId=385875968, AreaRegionId=230100, ChannelId=0,
                  MatchingLevel=46, SummonData="opaque-native-data", SummonDataVersion=3,
                  SummonMethod=0, SummonType=0, SummonWord=None, PosX=143, PosY=-116, PosZ=-87)
    search = dict(advert, MessageId="SummonDataGetListRequest", SessionId="host-session", UserId=2466,
                  SummonTypeList=[{"SummonType": 0}], DistanceThreshold=100, GetMaxCount=20)
    claim = dict(MessageId="SummonDataSummonRequest", SessionId="native-session", UserId=2466,
                 TargetUserId=2465, TargetCharaId=9223372036854775808, HostData="native-host")
    assert json.loads(http(31315, "/summon_messenger/create", advert))["ResKind"] == 0
    assert len(json.loads(http(31415, "/summon_messenger/get", search))["SummonDataList"]) == 0
    for port in (31315, 31415):
        assert json.loads(http(port, "/summon_messenger/create", advert))["ResKind"] == 0
        assert len(json.loads(http(port, "/summon_messenger/get", search))["SummonDataList"]) == 1
        assert json.loads(http(port, "/summon_messenger/request", claim))["ResKind"] == 0
        delivery = json.loads(http(port, "/summon_messenger/create", advert))
        assert delivery["HostData"] == "native-host"
        assert delivery["TargetCharaId"] == 9223372036854775808
    results["summon_advertise_search_claim_delivery_and_isolation"] = True
    print("Summon flows: OK", flush=True)

    for _ in range(60):
        try:
            xml = base64.b64decode(http(20443, "/bb-eu/ss.info")).decode()
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise AssertionError("BBSC game server did not start")
    for tag in ("api_SummonDataCreate", "api_SummonDataGetList", "api_SummonDataRemove", "api_SummonDataSummon"):
        assert f"<{tag}>http://127.0.0.1:31415</{tag}>" in xml
    assert ":31315" not in xml and "{YOUR SHADNET SERVER}" not in xml
    results["BBSC_ss_info_uses_independent_31415"] = True
    with socket.create_connection(("127.0.0.1", 20444), timeout=2) as left, \
         socket.create_connection(("127.0.0.1", 20444), timeout=2) as right:
        # TCP connect can finish before the server has registered both relay clients.
        for connection in (left, right):
            for _ in range(5):
                if frame(connection) == b"\x7f\x01":
                    break
            else:
                raise AssertionError("Relay did not announce the other client")
        for source, target, payload in ((left, right, b"native-left-to-right"),
                                        (right, left, b"native-right-to-left")):
            source.sendall(struct.pack("<I", len(payload)) + payload)
            for _ in range(5):
                received = frame(target)
                if not received.startswith(b"\x7f"):
                    assert received == payload
                    break
            else:
                raise AssertionError("No relayed frame")
    results["BBSC_relay_bidirectional"] = True
    print("BBSC HTTP and relay: OK", flush=True)
    stop(bbsc)
    stop(normal)
    normal, bbsc = launch("normal"), launch("bbsc")
    assert b"[login] OK userId=" in sample("normal", "login", "normal01", password)
    assert b"[login] OK userId=" in sample("bbsc", "login", "seamless01", password)
    results["accounts_persist_across_restart"] = True
    stop(bbsc)
    stop(normal)
    for port in (31313, 31315, 31413, 31415, 20443, 20444):
        with socket.socket() as probe:
            probe.settimeout(0.3)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
    for port in (31314, 31414):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", port))
    results["owned_processes_stopped_ports_released"] = True
finally:
    for item in list(running):
        stop(item)
    (ROOT / "smoke-results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
print(json.dumps(results, indent=2))
