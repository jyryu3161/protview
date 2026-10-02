"""Refusal-path and record tests for scripts/setup_docking_worker.py. No real venv or pip install runs here."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts import setup_docking_worker as sd


def _wheel(name: str, version: str, data: bytes) -> dict:
    return {"file": f"{name}-{version}-py3-none-any.whl", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture
def synthetic(tmp_path):
    """Two synthetic (not real) wheels and a matching lock."""
    house = tmp_path / "wheelhouse"
    house.mkdir()
    entries = []
    for name, data in (("alpha", b"alpha-bytes"), ("beta", b"beta-bytes")):
        entry = _wheel(name, "1.0", data)
        (house / entry["file"]).write_bytes(data)
        entries.append(entry)
    return house, entries


# --- platform ---------------------------------------------------------------

@pytest.mark.parametrize("version,system,machine", [
    ((3, 12), "Darwin", "arm64"),
    ((3, 10), "Darwin", "arm64"),
    ((3, 11), "Linux", "arm64"),
    ((3, 11), "Darwin", "x86_64"),
])
def test_platform_refused(version, system, machine):
    with pytest.raises(sd.SetupError):
        sd.check_platform(version, system, machine)


def test_platform_accepted():
    sd.check_platform((3, 11), "Darwin", "arm64")


# --- lock -------------------------------------------------------------------

def test_repository_lock_is_complete_and_pins_engines():
    entries = sd.load_lock(sd.LOCK, sd.REQUIREMENTS)
    assert len(entries) == sd.EXPECTED_ARTIFACTS == 26
    files = {e["file"] for e in entries}
    for name, version in sd.PINNED.items():
        assert any(f.lower().startswith(f"{name}-{version}-") for f in files), name
    assert not any(f.lower().startswith(("prolif-", "psutil-", "pandas-", "pip-", "setuptools-")) for f in files)


def test_lock_matches_t1_measurement_and_m11_wheels():
    """Every locked wheel is a T1-measured file; every non-Meeko wheel is byte-identical to the M11 ProLIF lock."""
    t1 = json.loads((sd.ROOT / "docs/qa/m18-docking-20261002/lock-inputs.json").read_text())
    measured = {(w["file"], w["bytes"], w["sha256"]) for w in t1["docking_python_core"]["wheels"]}
    measured |= {(w["file"], w["bytes"], w["sha256"])
                 for w in t1["docking_python_mdanalysis_option"]["additional_wheels_beyond_core"]}
    locked = {(e["file"], e["bytes"], e["sha256"]) for e in sd.load_lock(sd.LOCK, sd.REQUIREMENTS)}
    assert locked <= measured
    prolif = {(e["file"], e["bytes"], e["sha256"])
              for e in json.loads((sd.ROOT / "config/chemical/prolif-wheel-hashes-macos-arm64-py311.json").read_text())}
    assert {e for e in locked if not e[0].startswith("meeko-")} <= prolif


def test_requirements_lock_disagreement_refused(tmp_path):
    reqs = tmp_path / "reqs.txt"
    reqs.write_text("\n".join(line for line in sd.REQUIREMENTS.read_text().splitlines()
                              if not line.startswith("meeko==")) + "\n")
    with pytest.raises(sd.SetupError):
        sd.load_lock(sd.LOCK, reqs)


def test_requirements_without_hash_refused(tmp_path):
    reqs = tmp_path / "reqs.txt"
    reqs.write_text(sd.REQUIREMENTS.read_text().replace(" --hash=sha256:", " #sha256:", 1))
    with pytest.raises(sd.SetupError):
        sd.load_lock(sd.LOCK, reqs)


def test_lock_wrong_count_refused(tmp_path):
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(json.loads(sd.LOCK.read_text())[:-1]))
    with pytest.raises(sd.SetupError):
        sd.load_lock(lock, sd.REQUIREMENTS)


def test_lock_tampered_meeko_hash_refused(tmp_path):
    entries = json.loads(sd.LOCK.read_text())
    old = next(e["sha256"] for e in entries if e["file"].startswith("meeko-"))
    for entry in entries:
        if entry["file"].startswith("meeko-"):
            entry["sha256"] = "0" * 64
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(entries))
    reqs = tmp_path / "reqs.txt"
    reqs.write_text(sd.REQUIREMENTS.read_text().replace(old, "0" * 64))
    with pytest.raises(sd.SetupError, match="meeko"):
        sd.load_lock(lock, reqs)


def test_lock_path_traversal_refused(tmp_path):
    entries = json.loads(sd.LOCK.read_text())
    entries[0]["file"] = "../" + entries[0]["file"]
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(entries))
    with pytest.raises(sd.SetupError):
        sd.load_lock(lock, sd.REQUIREMENTS)


# --- wheels -----------------------------------------------------------------

def test_wheels_verified(synthetic):
    house, entries = synthetic
    assert sorted(sd.verify_wheels(house, entries)) == sorted(e["file"] for e in entries)


def test_missing_wheel_refused(synthetic):
    house, entries = synthetic
    (house / entries[1]["file"]).unlink()
    with pytest.raises(sd.SetupError, match="missing"):
        sd.verify_wheels(house, entries)


def test_wheel_hash_mismatch_refused(synthetic):
    house, entries = synthetic
    (house / entries[0]["file"]).write_bytes(b"alpha-bytez")  # same size, different bytes
    with pytest.raises(sd.SetupError, match="SHA-256"):
        sd.verify_wheels(house, entries)


def test_wheel_size_mismatch_refused(synthetic):
    house, entries = synthetic
    (house / entries[0]["file"]).write_bytes(b"alpha-bytes-longer")
    with pytest.raises(sd.SetupError, match="size"):
        sd.verify_wheels(house, entries)


def test_symlinked_wheel_refused(synthetic, tmp_path):
    house, entries = synthetic
    target = house / entries[0]["file"]
    real = tmp_path / "elsewhere.whl"
    real.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(real)
    with pytest.raises(sd.SetupError):
        sd.verify_wheels(house, entries)


def test_pip_install_command_is_offline_and_hash_checked(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(sd.subprocess, "run", lambda argv, **kw: seen.append(argv) or
                        type("R", (), {"returncode": 0})())
    sd.run_pip_install(tmp_path / "venv", tmp_path / "staged")
    argv = seen[0]
    assert argv[0] == str(tmp_path / "venv/bin/python") and argv[1:4] == ["-m", "pip", "install"]
    for flag in ("--no-index", "--require-hashes", "--no-deps", "--only-binary=:all:"):
        assert flag in argv
    assert argv[argv.index("--find-links") + 1] == str(tmp_path / "staged")
    assert argv[argv.index("-r") + 1] == str(sd.REQUIREMENTS)


# --- installed set check -----------------------------------------------------

def _inspected(entries: list[dict]) -> dict:
    out = {"pip": {"version": "24.0", "license": "MIT", "license_files": []},
           "setuptools": {"version": "65.5.0", "license": "", "license_files": []}}
    for entry in entries:
        name, version = entry["file"].split("-")[:2]
        out[name.lower().replace("_", "-")] = {"version": version, "license": "X", "license_files": []}
    return out


def test_installed_set_must_equal_lock(synthetic):
    _house, entries = synthetic
    sd.verify_installed(_inspected(entries), entries, pinned={"alpha": "1.0"}, meeko_license=None)
    extra = _inspected(entries)
    extra["prolif"] = {"version": "2.2.2", "license": "", "license_files": []}
    with pytest.raises(sd.SetupError, match="differs"):
        sd.verify_installed(extra, entries, pinned={}, meeko_license=None)
    wrong = _inspected(entries)
    wrong["alpha"]["version"] = "1.1"
    with pytest.raises(sd.SetupError):
        sd.verify_installed(wrong, entries, pinned={"alpha": "1.0"}, meeko_license=None)


def test_meeko_license_must_be_lgpl(synthetic):
    _house, entries = synthetic
    entries = entries + [_wheel("meeko", "0.8.0", b"m")]
    inspected = _inspected(entries)
    inspected["meeko"]["license"] = "LGPL-2.1"
    sd.verify_installed(inspected, entries, pinned={"meeko": "0.8.0"}, meeko_license="LGPL-2.1")
    inspected["meeko"]["license"] = "MIT"
    with pytest.raises(sd.SetupError, match="license"):
        sd.verify_installed(inspected, entries, pinned={"meeko": "0.8.0"}, meeko_license="LGPL-2.1")


# --- main: nothing is created on refusal; failures remove what this run made ---

@pytest.fixture
def no_venv_call(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("venv must not be created on a refused setup")
    monkeypatch.setattr(sd, "run_venv_create", forbidden)


def _ok_platform(monkeypatch):
    monkeypatch.setattr(sd, "platform_info", lambda: ((3, 11), "Darwin", "arm64"))


def test_main_wrong_platform_creates_nothing(tmp_path, monkeypatch, no_venv_call):
    monkeypatch.setattr(sd, "platform_info", lambda: ((3, 12), "Darwin", "arm64"))
    dest = tmp_path / "deps" / "venv-locked"
    assert sd.main(["--wheelhouse", str(tmp_path), "--destination", str(dest)]) != 0
    assert not dest.parent.exists()


def test_main_hash_mismatch_creates_nothing(tmp_path, monkeypatch, no_venv_call):
    _ok_platform(monkeypatch)
    house = tmp_path / "house"
    house.mkdir()
    for entry in sd.load_lock(sd.LOCK, sd.REQUIREMENTS):
        (house / entry["file"]).write_bytes(b"\0" * entry["bytes"])  # right size, wrong bytes
    dest = tmp_path / "deps" / "venv-locked"
    assert sd.main(["--wheelhouse", str(house), "--destination", str(dest)]) != 0
    assert not dest.parent.exists()


@pytest.mark.parametrize("existing", ["venv-locked", sd.RECORD_NAME])
def test_main_existing_install_refused(tmp_path, monkeypatch, no_venv_call, synthetic, existing):
    _ok_platform(monkeypatch)
    house, entries = synthetic
    monkeypatch.setattr(sd, "load_lock", lambda *_a: entries)
    dest = tmp_path / "deps" / "venv-locked"
    dest.parent.mkdir(parents=True)
    (dest.parent / existing).mkdir()
    assert sd.main(["--wheelhouse", str(house), "--destination", str(dest)]) != 0
    assert [p.name for p in dest.parent.iterdir()] == [existing]
    assert not any((dest.parent / existing).iterdir())


def _fake_venv(python, dest):
    (dest / "bin").mkdir(parents=True)
    (dest / "bin" / "python").write_bytes(b"python-binary")


@pytest.mark.parametrize("failing", ["run_pip_install", "run_pip_check", "inspect_environment"])
def test_main_failure_after_venv_leaves_nothing_installed(tmp_path, monkeypatch, synthetic, failing):
    _ok_platform(monkeypatch)
    house, entries = synthetic
    monkeypatch.setattr(sd, "load_lock", lambda *_a: entries)
    monkeypatch.setattr(sd, "run_venv_create", _fake_venv)
    monkeypatch.setattr(sd, "run_pip_install", lambda dest, staged: None)
    monkeypatch.setattr(sd, "run_pip_check", lambda dest: "No broken requirements.")
    monkeypatch.setattr(sd, "inspect_environment", lambda dest: _inspected(entries))

    def boom(*_a, **_k):
        raise sd.SetupError(f"{failing} failed")

    monkeypatch.setattr(sd, failing, boom)
    dest = tmp_path / "deps" / "venv-locked"
    assert sd.main(["--wheelhouse", str(house), "--destination", str(dest)]) != 0
    assert not dest.parent.exists()


def test_main_installed_set_mismatch_leaves_nothing_installed(tmp_path, monkeypatch, synthetic):
    _ok_platform(monkeypatch)
    house, entries = synthetic
    monkeypatch.setattr(sd, "load_lock", lambda *_a: entries)
    monkeypatch.setattr(sd, "PINNED", {})
    monkeypatch.setattr(sd, "run_venv_create", _fake_venv)
    monkeypatch.setattr(sd, "run_pip_install", lambda dest, staged: None)
    monkeypatch.setattr(sd, "run_pip_check", lambda dest: "No broken requirements.")
    monkeypatch.setattr(sd, "inspect_environment", lambda dest: _inspected(entries[:1]))
    dest = tmp_path / "deps" / "venv-locked"
    assert sd.main(["--wheelhouse", str(house), "--destination", str(dest)]) != 0
    assert not dest.parent.exists()


def test_install_record_contents(tmp_path, monkeypatch, synthetic):
    _ok_platform(monkeypatch)
    house, entries = synthetic
    entries = entries + [_wheel("meeko", "0.8.0", b"meeko-bytes")]
    (house / entries[-1]["file"]).write_bytes(b"meeko-bytes")
    monkeypatch.setattr(sd, "load_lock", lambda *_a: entries)
    monkeypatch.setattr(sd, "PINNED", {"meeko": "0.8.0"})
    monkeypatch.setattr(sd, "run_venv_create", _fake_venv)
    staged_seen = []
    monkeypatch.setattr(sd, "run_pip_install", lambda dest, staged: staged_seen.append(sorted(
        p.name for p in staged.iterdir())))
    monkeypatch.setattr(sd, "run_pip_check", lambda dest: "No broken requirements.")
    dest = tmp_path / "deps" / "venv-locked"
    lic = dest / "lib/python3.11/site-packages/meeko-0.8.0.dist-info/licenses/LICENSE"

    def fake_inspect(d):
        lic.parent.mkdir(parents=True)
        lic.write_text("GNU LESSER GENERAL PUBLIC LICENSE\n")
        out = _inspected(entries)
        out["meeko"].update(license="LGPL-2.1", license_files=[str(lic)])
        return out

    monkeypatch.setattr(sd, "inspect_environment", fake_inspect)
    monkeypatch.setattr(sd, "capture_python_version", lambda d: {
        "version_argv": ["python", "--version"], "version_exit_code": 0, "version_stdout": "Python 3.11.11\n",
        "version_stdout_sha256": hashlib.sha256(b"Python 3.11.11\n").hexdigest()})
    assert sd.main(["--wheelhouse", str(house), "--destination", str(dest)]) == 0
    assert staged_seen == [sorted(e["file"] for e in entries)]
    record = json.loads((dest.parent / sd.RECORD_NAME).read_text())
    assert record["schema"] == "docking_worker_install_record@1"
    assert record["install_root"] == str(dest.parent) and record["destination"] == "venv-locked"
    assert record["python"]["path"] == "venv-locked/bin/python"
    assert record["python"]["sha256"] == hashlib.sha256(b"python-binary").hexdigest()
    assert record["version_stdout"] == "Python 3.11.11\n" and record["version_exit_code"] == 0
    assert record["pinned"] == {"meeko": "0.8.0"}
    assert record["licenses"] == {"meeko": "LGPL-2.1"}
    assert record["pip_check"] == "No broken requirements."
    assert [p["wheel"] for p in record["packages"]] == [e["file"] for e in entries]
    assert {p["name"] for p in record["packages"]} == {"alpha", "beta", "meeko"}
    assert record["license_files"] == [{
        "package": "meeko", "path": "venv-locked/lib/python3.11/site-packages/meeko-0.8.0.dist-info/licenses/LICENSE",
        "sha256": hashlib.sha256(b"GNU LESSER GENERAL PUBLIC LICENSE\n").hexdigest()}]
    assert record["lock"] == {"wheel_hashes_sha256": sd.sha256_file(sd.LOCK),
                              "requirements_sha256": sd.sha256_file(sd.REQUIREMENTS), "artifact_count": 3}
    assert set(record["installer"]) == {"python", "macos", "machine", "platform"}
    assert record["installed_at_utc"].endswith("Z")
    assert sorted(p.name for p in dest.parent.iterdir()) == [sd.RECORD_NAME, "venv-locked"]


def test_default_destination_is_repository_deps():
    assert sd.DEFAULT_DEST == sd.ROOT / ".deps/docking/venv-locked"
    assert isinstance(sd.DEFAULT_DEST, Path)
