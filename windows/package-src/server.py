"""Small native Windows server runner. All state stays beside this file."""
import argparse
import configparser
from contextlib import contextmanager
import getpass
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime" / "bin"
PORTS = {"normal": (31313, 31314, 31315), "bbsc": (31413, 31414, 31415)}


@contextmanager
def mode_lock(mode):
    """Serialize service lifetime with offline account maintenance in this folder."""
    import msvcrt
    if mode not in PORTS:
        raise ValueError("无效服务模式。")
    path = ROOT / mode / ".server.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError("此模式正在运行或进行账号维护，请先停止对应服务。") from None
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


def settings():
    path = ROOT / "server.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"address": "127.0.0.1"}


def profile(mode):
    address = str(ipaddress.IPv4Address(settings()["address"]))
    if address == "0.0.0.0":
        raise ValueError("请填写实际的局域网或 VPN IPv4，不能填 0.0.0.0。")
    path = ROOT / mode / "shadnet.cfg"
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str
    if path.exists():
        cfg.read(path, encoding="utf-8")
    if not cfg.has_section("General"):
        cfg.add_section("General")
    general = cfg["General"]
    tcp, udp, web = PORTS[mode]
    general.update(Host=address, UnsecuredPort=str(tcp), MatchingUdpPort=str(udp),
                   WebApiPort=str(web), StatsEnabled="false", Matching2Enabled="true",
                   BloodborneSeamlessCoop=str(mode == "bbsc").lower(), EmailValidated="false")
    if not general.get("RegistrationSecretKey"):
        general["RegistrationSecretKey"] = secrets.token_hex(32)
    with path.open("w", encoding="utf-8") as handle:
        cfg.write(handle, space_around_delimiters=False)
    return address, general


