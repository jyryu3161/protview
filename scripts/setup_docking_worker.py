"""Install the pinned M18 docking worker environment (Meeko 0.8.0, RDKit 2026.3.6, MDAnalysis 2.10.0) offline.

This is an explicit development/deployment setup command, never invoked at runtime, and it never downloads.
Every one of the 26 locked wheels in --wheelhouse must match the lock by file name, size and SHA-256 before
anything is created. The verified wheels are copied to a private directory, re-verified, and installed into a
new venv with ``pip --no-index --require-hashes --no-deps``. The installed distribution set must equal the
lock (plus the venv's own pip/setuptools). Any failure removes what this run created; the install record is
written last. Meeko is LGPL-2.1 and is imported only inside this isolated environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "config/docking/docking-wheel-hashes-macos-arm64-py311.json"
REQUIREMENTS = ROOT / "config/docking/docking-requirements-macos-arm64-py311.txt"
DEFAULT_DEST = ROOT / ".deps/docking/venv-locked"
RECORD_NAME = "install-record.json"

EXPECTED_ARTIFACTS = 26
PINNED = {"meeko": "0.8.0", "rdkit": "2026.3.6", "mdanalysis": "2.10.0"}
PINNED_WHEEL_SHA256 = {
    "meeko": "38e73da7f0b11f7f8f0bfb2c481ccd148b8dfb9957522655b5cb0c4f6d68d1d6",
    "rdkit": "3c5395ccf20eb4301195086b15b3628c3cba770994dfbca7e0ca0992fe0e5e1c",
}
MEEKO_LICENSE = "LGPL-2.1"
VENV_BOOTSTRAP = {"pip", "setuptools"}  # installed by the venv itself (ensurepip), not from the lock
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REQUIREMENT = re.compile(r"([A-Za-z0-9._-]+)==(\S+) --hash=sha256:([0-9a-f]{64})")

_INSPECT = r"""
import json, sys
from importlib import metadata
out = {}
for dist in metadata.distributions():
    meta = dist.metadata
    lic = meta.get("License-Expression") or meta.get("License") or ""
    files = []
    for f in dist.files or []:
        parts = f.parts
        if parts and parts[0].endswith(".dist-info") and (
                "licenses" in parts[1:-1] or parts[-1].upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))):
            files.append(str(dist.locate_file(f)))
    out[meta["Name"]] = {"version": dist.version, "license": (lic.splitlines() or [""])[0][:200],
                         "license_files": sorted(files)}
