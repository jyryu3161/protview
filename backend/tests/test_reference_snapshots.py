"""Server-side reference snapshot set reading (mw.reference_snapshots).

Every reference folder here is a synthetic FIXTURE written in pytest tmp_path in the importer's layout; it is not
real UniProt/SIFTS/KLIFS data and never touches ../kbase_kinase.
"""

import hashlib
import json
import threading
from pathlib import Path

import pytest

from mw import reference_snapshots as rs

REPO = Path(__file__).resolve().parents[2]

SOURCE_FILES = {"uniprot": [("entries.jsonl", "product")],
                "sifts": [("residues.jsonl", "product"), ("segments.jsonl", "product")],
                "klifs": [("kinases.jsonl", "product"), ("match_residues.jsonl", "comparison_only")]}


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _write_set(root: Path, tag: str, *, activate: bool = True) -> str:
    """Write one FIXTURE set exactly as scripts/import_reference_snapshots.py lays it out; return its hash."""
    staging = root / "sets" / f".staging-{tag}"
    sources = []
    for source, files in SOURCE_FILES.items():
        date = "2026-01-05"
        entries = []
        for name, use in files:
            data = f'{{"fixture":"{tag}-{source}-{name}"}}\n{{"fixture":2}}\n'.encode()
            rel = f"{source}/{date}/{name}"
            path = staging / "files" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            entries.append({"name": name, "path": rel, "sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data), "rows": 2, "use": use})
        sources.append({"source": source, "snapshot_id": f"SNAP-{source}-{date}", "date": date,
                        "version_hint": "2026_03" if source == "uniprot" else None,
                        "license": {"uniprot": "CC-BY-4.0", "sifts": "EMBL-EBI-terms", "klifs": "none-stated"}[source],
                        "origin": "kbase_kinase processed snapshot", "url_count": 2,
                        "raw_sha256": ["sha256:" + "c" * 64], "files": entries})
    manifest = {"schema": "reference_snapshot_set@1", "imported_at": f"2026-09-30T00:00:00.{tag}Z",
                "kbase_repo": {"commit": "0" * 40, "dirty": False}, "sources": sources}
    raw = _canonical(manifest)
    (staging / "manifest.json").write_bytes(raw)
    set_hash = hashlib.sha256(raw).hexdigest()
    staging.rename(root / "sets" / set_hash)
    if activate:
        _activate(root, set_hash)
    return set_hash


def _activate(root: Path, set_hash: str) -> None:
    tmp = root / "active.json.tmp"
    tmp.write_bytes(_canonical({"schema": "reference_active@1", "set_hash": set_hash}))
    tmp.replace(root / "active.json")


@pytest.fixture
def ref(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    return root


# --- location -----------------------------------------------------------------------------------------

def test_default_dir_is_project_deps(monkeypatch):
    monkeypatch.delenv(rs.ENV_VAR, raising=False)
    assert rs.reference_dir() == REPO / ".deps" / "reference"


def test_env_var_selects_dir(ref):
    assert rs.reference_dir() == ref


# --- not installed ------------------------------------------------------------------------------------

def test_not_installed_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(rs.ENV_VAR, str(tmp_path / "absent"))
    cap = rs.capability()
    assert cap == {"available": False, "reason_code": "not_installed", "reason": rs.REASONS["not_installed"],
                   "set_hash": None, "sources": []}
    with pytest.raises(rs.SnapshotUnavailable) as err:
        rs.pin_active_set()
    assert err.value.reason_code == "not_installed"


def test_not_installed_when_no_active_pointer(ref):
    _write_set(ref, "000001", activate=False)
    assert rs.capability()["reason_code"] == "not_installed"


# --- available ----------------------------------------------------------------------------------------

def test_available_capability_and_pinned_access(ref):
    set_hash = _write_set(ref, "000001")
    cap = rs.capability()
    assert cap["available"] is True and cap["reason_code"] is None and cap["reason"] is None
    assert cap["set_hash"] == set_hash
    assert [s["source"] for s in cap["sources"]] == ["uniprot", "sifts", "klifs"]
    assert cap["sources"][0] == {"source": "uniprot", "snapshot_id": "SNAP-uniprot-2026-01-05", "date": "2026-01-05",
                                 "version_hint": "2026_03", "license": "CC-BY-4.0",
                                 "origin": "kbase_kinase processed snapshot"}
    pinned = rs.pin_active_set()
    assert pinned.set_hash == set_hash
    assert pinned.manifest_bytes == (ref / "sets" / set_hash / "manifest.json").read_bytes()
    assert pinned.source("sifts")["license"] == "EMBL-EBI-terms"
    rows = list(pinned.iter_jsonl("uniprot", "entries.jsonl"))
    assert rows == [{"fixture": "000001-uniprot-entries.jsonl"}, {"fixture": 2}]
    assert pinned.file_path("sifts", "segments.jsonl") == ref / "sets" / set_hash / "files/sifts/2026-01-05/segments.jsonl"


def test_comparison_only_file_needs_explicit_opt_in(ref):
    _write_set(ref, "000001")
    pinned = rs.pin_active_set()
    with pytest.raises(rs.SnapshotAccessError):
        pinned.file_path("klifs", "match_residues.jsonl")
    with pytest.raises(rs.SnapshotAccessError):
        list(pinned.iter_jsonl("klifs", "match_residues.jsonl"))
    assert pinned.file_path("klifs", "match_residues.jsonl", allow_comparison_only=True).is_file()


def test_unknown_source_or_file_refused(ref):
    _write_set(ref, "000001")
    pinned = rs.pin_active_set()
    with pytest.raises(rs.SnapshotAccessError):
        pinned.source("chembl")
    with pytest.raises(rs.SnapshotAccessError):
        pinned.file_path("sifts", "entries.jsonl")


# --- snapshot_invalid ---------------------------------------------------------------------------------

def _invalid(ref) -> None:
    cap = rs.capability()
    assert cap == {"available": False, "reason_code": "snapshot_invalid", "reason": rs.REASONS["snapshot_invalid"],
                   "set_hash": None, "sources": []}
    with pytest.raises(rs.SnapshotUnavailable) as err:
        rs.pin_active_set()
    assert err.value.reason_code == "snapshot_invalid"


def test_file_hash_mismatch_is_invalid(ref):
    set_hash = _write_set(ref, "000001")
    path = ref / "sets" / set_hash / "files/sifts/2026-01-05/residues.jsonl"
    data = path.read_bytes()
    path.write_bytes(data.replace(b"000001", b"999999"))  # same length, different bytes
    _invalid(ref)


def test_missing_file_is_invalid(ref):
    set_hash = _write_set(ref, "000001")
    (ref / "sets" / set_hash / "files/klifs/2026-01-05/kinases.jsonl").unlink()
    _invalid(ref)


def test_manifest_edit_is_invalid(ref):
    set_hash = _write_set(ref, "000001")
    path = ref / "sets" / set_hash / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["sources"][0]["license"] = "public-domain"
    path.write_bytes(_canonical(manifest))
    _invalid(ref)


def test_pointer_to_missing_set_is_invalid(ref):
    _activate(ref, "f" * 64)
    _invalid(ref)


@pytest.mark.parametrize("pointer", [b"{not json", b"[]", b'{"schema":"reference_active@2","set_hash":"' + b"a" * 64
                                     + b'"}', b'{"schema":"reference_active@1","set_hash":"../x"}'])
def test_malformed_pointer_is_invalid(ref, pointer):
    (ref / "active.json").write_bytes(pointer)
    _invalid(ref)


def _rewrite(ref, set_hash, mutate) -> str:
    path = ref / "sets" / set_hash / "manifest.json"
    manifest = json.loads(path.read_bytes())
    mutate(manifest)
    raw = _canonical(manifest)
    new_hash = hashlib.sha256(raw).hexdigest()
    (ref / "sets" / set_hash).rename(ref / "sets" / new_hash)
    (ref / "sets" / new_hash / "manifest.json").write_bytes(raw)
    _activate(ref, new_hash)
    return new_hash


@pytest.mark.parametrize("mutate", [
    lambda m: m.update(schema="reference_snapshot_set@2"),
    lambda m: m.update(extra=1),
    lambda m: m["sources"].pop(),
    lambda m: m["sources"].append(dict(m["sources"][0])),
    lambda m: m["sources"][0]["files"][0].update(path="../../../etc/passwd"),
    lambda m: m["sources"][0]["files"][0].update(path="/abs/entries.jsonl"),
    lambda m: m["sources"][1]["files"].pop(),
    lambda m: m["sources"][2]["files"][1].update(use="product"),
    lambda m: m["sources"][0]["files"][0].update(sha256="sha256:" + "0" * 64),
    lambda m: m["sources"][0].update(license=None),
])
def test_unknown_or_malformed_manifest_is_invalid(ref, mutate):
    _rewrite(ref, _write_set(ref, "000001"), mutate)
    _invalid(ref)


def test_non_canonical_manifest_bytes_are_invalid(ref):
    set_hash = _write_set(ref, "000001")
    path = ref / "sets" / set_hash / "manifest.json"
    raw = json.dumps(json.loads(path.read_bytes()), indent=1).encode()
    new_hash = hashlib.sha256(raw).hexdigest()
    (ref / "sets" / set_hash).rename(ref / "sets" / new_hash)
    (ref / "sets" / new_hash / "manifest.json").write_bytes(raw)
    _activate(ref, new_hash)
    _invalid(ref)


# --- verification cache -------------------------------------------------------------------------------

def test_hashes_verified_once_per_set_and_again_after_swap(ref, monkeypatch):
    first = _write_set(ref, "000001")
    calls: list[str] = []
    real = rs._file_sha256

    def counting(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(rs, "_file_sha256", counting)
    rs.pin_active_set()
    assert len(calls) == 5
    rs.pin_active_set()
    rs.capability()
    assert len(calls) == 5  # cached for the same set
    second = _write_set(ref, "000002")
    assert rs.pin_active_set().set_hash == second
    assert len(calls) == 10  # the new active set is verified on first use
    _activate(ref, first)
    rs.pin_active_set()
    assert len(calls) == 10  # the earlier verified set is still cached


def test_verified_cache_keeps_only_the_latest_entry_per_set_folder(ref):
    set_hash = _write_set(ref, "000001")
    rs.pin_active_set()
    path = ref / "sets" / set_hash / "files/uniprot/2026-01-05/entries.jsonl"
    for _ in range(3):  # same bytes, new stat identity each time -> re-verified
        data = path.read_bytes()
        path.unlink()
        path.write_bytes(data)
        rs.pin_active_set()
    assert len(rs._VERIFIED) == 1
    second = _write_set(ref, "000002")
    assert rs.pin_active_set().set_hash == second
    assert len(rs._VERIFIED) == 2  # one per set folder


def test_in_place_tamper_after_cache_is_detected(ref):
    set_hash = _write_set(ref, "000001")
    rs.pin_active_set()
    path = ref / "sets" / set_hash / "files/uniprot/2026-01-05/entries.jsonl"
    path.write_bytes(path.read_bytes() + b'{"fixture":3}\n')
    _invalid(ref)


def test_read_rechecks_bytes_of_pinned_file(ref):
    set_hash = _write_set(ref, "000001")
    pinned = rs.pin_active_set()
    path = ref / "sets" / set_hash / "files/uniprot/2026-01-05/entries.jsonl"
    path.write_bytes(path.read_bytes().replace(b"000001", b"999999"))
    with pytest.raises(rs.SnapshotUnavailable) as err:
        list(pinned.iter_jsonl("uniprot", "entries.jsonl"))
    assert err.value.reason_code == "snapshot_invalid"


# --- pinning across a concurrent re-import ------------------------------------------------------------

def test_pinned_set_survives_a_concurrent_swap(ref):
    first = _write_set(ref, "000001")
    pinned = rs.pin_active_set()
    second = _write_set(ref, "000002")  # re-import swaps the active pointer
    assert rs.pin_active_set().set_hash == second
    assert pinned.set_hash == first
    assert next(pinned.iter_jsonl("uniprot", "entries.jsonl")) == {"fixture": "000001-uniprot-entries.jsonl"}
    assert first in str(pinned.file_path("sifts", "residues.jsonl"))


def test_pin_reads_active_pointer_once(ref, monkeypatch):
    first = _write_set(ref, "000001")
    second = _write_set(ref, "000002", activate=False)
    real = rs._read_pointer
    reads = {"n": 0}

    def swap_after_read(root):
        value = real(root)
        reads["n"] += 1
        _activate(ref, second)  # a re-import lands right after the pointer read
        return value

    monkeypatch.setattr(rs, "_read_pointer", swap_after_read)
    _activate(ref, first)
    pinned = rs.pin_active_set()
    assert reads["n"] == 1
    assert pinned.set_hash == first
    assert all(first in str(pinned.file_path(s, n, allow_comparison_only=True))
               for s, files in SOURCE_FILES.items() for n, _u in files)


def test_many_threads_each_see_one_whole_set(ref):
    hashes = [_write_set(ref, "000001")]
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                pinned = rs.pin_active_set()
                tags = {next(pinned.iter_jsonl(s, n))["fixture"].split("-")[0]
                        for s, files in SOURCE_FILES.items() for n, u in files if u == "product"}
                assert len(tags) == 1
            except BaseException as exc:  # noqa: BLE001 - collected for the main thread
                errors.append(exc)
                return

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for i in range(2, 12):
            hashes.append(_write_set(ref, f"{i:06d}"))
    finally:
        stop.set()
        for t in threads:
            t.join()
    assert errors == []


def test_module_does_not_touch_kbase_or_network():
    source = Path(rs.__file__).read_text()
    for banned in ("kbase_kinase/", "../kbase", "import socket", "urllib", "httpx", "http.client"):
        assert banned not in source
    assert "reference_snapshots" not in "".join(p.read_text() for p in (Path(rs.__file__).parent / "core").glob("*.py"))
