"""Assemble native binaries and their runtime dependency closure, not a dev tree."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
PREFIX = Path(os.environ.get("WIN_SERVER_TOOLCHAIN", r"C:\bbsc-dev\msys64\clang64"))
from build_config import OUT, VERSION
BIN = OUT / "runtime" / "bin"
BIN.mkdir(parents=True, exist_ok=True)
dependencies = {}


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def closure(source):
    key = source.name.lower()
    if key in dependencies:
        return
    dependencies[key] = str(source)
    output = subprocess.check_output([str(PREFIX / "bin" / "llvm-objdump.exe"), "-p", str(source)])
    for name in re.findall(rb"DLL Name: ([^\r\n]+)", output):
        filename = name.decode("ascii").strip()
        candidate = PREFIX / "bin" / filename
        if candidate.exists():
            copy(candidate, BIN / filename)
            closure(candidate)
        elif not filename.lower().startswith(("api-ms-", "ext-ms-")) and not (
            Path(os.environ["SystemRoot"]) / "System32" / filename).exists():
            raise ValueError(f"Unresolved runtime dependency: {source.name} -> {filename}")


for mode in ("normal", "bbsc"):
    folder = OUT / mode
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("shadnet.exe", "worlds.cfg", "scoreboards.cfg"):
        copy(ROOT / "build" / name, folder / name)
    (folder / "qt.conf").write_text("[Paths]\nPlugins=../runtime/plugins\n", encoding="ascii")
closure(ROOT / "build" / "shadnet.exe")
copy(ROOT / "build" / "clientsample" / "shadnet-sample.exe", BIN / "shadnet-sample.exe")
closure(BIN / "shadnet-sample.exe")
copy(ROOT / "build" / "clientsample" / "shadnet-admin.exe", BIN / "shadnet-admin.exe")
closure(BIN / "shadnet-admin.exe")
copy(PREFIX / "share" / "qt6" / "plugins" / "sqldrivers" / "qsqlite.dll",
     OUT / "runtime" / "plugins" / "sqldrivers" / "qsqlite.dll")
closure(OUT / "runtime" / "plugins" / "sqldrivers" / "qsqlite.dll")
copy(PREFIX / "bin" / "python.exe", BIN / "python.exe")
closure(BIN / "python.exe")

# Keep the standard library and native extensions, excluding dev-only/test/UI packages.
python_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
standard = PREFIX / "lib" / python_dir
skip = {"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib-dynload"}
shutil.copytree(standard, OUT / "runtime" / "lib" / python_dir, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*skip, "*.pyc", "*.a", "*.exe"))
for source in (standard / "lib-dynload").glob("*.pyd"):
    if "test" in source.name or source.name.startswith(("_tkinter", "_curses", "readline")):
        continue
    copy(source, OUT / "runtime" / "lib" / python_dir / "lib-dynload" / source.name)
    closure(source)

shutil.copytree(ROOT / "bbsc-game", OUT / "bbsc-game", dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(ROOT / "package-src", OUT, dirs_exist_ok=True)
copy(ROOT / "build-ui" / "Server.exe", OUT / "Server.exe")
copy(ROOT / "build-ui" / "TheHunt.ico", OUT / "TheHunt.ico")
copy(ROOT.parent / "docs" / "updates.md", OUT / "docs" / "updates.md")
(OUT / "server.json").write_text('{"address": "127.0.0.1"}\n', encoding="ascii")

licenses = OUT / "licenses"
for source, target in ((ROOT / "src" / "LICENSES", "shadnet"),
                       (ROOT / "src" / "externals" / "abseil-cpp" / "LICENSE", "abseil-LICENSE"),
                       (ROOT / "src" / "externals" / "protobuf" / "LICENSE", "protobuf-LICENSE")):
    if source.is_dir():
        shutil.copytree(source, licenses / target, dirs_exist_ok=True)
    else:
        copy(source, licenses / target)

packages = subprocess.check_output([str(PREFIX.parent / "usr" / "bin" / "pacman.exe"), "-Q"], text=True)
for package in (PREFIX / "share" / "licenses").iterdir():
    # License texts are tiny; preserve all installed runtime notices rather than risk omissions.
    if package.is_dir():
        shutil.copytree(package, licenses / "runtime" / package.name, dirs_exist_ok=True)
(licenses / "runtime-packages.txt").write_text(packages, encoding="utf-8")
copy(ROOT / "source-manifest.json", OUT / "source-manifest.json")
manifest = {str(p.relative_to(OUT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "BUILD-INFO.json"}
info = {"label": VERSION, "platform": "Windows x64", "compiler": subprocess.check_output(
    [str(PREFIX / "bin" / "clang++.exe"), "--version"], text=True).splitlines()[0],
        "qt": subprocess.check_output([str(PREFIX / "bin" / "qmake6.exe"), "-query", "QT_VERSION"], text=True).strip(), "python": sys.version, "files": manifest,
        "patches": ["STUN 4/6 byte framing", "enable shadnet-sample target", "BBSC explicit summon WebAPI",
                    "same-PC login endpoints use the bound listener address"]}
(OUT / "BUILD-INFO.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Runtime staged: {len(manifest)} files, {sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file()) / 1048576:.1f} MiB")


def archive(folder, output):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                bundle.write(file, str(file.relative_to(folder.parent)))
    print(f"ZIP: {output.name} SHA256={hashlib.sha256(output.read_bytes()).hexdigest()}")


if "--zip" in sys.argv:
    archive(OUT, OUT.parent / (OUT.name + ".zip"))
