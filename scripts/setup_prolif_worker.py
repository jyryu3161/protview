"""Install the pinned local M11 worker from a prepopulated, verified wheelhouse.

This is an explicit development/deployment setup command, never invoked at runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "config/chemical/prolif-wheel-hashes-macos-arm64-py311.json"
REQUIREMENTS = ROOT / "config/chemical/prolif-requirements-macos-arm64-py311.txt"
DEFAULT_DEST = ROOT / ".deps/prolif/venv-locked"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11) or platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("this wheel lock requires CPython 3.11 on macOS arm64")
    wheelhouse = args.wheelhouse.resolve(strict=True)
    entries = json.loads(LOCK.read_text())
    if len(entries) != 33 or len({e["file"] for e in entries}) != 33:
        parser.error("invalid complete 33-artifact lock")
    for entry in entries:
        name = entry["file"]
        if Path(name).name != name or not name.endswith(".whl"):
            parser.error("invalid locked filename")
        wheel = wheelhouse / name
        if not wheel.is_file() or wheel.is_symlink():
            parser.error(f"locked wheel unavailable: {name}")
        data = wheel.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            parser.error(f"locked wheel hash/size mismatch: {name}")
    dest = args.destination.resolve()
    if dest.exists():
        parser.error("destination already exists; select a new destination for reproducible setup")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(dest)], check=True)
    pip = dest / "bin/pip"
    subprocess.run([str(pip), "install", "--no-index", "--find-links", str(wheelhouse),
                    "--require-hashes", "--force-reinstall", "--no-deps", "-r", str(REQUIREMENTS)], check=True)
    subprocess.run([str(pip), "check"], check=True)
    print(json.dumps({"python": str(dest / "bin/python"),
                      "installer_python": sys.version.split()[0], "platform": platform.platform(),
                      "machine": platform.machine(),
                      "lock_sha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(),
                      "requirements_sha256": hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest(),
                      "artifacts": len(entries)}, sort_keys=True))


if __name__ == "__main__":
    main()
