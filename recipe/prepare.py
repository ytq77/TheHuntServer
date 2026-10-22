#!/usr/bin/env python3
"""Fetch pinned sources and prepare a new, Tailscale-only deployment directory."""
import argparse
import configparser
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import urllib.request

ROOT = Path(__file__).resolve().parent


def write_once(path, data):
    """Keep existing matching material; never silently overwrite a different file."""
    if path.is_symlink():
        raise ValueError(f"Refusing symlink: {path}")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Existing file differs; inspect it before continuing: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def fetch(url, path, digest, offline):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"Refusing symlink: {path}")
    if path.exists():
        data = path.read_bytes()
    elif offline:
        raise ValueError(f"Offline cache missing: {path}")
    else:
        request = urllib.request.Request(url, headers={"User-Agent": "The-Hunt-server-recipe"})
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"SHA256 mismatch: {path.name}")
    write_once(path, data)
    return data


def patch_gameserver(data):
    """Only add the explicit summon WebAPI URL; keep other upstream behavior."""
    text = data.decode("utf-8")
    replacements = [
        (
            '        xml = xml.replace("{YOUR SHADNET SERVER}", ARGS.shadnet)\n'
            '        print("  summon endpoints -> {}:31315  ({} replaced)".format(ARGS.shadnet, before))',
            '        summon_base = ARGS.shadnet_webapi or "http://{}:31315".format(ARGS.shadnet)\n'
            '        xml = xml.replace("http://{YOUR SHADNET SERVER}:31315", summon_base.rstrip("/"))\n'
            '        print("  summon endpoints -> {}  ({} replaced)".format(summon_base, before))',
        ),
        (
            '    parser.add_argument("--host", default="127.0.0.1")',
            '    parser.add_argument("--shadnet-webapi", default="",\n'
            '                        help="explicit summon WebAPI base URL (for isolated server ports)")\n'
            '    parser.add_argument("--host", default="127.0.0.1")',
        ),
    ]
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError("Pinned BBSC source no longer matches the WebAPI patch.")
        text = text.replace(before, after, 1)
    return text.encode("utf-8")


def patch_local_login(data):
    text = data.decode('utf-8')
    before = '''    here = "http://127.0.0.1:{}".format(ARGS.port) if local else \\
        "http://{}:{}".format(ARGS.advertise or ARGS.host, ARGS.port)'''
    after = '''    # A VPN-only listener does not accept connections on 127.0.0.1.
    local_host = "127.0.0.1" if ARGS.host == "0.0.0.0" else ARGS.host
    here = "http://{}:{}".format(local_host if local else (ARGS.advertise or ARGS.host), ARGS.port)'''
    if text.count(before) != 2:
        raise ValueError('Unexpected BBSC local endpoint implementation; recheck fixed source.')
    text = text.replace(before, after)
    before = '''    with "Failed to connect to Bloodborne server". Serving the host's own game its check-ins on
    127.0.0.1 means the host is never kicked because the VPN adapter dropped or was switched off.
    The summon endpoints keep the shadnet address either way: co-op needs the VPN regardless.'''
    after = '''    with "Failed to connect to Bloodborne server". The host's own game must use the bound
    address too: advertising 127.0.0.1 while listening only on a VPN address breaks local login.
    The summon endpoints keep the shadnet address either way.'''
    if text.count(before) != 1:
        raise ValueError('Unexpected BBSC local endpoint documentation.')
    return text.replace(before, after).encode('utf-8')


def validate_existing_config(server_ip):
    """Reject conflicting configurations before downloading or generating anything."""
    env = ROOT / ".env"
    expected_env = f"SERVER_IP={server_ip}\n".encode()
    if env.exists() and env.read_bytes() != expected_env:
        raise ValueError("Existing .env differs; it has been left unchanged.")
    cfg = ROOT / "shadnet-state" / "shadnet.cfg"
    if cfg.is_symlink():
        raise ValueError("Refusing symlink: shadnet-state/shadnet.cfg")
    if cfg.exists():
        parsed = configparser.ConfigParser(interpolation=None)
        parsed.read(cfg, encoding="utf-8")
        values = parsed["General"]
        expected = {
            "Host": server_ip, "UnsecuredPort": "31413", "MatchingUdpPort": "31414",
            "WebApiPort": "31415", "StatsEnabled": "false", "Matching2Enabled": "true",
            "BloodborneSeamlessCoop": "true", "EmailValidated": "false",
        }
        if any(values.get(key) != value for key, value in expected.items()):
            raise ValueError("Existing shadnet.cfg differs; it has been left unchanged.")
        if not values.get("RegistrationSecretKey") or "__" in values["RegistrationSecretKey"]:
            raise ValueError("Existing shadnet.cfg has no usable registration secret.")
    return expected_env, cfg


def prepare(server_ip, offline=False):
    address = ipaddress.IPv4Address(server_ip)
    if address not in ipaddress.IPv4Network("100.64.0.0/10"):
        raise ValueError("Use the server's Tailscale IPv4 (100.64.0.0/10), not a public or wildcard IP.")
    for path in [ROOT / ".build", ROOT / ".env", ROOT / "shadnet-state", ROOT / "game-state"]:
        if path.is_symlink():
            raise ValueError(f"Refusing symlink: {path}")
    expected_env, config_path = validate_existing_config(str(address))
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    build = ROOT / ".build"
    vendor = build / "vendor-source"
    for item in sources["archives"]:
        url = f"https://codeload.github.com/{item['repo']}/tar.gz/{item['revision']}"
        fetch(url, vendor / item["name"], item["sha256"], offline)
    sums = "".join(f"{x['sha256']}  {x['name']}\n" for x in sources["archives"])
    write_once(vendor / "SHA256SUMS", sums.encode())
    write_once(vendor / "source-manifest.json", (ROOT / "sources.json").read_bytes())

    bbsc = sources["bbsc"]
    for relative, digest in bbsc["files"].items():
        url = f"https://raw.githubusercontent.com/{bbsc['repo']}/{bbsc['revision']}/{relative}"
        data = fetch(url, build / "bbsc-original" / relative, digest, offline)
        if relative.endswith("/bbsc_gameserver.py"):
            data = patch_local_login(patch_gameserver(data))
        output = build / "game-app" / Path(relative).name
        write_once(output, data)
        output.chmod(0o644)  # The unprivileged gameserver must read public source files.
    write_once(build / "game-app" / "source-manifest.json", (ROOT / "sources.json").read_bytes())
    (build / "game-app" / "source-manifest.json").chmod(0o644)
    (build / "game-app").chmod(0o755)
    for name in ("shadnet-state", "game-state"):
        (ROOT / name).mkdir(mode=0o700, exist_ok=True)
    if not config_path.exists():
        template = (ROOT / "shadnet.cfg.example").read_text(encoding="utf-8")
        config = template.replace("__SERVER_IP__", str(address)).replace(
            "__REGISTRATION_SECRET__", secrets.token_hex(32))
        write_once(config_path, config.encode())
        config_path.chmod(0o600)
    write_once(ROOT / ".env", expected_env)
    print("Pinned sources verified; game server patched; deployment material ready.")
    print("Existing matching configuration was preserved. No service/account/firewall was changed.")
    print("On the Linux server: chown state directories to UID/GID 10001 before starting Compose.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-ip", required=True, help="server's Tailscale IPv4")
    parser.add_argument("--offline", action="store_true", help="require all pinned files in .build")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        prepare(args.server_ip, args.offline)
    except (OSError, ValueError, KeyError, configparser.Error) as error:
        parser.exit(1, f"Preparation stopped: {error}\n")


if __name__ == "__main__":
    main()
