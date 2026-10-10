"""Server-side M27 precedent reference set pinning (mw.precedent_snapshots).

Every reference folder is a LABELLED SYNTHETIC FIXTURE written in pytest tmp_path with ``precedent_fixture.build_set``
(the importer's layout); no real kbase_kinase data, no network, no ``.deps`` folder is touched.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import threading
from pathlib import Path

import precedent_fixture as PF
import pytest

from mw import precedent_constants as K
from mw import precedent_snapshots as ps

REPO = Path(__file__).resolve().parents[2]
NAMES = (*K.DIST_FILE_NAMES, K.pubmed_file_name(PF.PUBMED_DATE))


@pytest.fixture
def ref(tmp_path, monkeypatch):
    root = tmp_path / "precedent_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    ps._VERIFIED.clear()
    return root


def _invalid(root=None):
    with pytest.raises(ps.SnapshotUnavailable) as err:
        ps.pin_active_set(root)
    assert err.value.reason_code == "snapshot_invalid"
    assert err.value.reason == K.SNAPSHOT_REASONS["snapshot_invalid"]


def _file(root: Path, set_hash: str, name: str) -> Path:
    return root / "sets" / set_hash / K.file_path(name)


# ------------------------------------------------------------------------------------------- location

def test_default_dir_is_project_deps_and_separate_from_m15_and_m26(monkeypatch):
    monkeypatch.delenv(K.ENV_VAR, raising=False)
    monkeypatch.setenv("MW_REFERENCE_DIR", "/somewhere/else")            # the M15 variable never moves this family
    monkeypatch.setenv("MW_REACTION_REFERENCE_DIR", "/somewhere/other")  # nor does the M26 one
    assert ps.reference_dir() == REPO / ".deps" / "precedent_reference"


def test_env_var_selects_dir_and_relative_values_resolve_against_the_repo(ref, monkeypatch):
    assert ps.reference_dir() == ref
    monkeypatch.setenv(K.ENV_VAR, "runs/qa/precedent_reference")
    assert ps.reference_dir() == REPO / "runs" / "qa" / "precedent_reference"
    monkeypatch.setenv(K.ENV_VAR, "")
    assert ps.reference_dir() == REPO / ".deps" / "precedent_reference"


# ------------------------------------------------------------------------------------------- not installed

def test_not_installed_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(K.ENV_VAR, str(tmp_path / "absent"))
    assert ps.capability() == {"available": False, "reason_code": "not_installed",
                               "reason": K.SNAPSHOT_REASONS["not_installed"], "set_hash": None, "sources": []}
    with pytest.raises(ps.SnapshotUnavailable) as err:
        ps.pin_active_set()
    assert err.value.reason_code == "not_installed"
    assert err.value.reason == K.SNAPSHOT_REASONS["not_installed"]


def test_not_installed_when_no_active_pointer(ref):
    PF.build_set(ref, activate_set=False)
    with pytest.raises(ps.SnapshotUnavailable) as err:
        ps.pin_active_set()
    assert err.value.reason_code == "not_installed"


# ------------------------------------------------------------------------------------------- ok

def test_pin_ok_and_bound_accessors(ref):
    set_hash = PF.build_set(ref)
    pinned = ps.pin_active_set()
    assert pinned.set_hash == set_hash
    assert pinned.set_dir == ref / "sets" / set_hash
    assert pinned.manifest_bytes == (ref / "sets" / set_hash / "manifest.json").read_bytes()
    manifest = pinned.manifest
    manifest["schema"] = "edited"
    assert pinned.manifest["schema"] == K.SET_SCHEMA  # a copy each time
    assert pinned.names() == NAMES
    t2 = PF.t2_bytes()
    for name, key in zip(NAMES, ("moves", "moves_flagged", "references", "pubmed")):
        assert pinned.file_path(name) == _file(ref, set_hash, name)
        assert pinned.read_bytes(name) == t2[key]
    assert len(pinned.files_identity) == 4  # three dist files + the bibliography file
    rows = {key: data.count(b"\n") for key, data in t2.items()}
    assert pinned.summary() == [
        {"source": "kbase_dist", "date": "2026-10-01", "license": "none-stated",
         "origin": "kbase_kinase processed dist", "rows": rows["moves"] + rows["moves_flagged"] + rows["references"]},
        {"source": "kbase_pubmed", "date": PF.PUBMED_DATE, "license": PF.BIBLIOGRAPHY["license"],
         "origin": "kbase_kinase processed ref/pubmed", "rows": rows["pubmed"]},
    ]
    assert ps.capability() == {"available": True, "reason_code": None, "reason": None, "set_hash": set_hash,
                               "sources": pinned.summary()}


def test_dist_date_is_null_without_a_dist_commit(ref):
    PF.build_set(ref, kbase=dict(PF.KBASE) | {"dist_commit": None, "dist_commit_date": None})
    assert ps.pin_active_set().summary()[0]["date"] is None


def test_unknown_file_refused(ref):
    PF.build_set(ref)
    pinned = ps.pin_active_set()
    for name in ("dist/structures.jsonl", "manifest.json", "files/dist/moves.jsonl", "../active.json"):
        with pytest.raises(ps.SnapshotAccessError):
            pinned.read_bytes(name)
        with pytest.raises(ps.SnapshotAccessError):
            pinned.file_path(name)


# ------------------------------------------------------------------------------------------- snapshot_invalid

def test_tampered_file_same_size(ref):
    set_hash = PF.build_set(ref)
    path = _file(ref, set_hash, "dist/moves.jsonl")
    path.write_bytes(path.read_bytes().replace(b"SYNTHETIC", b"synthetic", 1))
    _invalid()


def test_tampered_file_after_a_cached_pin(ref):
    set_hash = PF.build_set(ref)
    ps.pin_active_set()
    path = _file(ref, set_hash, "dist/references.jsonl")
    path.write_bytes(path.read_bytes() + b"{}\n")
    _invalid()


def test_tampered_bibliography_file(ref):
    set_hash = PF.build_set(ref)
    path = _file(ref, set_hash, K.pubmed_file_name(PF.PUBMED_DATE))
    path.write_bytes(path.read_bytes().replace(b'"ok"', b'"OK"', 1))
    _invalid()


def test_missing_file(ref):
    set_hash = PF.build_set(ref)
    _file(ref, set_hash, "dist/moves_flagged.jsonl").unlink()
    _invalid()


def test_tampered_manifest_bytes(ref):
    set_hash = PF.build_set(ref)
    path = ref / "sets" / set_hash / "manifest.json"
    path.write_bytes(path.read_bytes().replace(b"2026-10-10T00:00:00Z", b"2026-10-10T00:00:01Z"))
    _invalid()


def test_pointer_to_a_missing_set_or_malformed_pointer(ref):
    PF.build_set(ref)
    for pointer in (b'{"schema":"precedent_active@1","set_hash":"' + b"0" * 64 + b'"}',
                    b'{"schema":"reaction_active@1","set_hash":"' + b"0" * 64 + b'"}',
                    b'{"schema":"precedent_active@1"}', b"not json", b"[]", b"{" * 5000 + b"\n"):
        (ref / "active.json").write_bytes(pointer)
        _invalid()


@pytest.mark.parametrize("field, delta", [("bytes", 1), ("rows", 1), ("sha256", None)])
def test_manifest_with_wrong_size_rows_or_hash(ref, field, delta):
    def patch(manifest):
        entry = manifest["files"][1]
        if delta is None:
            entry["sha256"] = "0" * 64
            entry["kbase_sha256"] = "sha256:" + "0" * 64
        else:
            entry[field] += delta
        if field == "rows":
            manifest["verification"]["records_hash_verified"]["moves_flagged"] += delta

    PF.build_set(ref, manifest_patch=patch)
    _invalid()


def test_wrong_bibliography_hash_in_manifest(ref):
    def patch(manifest):
        manifest["bibliography"]["file"]["sha256"] = "1" * 64
        manifest["bibliography"]["file"]["kbase_sha256"] = "sha256:" + "1" * 64

    PF.build_set(ref, manifest_patch=patch)
    _invalid()


def test_unknown_schema_or_pin_with_a_consistent_hash(ref):
    PF.build_set(ref, manifest_patch=lambda m: m.update(schema="precedent_reference_set@2"), validate=False)
    _invalid()
    PF.build_set(ref, imported_at="2026-10-10T00:00:05Z", validate=False,
                 manifest_patch=lambda m: m["kbase"].update(vocab_version="site@3"))
    _invalid()


def test_non_canonical_manifest_with_a_consistent_hash(ref):
    set_hash = PF.build_set(ref)
    manifest = json.loads((ref / "sets" / set_hash / "manifest.json").read_bytes())
    pretty = json.dumps(manifest, indent=1, sort_keys=True).encode()
    new_hash = K.set_hash_of(pretty)
    (ref / "sets" / set_hash).rename(ref / "sets" / new_hash)
    (ref / "sets" / new_hash / "manifest.json").write_bytes(pretty)
    PF.activate(ref, new_hash)
    _invalid()


def test_deeply_nested_manifest_with_a_consistent_hash_is_snapshot_invalid(ref):
    raw = b"[" * 100000
    set_hash = K.set_hash_of(raw)
    (ref / "sets" / set_hash).mkdir()
    (ref / "sets" / set_hash / "manifest.json").write_bytes(raw)
    PF.activate(ref, set_hash)
    _invalid()
    assert ps.capability()["reason_code"] == "snapshot_invalid"


def _rehome(ref: Path, set_hash: str, patch) -> str:
    """Edit a set's manifest, rename its folder to the new hash and activate it (an internally consistent set)."""
    manifest = json.loads((ref / "sets" / set_hash / "manifest.json").read_bytes())
    patch(manifest)
    raw = K.canonical_json(manifest)
    new_hash = K.set_hash_of(raw)
    (ref / "sets" / set_hash).rename(ref / "sets" / new_hash)
    (ref / "sets" / new_hash / "manifest.json").write_bytes(raw)
    PF.activate(ref, new_hash)
    return new_hash


