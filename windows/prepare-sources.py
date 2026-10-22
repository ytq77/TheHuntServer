"""Fetch verified, pinned sources into this disposable native-build directory."""
import importlib.util
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent
RECIPE = ROOT.parent / "recipe"
spec = importlib.util.spec_from_file_location("recipe", RECIPE / "prepare.py")
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)
manifest = json.loads((RECIPE / "sources.json").read_text(encoding="utf-8"))

for item in manifest["archives"]:
    archive = ROOT / "downloads" / item["name"]
    recipe.fetch(f"https://codeload.github.com/{item['repo']}/tar.gz/{item['revision']}",
                 archive, item["sha256"], False)
    destination = ROOT / "src" if item["name"] == "shadnet.tar.gz" else (
        ROOT / "src" / "externals" / ("protobuf" if item["name"] == "protobuf.tar.gz" else "abseil-cpp"))
    stamp = destination / ".source-revision"
    if stamp.exists():
        if stamp.read_text() != item["revision"]:
            raise ValueError(f"Conflicting source: {destination}")
        continue
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        prefix = members[0].name.split("/")[0] + "/"
        for member in members:
            if not member.name.startswith(prefix) or member.name == prefix.rstrip("/"):
                continue
            member.name = member.name[len(prefix):]
            bundle.extract(member, destination, filter="data")
    stamp.write_text(item["revision"])

for name in ("stun_server.cpp", "stun_server.h"):
    shutil.copy2(RECIPE / "fixes" / name, ROOT / "src" / "src" / name)
cmake = ROOT / "src" / "CMakeLists.txt"
text = cmake.read_text(encoding="utf-8")
if "add_subdirectory(clientsample)" not in text:
    cmake.write_text(text + "\nadd_subdirectory(clientsample)\n", encoding="utf-8")

bbsc = manifest["bbsc"]
for relative, digest in bbsc["files"].items():
    original = ROOT / "downloads" / "bbsc" / relative
    data = recipe.fetch(f"https://raw.githubusercontent.com/{bbsc['repo']}/{bbsc['revision']}/{relative}",
                        original, digest, False)
    if relative.endswith("/bbsc_gameserver.py"):
        data = recipe.patch_local_login(recipe.patch_gameserver(data))
    output = ROOT / "bbsc-game" / Path(relative).name
    output.parent.mkdir(exist_ok=True)
    output.write_bytes(data)
(ROOT / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Pinned sources verified and staged; STUN, summon WebAPI and same-PC login patches applied.")
