"""Install the pinned QuickVina 2.1 (conda-forge qvina 2.1.0, osx-arm64) from verified local conda archives.

This is an explicit setup command, never invoked at runtime, and it never downloads. conda is a prerequisite.
Every one of the 8 locked archives in --pkgs must match the lock by file name, size and SHA-256 before
anything is created. The environment is created offline from an explicit list that points only at private
copies of those verified archives. Any failure removes what this run created; the install record is written
last. The same package also ships bin/vina (AutoDock Vina 1.1.2); it is hashed for the record and never run.
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
EXPLICIT = ROOT / "config/docking/qvina-conda-explicit-osx-arm64.txt"
LOCK_JSON = ROOT / "config/docking/qvina-conda-lock-hashes-osx-arm64.json"
DEFAULT_PREFIX = ROOT / ".deps/qvina/env"
RECORD_NAME = "install-record.json"
CACHE_NAME = "pkgs"

EXPECTED_PACKAGES = 8
QVINA_ARCHIVE = "qvina-2.1.0-h4a521e9_8.conda"
QVINA_PACKAGE_SHA256 = "a13781ae2c9a188c8c04854a75ae86579b009d46cd61613f1402cd16d6397077"
QVINA_EXECUTABLE_SHA256 = "caf5f22a3928be8adf3cb017508eaacbdcecf68ef29c5bca24fceea016c5f79c"
QVINA_VERSION_SHA256 = "f5749196ee2e33e4d6daa6725ad4ba27c90fe67d01fb0db10af3f5ae0cf3f069"
QVINA_LICENSE = "Apache-2.0"
VINA_NOT_CALLED_REASON = "AutoDock Vina 1.1.2 shipped in the same conda package; M18 uses qvina2 only"
MIN_MACOS = (11, 0)
_SHA256 = re.compile(r"[0-9a-f]{64}")


class SetupError(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_name(entry: dict) -> str:
    return f"{entry['name']}-{entry['version']}-{entry['build']}.conda"


def platform_info() -> tuple[str, str, str]:
    return platform.system(), platform.machine(), platform.mac_ver()[0]


def check_platform(system: str, machine: str, mac_version: str) -> None:
    if system != "Darwin" or machine != "arm64":
        raise SetupError(f"qvina lock requires macOS arm64 (found {system} {machine})")
    try:
        parts = tuple(int(p) for p in mac_version.split("."))
    except ValueError:
        parts = ()
    if not parts or (parts + (0,))[:2] < MIN_MACOS:
        raise SetupError(f"locked qvina packages require macOS >= 11.0 (found {mac_version or 'unknown'})")


def find_conda(explicit: Path | None, env=os.environ, which=shutil.which) -> Path:
    candidates = [explicit] if explicit is not None else [env.get("CONDA_EXE"), which("conda")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate).resolve()
    raise SetupError("conda executable not found; conda is required to install qvina")


def _explicit_urls(explicit: Path) -> list[str]:
    lines = [line.strip() for line in explicit.read_text().splitlines()]
    body = [line for line in lines if line and not line.startswith("#")]
    if not body or body[0] != "@EXPLICIT":
        raise SetupError("explicit list must start with @EXPLICIT")
    return body[1:]


def load_lock(lock_path: Path, explicit_path: Path) -> list[dict]:
    """Return lock entries in explicit (install) order after cross-checking both lock files."""
    entries = json.loads(lock_path.read_text())
    urls = _explicit_urls(explicit_path)
    if len(entries) != EXPECTED_PACKAGES or len(urls) != EXPECTED_PACKAGES:
        raise SetupError(f"lock must list exactly {EXPECTED_PACKAGES} packages")
    by_url = {}
    for entry in entries:
        name = archive_name(entry)
        if Path(name).name != name or entry["url"].rsplit("/", 1)[-1] != name:
            raise SetupError(f"invalid locked archive name: {name}")
        if not _SHA256.fullmatch(entry["sha256"]) or not isinstance(entry["size"], int) or entry["size"] <= 0:
            raise SetupError(f"invalid lock hash/size: {name}")
        by_url[entry["url"]] = entry
    if len(by_url) != EXPECTED_PACKAGES or set(by_url) != set(urls):
        raise SetupError("explicit list and lock hashes disagree")
    ordered = [by_url[url] for url in urls]
    pinned = [e for e in ordered if archive_name(e) == QVINA_ARCHIVE]
    if len(pinned) != 1 or pinned[0]["sha256"] != QVINA_PACKAGE_SHA256:
        raise SetupError("lock does not pin qvina-2.1.0-h4a521e9_8 with the expected SHA-256")
    return ordered


def verify_archives(pkgs_dir: Path, entries: list[dict]) -> dict[str, Path]:
    found = {}
    for entry in entries:
        name = archive_name(entry)
        path = pkgs_dir / name
        if path.is_symlink() or not path.is_file():
            raise SetupError(f"locked archive missing (or not a regular file): {name}")
        if path.stat().st_size != entry["size"]:
            raise SetupError(f"locked archive size mismatch: {name}")
        if sha256_file(path) != entry["sha256"]:
            raise SetupError(f"locked archive SHA-256 mismatch: {name}")
        found[name] = path
    return found


def stage_archives(found: dict[str, Path], entries: list[dict], staged: Path) -> None:
    """Copy verified archives into a private directory and re-verify the copies."""
    staged.mkdir()
    for entry in entries:
        name = archive_name(entry)
        shutil.copyfile(found[name], staged / name)
    verify_archives(staged, entries)


def write_local_explicit(path: Path, staged: Path, entries: list[dict]) -> Path:
    lines = ["# platform: osx-arm64", "@EXPLICIT"] + [(staged / archive_name(e)).as_uri() for e in entries]
    path.write_text("\n".join(lines) + "\n")
    return path


def run_conda_create(conda: Path, prefix: Path, explicit: Path, cache: Path, env: dict) -> None:
    argv = [str(conda), "create", "--offline", "--yes", "--prefix", str(prefix), "--file", str(explicit)]
    result = subprocess.run(argv, env=env, check=False)
    if result.returncode != 0:
        raise SetupError(f"conda create failed (exit {result.returncode})")


def verify_environment(prefix: Path, cache: Path, entries: list[dict]) -> None:
    executable = prefix / "bin/qvina2"
    if not executable.is_file() or sha256_file(executable) != QVINA_EXECUTABLE_SHA256:
        raise SetupError("installed bin/qvina2 SHA-256 does not match the pinned value")
    meta = prefix / "conda-meta"
    expected = {archive_name(e)[: -len(".conda")] for e in entries}
    records = {p.stem: json.loads(p.read_text()) for p in meta.glob("*.json")} if meta.is_dir() else {}
    if set(records) != expected:
        raise SetupError("installed package set differs from the lock")
    for dist, record in records.items():
        extracted = Path(record.get("extracted_package_dir", ""))
        if extracted.parent != cache:
            raise SetupError(f"{dist} was not linked from the private verified package cache")
    verify_archives(cache, entries)


def capture_version(executable: Path, workdir: Path) -> dict:
    """Run ``qvina2 --version`` once and require exit 0 and the pinned stdout bytes."""
    result = subprocess.run([str(executable), "--version"], cwd=workdir, capture_output=True, timeout=60,
                            check=False)
    stdout_sha = hashlib.sha256(result.stdout).hexdigest()
    if result.returncode != 0 or stdout_sha != QVINA_VERSION_SHA256:
        raise SetupError(f"qvina2 --version output does not match the pinned value (exit {result.returncode})")
    return {"version_argv": ["qvina2", "--version"], "version_exit_code": result.returncode,
            "version_stdout": result.stdout.decode("utf-8"), "version_stdout_sha256": stdout_sha,
            "version_stderr_sha256": hashlib.sha256(result.stderr).hexdigest()}


def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def recipe_provenance(info: Path, base: Path) -> dict:
    about = json.loads((info / "about.json").read_text())
    extra = about.get("extra") or {}
    recipe_files = sorted(p for p in (info / "recipe").rglob("*") if p.is_file())
    return {
        "license": about.get("license"),
        "feedstock_remote_url": extra.get("remote_url"),
        "feedstock_sha": extra.get("sha"),
        "recipe_files": [{"path": _rel(p, base), "sha256": sha256_file(p)} for p in recipe_files],
    }


def license_files(cache: Path, entries: list[dict], base: Path) -> list[dict]:
    out = []
    for entry in entries:
        info = cache / archive_name(entry)[: -len(".conda")] / "info"
        paths = set((info / "licenses").rglob("*")) if (info / "licenses").is_dir() else set()
        paths |= set(info.glob("LICENSE*"))
        for path in sorted(p for p in paths if p.is_file()):
            out.append({"package": entry["name"], "path": _rel(path, base), "sha256": sha256_file(path),
                        "kind": "notice" if "NOTICE" in path.name.upper() else "license"})
    return out


def conda_version(conda: Path, env: dict) -> str:
    result = subprocess.run([str(conda), "--version"], env=env, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def _remove_created(path: Path, base: Path) -> None:
    """Remove a path this run created; refuse to touch anything outside the install root."""
    if path.parent != base:
        raise SetupError(f"refusing to remove unexpected path {path}")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def install(pkgs_dir: Path, prefix: Path, conda: Path, entries: list[dict]) -> dict:
    base = prefix.parent
    cache = base / CACHE_NAME
    record_path = base / RECORD_NAME
    for existing in (prefix, cache, record_path):
        if existing.exists() or existing.is_symlink():
            raise SetupError(f"{existing} already exists; remove it before a fresh reproducible setup")
    found = verify_archives(pkgs_dir, entries)
    base_existed = base.exists()
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".setup-", dir=base))
    env = dict(os.environ, CONDA_PKGS_DIRS=str(cache), CONDA_OFFLINE="true")
    completed = False
    try:
        staged = work / "archives"
        stage_archives(found, entries, staged)
        explicit = write_local_explicit(work / "explicit-local.txt", staged, entries)
        run_conda_create(conda, prefix, explicit, cache, env)
        verify_environment(prefix, cache, entries)
        version = capture_version(prefix / "bin/qvina2", work)
        pinned = next(e for e in entries if archive_name(e) == QVINA_ARCHIVE)
        vina = prefix / "bin/vina"
        record = {
            "schema": "qvina_install_record@1",
            "engine": "qvina", "release": "2.1.0", "build": "h4a521e9_8", "subdir": "osx-arm64",
            "license": QVINA_LICENSE,
            "install_root": str(base),
            "prefix": _rel(prefix, base),
            "executable": {"path": _rel(prefix / "bin/qvina2", base), "sha256": QVINA_EXECUTABLE_SHA256},
            "package_sha256": pinned["sha256"],
            **version,
            "not_called": ([{"path": _rel(vina, base), "sha256": sha256_file(vina), "reason": VINA_NOT_CALLED_REASON}]
                           if vina.is_file() else []),
            "lock": {"explicit_sha256": sha256_file(EXPLICIT), "hashes_sha256": sha256_file(LOCK_JSON),
                     "package_count": len(entries)},
            "packages": [{"name": e["name"], "version": e["version"], "build": e["build"],
                          "archive": archive_name(e), "sha256": e["sha256"], "size": e["size"]} for e in entries],
            "recipe_provenance": recipe_provenance(cache / QVINA_ARCHIVE[: -len(".conda")] / "info", base),
            "license_files": license_files(cache, entries, base),
            "installer": {"conda": conda_version(conda, env), "macos": platform.mac_ver()[0],
                          "machine": platform.machine(), "python": sys.version.split()[0]},
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
            for created in (base / (RECORD_NAME + ".partial"), record_path, prefix, cache):
                _remove_created(created, base)
            if not base_existed and not any(base.iterdir()):
                base.rmdir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pkgs", type=Path, required=True, help="directory holding the 8 locked .conda archives")
    parser.add_argument("--prefix", type=Path, default=DEFAULT_PREFIX)
    parser.add_argument("--conda", type=Path, default=None, help="conda executable (default: $CONDA_EXE, PATH)")
    args = parser.parse_args(argv)
    try:
        check_platform(*platform_info())
        conda = find_conda(args.conda)
        entries = load_lock(LOCK_JSON, EXPLICIT)
        pkgs_dir = args.pkgs.resolve(strict=True) if args.pkgs.exists() else args.pkgs
        if not pkgs_dir.is_dir():
            raise SetupError(f"--pkgs is not a directory: {args.pkgs}")
        prefix = args.prefix.absolute().parent.resolve() / args.prefix.name
        record = install(pkgs_dir, prefix, conda, entries)
    except SetupError as exc:
        print(f"setup_qvina: refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"installed": True, "prefix": str(prefix), "executable_sha256": record["executable"]["sha256"],
                      "version_stdout": record["version_stdout"], "packages": len(record["packages"])},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