def test_unterminated_last_line_is_a_rows_mismatch(ref):
    set_hash = PF.build_set(ref)
    path = _file(ref, set_hash, "dist/references.jsonl")
    data = path.read_bytes()[:-1]  # last line without "\n": the newline count is one short of the rows
    path.write_bytes(data)

    def patch(manifest):
        entry = manifest["files"][2]
        entry.update(bytes=len(data), sha256=K.sha256_hex(data), kbase_sha256="sha256:" + K.sha256_hex(data))

    _rehome(ref, set_hash, patch)
    _invalid()
    with pytest.raises(K.FormatError):  # the fixture (like the importer) never records such a file
        PF.build_set(ref, file_bytes={"references": data}, imported_at="2026-10-10T00:00:07Z")


def test_file_symlink_escaping_the_set(ref, tmp_path):
    set_hash = PF.build_set(ref)
    path = _file(ref, set_hash, "dist/moves.jsonl")
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    _invalid()


def test_file_symlink_inside_the_set_is_refused_by_o_nofollow(ref):
    set_hash = PF.build_set(ref)
    path = _file(ref, set_hash, "dist/moves.jsonl")
    copy = path.parent / "copy.jsonl"
    copy.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(copy.name)
    _invalid()


def test_directory_symlink_escaping_the_set(ref, tmp_path):
    set_hash = PF.build_set(ref)
    folder = ref / "sets" / set_hash / "files" / "pubmed"
    outside = tmp_path / "outside_pubmed"
    folder.rename(outside)
    folder.symlink_to(outside, target_is_directory=True)
    _invalid()


