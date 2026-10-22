"""One version and output name shared by build, package and runtime tests."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT.parent / "VERSION").read_text(encoding="ascii").strip()
if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", VERSION):
    raise ValueError("Invalid VERSION")
OUT = ROOT / "dist" / f"TheHuntServer-Windows-v{VERSION}"
