"""Local desktop manager. JSON over inherited pipes; no management network port."""
from contextlib import contextmanager
import configparser
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

import server

ROOT = Path(__file__).resolve().parent
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def mode_name(mode):
    if mode not in server.PORTS:
        raise ValueError("请选择普通联机或 BBSC 无缝联机。")
    return mode


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,16}", value) or value == "DeletedUser":
        raise ValueError("账号须为 3–16 位英文字母、数字、下划线或连字符。")
    return value


def password_hash(password, salt):
    if not isinstance(password, str) or not password or len(password) > 256 or "\0" in password:
        raise ValueError("请输入 1–256 个字符的密码。")
    value = password.encode("utf-8") + salt
    # Matches the fixed shadNet Database::HashPassword, not PBKDF2.
    for _ in range(100000):
        value = hashlib.sha256(value).digest()
    return value


def database(mode):
    return ROOT / mode_name(mode) / "db" / "shadnet.db"


@contextmanager
def read_db(mode):
    path = database(mode)
    if not path.is_file():
        raise ValueError("此模式尚未初始化，请先启动一次对应服务。")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
    try:
        yield connection
    finally:
        connection.close()


def accounts(mode):
    if not database(mode).exists():
        return []
    with read_db(mode) as connection:
        return [dict(id=row[0], name=row[1], email=row[2], state="已封禁" if row[4] else
                     ("管理员" if row[3] else "正常")) for row in connection.execute(
                         "SELECT user_id,username,email,admin,banned FROM account ORDER BY user_id")]


def backup(mode):
    folder = ROOT / "backups" / mode_name(mode)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(8) + ".db")
    pending = path.with_suffix(".tmp")
    with read_db(mode) as source:
        target = sqlite3.connect(pending)
        try:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("数据库备份校验失败，已停止修改。")
        finally:
            target.close()
    pending.rename(path)
    return path


def native_account(mode, action, values):
    mode_name(mode)
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(ROOT / mode / "shadnet.cfg", encoding="utf-8")
    if "General" not in cfg:
        raise ValueError("请先启动对应服务，再创建账号。")
    general = cfg["General"]
    request = dict(values)
    if action == "register":
        request["key"] = general["RegistrationSecretKey"]
    result = subprocess.run([str(server.RUNTIME / "shadnet-admin.exe"), general["Host"],
                             general["UnsecuredPort"], action],
                            input=json.dumps(request, ensure_ascii=True).encode("ascii") + b"\n",
                            capture_output=True, timeout=20, env=server.environment(),
                            creationflags=subprocess.CREATE_NO_WINDOW)
    # Upstream client prints non-secret status lines before the helper's final JSON.
    rows = result.stdout.decode("utf-8", errors="replace").splitlines()
    response = json.loads(next((row for row in reversed(rows) if row.startswith('{"ok":')), '{}'))
    if result.returncode or not response.get("ok"):
        code = response.get("error", "ConnectionFailed")
        messages = {"CreationExistingUsername": "账号已存在。", "CreationExistingEmail": "此邮箱字段已被使用。",
                    "LoginInvalidPassword": "账号或密码不正确。", "LoginAlreadyLoggedIn": "此账号正在游戏中，请先退出。",
                    "Unauthorized": "注册密钥不匹配，请检查此模式的配置。"}
        raise RuntimeError(messages.get(code, "服务未就绪或操作失败：" + code))
    return response