json.dump(out, sys.stdout, sort_keys=True)
"""


class SetupError(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_name_version(file: str) -> tuple[str, str]:
    name, version = file.split("-")[:2]
    return normalize(name), version


def platform_info() -> tuple[tuple[int, int], str, str]:
    return tuple(sys.version_info[:2]), platform.system(), platform.machine()


def check_platform(version: tuple[int, int], system: str, machine: str) -> None:
    if tuple(version) != (3, 11) or system != "Darwin" or machine != "arm64":
        raise SetupError(f"this wheel lock requires CPython 3.11 on macOS arm64 (found {version} {system} {machine})")


def load_lock(lock_path: Path, requirements_path: Path) -> list[dict]:
    """Return lock entries after cross-checking the wheel lock against the hash-pinned requirements."""
    entries = json.loads(lock_path.read_text())
    if len(entries) != EXPECTED_ARTIFACTS or len({e["file"] for e in entries}) != EXPECTED_ARTIFACTS:
        raise SetupError(f"lock must list exactly {EXPECTED_ARTIFACTS} distinct wheels")
    lines = [line.strip() for line in requirements_path.read_text().splitlines() if line.strip()]
    required = {}
    for line in lines:
        match = _REQUIREMENT.fullmatch(line)
        if not match:
            raise SetupError(f"requirement line is not 'name==version --hash=sha256:<hex>': {line}")
        required[normalize(match[1])] = (match[2], match[3])
    by_name = {}
    for entry in entries:
        file = entry["file"]
        if Path(file).name != file or not file.endswith(".whl"):
            raise SetupError(f"invalid locked filename: {file}")
        if not _SHA256.fullmatch(entry["sha256"]) or not isinstance(entry["bytes"], int) or entry["bytes"] <= 0:
            raise SetupError(f"invalid lock hash/size: {file}")
        by_name[wheel_name_version(file)[0]] = entry
    if len(lines) != EXPECTED_ARTIFACTS or set(required) != set(by_name):
        raise SetupError("requirements and wheel lock disagree")
    for name, entry in by_name.items():
        if required[name] != (wheel_name_version(entry["file"])[1], entry["sha256"]):
            raise SetupError(f"requirements and wheel lock disagree for {name}")
    for name, version in PINNED.items():
        if name not in by_name or wheel_name_version(by_name[name]["file"])[1] != version:
            raise SetupError(f"lock does not pin {name}=={version}")
    for name, sha in PINNED_WHEEL_SHA256.items():
        if by_name[name]["sha256"] != sha:
            raise SetupError(f"lock does not pin the expected {name} wheel SHA-256")
    return entries


def verify_wheels(wheelhouse: Path, entries: list[dict]) -> dict[str, Path]:
    found = {}
    for entry in entries:
        path = wheelhouse / entry["file"]
        if path.is_symlink() or not path.is_file():
            raise SetupError(f"locked wheel missing (or not a regular file): {entry['file']}")
        if path.stat().st_size != entry["bytes"]:
            raise SetupError(f"locked wheel size mismatch: {entry['file']}")
        if sha256_file(path) != entry["sha256"]:
            raise SetupError(f"locked wheel SHA-256 mismatch: {entry['file']}")
        found[entry["file"]] = path
    return found


def stage_wheels(found: dict[str, Path], entries: list[dict], staged: Path) -> None:
    """Copy verified wheels into a private directory and re-verify the copies."""
    staged.mkdir()
    for entry in entries:
        shutil.copyfile(found[entry["file"]], staged / entry["file"])
    verify_wheels(staged, entries)


def run_venv_create(python: Path, dest: Path) -> None:
    result = subprocess.run([str(python), "-m", "venv", str(dest)], check=False)
    if result.returncode != 0:
        raise SetupError(f"venv creation failed (exit {result.returncode})")


def run_pip_install(dest: Path, staged: Path) -> None:
    argv = [str(dest / "bin/python"), "-m", "pip", "install", "--isolated", "--disable-pip-version-check",
            "--no-cache-dir", "--no-index", "--find-links", str(staged), "--only-binary=:all:",
            "--require-hashes", "--no-deps", "-r", str(REQUIREMENTS)]
    result = subprocess.run(argv, check=False)
    if result.returncode != 0:
        raise SetupError(f"pip install failed (exit {result.returncode})")


def run_pip_check(dest: Path) -> str:
    result = subprocess.run([str(dest / "bin/python"), "-m", "pip", "check"], capture_output=True, text=True,
                            check=False)
    if result.returncode != 0:
        raise SetupError(f"pip check failed: {result.stdout.strip()} {result.stderr.strip()}")
    return result.stdout.strip()


def inspect_environment(dest: Path) -> dict:
    result = subprocess.run([str(dest / "bin/python"), "-I", "-c", _INSPECT], capture_output=True, text=True,
                            check=False)
    if result.returncode != 0:
        raise SetupError(f"could not inspect the installed environment (exit {result.returncode})")
    return {normalize(name): info for name, info in json.loads(result.stdout).items()}


def verify_installed(inspected: dict, entries: list[dict], pinned: dict, meeko_license: str | None) -> None:
    expected = dict(wheel_name_version(e["file"]) for e in entries)
    installed = {name: info["version"] for name, info in inspected.items() if name not in VENV_BOOTSTRAP}
    if installed != expected:
        raise SetupError("installed distribution set differs from the lock")
    for name, version in pinned.items():
        if installed.get(name) != version:
            raise SetupError(f"installed {name} is not {version}")
    if meeko_license is not None and inspected["meeko"]["license"] != meeko_license:
        raise SetupError(f"installed meeko declares license {inspected['meeko']['license']!r}, not {meeko_license}")


def capture_python_version(dest: Path) -> dict:
    result = subprocess.run([str(dest / "bin/python"), "--version"], capture_output=True, check=False)
    text = result.stdout.decode("utf-8", errors="replace")
    if result.returncode != 0 or not text.startswith("Python 3.11."):
        raise SetupError(f"venv python --version is not CPython 3.11 (exit {result.returncode})")
    return {"version_argv": ["python", "--version"], "version_exit_code": result.returncode,
            "version_stdout": text, "version_stdout_sha256": hashlib.sha256(result.stdout).hexdigest()}


def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _remove_created(path: Path, base: Path) -> None:
    """Remove a path this run created; refuse to touch anything outside the install root."""
    if path.parent != base:
        raise SetupError(f"refusing to remove unexpected path {path}")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def install(wheelhouse: Path, dest: Path, python: Path, entries: list[dict]) -> dict:
    base = dest.parent
    record_path = base / RECORD_NAME
    for existing in (dest, record_path):
        if existing.exists() or existing.is_symlink():
            raise SetupError(f"{existing} already exists; remove it before a fresh reproducible setup")
    found = verify_wheels(wheelhouse, entries)
    base_existed = base.exists()
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".setup-", dir=base))
    completed = False
    try:
        staged = work / "wheels"
        stage_wheels(found, entries, staged)
        run_venv_create(python, dest)
        run_pip_install(dest, staged)
        pip_check = run_pip_check(dest)
        inspected = inspect_environment(dest)
        verify_installed(inspected, entries, PINNED, MEEKO_LICENSE if "meeko" in PINNED else None)
        version = capture_python_version(dest)
        executable = dest / "bin/python"
        record = {
            "schema": "docking_worker_install_record@1",
            "install_root": str(base),
            "destination": _rel(dest, base),
            "python": {"path": _rel(executable, base), "resolved": str(executable.resolve()),
                       "sha256": sha256_file(executable)},
            **version,
            "pinned": dict(PINNED),
            "licenses": {name: inspected[name]["license"] for name in ("meeko",) if name in inspected},
            "pip_check": pip_check,
            "venv_bootstrap": {name: inspected[name]["version"] for name in sorted(VENV_BOOTSTRAP & set(inspected))},
            "packages": [{"name": wheel_name_version(e["file"])[0], "version": wheel_name_version(e["file"])[1],
                          "wheel": e["file"], "sha256": e["sha256"], "bytes": e["bytes"],
                          "license_metadata": inspected[wheel_name_version(e["file"])[0]]["license"]}
                         for e in entries],
            "license_files": [{"package": name, "path": _rel(Path(p), base), "sha256": sha256_file(Path(p))}
                              for name in sorted(inspected) for p in inspected[name]["license_files"]],
            "lock": {"wheel_hashes_sha256": sha256_file(LOCK), "requirements_sha256": sha256_file(REQUIREMENTS),
                     "artifact_count": len(entries)},
            "installer": {"python": sys.version.split()[0], "macos": platform.mac_ver()[0],
                          "machine": platform.machine(), "platform": platform.platform()},
            "installed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        pending = base / (RECORD_NAME + ".partial")
        pending.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        os.replace(pending, record_path)
        completed = True
        return record
    finally:
        shutil.rmtree(work)
        if not completed:
            for created in (base / (RECORD_NAME + ".partial"), record_path, dest):
                _remove_created(created, base)
            if not base_existed and not any(base.iterdir()):
                base.rmdir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True, help="directory holding the 26 locked wheels")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)
    try:
        check_platform(*platform_info())
        entries = load_lock(LOCK, REQUIREMENTS)
        wheelhouse = args.wheelhouse.resolve(strict=True) if args.wheelhouse.exists() else args.wheelhouse
        if not wheelhouse.is_dir():
            raise SetupError(f"--wheelhouse is not a directory: {args.wheelhouse}")
        dest = args.destination.absolute().parent.resolve() / args.destination.name
        python = Path(getattr(sys, "_base_executable", sys.executable))
        record = install(wheelhouse, dest, python, entries)
    except SetupError as exc:
        print(f"setup_docking_worker: refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"installed": True, "destination": str(dest), "pinned": record["pinned"],
                      "artifacts": len(record["packages"]), "pip_check": record["pip_check"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