def test_symlinked_set_folder_is_refused(ref, tmp_path):
    set_hash = PF.build_set(ref)
    elsewhere = tmp_path / "elsewhere"
    (ref / "sets" / set_hash).rename(elsewhere)
    (ref / "sets" / set_hash).symlink_to(elsewhere, target_is_directory=True)
    _invalid()


def test_manifest_and_pointer_symlinks_are_refused(ref, tmp_path):
    set_hash = PF.build_set(ref)
    path = ref / "sets" / set_hash / "manifest.json"
    outside = tmp_path / "manifest.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    _invalid()
    path.unlink()
    path.write_bytes(outside.read_bytes())
    ps.pin_active_set()
    pointer = ref / "active.json"
    moved = tmp_path / "active.json"
    moved.write_bytes(pointer.read_bytes())
    pointer.unlink()
    pointer.symlink_to(moved)
    _invalid()


def test_oversized_file_is_refused(ref, monkeypatch):
    PF.build_set(ref)
    monkeypatch.setattr(K, "MAX_FILE_BYTES", 64)
    _invalid()


# ------------------------------------------------------------------------------------------- verification cache

def test_hashes_verified_once_per_set_and_again_after_a_stat_change(ref, monkeypatch):
    first = PF.build_set(ref)
    calls: list[str] = []
    real = ps._verify_file

    def counting(path, entry):
        calls.append(path.name)
        return real(path, entry)

    monkeypatch.setattr(ps, "_verify_file", counting)
    ps.pin_active_set()
    assert len(calls) == 4
    ps.pin_active_set()
    ps.capability()
    assert len(calls) == 4  # cached: same set and the same file stat identity
    second = PF.build_set(ref, imported_at="2026-10-10T00:00:02Z")
    assert ps.pin_active_set().set_hash == second
    assert len(calls) == 8
    PF.activate(ref, first)
    ps.pin_active_set()
    assert len(calls) == 8  # the first set's verification is still cached (one entry per set folder)
    path = _file(ref, first, "dist/references.jsonl")
    data = path.read_bytes()
    path.unlink()
    path.write_bytes(data)  # same bytes, new stat identity -> verified again
    ps.pin_active_set()
    assert len(calls) == 12
    assert len(ps._VERIFIED) == 2


