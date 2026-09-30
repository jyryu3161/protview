"""Tests for scripts/import_reference_snapshots.py.

Every kbase-like tree here is a synthetic FIXTURE built in pytest tmp_path (not real UniProt/SIFTS/KLIFS data).
No network is used; the real kbase_kinase checkout is never read by these tests.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import import_reference_snapshots as irs

FIXED_GIT = {"commit": "0" * 40, "dirty": False}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(ref: Path, source: str, date: str, files: dict[str, bytes], *, license: str,
              version_hint: str | None = None) -> dict:
    entries = []
    for name, data in files.items():
        path = ref / source / date / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entries.append({"path": f"{source}/{date}/{name}", "sha256": "sha256:" + _sha(data), "bytes": len(data),
                        "rows": data.count(b"\n")})
    return {"snapshot_id": f"SNAP-{source}-{date}", "source": source, "date": date,
            "urls": [f"https://fixture.invalid/{source}/{i}" for i in range(3)], "license": license,
            "version_hint": version_hint, "raw_sha256": ["sha256:" + "a" * 64, "sha256:" + "b" * 64],
            "files": entries}


def _fixture_kbase(root: Path, *, newer_sifts: bytes | None = None) -> Path:
    """Build a synthetic FIXTURE kbase tree: two dates per source, the newer one must win."""
    ref = root / "ref"
    snaps = [
        _snapshot(ref, "uniprot", "2026-01-01", {"entries.jsonl": b'{"fixture":"old"}\n'}, license="CC-BY-4.0",
                  version_hint="2026_00"),
        _snapshot(ref, "uniprot", "2026-01-05", {"entries.jsonl": b'{"fixture":"u1"}\n{"fixture":"u2"}\n'},
                  license="CC-BY-4.0", version_hint="2026_01"),
        _snapshot(ref, "sifts", "2026-01-02", {"residues.jsonl": b'{"fixture":"old"}\n',
                                               "segments.jsonl": b'{"fixture":"old"}\n'}, license="EMBL-EBI-terms"),
        _snapshot(ref, "sifts", "2026-01-06",
                  {"residues.jsonl": newer_sifts or b'{"fixture":"r1"}\n', "segments.jsonl": b'{"fixture":"s1"}\n'},
                  license="EMBL-EBI-terms"),
        _snapshot(ref, "klifs", "2026-01-07", {"kinases.jsonl": b'{"fixture":"k1"}\n',
                                               "match_residues.jsonl": b'{"fixture":"m1"}\n',
                                               "structures.jsonl": b'{"fixture":"not copied"}\n'},
                  license="none-stated"),
        _snapshot(ref, "chembl", "2026-01-08", {"activities.jsonl": b'{"fixture":"not copied"}\n'},
                  license="CC-BY-SA-3.0"),
    ]
    (ref / "manifest.json").write_text(json.dumps({"snapshots": snaps}))
    return root


def _manifest(root: Path) -> dict:
    return json.loads((root / "ref" / "manifest.json").read_text())


def _tree(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def _run(kbase: Path, dest: Path, **kw):
    return irs.import_snapshots(kbase, dest, git_info=lambda _p: dict(FIXED_GIT), **kw)


# --- happy path and manifest fields ----------------------------------------------------------------

def test_import_writes_set_and_active_pointer(tmp_path):
    kbase = _fixture_kbase(tmp_path / "kbase")
    dest = tmp_path / "reference"
    result = _run(kbase, dest)
    set_hash = result["set_hash"]
    pointer = json.loads((dest / irs.ACTIVE_NAME).read_bytes())
    assert pointer == {"schema": irs.POINTER_SCHEMA, "set_hash": set_hash}
    set_dir = dest / "sets" / set_hash
    raw = (set_dir / irs.MANIFEST_NAME).read_bytes()
    assert _sha(raw) == set_hash
    assert raw == irs.canonical_json(json.loads(raw))
    manifest = json.loads(raw)
    assert manifest["schema"] == irs.SET_SCHEMA
    assert manifest["kbase_repo"] == FIXED_GIT
    assert type(manifest["imported_at"]) is str and manifest["imported_at"].endswith("Z")
    by_source = {s["source"]: s for s in manifest["sources"]}
    assert set(by_source) == {"uniprot", "sifts", "klifs"}
    uni = by_source["uniprot"]
    assert uni["snapshot_id"] == "SNAP-uniprot-2026-01-05" and uni["date"] == "2026-01-05"
    assert uni["version_hint"] == "2026_01" and uni["license"] == "CC-BY-4.0"
    assert uni["origin"] == "kbase_kinase processed snapshot"
    assert uni["url_count"] == 3 and uni["raw_sha256"] == ["sha256:" + "a" * 64, "sha256:" + "b" * 64]
    assert uni["files"] == [{"name": "entries.jsonl", "path": "uniprot/2026-01-05/entries.jsonl",
                             "sha256": _sha(b'{"fixture":"u1"}\n{"fixture":"u2"}\n'), "bytes": 34, "rows": 2,
                             "use": "product"}]
    assert by_source["sifts"]["version_hint"] is None and by_source["sifts"]["license"] == "EMBL-EBI-terms"
    assert [f["name"] for f in by_source["sifts"]["files"]] == ["residues.jsonl", "segments.jsonl"]
    klifs = {f["name"]: f["use"] for f in by_source["klifs"]["files"]}
    assert klifs == {"kinases.jsonl": "product", "match_residues.jsonl": "comparison_only"}
    assert by_source["klifs"]["license"] == "none-stated"
    # Only the listed files are copied, byte-identical to the kbase source.
    copied = _tree(set_dir / "files")
    assert sorted(copied) == sorted(f["path"] for s in manifest["sources"] for f in s["files"])
    for rel, data in copied.items():
        assert data == (kbase / "ref" / rel).read_bytes()
    assert not any(p.name.startswith(".staging") for p in (dest / "sets").iterdir())


def test_real_git_commit_and_dirty_flag(tmp_path):
    kbase = _fixture_kbase(tmp_path / "kbase")
    git = ["git", "-C", str(kbase), "-c", "user.name=fixture", "-c", "user.email=fixture@invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "ref"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "fixture"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    assert irs.read_git_info(kbase) == {"commit": head, "dirty": False}
    (kbase / "untracked.txt").write_text("x")
    assert irs.read_git_info(kbase) == {"commit": head, "dirty": True}


def test_not_a_git_repo_refused(tmp_path):
    kbase = _fixture_kbase(tmp_path / "kbase")
    with pytest.raises(irs.ImportFailure):
        irs.read_git_info(kbase)


# --- refusal: nothing changes ------------------------------------------------------------------------

def _tamper_hash(kbase: Path) -> None:
    path = kbase / "ref" / "sifts" / "2026-01-06" / "residues.jsonl"
    path.write_bytes(path.read_bytes().replace(b"r1", b"r9"))  # same length: only SHA-256 differs


def _tamper_bytes(kbase: Path) -> None:
    m = _manifest(kbase)
    for snap in m["snapshots"]:
        if snap["snapshot_id"] == "SNAP-klifs-2026-01-07":
            snap["files"][0]["bytes"] += 1
    (kbase / "ref" / "manifest.json").write_text(json.dumps(m))


def _missing_file(kbase: Path) -> None:
    (kbase / "ref" / "uniprot" / "2026-01-05" / "entries.jsonl").unlink()


def _missing_required(kbase: Path) -> None:
    m = _manifest(kbase)
    for snap in m["snapshots"]:
        if snap["snapshot_id"] == "SNAP-sifts-2026-01-06":
            snap["files"] = [f for f in snap["files"] if not f["path"].endswith("segments.jsonl")]
    (kbase / "ref" / "manifest.json").write_text(json.dumps(m))


def _traversal_path(kbase: Path) -> None:
    m = _manifest(kbase)
    for snap in m["snapshots"]:
        if snap["snapshot_id"] == "SNAP-uniprot-2026-01-05":
            snap["files"][0]["path"] = "uniprot/2026-01-05/../../../outside/entries.jsonl"
    (kbase / "ref" / "manifest.json").write_text(json.dumps(m))


def _duplicate_latest(kbase: Path) -> None:
    m = _manifest(kbase)
    dup = next(s for s in m["snapshots"] if s["snapshot_id"] == "SNAP-klifs-2026-01-07")
    m["snapshots"].append({**dup, "snapshot_id": "SNAP-klifs-2026-01-07b"})
    (kbase / "ref" / "manifest.json").write_text(json.dumps(m))


def _no_source(kbase: Path) -> None:
    m = _manifest(kbase)
    m["snapshots"] = [s for s in m["snapshots"] if s["source"] != "uniprot"]
    (kbase / "ref" / "manifest.json").write_text(json.dumps(m))


def _rows_mismatch(kbase: Path) -> None:
    m = _manifest(kbase)
    for snap in m["snapshots"]:
        if snap["snapshot_id"] == "SNAP-uniprot-2026-01-05":
            snap["files"][0]["rows"] = 7
    (kbase / "ref" / "manifest.json").write_text(json.dumps(m))


def _malformed_manifest(kbase: Path) -> None:
    (kbase / "ref" / "manifest.json").write_text("{not json")


@pytest.mark.parametrize("tamper", [_tamper_hash, _tamper_bytes, _missing_file, _missing_required, _traversal_path,
                                    _duplicate_latest, _no_source, _rows_mismatch, _malformed_manifest])
def test_mismatch_changes_nothing_on_fresh_dest(tmp_path, tamper):
    kbase = _fixture_kbase(tmp_path / "kbase")
    tamper(kbase)
    dest = tmp_path / "reference"
    with pytest.raises(irs.ImportFailure):
        _run(kbase, dest)
    assert not dest.exists()


def test_mismatch_leaves_existing_active_set_untouched(tmp_path):
    kbase = _fixture_kbase(tmp_path / "kbase")
    dest = tmp_path / "reference"
    _run(kbase, dest)
    before = _tree(dest)
    _tamper_hash(kbase)
    with pytest.raises(irs.ImportFailure, match="sha256"):
        _run(kbase, dest)
    assert _tree(dest) == before


def test_same_length_tamper_is_caught_by_sha256(tmp_path):
    # Same length, different content: the byte count matches, only SHA-256 catches it.
    kbase = _fixture_kbase(tmp_path / "kbase")
    path = kbase / "ref" / "klifs" / "2026-01-07" / "kinases.jsonl"
    data = path.read_bytes()
    path.write_bytes(data.replace(b"k1", b"k2"))
    with pytest.raises(irs.ImportFailure, match="sha256"):
        _run(kbase, tmp_path / "reference")


# --- re-import: new set active, old set preserved, atomic pointer swap --------------------------------

def test_reimport_activates_new_set_and_preserves_old(tmp_path):
    kbase = _fixture_kbase(tmp_path / "kbase")
    dest = tmp_path / "reference"
    first = _run(kbase, dest, now=lambda: "2026-09-30T00:00:00.000001Z")
    old_tree = _tree(dest / "sets" / first["set_hash"])
    second = _run(kbase, dest, now=lambda: "2026-09-30T00:00:01.000001Z")
    assert first["set_hash"] != second["set_hash"]
    assert json.loads((dest / irs.ACTIVE_NAME).read_bytes())["set_hash"] == second["set_hash"]
    assert _tree(dest / "sets" / first["set_hash"]) == old_tree
    assert sorted(p.name for p in (dest / "sets").iterdir()) == sorted([first["set_hash"], second["set_hash"]])


def test_same_import_time_collision_refused_without_change(tmp_path):
    kbase = _fixture_kbase(tmp_path / "kbase")
    dest = tmp_path / "reference"
    _run(kbase, dest, now=lambda: "2026-09-30T00:00:00.000001Z")
    before = _tree(dest)
    with pytest.raises(irs.ImportFailure):
        _run(kbase, dest, now=lambda: "2026-09-30T00:00:00.000001Z")
    assert _tree(dest) == before


def test_pointer_swap_is_a_single_rename_after_the_set_is_complete(tmp_path, monkeypatch):
    kbase = _fixture_kbase(tmp_path / "kbase")
    dest = tmp_path / "reference"
    first = _run(kbase, dest, now=lambda: "2026-09-30T00:00:00.000001Z")
    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src, dst):
        dst = Path(dst)
        if dst.name == irs.ACTIVE_NAME:
            # At the moment of the swap the new set folder is complete and verifiable.
            pending = json.loads(Path(src).read_bytes())["set_hash"]
            set_dir = dest / "sets" / pending
            raw = (set_dir / irs.MANIFEST_NAME).read_bytes()
            assert _sha(raw) == pending
            for source in json.loads(raw)["sources"]:
                for entry in source["files"]:
                    assert _sha((set_dir / "files" / entry["path"]).read_bytes()) == entry["sha256"]
            # ...and the previous pointer is still intact.
            assert json.loads((dest / irs.ACTIVE_NAME).read_bytes())["set_hash"] == first["set_hash"]
        replaced.append((Path(src).name, dst.name))
        return real_replace(src, dst)

    monkeypatch.setattr(irs.os, "replace", spy)
    _run(kbase, dest, now=lambda: "2026-09-30T00:00:01.000001Z")
    assert [d for _s, d in replaced].count(irs.ACTIVE_NAME) == 1


def test_failure_while_writing_leaves_pointer_and_no_partial_set(tmp_path, monkeypatch):
    kbase = _fixture_kbase(tmp_path / "kbase")
    dest = tmp_path / "reference"
    _run(kbase, dest, now=lambda: "2026-09-30T00:00:00.000001Z")
    before = _tree(dest)
    real = irs._write_file
    calls = {"n": 0}

    def flaky(path, data):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("fixture disk failure")
        return real(path, data)

    monkeypatch.setattr(irs, "_write_file", flaky)
    with pytest.raises(OSError):
        _run(kbase, dest, now=lambda: "2026-09-30T00:00:01.000001Z")
    assert _tree(dest) == before


# --- CLI ----------------------------------------------------------------------------------------------

def test_cli_exit_codes(tmp_path):
    kbase = _fixture_kbase(tmp_path / "kbase")
    git = ["git", "-C", str(kbase), "-c", "user.name=fixture", "-c", "user.email=fixture@invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "ref"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "fixture"], check=True)
    script = Path(irs.__file__).resolve()
    dest = tmp_path / "reference"
    ok = subprocess.run([sys.executable, str(script), "--from", str(kbase), "--dest", str(dest)],
                        capture_output=True, text=True, check=False)
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["set_hash"] == json.loads((dest / irs.ACTIVE_NAME).read_bytes())["set_hash"]
    _tamper_hash(kbase)
    bad = subprocess.run([sys.executable, str(script), "--from", str(kbase), "--dest", str(tmp_path / "other")],
                         capture_output=True, text=True, check=False)
    assert bad.returncode == 1 and "sha256" in bad.stderr
    assert not (tmp_path / "other").exists()


def test_script_has_no_network_or_mw_imports():
    source = Path(irs.__file__).read_text()
    for banned in ("import socket", "urllib", "http.client", "httpx", "requests", "import mw", "from mw"):
        assert banned not in source