class Controller:
    def __init__(self):
        self.children = {}
        self.errors = {}

    def stop(self, mode):
        item = self.children.pop(mode_name(mode), None)
        if item:
            process, handle = item
            try:
                if process.poll() is None:
                    process.stdin.write(b"stop\n")
                    process.stdin.flush()
                process.wait(timeout=15)
            finally:
                handle.close()
        self.errors.pop(mode, None)

    def close(self):
        for mode in list(self.children):
            self.stop(mode)

    def start(self, mode):
        mode_name(mode)
        if mode in self.children and self.children[mode][0].poll() is None:
            raise ValueError("此模式已经由当前窗口启动。")
        self.stop(mode)
        address = server.settings()["address"]
        try:
            for port, kind in ((server.PORTS[mode][0], socket.SOCK_STREAM),
                               (server.PORTS[mode][1], socket.SOCK_DGRAM),
                               (server.PORTS[mode][2], socket.SOCK_STREAM)):
                server.require_free(address, port, kind)
        except OSError:
            raise ValueError("端口已被占用或地址不可用，请先关闭旧的命令行服务，并核对本机地址。") from None
        folder = ROOT / mode / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        handle = (folder / (time.strftime("%Y%m%d-%H%M%S-") + "manager.log")).open("ab")
        code = ("import sys,threading,_thread;import server;"
                "threading.Thread(target=lambda:(sys.stdin.readline(),_thread.interrupt_main()),daemon=True).start();"
                "server.start(sys.argv[1])")
        process = subprocess.Popen([str(server.RUNTIME / "python.exe"), "-B", "-u", "-c", code, mode],
                                   cwd=ROOT, env=server.environment(), stdin=subprocess.PIPE,
                                   stdout=handle, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        self.children[mode] = process, handle
        try:
            for _ in range(70):
                if process.poll() is not None:
                    raise RuntimeError("服务启动失败，请打开日志查看。")
                try:
                    with OPENER.open(f"http://{address}:{server.PORTS[mode][2]}/status", timeout=0.3) as reply:
                        ready = json.load(reply).get("ok")
                    if mode == "bbsc":
                        with OPENER.open(f"http://{address}:20443/bb-eu/ss.info", timeout=0.3) as reply:
                            ready = ready and bool(reply.read())
                    if ready:
                        return
                except OSError:
                    pass
                time.sleep(0.1)
            raise RuntimeError("服务启动超时，请打开日志查看。")
        except Exception:
            self.stop(mode)
            raise

    def status(self):
        states = {}
        for mode in server.PORTS:
            item = self.children.get(mode)
            active = item is not None and item[0].poll() is None
            if item and not active:
                self.errors[mode] = "服务异常退出，请查看日志。"
                item[1].close()
                self.children.pop(mode)
            external, ready = False, False
            if not active:
                try:
                    with server.mode_lock(mode):
                        pass
                except ValueError:
                    external = True
            else:
                try:
                    address = server.settings()["address"]
                    with OPENER.open(f"http://{address}:{server.PORTS[mode][2]}/status", timeout=0.3) as reply:
                        ready = bool(json.load(reply).get("ok"))
                    if mode == "bbsc":
                        with OPENER.open(f"http://{address}:20443/bb-eu/ss.info", timeout=0.3) as reply:
                            ready = ready and bool(reply.read())
                except OSError:
                    pass
            states[mode] = dict(running=active, external=external, ready=ready, error=self.errors.get(mode, ""))
        return dict(address=server.settings()["address"], modes=states)

    @contextmanager
    def offline(self, mode):
        mode_name(mode)
        if self.status()["modes"][mode]["running"]:
            raise ValueError("请先停止对应模式的服务，再修改账号。")
        with server.mode_lock(mode):
            address = server.settings()["address"]
            for port, kind in ((server.PORTS[mode][0], socket.SOCK_STREAM),
                               (server.PORTS[mode][1], socket.SOCK_DGRAM),
                               (server.PORTS[mode][2], socket.SOCK_STREAM)):
                try:
                    server.require_free(address, port, kind)
                except OSError:
                    raise ValueError("检测到外部服务占用端口，请先关闭该模式的命令行服务。") from None
            yield

    def configure(self, value):
        import ipaddress
        address = str(ipaddress.IPv4Address(value))
        if address == "0.0.0.0":
            raise ValueError("请选择这台电脑实际的局域网或 VPN IPv4。")
        with self.offline("normal"), self.offline("bbsc"):
            # Binding a temporary socket also rejects addresses not assigned to this machine.
            try:
                server.require_free(address, 0, socket.SOCK_STREAM)
            except OSError:
                raise ValueError("该地址不属于本机或暂不可用，请从「本机地址」重新选择。") from None
            (ROOT / "server.json").write_text(json.dumps(dict(address=address)) + "\n", encoding="utf-8")

    def create(self, mode, name, password, email):
        username(name)
        password_hash(password, b"validation")
        if not self.status()["modes"][mode_name(mode)]["running"]:
            raise ValueError("请先在此窗口启动对应模式的服务，再新建账号。")
        email = email.strip() or f"{name}-{secrets.token_hex(4)}@local.invalid"
        if "@" not in email or "." not in email or "\0" in email:
            raise ValueError("邮箱格式不正确；不需要邮箱时请留空。")
        saved = backup(mode)
        native_account(mode, "register", dict(name=name, password=password, email=email))
        try:
            native_account(mode, "login", dict(name=name, password=password))
        except RuntimeError:
            return dict(message="账号已创建；登录验证暂未完成，请刷新列表核对，勿重复创建。", backup=str(saved))
        return dict(message="账号已创建并通过登录验证。", backup=str(saved))

    def verify(self, mode, account_id, expected, password):
        with read_db(mode) as connection:
            row = connection.execute("SELECT username,hash,salt FROM account WHERE user_id=?", (account_id,)).fetchone()
        if not row or row[0] != expected:
            raise ValueError("账号记录已变化，请刷新列表。")
        if not hmac.compare_digest(password_hash(password, row[2]), row[1]):
            raise ValueError("密码不正确。")
        return dict(message="密码正确；本次检查没有登录或占用游戏会话。")

    def change(self, mode, action, account_id, expected, value):
        with self.offline(mode):
            # Open existing DB only; never create a replacement for a missing database.
            connection = sqlite3.connect(database(mode).as_uri() + "?mode=rw", uri=True, timeout=3)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT username FROM account WHERE user_id=?", (account_id,)).fetchone()
                if not row or row[0] != expected:
                    raise ValueError("账号记录已变化，请刷新列表。")
                if action == "rename":
                    username(value)
                    if connection.execute("SELECT 1 FROM account WHERE username=? COLLATE NOCASE AND user_id<>?", (value, account_id)).fetchone():
                        raise ValueError("新账号名已被使用。")
                elif action == "reset":
                    salt = secrets.token_bytes(64)
                    hashed = password_hash(value, salt)
                elif action == "delete":
                    if value != expected:
                        raise ValueError("请输入完整账号名确认删除。")
                else:
                    raise ValueError("不支持的账号操作。")
                # The stopped service and shared mode lock keep this snapshot stable.
                saved = backup(mode)
                if action == "rename":
                    connection.execute("UPDATE account SET username=? WHERE user_id=?", (value, account_id))
                elif action == "reset":
                    connection.execute("UPDATE account SET hash=?,salt=?,reset_token=NULL WHERE user_id=?", (hashed, salt, account_id))
                else:
                    connection.execute("DELETE FROM score WHERE user_id=?", (account_id,))
                    connection.execute("DELETE FROM account_timestamp WHERE user_id=?", (account_id,))
                    connection.execute("DELETE FROM account WHERE user_id=?", (account_id,))
                if connection.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("数据库关系校验失败，已回滚修改。")
                connection.commit()
            finally:
                connection.close()
        return dict(message={"rename": "账号已改名，ID 和密码保持不变。", "reset": "密码已重置。",
                             "delete": "账号已删除；玩家电脑上的角色存档未改动。"}[action], backup=str(saved))


def main():
    controller = Controller()
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                action = request["action"]
                mode = request.get("mode", "bbsc")
                if action == "status":
                    data = controller.status()
                elif action == "accounts":
                    data = accounts(mode)
                elif action == "start":
                    controller.start(mode)
                    data = controller.status()
                elif action == "stop":
                    controller.stop(mode)
                    data = controller.status()
                elif action == "configure":
                    controller.configure(request["address"])
                    data = controller.status()
                elif action == "create":
                    data = controller.create(mode, request["name"], request["password"], request.get("email", ""))
                elif action == "verify":
                    data = controller.verify(mode, int(request["id"]), request["expected"], request["password"])
                elif action in ("rename", "reset", "delete"):
                    data = controller.change(mode, action, int(request["id"]), request["expected"], request["value"])
                elif action == "close":
                    controller.close()
                    print(json.dumps(dict(ok=True, data=None)), flush=True)
                    return
                else:
                    raise ValueError("不支持的管理操作。")
                reply = dict(ok=True, data=data)
            except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
                reply = dict(ok=False, error=str(error))
            print(json.dumps(reply, ensure_ascii=True), flush=True)
    finally:
        controller.close()


if __name__ == "__main__":
    main()
