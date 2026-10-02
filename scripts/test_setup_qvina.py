"""Refusal-path and record tests for scripts/setup_qvina.py. No real conda install runs here."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts import setup_qvina as sq


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
        (pkgs / sq.archive_name(entry)).write_bytes(data)
        entries.append(entry)
    return pkgs, entries


# --- platform ---------------------------------------------------------------

@pytest.mark.parametrize("system,machine,version", [
    ("Linux", "arm64", "14.5"),
    ("Darwin", "x86_64", "15.6"),
    ("Darwin", "arm64", "10.15.7"),
    ("Darwin", "arm64", ""),
])
def test_platform_refused(system, machine, version):
    with pytest.raises(sq.SetupError):
        sq.check_platform(system, machine, version)


@pytest.mark.parametrize("version", ["11.0", "14.5.1", "15.6", "26.0"])
def test_platform_accepted(version):
    sq.check_platform("Darwin", "arm64", version)


# --- conda ------------------------------------------------------------------

def test_no_conda_refused():
    with pytest.raises(sq.SetupError, match="conda"):
        sq.find_conda(None, env={}, which=lambda _name: None)


def test_conda_found_via_conda_exe(tmp_path):
    exe = tmp_path / "conda"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert sq.find_conda(None, env={"CONDA_EXE": str(exe)}, which=lambda _name: None) == exe.resolve()


# --- lock -------------------------------------------------------------------

def test_repository_lock_is_complete_and_pins_qvina():
    entries = sq.load_lock(sq.LOCK_JSON, sq.EXPLICIT)
    assert len(entries) == sq.EXPECTED_PACKAGES == 8
    qv = [e for e in entries if e["name"] == "qvina"]
    assert len(qv) == 1
    assert sq.archive_name(qv[0]) == sq.QVINA_ARCHIVE == "qvina-2.1.0-h4a521e9_8.conda"
    assert qv[0]["sha256"] == sq.QVINA_PACKAGE_SHA256
    assert all(e["channel"] == "https://conda.anaconda.org/conda-forge/osx-arm64" for e in entries)


def test_lock_matches_t1_measurement():
    """The committed lock is exactly the T1-measured package set (names, sizes, SHA-256)."""
    t1 = json.loads((sq.ROOT / "docs/qa/m18-docking-20261002/lock-inputs.json").read_text())["qvina_conda"]
    measured = {(p["file"], p["size"], p["sha256"]) for p in t1["packages"]}
    locked = {(sq.archive_name(e), e["size"], e["sha256"]) for e in sq.load_lock(sq.LOCK_JSON, sq.EXPLICIT)}
    assert locked == measured
    assert t1["installed"]["qvina2_sha256"] == sq.QVINA_EXECUTABLE_SHA256
    assert t1["installed"]["qvina2_version_stdout_sha256"] == sq.QVINA_VERSION_SHA256


def test_lock_explicit_disagreement_refused(tmp_path):
    explicit = tmp_path / "explicit.txt"
    explicit.write_text("\n".join(line for line in sq.EXPLICIT.read_text().splitlines()
                                  if "qvina-2.1.0" not in line) + "\n")
    with pytest.raises(sq.SetupError):
        sq.load_lock(sq.LOCK_JSON, explicit)


def test_lock_wrong_count_refused(tmp_path):
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(json.loads(sq.LOCK_JSON.read_text())[:-1]))
    with pytest.raises(sq.SetupError):
        sq.load_lock(lock_path, sq.EXPLICIT)


def test_lock_tampered_qvina_hash_refused(tmp_path):
    lock = json.loads(sq.LOCK_JSON.read_text())
    for entry in lock:
        if entry["name"] == "qvina":
            entry["sha256"] = "0" * 64
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(sq.SetupError, match="qvina"):
        sq.load_lock(lock_path, sq.EXPLICIT)


def test_lock_path_traversal_refused(tmp_path):
    lock = json.loads(sq.LOCK_JSON.read_text())
    lock[0]["name"] = "../evil"
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(sq.SetupError):
        sq.load_lock(lock_path, sq.EXPLICIT)


# --- archives ---------------------------------------------------------------

def test_archives_verified(synthetic):
    pkgs, entries = synthetic
    assert sorted(sq.verify_archives(pkgs, entries)) == sorted(sq.archive_name(e) for e in entries)


def test_missing_archive_refused(synthetic):
    pkgs, entries = synthetic
    (pkgs / sq.archive_name(entries[1])).unlink()
    with pytest.raises(sq.SetupError, match="missing"):
        sq.verify_archives(pkgs, entries)


def test_hash_mismatch_refused(synthetic):
    pkgs, entries = synthetic
    (pkgs / sq.archive_name(entries[0])).write_bytes(b"alpha-bytez")  # same size, different bytes
    with pytest.raises(sq.SetupError, match="SHA-256"):
        sq.verify_archives(pkgs, entries)


def test_size_mismatch_refused(synthetic):
    pkgs, entries = synthetic
    (pkgs / sq.archive_name(entries[0])).write_bytes(b"alpha-bytes-longer")
    with pytest.raises(sq.SetupError, match="size"):
        sq.verify_archives(pkgs, entries)


def test_symlinked_archive_refused(synthetic, tmp_path):
    pkgs, entries = synthetic
    target = pkgs / sq.archive_name(entries[0])
    real = tmp_path / "elsewhere.conda"
    real.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(real)
    with pytest.raises(sq.SetupError):
        sq.verify_archives(pkgs, entries)


def test_local_explicit_points_only_at_verified_copies(tmp_path, synthetic):
    _pkgs, entries = synthetic
    staged = tmp_path / "staged"
    staged.mkdir()
    explicit = sq.write_local_explicit(tmp_path / "explicit.txt", staged, entries)
    lines = [line for line in explicit.read_text().splitlines() if line and not line.startswith("#")]
    assert lines[0] == "@EXPLICIT"
    assert lines[1:] == [(staged / sq.archive_name(e)).as_uri() for e in entries]


# --- version capture ---------------------------------------------------------

def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def test_version_capture_accepts_pinned_output(tmp_path, monkeypatch):
    exe = _script(tmp_path / "qvina2", "printf 'QuickVina 2.1 (24 Dec, 2017)\\n'\n")
    result = sq.capture_version(exe, tmp_path)
    assert result == {"version_argv": ["qvina2", "--version"], "version_exit_code": 0,
                      "version_stdout": "QuickVina 2.1 (24 Dec, 2017)\n",
                      "version_stdout_sha256": sq.QVINA_VERSION_SHA256,
                      "version_stderr_sha256": hashlib.sha256(b"").hexdigest()}


@pytest.mark.parametrize("body", [
    "printf 'QuickVina 2.1 (24 Dec, 2017)\\n'; exit 1\n",
    "printf 'AutoDock Vina 1.1.2\\n'\n",
])
def test_version_capture_refuses_other_output_or_exit(tmp_path, body):
    exe = _script(tmp_path / "qvina2", body)
    with pytest.raises(sq.SetupError, match="version"):
        sq.capture_version(exe, tmp_path)


# --- main: nothing is created on refusal; failures remove what this run made ---

@pytest.fixture
def no_conda_call(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("conda must not run on a refused setup")
    monkeypatch.setattr(sq, "run_conda_create", forbidden)


def _ok_platform(monkeypatch):
    monkeypatch.setattr(sq, "platform_info", lambda: ("Darwin", "arm64", "15.6"))


def test_main_wrong_platform_creates_nothing(tmp_path, monkeypatch, no_conda_call):
    monkeypatch.setattr(sq, "platform_info", lambda: ("Linux", "x86_64", ""))
    prefix = tmp_path / "deps" / "env"
    assert sq.main(["--pkgs", str(tmp_path), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


def test_main_no_conda_creates_nothing(tmp_path, monkeypatch, no_conda_call):
    _ok_platform(monkeypatch)
    monkeypatch.setattr(sq, "find_conda", lambda *_a, **_k: (_ for _ in ()).throw(sq.SetupError("conda not found")))
    prefix = tmp_path / "deps" / "env"
    assert sq.main(["--pkgs", str(tmp_path), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


def test_main_hash_mismatch_creates_nothing(tmp_path, monkeypatch, no_conda_call):
    _ok_platform(monkeypatch)
    monkeypatch.setattr(sq, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    pkgs = tmp_path / "pkgs"
    pkgs.mkdir()
    for entry in sq.load_lock(sq.LOCK_JSON, sq.EXPLICIT):
        (pkgs / sq.archive_name(entry)).write_bytes(b"\0" * entry["size"])  # right size, wrong bytes
    prefix = tmp_path / "deps" / "env"
    assert sq.main(["--pkgs", str(pkgs), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


@pytest.mark.parametrize("existing", ["env", sq.CACHE_NAME, sq.RECORD_NAME])
def test_main_existing_install_refused(tmp_path, monkeypatch, no_conda_call, existing):
    _ok_platform(monkeypatch)
    monkeypatch.setattr(sq, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    monkeypatch.setattr(sq, "verify_archives", lambda pkgs, entries: {})
    prefix = tmp_path / "deps" / "env"
    prefix.parent.mkdir(parents=True)
    (prefix.parent / existing).mkdir()
    assert sq.main(["--pkgs", str(tmp_path), "--prefix", str(prefix)]) != 0
    assert [p.name for p in prefix.parent.iterdir()] == [existing]
    assert not any((prefix.parent / existing).iterdir())


def _fake_env(prefix: Path, cache: Path, qvina: bytes, vina: bytes = b"vina") -> None:
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "qvina2").write_bytes(qvina)
    (prefix / "bin" / "vina").write_bytes(vina)
    cache.mkdir(parents=True, exist_ok=True)


def test_main_executable_mismatch_leaves_nothing_installed(tmp_path, monkeypatch, synthetic):
    """conda 'succeeds' but bin/qvina2 has the wrong hash: prefix, cache and record must be gone."""
    _ok_platform(monkeypatch)
    pkgs, entries = synthetic
    monkeypatch.setattr(sq, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    monkeypatch.setattr(sq, "load_lock", lambda *_a: entries)
    monkeypatch.setattr(sq, "run_conda_create",
                        lambda conda, prefix, explicit, cache, env: _fake_env(prefix, cache, b"not qvina"))
    prefix = tmp_path / "deps" / "env"
    assert sq.main(["--pkgs", str(pkgs), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


def test_main_conda_failure_leaves_nothing_installed(tmp_path, monkeypatch, synthetic):
    _ok_platform(monkeypatch)
    pkgs, entries = synthetic
    monkeypatch.setattr(sq, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    monkeypatch.setattr(sq, "load_lock", lambda *_a: entries)

    def failing_create(conda, prefix, explicit, cache, env):
        (prefix / "conda-meta").mkdir(parents=True)
        cache.mkdir(parents=True, exist_ok=True)
        raise sq.SetupError("conda create failed (exit 1)")

    monkeypatch.setattr(sq, "run_conda_create", failing_create)
    prefix = tmp_path / "deps" / "env"
    assert sq.main(["--pkgs", str(pkgs), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


def test_main_version_failure_leaves_nothing_installed(tmp_path, monkeypatch, synthetic):
    _ok_platform(monkeypatch)
    pkgs, entries = synthetic
    monkeypatch.setattr(sq, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    monkeypatch.setattr(sq, "load_lock", lambda *_a: entries)
    monkeypatch.setattr(sq, "run_conda_create",
                        lambda conda, prefix, explicit, cache, env: _fake_env(prefix, cache, b"q"))
    monkeypatch.setattr(sq, "verify_environment", lambda prefix, cache, entries: None)

    def bad_version(executable, workdir):
        raise sq.SetupError("qvina2 --version output does not match the pinned value")

    monkeypatch.setattr(sq, "capture_version", bad_version)
    prefix = tmp_path / "deps" / "env"
    assert sq.main(["--pkgs", str(pkgs), "--prefix", str(prefix)]) != 0
    assert not prefix.parent.exists()


def test_install_record_contents(tmp_path, monkeypatch, synthetic):
    """With conda and the verified-environment check stubbed, the record carries the required fields."""
    _ok_platform(monkeypatch)
    pkgs, entries = synthetic
    monkeypatch.setattr(sq, "find_conda", lambda *_a, **_k: Path("/usr/bin/true"))
    monkeypatch.setattr(sq, "load_lock", lambda *_a: entries)

    def fake_create(conda, prefix, explicit, cache, env):
        _fake_env(prefix, cache, b"qvina-binary", b"vina-binary")
        info = cache / "alpha-1.0-h0_0" / "info"
        (info / "licenses").mkdir(parents=True)
        (info / "licenses" / "LICENSE").write_text("Apache License 2.0\n")
        (info / "about.json").write_text(json.dumps({"license": "Apache-2.0", "extra": {
            "remote_url": "https://github.com/conda-forge/x-feedstock", "sha": "abc"}}))
        (info / "recipe").mkdir()
        (info / "recipe" / "recipe.yaml").write_text("package: {}\n")

    monkeypatch.setattr(sq, "run_conda_create", fake_create)
    monkeypatch.setattr(sq, "verify_environment", lambda prefix, cache, entries: None)
    monkeypatch.setattr(sq, "QVINA_ARCHIVE", "alpha-1.0-h0_0.conda")
    monkeypatch.setattr(sq, "capture_version", lambda executable, workdir: {
        "version_argv": ["qvina2", "--version"], "version_exit_code": 0, "version_stdout": "QuickVina 2.1\n",
        "version_stdout_sha256": "f" * 64, "version_stderr_sha256": "e" * 64})
    prefix = tmp_path / "deps" / "env"
    assert sq.main(["--pkgs", str(pkgs), "--prefix", str(prefix)]) == 0
    record = json.loads((prefix.parent / sq.RECORD_NAME).read_text())
    assert record["schema"] == "qvina_install_record@1"
    assert (record["engine"], record["release"], record["subdir"]) == ("qvina", "2.1.0", "osx-arm64")
    assert record["license"] == "Apache-2.0"
    assert record["executable"] == {"path": "env/bin/qvina2", "sha256": sq.QVINA_EXECUTABLE_SHA256}
    assert record["version_stdout_sha256"] == "f" * 64 and record["version_exit_code"] == 0
    assert record["not_called"] == [{"path": "env/bin/vina", "sha256": hashlib.sha256(b"vina-binary").hexdigest(),
                                     "reason": sq.VINA_NOT_CALLED_REASON}]
    assert [p["archive"] for p in record["packages"]] == [sq.archive_name(e) for e in entries]
    assert record["license_files"] == [{
        "package": "alpha", "path": "pkgs/alpha-1.0-h0_0/info/licenses/LICENSE", "kind": "license",
        "sha256": hashlib.sha256(b"Apache License 2.0\n").hexdigest()}]
    assert record["recipe_provenance"]["feedstock_remote_url"] == "https://github.com/conda-forge/x-feedstock"
    assert record["recipe_provenance"]["recipe_files"][0]["path"] == "pkgs/alpha-1.0-h0_0/info/recipe/recipe.yaml"
    assert record["lock"] == {"explicit_sha256": sq.sha256_file(sq.EXPLICIT),
                              "hashes_sha256": sq.sha256_file(sq.LOCK_JSON), "package_count": len(entries)}
    assert set(record["installer"]) == {"conda", "macos", "machine", "python"}
    assert record["installed_at_utc"].endswith("Z")
    assert record["install_root"] == str(prefix.parent)
    assert sorted(p.name for p in prefix.parent.iterdir()) == ["env", sq.RECORD_NAME, sq.CACHE_NAME]
