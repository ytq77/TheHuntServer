#!/usr/bin/env python3
"""Interactively register and verify an account on this recipe's private shadNet."""
import argparse
import configparser
import getpass
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent


def invoke(host, port, action, *values):
    # The upstream sample accepts credentials as argv. They are not printed or
    # written to shell history, but local administrators can inspect process args.
    command = ["docker", "compose", "exec", "-T", "shadnet", "shadnet-sample",
               host, port, action, *values]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=35)
    except subprocess.TimeoutExpired:
        raise ValueError(f"{action} timed out; check Compose health before retrying.") from None
    text = result.stdout + result.stderr
    marker = "[create] Account created successfully." if action == "register" else "[login] OK userId="
    if result.returncode != 0 or marker not in text:
        error = re.search(r"\[(?:create|login)\] FAILED: (\w+)", text)
        reason = error.group(1) if error else "no verified success response; inspect service health"
        raise ValueError(f"{action}: {reason}")  # Do not dump credentials or raw output.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", help="optional account name; password is always prompted")
    parser.add_argument("--email", help="optional unique email address")
    args = parser.parse_args()
    try:
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / "shadnet-state" / "shadnet.cfg", encoding="utf-8")
        general = config["General"]
        host, port = general["Host"], general["UnsecuredPort"]
        secret = general["RegistrationSecretKey"]
        if not secret or "__" in secret:
            raise ValueError("Run prepare.py first; a registration secret is required.")
        name = args.user or input("Account name (3-16 ASCII letters/digits/_/-): ").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,16}", name) or name == "DeletedUser":
            raise ValueError("Invalid account name.")
        email = args.email or input("Unique email address: ").strip()
        if "@" not in email or "." not in email:
            raise ValueError("Use a unique email address containing @ and a dot.")
        password = getpass.getpass("Password: ")
        if not password or password != getpass.getpass("Repeat password: "):
            raise ValueError("Passwords were empty or did not match.")
        invoke(host, port, "register", name, password, email, secret)
        invoke(host, port, "login", name, password)
        print(f"Account {name}: registered and authenticated.")
    except (OSError, ValueError, KeyError, configparser.Error) as error:
        parser.exit(1, f"Account creation stopped: {error}\n")
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, "\nCancelled.\n")


if __name__ == "__main__":
    main()