def test_failures_are_not_cached(ref):
    set_hash = PF.build_set(ref)
    path = _file(ref, set_hash, "dist/moves.jsonl")
    good = path.read_bytes()
    path.write_bytes(good.replace(b"SYNTHETIC", b"synthetic", 1))
    _invalid()
    assert ps._VERIFIED == {}
    path.write_bytes(good)
    assert ps.pin_active_set().set_hash == set_hash


def test_read_rechecks_the_bytes_of_a_pinned_file(ref):
    set_hash = PF.build_set(ref)
    pinned = ps.pin_active_set()
    path = _file(ref, set_hash, "dist/moves_flagged.jsonl")
    path.write_bytes(path.read_bytes().replace(b"SYNTHETIC", b"synthetic", 1))
    with pytest.raises(ps.SnapshotUnavailable) as err:
        pinned.read_bytes("dist/moves_flagged.jsonl")
    assert err.value.reason_code == "snapshot_invalid"


def test_read_refuses_a_file_replaced_by_a_symlink_after_pinning(ref, tmp_path):
    set_hash = PF.build_set(ref)
    pinned = ps.pin_active_set()
    path = _file(ref, set_hash, "dist/moves.jsonl")
    outside = tmp_path / "same.jsonl"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ps.SnapshotUnavailable) as err:
        pinned.read_bytes("dist/moves.jsonl")
    assert err.value.reason_code == "snapshot_invalid"


# ------------------------------------------------------------------------------------------- one call = one set

def test_pinned_set_survives_a_concurrent_swap(ref):
    first = PF.build_set(ref)
    pinned = ps.pin_active_set()
    records = PF.t2_records()
    second = PF.build_set(ref, moves=records["moves"][:1], imported_at="2026-10-10T00:00:03Z")
    assert ps.pin_active_set().set_hash == second
    assert pinned.set_hash == first
    assert pinned.read_bytes("dist/moves.jsonl") == PF.t2_bytes()["moves"]
    assert first in str(pinned.file_path("dist/moves.jsonl"))


def test_pin_reads_the_active_pointer_once(ref, monkeypatch):
    first = PF.build_set(ref)
    second = PF.build_set(ref, imported_at="2026-10-10T00:00:04Z", activate_set=False)
    real = ps._read_pointer
    reads = {"n": 0}

    def swap_after_read(root):
        value = real(root)
        reads["n"] += 1
        PF.activate(ref, second)  # a re-import lands right after the pointer read
        return value

    monkeypatch.setattr(ps, "_read_pointer", swap_after_read)
    PF.activate(ref, first)
    pinned = ps.pin_active_set()
    assert reads["n"] == 1
    assert pinned.set_hash == first
    assert all(first in str(pinned.file_path(name)) for name in NAMES)
    assert pinned.read_bytes("dist/moves.jsonl") == PF.t2_bytes()["moves"]


def test_many_threads_each_see_one_whole_set(ref):
    tags = {}
    base = PF.t2_records()["moves"]

    def build(i):
        moves = base[: 1 + i % 5]
        set_hash = PF.build_set(ref, moves=moves, imported_at=f"2026-10-10T00:01:{i:02d}Z", activate_set=False)
        tags[set_hash] = len(moves)
        PF.activate(ref, set_hash)

    build(0)
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                pinned = ps.pin_active_set()
                data = pinned.read_bytes("dist/moves.jsonl")
                assert data.count(b"\n") == tags[pinned.set_hash]
                assert pinned.manifest["files"][0]["rows"] == tags[pinned.set_hash]
            except BaseException as exc:  # noqa: BLE001 - collected for the main thread
                errors.append(exc)
                return

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for i in range(1, 10):
            build(i)
    finally:
        stop.set()
        for t in threads:
            t.join()
    assert errors == []


# ------------------------------------------------------------------------------------------- module boundary

def test_module_is_standard_library_plus_the_constants_module_only():
    source = Path(ps.__file__).read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
    assert {name for name in imported if name.startswith(".")} <= {"."}
    local = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level
             for alias in node.names}
    assert local == {"precedent_constants"}
    assert {name.split(".")[0] for name in imported if not name.startswith(".")} - {"__future__"} <= set(
        sys.stdlib_module_names)
    assert not {name.split(".")[0] for name in imported} & {"socket", "urllib", "http", "httpx", "requests", "ssl",
                                                            "subprocess", "mw"}
    for banned in ("import socket", "urllib", "httpx", "http.client", "subprocess", "raise_limits", "limit_approval",
                   "../kbase", "kbase_kinase/", ".git"):
        assert banned not in source
    assert os.path.basename(ps.__file__) == "precedent_snapshots.py"
