"""Refusal-path tests for scripts/setup_fpocket.py. No real conda install runs here."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts import setup_fpocket as sf


def _entry(name: str, data: bytes) -> dict:
    version, build = "1.0", "h0_0"
    file = f"{name}-{version}-{build}.conda"
    return {"name": name, "version": version, "build": build,
            "channel": "https://conda.anaconda.org/conda-forge/osx-arm64",
            "url": f"https://conda.anaconda.org/conda-forge/osx-arm64/{file}",
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


@pytest.fixture
def synthetic(tmp_path):
    """Two synthetic (not real conda) archives and a matching lock."""
    pkgs = tmp_path / "pkgs"
    pkgs.mkdir()
    entries = []
    for name, data in (("alpha", b"alpha-bytes"), ("beta", b"beta-bytes")):
        entry = _entry(name, data)
        (pkgs / sf.archive_name(entry)).write_bytes(data)
        entries.append(entry)
    return pkgs, entries


# --- platform ---------------------------------------------------------------

@pytest.mark.parametrize("system,machine,version", [
    ("Linux", "arm64", "14.5"),
    ("Darwin", "x86_64", "15.6"),
    ("Darwin", "arm64", "14.4"),
    ("Darwin", "arm64", "13.6.1"),
    ("Darwin", "arm64", ""),
])
def test_platform_refused(system, machine, version):
    with pytest.raises(sf.SetupError):
        sf.check_platform(system, machine, version)


@pytest.mark.parametrize("version", ["14.5", "14.5.1", "15.6", "26.0"])
def test_platform_accepted(version):
    sf.check_platform("Darwin", "arm64", version)


# --- conda ------------------------------------------------------------------

def test_no_conda_refused(tmp_path):
    with pytest.raises(sf.SetupError, match="conda"):
        sf.find_conda(None, env={}, which=lambda _name: None)


def test_conda_exe_must_be_executable_file(tmp_path):
    with pytest.raises(sf.SetupError, match="conda"):
        sf.find_conda(tmp_path / "missing-conda", env={}, which=lambda _name: None)


def test_conda_found_via_conda_exe(tmp_path):
    exe = tmp_path / "conda"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert sf.find_conda(None, env={"CONDA_EXE": str(exe)}, which=lambda _name: None) == exe.resolve()


# --- lock -------------------------------------------------------------------

def test_repository_lock_is_complete_and_pins_fpocket():
    entries = sf.load_lock(sf.LOCK_JSON, sf.EXPLICIT)
    assert len(entries) == sf.EXPECTED_PACKAGES == 35
    fp = [e for e in entries if e["name"] == "fpocket"]
    assert len(fp) == 1
    assert sf.archive_name(fp[0]) == sf.FPOCKET_ARCHIVE
    assert fp[0]["sha256"] == sf.FPOCKET_PACKAGE_SHA256


def test_lock_explicit_disagreement_refused(tmp_path):
    lock = json.loads(sf.LOCK_JSON.read_text())
    explicit_lines = sf.EXPLICIT.read_text().splitlines()
    explicit = tmp_path / "explicit.txt"
    explicit.write_text("\n".join(line for line in explicit_lines if "fpocket-4.2.3" not in line) + "\n")
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(sf.SetupError):
        sf.load_lock(lock_path, explicit)


def test_lock_wrong_count_refused(tmp_path):
    lock = json.loads(sf.LOCK_JSON.read_text())[:-1]
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(sf.SetupError):
        sf.load_lock(lock_path, sf.EXPLICIT)


def test_lock_tampered_fpocket_hash_refused(tmp_path):
    lock = json.loads(sf.LOCK_JSON.read_text())
    for entry in lock:
        if entry["name"] == "fpocket":
            entry["sha256"] = "0" * 64
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(sf.SetupError, match="fpocket"):
        sf.load_lock(lock_path, sf.EXPLICIT)


# --- archives ---------------------------------------------------------------

def test_archives_verified(synthetic):
    pkgs, entries = synthetic
    found = sf.verify_archives(pkgs, entries)
    assert sorted(found) == sorted(sf.archive_name(e) for e in entries)


def test_missing_archive_refused(synthetic):
    pkgs, entries = synthetic
    (pkgs / sf.archive_name(entries[1])).unlink()
    with pytest.raises(sf.SetupError, match="missing"):
        sf.verify_archives(pkgs, entries)


def test_hash_mismatch_refused(synthetic):
    pkgs, entries = synthetic
    (pkgs / sf.archive_name(entries[0])).write_bytes(b"alpha-bytez")  # same size, different bytes
    with pytest.raises(sf.SetupError, match="SHA-256"):
        sf.verify_archives(pkgs, entries)


def test_size_mismatch_refused(synthetic):
    pkgs, entries = synthetic
    (pkgs / sf.archive_name(entries[0])).write_bytes(b"alpha-bytes-longer")
    with pytest.raises(sf.SetupError):
        sf.verify_archives(pkgs, entries)


def test_symlinked_archive_refused(synthetic, tmp_path):
    pkgs, entries = synthetic
    target = pkgs / sf.archive_name(entries[0])
    real = tmp_path / "elsewhere.conda"
    real.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(real)
    with pytest.raises(sf.SetupError):
        sf.verify_archives(pkgs, entries)


# --- main: nothing is created on refusal --------------------------------------

@pytest.fixture
def no_conda_call(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("conda must not run on a refused setup")
    monkeypatch.setattr(sf, "run_conda_create", forbidden)


def _ok_platform(monkeypatch):
    monkeypatch.setattr(sf, "platform_info", lambda: ("Darwin", "arm64", "15.6"))


def test_main_wrong_platform_creates_nothing(tmp_path, monkeypatch, no_conda_call):
    monkeypatch.setattr(sf, "platform_info", lambda: ("Linux", "x86_64", ""))
    prefix = tmp_path / "deps" / "env"
    assert sf.main(["--pkgs", str(tmp_path), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


def test_main_no_conda_creates_nothing(tmp_path, monkeypatch, no_conda_call):
    _ok_platform(monkeypatch)
    monkeypatch.setattr(sf, "find_conda", lambda *_a, **_k: (_ for _ in ()).throw(sf.SetupError("conda not found")))
    prefix = tmp_path / "deps" / "env"
    assert sf.main(["--pkgs", str(tmp_path), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


def test_main_hash_mismatch_creates_nothing(tmp_path, monkeypatch, no_conda_call):
    _ok_platform(monkeypatch)
    monkeypatch.setattr(sf, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    pkgs = tmp_path / "pkgs"
    pkgs.mkdir()
    for entry in sf.load_lock(sf.LOCK_JSON, sf.EXPLICIT):
        (pkgs / sf.archive_name(entry)).write_bytes(b"\0" * entry["size"])  # right size, wrong bytes
    prefix = tmp_path / "deps" / "env"
    assert sf.main(["--pkgs", str(pkgs), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


def test_main_existing_install_refused(tmp_path, monkeypatch, no_conda_call):
    _ok_platform(monkeypatch)
    monkeypatch.setattr(sf, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    monkeypatch.setattr(sf, "verify_archives", lambda pkgs, entries: {})
    prefix = tmp_path / "deps" / "env"
    prefix.mkdir(parents=True)
    assert sf.main(["--pkgs", str(tmp_path), "--prefix", str(prefix)]) != 0
    assert prefix.is_dir() and not any(prefix.iterdir())
    assert not (prefix.parent / sf.RECORD_NAME).exists()


def test_main_executable_mismatch_leaves_nothing_installed(tmp_path, monkeypatch, synthetic):
    """conda 'succeeds' but bin/fpocket has the wrong hash: prefix, cache and record must be gone."""
    _ok_platform(monkeypatch)
    pkgs, entries = synthetic
    monkeypatch.setattr(sf, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    monkeypatch.setattr(sf, "load_lock", lambda *_a: entries)

    def fake_create(conda, prefix, explicit, cache, env):
        (prefix / "bin").mkdir(parents=True)
        (prefix / "bin" / "fpocket").write_bytes(b"not the pinned binary")
        cache.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(sf, "run_conda_create", fake_create)
    prefix = tmp_path / "deps" / "env"
    assert sf.main(["--pkgs", str(pkgs), "--prefix", str(prefix)]) != 0
    assert not prefix.exists()
    assert not (prefix.parent / sf.CACHE_NAME).exists()
    assert not (prefix.parent / sf.RECORD_NAME).exists()
    assert [p.name for p in prefix.parent.iterdir()] == []


def test_main_conda_failure_leaves_nothing_installed(tmp_path, monkeypatch, synthetic):
    _ok_platform(monkeypatch)
    pkgs, entries = synthetic
    monkeypatch.setattr(sf, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    monkeypatch.setattr(sf, "load_lock", lambda *_a: entries)

    def failing_create(conda, prefix, explicit, cache, env):
        (prefix / "conda-meta").mkdir(parents=True)
        raise sf.SetupError("conda create failed (exit 1)")

    monkeypatch.setattr(sf, "run_conda_create", failing_create)
    prefix = tmp_path / "deps" / "env"
    assert sf.main(["--pkgs", str(pkgs), "--prefix", str(prefix)]) != 0
    assert not prefix.exists()
    assert [p.name for p in prefix.parent.iterdir()] == []


def test_local_explicit_points_only_at_verified_copies(tmp_path, synthetic):
    _pkgs, entries = synthetic
    staged = tmp_path / "staged"
    staged.mkdir()
    explicit = sf.write_local_explicit(tmp_path / "explicit.txt", staged, entries)
    lines = [line for line in explicit.read_text().splitlines() if line and not line.startswith("#")]
    assert lines[0] == "@EXPLICIT"
    assert lines[1:] == [(staged / sf.archive_name(e)).as_uri() for e in entries]