def environment():
    env = os.environ.copy()
    env["PATH"] = str(RUNTIME) + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    env["QT_FORCE_STDERR_LOGGING"] = "1"
    env.pop("QT_PLUGIN_PATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def require_free(address, port, kind):
    with socket.socket(socket.AF_INET, kind) as connection:
        connection.bind((address, port))


def print_client_settings(mode, address):
    tcp, _, web = PORTS[mode]
    print("\n========== 客户端填写信息（可复制） ==========", flush=True)
    print("两台电脑填写相同的服务器地址，各自使用不同的联机账号。", flush=True)
    if mode == "bbsc":
        print("填写位置：The Hunt → 游戏与联机", flush=True)
    else:
        print("填写位置：普通版启动器 → 在线合作 → 选择 shadNet server", flush=True)
    print(f"\nshadNet 合作服务器：\n{address}:{tcp}\n"
          f"\nshadNet WebAPI：\nhttp://{address}:{web}", flush=True)
    if mode == "bbsc":
        print(f"\nBBSC 游戏服务器：\nhttp://{address}:20443\n"
              f"\nBBSC Relay：\n{address}:20444", flush=True)
    else:
        print("\n留言、血迹、幽灵的游戏服务器：保留客户端原有地址。", flush=True)
    choice = 5 if mode == "bbsc" else 4
    print(f"\n联机账号／密码：使用本服务创建的账号；云服账号不会自动同步。\n"
          f"创建账号：另开 Server-CLI.cmd，选择 {choice}；也可使用 Server.exe 的账号管理页。", flush=True)
    if ipaddress.IPv4Address(address).is_loopback:
        print("\n当前仅限本机连接。双机测试请先选 3，配置本机的局域网或 Tailscale IPv4 后重新开服。",
              flush=True)
    print("============================================\n", flush=True)


def start(mode):
    with mode_lock(mode):
        _start(mode)


def _start(mode):
    address, _ = profile(mode)
    tcp, udp, web = PORTS[mode]
    for port, kind in ((tcp, socket.SOCK_STREAM), (udp, socket.SOCK_DGRAM),
                       (web, socket.SOCK_STREAM)):
        require_free(address, port, kind)
    if mode == "bbsc":
        for port in (20443, 20444):
            require_free(address, port, socket.SOCK_STREAM)
    logs = ROOT / mode / "logs"
    logs.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    processes, handles = [], []
    try:
        def launch(command, name):
            handle = (logs / f"{stamp}-{name}.log").open("ab")
            handles.append(handle)
            process = subprocess.Popen(command, cwd=ROOT / mode, env=environment(),
                                       stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(process)

        launch([str(ROOT / mode / "shadnet.exe")], "shadnet")
        if mode == "bbsc":
            launch([str(RUNTIME / "python.exe"), "-B", "-u",
                    str(ROOT / "bbsc-game" / "bbsc_gameserver.py"), "--host", address,
                    "--advertise", address, "--shadnet", address, "--shadnet-webapi",
                    f"http://{address}:{web}", "--port", "20443", "--relay-port", "20444",
                    "--no-bbhost", "--no-playlog", "--summon-interval", "2",
                    "--log-dir", str(logs),
                    "--data", str(ROOT / mode / "online-data.json")], "gameserver")
        for _ in range(50):
            if any(process.poll() is not None for process in processes):
                raise RuntimeError(f"服务提前退出，请查看 {logs}")
            try:
                # Bypass the Windows system proxy for a server health check.
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://{address}:{web}/status", timeout=0.4) as response:
                    if json.load(response).get("ok"):
                        if mode == "bbsc":
                            with opener.open(f"http://{address}:20443/bb-eu/ss.info", timeout=0.4) as game:
                                if not game.read():
                                    continue
                        break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError(f"WebAPI 未就绪，请查看 {logs}")
        print(f"{mode} 服务已启动：{address}  TCP {tcp} / UDP {udp} / WebAPI {web}", flush=True)
        print_client_settings(mode, address)
        print(f"日志：{logs}\n保持此窗口打开。按 Ctrl+C 停止本次启动的服务。", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError(f"服务已退出，请查看 {logs}")
    except KeyboardInterrupt:
        print("\n正在停止本次服务……", flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
        for handle in handles:
            handle.close()


def account(mode):
    address, general = profile(mode)
    name = input("新账号（3-16 位英文字母、数字、_ 或 -）：").strip()
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,16}", name) or name == "DeletedUser":
        raise ValueError("账号格式不正确。")
    email = input(f"邮箱（可留空使用 {name}@local.invalid）：").strip() or f"{name}@local.invalid"
    password = getpass.getpass("密码：")
    if not password or password != getpass.getpass("重复密码："):
        raise ValueError("两次密码不同，或密码为空。")
    for action, values, marker in (
        ("register", [name, password, email, general["RegistrationSecretKey"]],
         "[create] Account created successfully."),
        ("login", [name, password], "[login] OK userId="),
    ):
        result = subprocess.run([str(RUNTIME / "shadnet-sample.exe"), address,
                                 general["UnsecuredPort"], action, *values],
                                env=environment(), capture_output=True, timeout=25,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or marker.encode() not in result.stdout:
            reason = re.search(rb"\[(?:create|login)\] FAILED: (\w+)", result.stdout)
            raise RuntimeError(f"{action} 失败：" + (reason.group(1).decode() if reason else "先启动对应服务并检查日志"))
    print(f"{mode} 账号 {name} 已创建并通过登录验证。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "account", "configure"), nargs="?")
    parser.add_argument("mode", choices=PORTS, nargs="?")
    args = parser.parse_args()
    if not args.action:
        print("The Hunt · Windows 私服测试版\n1 普通联机\n2 BBSC 无缝联机\n3 配置监听地址\n4 创建普通账号\n5 创建无缝账号\n6 退出")
        choice = input("选择：").strip()
        if choice == "6":
            return
        args.action, args.mode = {"1": ("start", "normal"), "2": ("start", "bbsc"),
                                  "3": ("configure", None), "4": ("account", "normal"),
                                  "5": ("account", "bbsc")}.get(choice, (None, None))
    if args.action == "configure":
        address = str(ipaddress.IPv4Address(input("本机实际的局域网 / VPN IPv4：").strip()))
        if address == "0.0.0.0":
            raise ValueError("请填写实际 IPv4。")
        (ROOT / "server.json").write_text(json.dumps({"address": address}, indent=2) + "\n", encoding="utf-8")
        print("地址已保存，下次启动生效。数据库和账号保持不变。")
    elif args.action and args.mode:
        (start if args.action == "start" else account)(args.mode)
    else:
        parser.error("无效选择，或缺少 normal / bbsc。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"操作失败：{error}", file=sys.stderr)
        sys.exit(1)
