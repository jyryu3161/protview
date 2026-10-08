"""Server-side M26 reaction reference set pinning (mw.reaction_snapshots).

Every reference folder is a LABELLED SYNTHETIC FIXTURE written in pytest tmp_path with ``reaction_fixture.build_set``
(the importer's layout); no real M-CSA / UniProt / Rhea data, no network, no ``.deps`` folder is touched.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import threading
from pathlib import Path

import pytest
import reaction_fixture as RF

from mw import reaction_knowledge_constants as K
from mw import reaction_snapshots as rs

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def ref(tmp_path, monkeypatch):
    root = tmp_path / "reaction_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    return root


def _invalid(root=None):
    with pytest.raises(rs.SnapshotUnavailable) as err:
        rs.pin_active_set(root)
    assert err.value.reason_code == "snapshot_invalid"
    assert err.value.reason == K.SNAPSHOT_REASONS["snapshot_invalid"]


def _file(root: Path, set_hash: str, rel: str) -> Path:
    return root / "sets" / set_hash / rel


# ------------------------------------------------------------------------------------------- location

def test_default_dir_is_project_deps_and_separate_from_m15(monkeypatch):
    monkeypatch.delenv(K.ENV_VAR, raising=False)
    monkeypatch.setenv("MW_REFERENCE_DIR", "/somewhere/else")  # the M15 variable never moves this family
    assert rs.reference_dir() == REPO / ".deps" / "reaction_reference"


def test_env_var_selects_dir_and_relative_values_resolve_against_the_repo(ref, monkeypatch):
    assert rs.reference_dir() == ref
    monkeypatch.setenv(K.ENV_VAR, "runs/qa/reaction_reference")
    assert rs.reference_dir() == REPO / "runs" / "qa" / "reaction_reference"


# ------------------------------------------------------------------------------------------- not installed

def test_not_installed_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(K.ENV_VAR, str(tmp_path / "absent"))
    assert rs.capability() == {"available": False, "reason_code": "not_installed",
                               "reason": K.SNAPSHOT_REASONS["not_installed"], "set_hash": None, "sources": []}
    with pytest.raises(rs.SnapshotUnavailable) as err:
        rs.pin_active_set()
    assert err.value.reason_code == "not_installed"


def test_not_installed_when_no_active_pointer(ref):
    RF.build_set(ref, activate_set=False)
    with pytest.raises(rs.SnapshotUnavailable) as err:
        rs.pin_active_set()
    assert err.value.reason_code == "not_installed"


# ------------------------------------------------------------------------------------------- ok

def test_pin_ok_and_bound_accessors(ref):
    set_hash = RF.build_set(ref)
    pinned = rs.pin_active_set()
    assert pinned.set_hash == set_hash
    assert pinned.set_dir == ref / "sets" / set_hash
    assert pinned.manifest_bytes == (ref / "sets" / set_hash / "manifest.json").read_bytes()
    manifest = pinned.manifest
    manifest["schema"] = "edited"
    assert pinned.manifest["schema"] == K.SET_SCHEMA  # a copy each time
    rows = RF.synthetic_rows()
    for source in K.SOURCES:
        (name,) = K.SOURCE_FILES[source]
        assert pinned.file_path(source, name) == ref / "sets" / set_hash / "files" / source / name
        assert pinned.read_bytes(source, name) == K.encode_jsonl(source, rows[source])
    assert pinned.source("rhea")["license"] == "CC-BY-4.0"
    assert pinned.summary() == [{"source": s, "date": RF.DATE, "license": "CC-BY-4.0", "origin": "public server import",
                                 "rows": len(rows[s])} for s in K.SOURCES]
    assert len(pinned.files_identity) == 4  # three processed files + the request log
    cap = rs.capability()
    assert cap == {"available": True, "reason_code": None, "reason": None, "set_hash": set_hash,
                   "sources": pinned.summary()}


def test_unknown_source_or_file_refused(ref):
    RF.build_set(ref)
    pinned = rs.pin_active_set()
    with pytest.raises(rs.SnapshotAccessError):
        pinned.read_bytes("cofactor", "entries.jsonl")
    with pytest.raises(rs.SnapshotAccessError):
        pinned.read_bytes("mcsa", "residues.jsonl")
    with pytest.raises(rs.SnapshotAccessError):
        pinned.source("kbase")


# ------------------------------------------------------------------------------------------- snapshot_invalid

def test_tampered_file_same_size(ref):
    set_hash = RF.build_set(ref)
    path = _file(ref, set_hash, "files/rhea/reactions.jsonl")
    data = path.read_bytes()
    path.write_bytes(data.replace(b"synthetic", b"SYNTHETIC", 1))
    _invalid()


def test_tampered_file_after_a_cached_pin(ref):
    set_hash = RF.build_set(ref)
    rs.pin_active_set()
    path = _file(ref, set_hash, "files/mcsa/entries.jsonl")
    path.write_bytes(path.read_bytes() + b"\n")
    _invalid()


def test_tampered_request_log(ref):
    set_hash = RF.build_set(ref)
    path = _file(ref, set_hash, K.REQUEST_LOG_PATH)
    path.write_bytes(path.read_bytes().replace(b'"status":200', b'"status":201', 1))
    _invalid()


def test_missing_file(ref):
    set_hash = RF.build_set(ref)
    _file(ref, set_hash, "files/uniprot_function/entries.jsonl").unlink()
    _invalid()


def test_tampered_manifest_bytes(ref):
    set_hash = RF.build_set(ref)
    path = _file(ref, set_hash, "manifest.json")
    path.write_bytes(path.read_bytes().replace(b"2026-10-08T00:00:00Z", b"2026-10-08T00:00:01Z"))
    _invalid()


def test_pointer_to_a_missing_set_or_malformed_pointer(ref):
    RF.build_set(ref)
    for pointer in (b'{"schema":"reaction_active@1","set_hash":"' + b"0" * 64 + b'"}',
                    b'{"schema":"reference_active@1","set_hash":"' + b"0" * 64 + b'"}',
                    b'{"schema":"reaction_active@1"}', b"not json", b"[]"):
        (ref / "active.json").write_bytes(pointer)
        _invalid()


@pytest.mark.parametrize("field, delta", [("bytes", 1), ("rows", 1), ("sha256", None)])
def test_manifest_with_wrong_size_rows_or_hash(ref, field, delta):
    def patch(manifest):
        entry = manifest["sources"][1]["files"][0]
        entry[field] = "0" * 64 if delta is None else entry[field] + delta

    RF.build_set(ref, manifest_patch=patch)
    _invalid()


def test_unknown_schema_with_a_consistent_hash(ref):
    RF.build_set(ref, manifest_patch=lambda m: m.update(schema="reaction_reference_set@2"), validate=False)
    _invalid()


def test_non_canonical_manifest_with_a_consistent_hash(ref):
    set_hash = RF.build_set(ref)
    manifest = json.loads(_file(ref, set_hash, "manifest.json").read_bytes())
    pretty = json.dumps(manifest, indent=1, sort_keys=True).encode()
    new_hash = K.set_hash_of(pretty)
    (ref / "sets" / set_hash).rename(ref / "sets" / new_hash)
    _file(ref, new_hash, "manifest.json").write_bytes(pretty)
    RF.activate(ref, new_hash)
    _invalid()


def test_unterminated_last_line_is_a_rows_mismatch(ref):
    rows = RF.synthetic_rows()
    data = K.encode_jsonl("rhea", rows["rhea"])[:-1]  # last line without "\n": line count differs from rows
    RF.build_set(ref, file_bytes={"rhea": data},
                 manifest_patch=lambda m: m["sources"][2]["files"][0].update(rows=len(rows["rhea"])))
    _invalid()


def test_file_symlink_escaping_the_set(ref, tmp_path):
    set_hash = RF.build_set(ref)
    path = _file(ref, set_hash, "files/mcsa/entries.jsonl")
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    _invalid()


def test_file_symlink_inside_the_set_is_refused_by_o_nofollow(ref):
    set_hash = RF.build_set(ref)
    path = _file(ref, set_hash, "files/mcsa/entries.jsonl")
    copy = _file(ref, set_hash, "files/mcsa/copy.jsonl")
    copy.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(copy.name)
    _invalid()


def test_directory_symlink_escaping_the_set(ref, tmp_path):
    set_hash = RF.build_set(ref)
    folder = _file(ref, set_hash, "files/rhea")
    outside = tmp_path / "outside_rhea"
    folder.rename(outside)
    folder.symlink_to(outside, target_is_directory=True)
    _invalid()


def test_symlinked_set_folder_is_refused(ref, tmp_path):
    set_hash = RF.build_set(ref)
    elsewhere = tmp_path / "elsewhere"
    (ref / "sets" / set_hash).rename(elsewhere)
    (ref / "sets" / set_hash).symlink_to(elsewhere, target_is_directory=True)
    _invalid()


def test_manifest_symlink_is_refused(ref, tmp_path):
    set_hash = RF.build_set(ref)
    path = _file(ref, set_hash, "manifest.json")
    outside = tmp_path / "manifest.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    _invalid()


def test_oversized_file_is_refused(ref, monkeypatch):
    RF.build_set(ref)
    monkeypatch.setattr(K, "MAX_FILE_BYTES", 64)
    _invalid()


# ------------------------------------------------------------------------------------------- verification cache

def test_hashes_verified_once_per_set_and_again_after_a_stat_change(ref, monkeypatch):
    first = RF.build_set(ref)
    calls: list[str] = []
    real = rs._verify_file

    def counting(path, entry):
        calls.append(path.name)
        return real(path, entry)

    monkeypatch.setattr(rs, "_verify_file", counting)
    rs.pin_active_set()
    assert len(calls) == 4
    rs.pin_active_set()
    rs.capability()
    assert len(calls) == 4  # cached: same set and the same file stat identity
    second = RF.build_set(ref, imported_at="2026-10-08T00:00:02Z")
    assert rs.pin_active_set().set_hash == second
    assert len(calls) == 8
    RF.activate(ref, first)
    rs.pin_active_set()
    assert len(calls) == 8  # the first set's verification is still cached (one entry per set folder)
    path = _file(ref, first, "files/rhea/reactions.jsonl")
    data = path.read_bytes()
    path.unlink()
    path.write_bytes(data)  # same bytes, new stat identity -> verified again
    rs.pin_active_set()
    assert len(calls) == 12
    assert len(rs._VERIFIED) == 2


def test_failures_are_not_cached(ref):
    set_hash = RF.build_set(ref)
    path = _file(ref, set_hash, "files/rhea/reactions.jsonl")
    good = path.read_bytes()
    path.write_bytes(good.replace(b"synthetic", b"SYNTHETIC", 1))
    _invalid()
    assert rs._VERIFIED == {}
    path.write_bytes(good)
    assert rs.pin_active_set().set_hash == set_hash


def test_read_rechecks_the_bytes_of_a_pinned_file(ref):
    set_hash = RF.build_set(ref)
    pinned = rs.pin_active_set()
    path = _file(ref, set_hash, "files/mcsa/entries.jsonl")
    path.write_bytes(path.read_bytes().replace(b"SYNTHETIC", b"synthetic", 1))
    with pytest.raises(rs.SnapshotUnavailable) as err:
        pinned.read_bytes("mcsa", "entries.jsonl")
    assert err.value.reason_code == "snapshot_invalid"


# ------------------------------------------------------------------------------------------- one call = one set

def test_pinned_set_survives_a_concurrent_swap(ref):
    first = RF.build_set(ref)
    pinned = rs.pin_active_set()
    rows = RF.synthetic_rows()
    rows["rhea"] = rows["rhea"][:1]
    second = RF.build_set(ref, rows=rows, imported_at="2026-10-08T00:00:03Z")
    assert rs.pin_active_set().set_hash == second
    assert pinned.set_hash == first
    assert pinned.read_bytes("rhea", "reactions.jsonl") == K.encode_jsonl("rhea", RF.synthetic_rows()["rhea"])
    assert first in str(pinned.file_path("rhea", "reactions.jsonl"))


def test_pin_reads_the_active_pointer_once(ref, monkeypatch):
    first = RF.build_set(ref)
    second = RF.build_set(ref, imported_at="2026-10-08T00:00:04Z", activate_set=False)
    real = rs._read_pointer
    reads = {"n": 0}

    def swap_after_read(root):
        value = real(root)
        reads["n"] += 1
        RF.activate(ref, second)  # a re-import lands right after the pointer read
        return value

    monkeypatch.setattr(rs, "_read_pointer", swap_after_read)
    RF.activate(ref, first)
    pinned = rs.pin_active_set()
    assert reads["n"] == 1
    assert pinned.set_hash == first
    assert all(first in str(pinned.file_path(s, K.SOURCE_FILES[s][0])) for s in K.SOURCES)


def test_many_threads_each_see_one_whole_set(ref):
    tags = {}
    base = RF.synthetic_rows()

    def build(i):
        rows = RF.synthetic_rows()
        rows["rhea"] = base["rhea"][: 1 + i % 5]
        set_hash = RF.build_set(ref, rows=rows, imported_at=f"2026-10-08T00:01:{i:02d}Z", activate_set=False)
        tags[set_hash] = len(rows["rhea"])
        RF.activate(ref, set_hash)

    build(0)
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                pinned = rs.pin_active_set()
                data = pinned.read_bytes("rhea", "reactions.jsonl")
                assert data.count(b"\n") == tags[pinned.set_hash]
                assert pinned.summary()[2]["rows"] == tags[pinned.set_hash]
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

def test_module_is_standard_library_only_and_never_networks():
    source = Path(rs.__file__).read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
    assert {name for name in imported if name.startswith(".")} <= {"."}  # only the constants module
    local = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level
             for alias in node.names}
    assert local == {"reaction_knowledge_constants"}
    assert {name.split(".")[0] for name in imported if not name.startswith(".")} - {"__future__"} <= set(
        sys.stdlib_module_names)
    assert not {name.split(".")[0] for name in imported} & {"socket", "urllib", "http", "httpx", "requests", "ssl"}
    for banned in ("import socket", "urllib", "httpx", "http.client", "raise_limits", "limit_approval",
                   "../kbase"):
        assert banned not in source
    assert os.path.basename(rs.__file__) == "reaction_snapshots.py"
