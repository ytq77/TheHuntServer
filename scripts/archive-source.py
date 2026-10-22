"""Archive tracked project files plus exactly the pinned, verified upstream sources."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
OUT = ROOT / "dist"
OUT.mkdir(exist_ok=True)
tracked = subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}",
    "-C", str(ROOT), "ls-files", "-z"]).decode("utf-8").split("\0")
tracked = [name for name in tracked if name]
assert "VERSION" in tracked and "recipe/sources.json" in tracked, "Register project files in Git first"
manifest = json.loads((ROOT / "recipe/sources.json").read_text(encoding="utf-8"))
fixed = [(item["name"], item["sha256"]) for item in manifest["archives"]]
fixed += [("bbsc/" + name, sha) for name, sha in manifest["bbsc"]["files"].items()]
prefix = f"TheHuntServer-source-v{VERSION}"
with zipfile.ZipFile(OUT / f"{prefix}.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
    for name in sorted(tracked):
        bundle.write(ROOT / name, f"{prefix}/{name}")
    for name, digest in fixed:
        path = ROOT / "windows/downloads" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"Source hash mismatch: {name}"
        bundle.write(path, f"{prefix}/windows/downloads/{name}")
with zipfile.ZipFile(OUT / f"TheHuntServer-Linux-recipe-v{VERSION}.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
    for name in sorted(tracked):
        if name.startswith(("recipe/", "docs/")) or name in ("README.md", "VERSION", "LICENSE", "NOTICE.md"):
            bundle.write(ROOT / name, f"TheHuntServer/{name}")
binary = ROOT / "windows/dist" / f"TheHuntServer-Windows-v{VERSION}.zip"
shutil.copy2(binary, OUT / binary.name)
lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in sorted(OUT.glob('*.zip'))]
(OUT / "SHA256SUMS.txt").write_text("".join(lines), encoding="ascii")
print("".join(lines), end="")
