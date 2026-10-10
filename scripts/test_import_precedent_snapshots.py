"""Tests for scripts/import_precedent_snapshots.py (M27 T3, spec 4).

Every kbase-like folder here is a SYNTHETIC FIXTURE (합성) built in pytest tmp_path from the committed T2 synthetic
files and ``backend/tests/precedent_fixture.py`` (provenance:
backend/tests/fixtures/precedent/t3/SYNTHETIC-PROVENANCE-t3.md). No real kbase_kinase record is read or written and
the real checkout is never touched. No network is used: an autouse guard makes every socket connection and name
lookup fail, and the child-process test blocks sockets and the network modules.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import import_precedent_snapshots as imp

REPO = Path(__file__).resolve().parents[1]
SCRIPT = Path(imp.__file__).resolve()
CONSTANTS = REPO / "backend" / "mw" / "precedent_constants.py"


def _load_fixture():
    """``backend/tests/precedent_fixture.py`` (T2's synthetic record factory), loaded once under its own name."""
    name = "precedent_fixture"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / "backend" / "tests" / "precedent_fixture.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


PF = _load_fixture()
NOW = dt.datetime(2026, 10, 10, 1, 2, 3, tzinfo=dt.timezone.utc)
LATER = dt.datetime(2026, 10, 10, 1, 2, 8, tzinfo=dt.timezone.utc)
COMMIT_DATE = "2026-09-21T00:05:28+09:00"
KB_VERSION = "kbv1:synthetic-t3"
SOURCE_SNAPSHOTS = ["SNAP-synthetic-t3-uniprot-2026-09-01", "SNAP-synthetic-t3-sifts-2026-09-02"]
PUBMED_OLD, PUBMED_NEW = "2026-09-01", "2026-09-30"
PUBMED_LICENSE = "synthetic-t3-license"
DIST = {"moves": "moves.jsonl", "moves_flagged": "moves_flagged.jsonl", "references": "references.jsonl"}
PINS = {"schema_version": "1", "effect_rules_version": "1",
        "vocab_version": ("contact_class@1+goal@1+interaction@1+site@2+tactic@1+target_aliases@2:"
                          "024a47d5a62eab2a1ad1a52a0bb8f8e2740cbe3f8ad279bc6c62055c778cc11e")}


# --- no network ---------------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# --- synthetic kbase look-alike -----------------------------------------------------------------------------------

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@invalid", "GIT_COMMITTER_NAME": "fixture",
                "GIT_COMMITTER_EMAIL": "fixture@invalid", "GIT_AUTHOR_DATE": COMMIT_DATE,
                "GIT_COMMITTER_DATE": COMMIT_DATE})
    return env


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
                          env=git_env(root.parent), stdin=subprocess.DEVNULL, timeout=60)
    return proc.stdout


def git_commit(root: Path, *paths: str) -> str:
    git(root, "init", "-q")
    git(root, "add", *paths)
    git(root, "commit", "-q", "-m", "synthetic fixture")
    return git(root, "rev-parse", "HEAD").strip()


def build_kbase(root: Path, *, records: dict | None = None, file_bytes: dict | None = None,
                meta_patch=None, dist_patch=None, ref_patch=None, pubmed_rows: list | None = None,
                commit: tuple[str, ...] | None = ("dist", "ref")) -> Path:
    """A SYNTHETIC kbase_kinase look-alike: dist/ (three imported files + files that must not be copied +
    manifest.json), ref/manifest.json with two pubmed snapshots (the newer must win) and one other source.
    ``records`` (keys moves / moves_flagged / references) or ``file_bytes`` replace a file before the manifest is
    written (the manifest then matches the new bytes); the patches edit the manifests before they are written;
    ``commit`` names the paths of one git commit (None: no git repository)."""
    root.mkdir(parents=True)
    data = PF.t2_bytes()
    if pubmed_rows is not None:
        data["pubmed"] = PF.jsonl(pubmed_rows)
    for key, value in (records or {}).items():
        data[key] = PF.jsonl(value)
    data.update(file_bytes or {})
    dist = root / "dist"
    dist.mkdir()
    entries = []
    extra = {"structures.jsonl": b'{"synthetic": "not imported"}\n', "figures.jsonl": b'{"synthetic": "no"}\n',
             "CONTRACT.md": "합성 SYNTHETIC fixture contract (not imported)\n".encode()}
    for name, payload in [*((DIST[key], data[key]) for key in DIST), *extra.items()]:
        (dist / name).write_bytes(payload)
        entries.append({"bytes": len(payload), "name": name,
                        "records": payload.count(b"\n") if name.endswith(".jsonl") else None,
                        "sha256": "sha256:" + sha(payload)})
    meta = {**PINS, "source_snapshots": list(SOURCE_SNAPSHOTS), "counts": {"synthetic": 1},
            "consumer_agents_sha256": "sha256:" + "0" * 64}
    if meta_patch is not None:
        meta_patch(meta)
    manifest = {"files": entries, "kb_version": KB_VERSION, "meta": meta}
    if dist_patch is not None:
        dist_patch(manifest)
    (dist / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    ref = root / "ref"
    old = b"".join(data["pubmed"].splitlines(keepends=True)[:2])
    other = b'{"synthetic": "uniprot row, not imported"}\n'
    snapshots = []
    for source, date, rel, payload in (("pubmed", PUBMED_OLD, f"pubmed/{PUBMED_OLD}/documents.jsonl", old),
                                       ("pubmed", PUBMED_NEW, f"pubmed/{PUBMED_NEW}/documents.jsonl", data["pubmed"]),
                                       ("uniprot", "2026-10-05", "uniprot/2026-10-05/entries.jsonl", other)):
        (ref / rel).parent.mkdir(parents=True, exist_ok=True)
        (ref / rel).write_bytes(payload)
        snapshots.append({"snapshot_id": f"SNAP-{source}-{date}", "source": source, "date": date,
                          "license": PUBMED_LICENSE if source == "pubmed" else "synthetic-other", "version_hint": None,
                          "urls": [f"synthetic-url-{source}-{date}"], "raw_sha256": ["sha256:" + "a" * 64],
                          "files": [{"path": rel, "sha256": "sha256:" + sha(payload), "bytes": len(payload),
                                     "rows": payload.count(b"\n")}]})
    ref_manifest = {"snapshots": snapshots}
    if ref_patch is not None:
        ref_patch(ref_manifest)
    (ref / "manifest.json").write_text(json.dumps(ref_manifest, indent=2) + "\n")
    if commit is not None:
        git_commit(root, *commit)
    return root


def tree(root: Path) -> dict[str, object]:
    """Every path under ``root`` -> file bytes, "<dir>" or the link target."""
    if not os.path.lexists(root):
        return {}
    out: dict[str, object] = {}
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            out[rel] = "-> " + os.readlink(path)
        elif path.is_dir():
            out[rel] = "<dir>"
        else:
            out[rel] = path.read_bytes()
    return out


def run(kbase: Path, dest: Path, *, now=NOW, **kwargs):
    kwargs.setdefault("yes", True)
    return imp.run_import(kbase, dest, now=lambda: now, **kwargs)


def installed(tmp_path: Path) -> Path:
    """A destination that already holds one active set (imported from a good synthetic kbase at NOW)."""
    dest = tmp_path / "installed-dest"
    run(build_kbase(tmp_path / "good-kbase"), dest, now=NOW)
    return dest


def assert_refused(tmp_path: Path, kbase: Path, kind: str) -> imp.ImportRefused:
    """The import is refused with ``kind``: a fresh destination is not created, and an installed destination
    (active.json, the earlier set, every other byte) is unchanged."""
    fresh = tmp_path / "fresh-dest"
    with pytest.raises(imp.ImportRefused) as info:
        run(kbase, fresh, now=LATER)
    assert info.value.kind == kind, str(info.value)
    assert not os.path.lexists(fresh)
    dest = installed(tmp_path)
    before = tree(dest)
    with pytest.raises(imp.ImportRefused) as again:
        run(kbase, dest, now=LATER)
    assert again.value.kind == kind
    assert tree(dest) == before
    return info.value


def references_without_hash(data: bytes) -> int:
    return sum(1 for line in data.splitlines() if json.loads(line)["content_hash"] is None)


def expected_manifest(kbase: Path, *, imported_at: str, commit: str, dist_commit: str | None,
                      dist_commit_date: str | None, dirty: bool) -> dict:
    """The spec 3.2 manifest written out here independently of the script and of precedent_constants."""
    def entry(name: str, data: bytes) -> dict:
        digest = sha(data)
        return {"name": name, "path": f"files/{name}", "sha256": digest, "bytes": len(data),
                "rows": data.count(b"\n"), "kbase_sha256": "sha256:" + digest}

    data = {key: (kbase / "dist" / name).read_bytes() for key, name in DIST.items()}
    pubmed = (kbase / "ref" / "pubmed" / PUBMED_NEW / "documents.jsonl").read_bytes()
    without = references_without_hash(data["references"])
    return {
        "schema": "precedent_reference_set@1",
        "imported_at": imported_at,
        "importer_version": "precedent_import/1",
        "kbase": {"commit": commit, "dist_commit": dist_commit, "dist_commit_date": dist_commit_date, "dirty": dirty,
                  "kb_version": KB_VERSION, **PINS, "source_snapshots": SOURCE_SNAPSHOTS,
                  "origin": "kbase_kinase processed dist"},
        "files": [entry(f"dist/{DIST[key]}", data[key]) for key in DIST],
        "bibliography": {"snapshot_id": f"SNAP-pubmed-{PUBMED_NEW}", "date": PUBMED_NEW, "license": PUBMED_LICENSE,
                         "origin": "kbase_kinase processed ref/pubmed",
                         "file": entry(f"pubmed/{PUBMED_NEW}/documents.jsonl", pubmed)},
        "verification": {"records_hash_verified": {"moves": data["moves"].count(b"\n"),
                                                   "moves_flagged": data["moves_flagged"].count(b"\n"),
                                                   "references": data["references"].count(b"\n") - without},
                         "references_without_hash": without},
    }


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


# --- normal import --------------------------------------------------------------------------------------------------

def test_normal_import_installs_one_set_and_the_pointer(tmp_path, capsys):
    kbase = build_kbase(tmp_path / "kbase")
    head = git(kbase, "rev-parse", "HEAD").strip()
    kbase_before = {k: v for k, v in tree(kbase).items() if not k.startswith(".git")}
    dest = tmp_path / "dest"
    result = run(kbase, dest)

    raw_pointer = (dest / "active.json").read_bytes()
    assert raw_pointer == canonical({"schema": "precedent_active@1", "set_hash": result["set_hash"]})
    set_dir = dest / "sets" / result["set_hash"]
    raw = (set_dir / "manifest.json").read_bytes()
    assert sha(raw) == result["set_hash"]
    expected = expected_manifest(kbase, imported_at="2026-10-10T01:02:03Z", commit=head, dist_commit=head,
                                 dist_commit_date=COMMIT_DATE, dirty=False)
    assert raw == canonical(expected)  # canonical JSON, byte for byte, no trailing newline
    # Exactly the four files + the manifest, bytes copied as they are; nothing else from dist/ or ref/.
    files = {k: v for k, v in tree(set_dir).items() if v != "<dir>"}
    assert sorted(files) == sorted(["manifest.json", "files/dist/moves.jsonl", "files/dist/moves_flagged.jsonl",
                                    "files/dist/references.jsonl", f"files/pubmed/{PUBMED_NEW}/documents.jsonl"])
    for name in DIST.values():
        assert files[f"files/dist/{name}"] == (kbase / "dist" / name).read_bytes()
    assert files[f"files/pubmed/{PUBMED_NEW}/documents.jsonl"] == (
        kbase / "ref" / "pubmed" / PUBMED_NEW / "documents.jsonl").read_bytes()
    assert sorted(p.name for p in (dest / "sets").iterdir()) == [result["set_hash"]]  # no staging left
    assert sorted(p.name for p in dest.iterdir()) == ["active.json", "sets"]          # no temporary pointer left
    # The kbase checkout is only read.
    assert {k: v for k, v in tree(kbase).items() if not k.startswith(".git")} == kbase_before
    assert git(kbase, "status", "--porcelain") == ""

    assert result["set_hash"] == sha(raw) and result["set_dir"] == str(set_dir)
    assert result["imported_at"] == "2026-10-10T01:02:03Z"
    assert result["rows"] == {"dist/moves.jsonl": 7, "dist/moves_flagged.jsonl": 6, "dist/references.jsonl": 6,
                              f"pubmed/{PUBMED_NEW}/documents.jsonl": 5}
    assert result["verification"] == expected["verification"]
    assert result["verification"] == {"records_hash_verified": {"moves": 7, "moves_flagged": 6, "references": 6},
                                      "references_without_hash": 0}
    assert result["dirty"] is False
    out = capsys.readouterr().out
    for text in (str(set_dir), result["set_hash"], "dist/moves.jsonl 7", "dist/moves_flagged.jsonl 6",
                 "dist/references.jsonl 6", f"pubmed/{PUBMED_NEW}/documents.jsonl 5", "moves 7", "moves_flagged 6",
                 "references 6", "references_without_hash 0", "dirty: false"):
        assert text in out, text


def test_references_without_a_hash_are_counted_not_refused(tmp_path):
    references = PF.t2_records()["references"]
    references.append(PF.make_reference("REF-SYN-0099", "P0SYN1", hashed=False))
    dest = tmp_path / "dest"
    result = run(build_kbase(tmp_path / "kbase", records={"references": references}), dest)
    assert result["verification"] == {"records_hash_verified": {"moves": 7, "moves_flagged": 6, "references": 6},
                                      "references_without_hash": 1}
    manifest = json.loads((dest / "sets" / result["set_hash"] / "manifest.json").read_bytes())
    assert manifest["verification"] == result["verification"]


def test_the_installed_set_is_pinned_and_indexed_by_the_server_modules(tmp_path):
    from mw import kinase_precedents, precedent_snapshots

    dest = tmp_path / "dest"
    result = run(build_kbase(tmp_path / "kbase"), dest)
    pinned = precedent_snapshots.pin_active_set(dest)
    assert pinned.set_hash == result["set_hash"]
    assert pinned.manifest_bytes == (dest / "sets" / result["set_hash"] / "manifest.json").read_bytes()
    pinned2, index = kinase_precedents.pin_and_index(dest)
    assert pinned2.set_hash == result["set_hash"] and index.set_hash == result["set_hash"]
    assert index.summary["records"] == {"moves": 7, "moves_flagged": 6}
    assert index.summary["references"] == 6
    assert sorted(index.bibliography) == ["90000001", "90000005", "90000006"]
    assert precedent_snapshots.capability(dest)["available"] is True
    assert kinase_precedents.capability(dest)["set_hash"] == result["set_hash"]


def test_the_script_uses_the_server_constants_file_and_its_canonical_json():
    from mw import precedent_constants
    from mw.core.handles import canonical_json

    assert Path(imp.K.__file__).resolve() == CONSTANTS.resolve()
    assert imp.K is not precedent_constants  # loaded by file path, not through the mw package
    for obj in ({"b": [1, 2.5, None], "a": "전례 é ☃", "c": {"z": True, "y": ""}}, [], "x", {"k": -0.0}):
        assert imp.K.canonical_json(obj) == canonical_json(obj) == canonical(obj)
    assert imp.DEFAULT_DEST == REPO / ".deps" / "precedent_reference"


def test_two_imports_of_the_same_input_give_new_set_hashes_and_the_same_file_hashes(tmp_path):
    kbase = build_kbase(tmp_path / "kbase")
    dest = tmp_path / "dest"
    first = run(kbase, dest, now=NOW)
    first_set = tree(dest / "sets" / first["set_hash"])
    second = run(kbase, dest, now=LATER)
    assert first["set_hash"] != second["set_hash"]
    one = json.loads((dest / "sets" / first["set_hash"] / "manifest.json").read_bytes())
    two = json.loads((dest / "sets" / second["set_hash"] / "manifest.json").read_bytes())
    assert [f["sha256"] for f in one["files"]] == [f["sha256"] for f in two["files"]]
    assert one["bibliography"]["file"]["sha256"] == two["bibliography"]["file"]["sha256"]
    assert {k: v for k, v in one.items() if k != "imported_at"} == {k: v for k, v in two.items() if k != "imported_at"}
    assert tree(dest / "sets" / first["set_hash"]) == first_set  # the earlier set is kept as it was
    assert json.loads((dest / "active.json").read_bytes())["set_hash"] == second["set_hash"]


def test_the_same_second_again_is_refused_and_changes_nothing(tmp_path):
    kbase = build_kbase(tmp_path / "kbase")
    dest = tmp_path / "dest"
    run(kbase, dest, now=NOW)
    before = tree(dest)
    with pytest.raises(imp.ImportRefused) as info:
        run(kbase, dest, now=NOW)  # same content, same imported_at -> same set hash
    assert info.value.kind == "set_exists"
    assert tree(dest) == before


def test_pubmed_rows_missing_for_some_pmids_is_not_an_error(tmp_path):
    from mw import kinase_precedents

    rows = [PF.make_pubmed_row("90000001")]
    dest = tmp_path / "dest"
    result = run(build_kbase(tmp_path / "kbase", pubmed_rows=rows), dest)
    assert result["rows"][f"pubmed/{PUBMED_NEW}/documents.jsonl"] == 1
    _pinned, index = kinase_precedents.pin_and_index(dest)
    assert sorted(index.bibliography) == ["90000001"]


# --- git information --------------------------------------------------------------------------------------------------

def test_dirty_dist_or_ref_pubmed_is_recorded_not_refused(tmp_path):
    kbase = build_kbase(tmp_path / "kbase")
    (kbase / "dist" / "untracked-synthetic.txt").write_text("synthetic untracked file\n")
    result = run(kbase, tmp_path / "dest")
    assert result["dirty"] is True
    manifest = json.loads((tmp_path / "dest" / "sets" / result["set_hash"] / "manifest.json").read_bytes())
    assert manifest["kbase"]["dirty"] is True

    other = build_kbase(tmp_path / "kbase2")
    old = other / "ref" / "pubmed" / PUBMED_OLD / "documents.jsonl"  # a tracked file of the older snapshot
    old.write_bytes(old.read_bytes() + PF.jsonl([PF.make_pubmed_row("90000042")]))
    assert run(other, tmp_path / "dest2")["dirty"] is True


def test_changes_outside_dist_and_ref_pubmed_do_not_make_it_dirty(tmp_path):
    kbase = build_kbase(tmp_path / "kbase")
    (kbase / "README-untracked.md").write_text("synthetic untracked file outside dist/ and ref/pubmed/\n")
    (kbase / "ref" / "uniprot" / "2026-10-05" / "extra.jsonl").write_text('{"synthetic": 1}\n')
    result = run(kbase, tmp_path / "dest")
    assert result["dirty"] is False


def test_a_dist_folder_without_a_commit_records_null_dist_commit(tmp_path):
    kbase = build_kbase(tmp_path / "kbase", commit=("ref",))  # dist/ never committed (and untracked)
    head = git(kbase, "rev-parse", "HEAD").strip()
    result = run(kbase, tmp_path / "dest")
    manifest = json.loads((tmp_path / "dest" / "sets" / result["set_hash"] / "manifest.json").read_bytes())
    assert manifest["kbase"]["commit"] == head
    assert manifest["kbase"]["dist_commit"] is None and manifest["kbase"]["dist_commit_date"] is None
    assert manifest["kbase"]["dirty"] is True


def test_a_kbase_that_is_not_a_git_repository_is_refused(tmp_path):
    kbase = build_kbase(tmp_path / "kbase", commit=None)
    info = assert_refused(tmp_path, kbase, "git")
    assert "rev-parse" in str(info)


def test_a_plain_folder_inside_another_git_repository_is_refused(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    (outer / "synthetic.txt").write_text("synthetic\n")
    git_commit(outer, "synthetic.txt")
    kbase = build_kbase(outer / "kbase", commit=None)  # git would find the outer repository's HEAD
    assert_refused(tmp_path, kbase, "git")


def test_a_repository_without_a_commit_is_refused(tmp_path):
    kbase = build_kbase(tmp_path / "kbase", commit=None)
    git(kbase, "init", "-q")
    assert_refused(tmp_path, kbase, "git")


def test_git_runs_read_only_with_the_three_spec_commands(tmp_path, monkeypatch):
    kbase = build_kbase(tmp_path / "kbase")
    calls = []
    real_run = subprocess.run

    def spy(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(imp.subprocess, "run", spy)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere" / ".git"))  # must not redirect the repository
    run(kbase, tmp_path / "dest")
    kb = str(kbase.resolve())
    # -c core.fsmonitor=false: no configured fsmonitor command runs; -c protocol.allow=never: no transport at all,
    # so a partial clone's lazy fetch of a missing object fails instead of reaching a remote.
    no_net = ["-c", "core.fsmonitor=false", "-c", "protocol.allow=never"]
    assert [cmd for cmd, _ in calls] == [
        ["git", "-C", kb, *no_net, "rev-parse", "HEAD"],
        ["git", "-C", kb, *no_net, "log", "-1", "--format=%H%n%cI", "--", "dist"],
        ["git", "-C", kb, *no_net, "status", "--porcelain", "--untracked-files=normal", "--", "dist", "ref/pubmed"],
    ]
    for _cmd, kwargs in calls:
        assert kwargs["timeout"] == 60 and kwargs["stdin"] == subprocess.DEVNULL and kwargs["check"] is False
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
        assert not any(k.startswith("GIT_") and k not in ("GIT_OPTIONAL_LOCKS", "GIT_CEILING_DIRECTORIES")
                       for k in kwargs["env"])
        assert kwargs["env"]["GIT_CEILING_DIRECTORIES"] == str(kbase.resolve().parent)


# --- refusals: nothing written --------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["schema_version", "effect_rules_version", "vocab_version"])
def test_each_pinned_kbase_version_value_must_match(tmp_path, key):
    def patch(meta):
        meta[key] = meta[key] + "x"

    info = assert_refused(tmp_path, build_kbase(tmp_path / "kbase", meta_patch=patch), "pins")
    assert key in str(info)


@pytest.mark.parametrize("change", ["missing", "integer"])
def test_a_missing_or_non_string_pin_is_refused(tmp_path, change):
    def patch(meta):
        if change == "missing":
            del meta["vocab_version"]
        else:
            meta["schema_version"] = 1

    assert_refused(tmp_path, build_kbase(tmp_path / "kbase", meta_patch=patch), "pins")


def _drop(name):
    def patch(manifest):
        manifest["files"] = [f for f in manifest["files"] if f["name"] != name]
    return patch


def _set(name, field, value):
    def patch(manifest):
        for f in manifest["files"]:
            if f["name"] == name:
                f[field] = value(f[field]) if callable(value) else value
    return patch


def _repeat(name):
    def patch(manifest):
        manifest["files"].append(dict(next(f for f in manifest["files"] if f["name"] == name)))
    return patch


@pytest.mark.parametrize("patch", [
    _set("moves.jsonl", "sha256", "sha256:" + "0" * 64),
    _set("moves_flagged.jsonl", "bytes", lambda v: v + 1),
    _set("references.jsonl", "records", lambda v: v - 1),
    _set("moves.jsonl", "sha256", lambda v: v.upper()),
    _set("moves.jsonl", "records", None),
    _drop("moves_flagged.jsonl"),
    _repeat("references.jsonl"),
], ids=["sha256", "bytes", "records", "sha256-case", "records-null", "entry-missing", "entry-twice"])
def test_dist_file_bytes_hash_and_line_count_must_match_the_kbase_manifest(tmp_path, patch):
    assert_refused(tmp_path, build_kbase(tmp_path / "kbase", dist_patch=patch), "dist_files")


def test_a_same_length_change_to_a_dist_file_is_caught_by_sha256(tmp_path):
    kbase = build_kbase(tmp_path / "kbase")
    path = kbase / "dist" / "moves.jsonl"
    data = path.read_bytes()
    path.write_bytes(data.replace(b"SYNTHETIC", b"SYNTHETIx", 1))
    assert len(path.read_bytes()) == len(data)
    assert_refused(tmp_path, kbase, "dist_files")


def test_a_dist_file_without_a_final_newline_is_refused(tmp_path):
    data = PF.t2_bytes()["moves"].rstrip(b"\n")  # the kbase manifest then lists these exact bytes
    assert_refused(tmp_path, build_kbase(tmp_path / "kbase", file_bytes={"moves": data}), "dist_files")


def test_a_linked_or_missing_dist_file_is_refused(tmp_path):
    kbase = build_kbase(tmp_path / "kbase")
    target = tmp_path / "outside-moves.jsonl"
    (kbase / "dist" / "moves.jsonl").rename(target)
    (kbase / "dist" / "moves.jsonl").symlink_to(target)
    assert_refused(tmp_path, kbase, "dist_files")
    (kbase / "dist" / "moves.jsonl").unlink()
    assert_refused(tmp_path / "again", kbase, "dist_files")


def test_a_record_whose_content_hash_differs_is_refused(tmp_path):
    moves = PF.t2_records()["moves"]
    moves[2]["observation"]["text"] = "합성 SYNTHETIC changed after hashing"  # no rehash
    info = assert_refused(tmp_path, build_kbase(tmp_path / "kbase", records={"moves": moves}), "records")
    assert "content_hash" in str(info)


def test_a_reference_whose_content_hash_differs_is_refused(tmp_path):
    references = PF.t2_records()["references"]
    hashed = next(r for r in references if r["content_hash"] is not None)
    hashed["family"] = "SYNFAMILY-changed"
    assert_refused(tmp_path, build_kbase(tmp_path / "kbase", records={"references": references}), "records")


def _move_case(name):
    """Record lists that break one spec 3.4 rule while every content_hash still matches its record."""
    records = PF.t2_records()
    moves, flagged, references = records["moves"], records["moves_flagged"], records["references"]
    if name == "missing-top-level-key":
        del moves[1]["figures"]
        PF.rehash(moves[1])
    elif name == "missing-effect-key":
        del moves[0]["effects"][0]["fold_change"]
        PF.rehash(moves[0])
    elif name == "unknown-site-term":
        moves[0]["tags"]["site"] = ["bp_SYNTHETIC"]
        PF.rehash(moves[0])
    elif name == "unknown-tactic-term":
        flagged[0]["tags"]["tactic"] = ["synthetic_tactic"]
        PF.rehash(flagged[0])
    elif name == "unknown-direction":
        moves[0]["effects"][0]["direction"] = "better"
        PF.rehash(moves[0])
    elif name == "review-status":
        moves[3]["review_status"] = "reviewed"
        PF.rehash(moves[3])
    elif name == "reference-review-status":
        references[0]["review_status"] = "reviewed"
        references[0]["content_hash"] = PF.K.content_hash(references[0])
    elif name == "duplicate-move-id":
        flagged[0]["move_id"] = moves[0]["move_id"]
        PF.rehash(flagged[0])
    elif name == "duplicate-ref-id":
        references[1]["ref_id"] = references[0]["ref_id"]
        references[1]["content_hash"] = PF.K.content_hash(references[1])
    elif name == "pmid-format":
        moves[0]["source"]["pmid"] = "PMID90000001"
        PF.rehash(moves[0])
    elif name == "page-missing":
        moves[0]["source"]["locations"][0]["page"] = None
        PF.rehash(moves[0])
    elif name == "move-id-format":
        moves[0]["move_id"] = "MOVE-12"
        PF.rehash(moves[0])
    else:
        raise AssertionError(name)
    return {"moves": moves, "moves_flagged": flagged, "references": references}


FORMAT_CASES = ["missing-top-level-key", "missing-effect-key", "unknown-site-term", "unknown-tactic-term",
                "unknown-direction", "review-status", "reference-review-status", "duplicate-move-id",
                "duplicate-ref-id", "pmid-format", "page-missing", "move-id-format"]


@pytest.mark.parametrize("name", FORMAT_CASES)
def test_each_record_format_violation_is_refused(tmp_path, name):
    records = _move_case(name)
    for move in [*records["moves"], *records["moves_flagged"]]:
        assert PF.K.hash_matches(move)  # the refusal is the format rule, not a hash mismatch
    assert_refused(tmp_path, build_kbase(tmp_path / "kbase", records=records), "records")


def test_a_non_json_line_is_refused(tmp_path):
    data = PF.t2_bytes()["moves_flagged"] + b"{not json}\n"
    assert_refused(tmp_path, build_kbase(tmp_path / "kbase", file_bytes={"moves_flagged": data}), "records")


@pytest.fixture
def default_digit_limit():
    """The interpreter's default integer-string digit limit (Python 3.11: 4,300 digits), restored afterwards."""
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4300)
    yield 4300
    sys.set_int_max_str_digits(previous)


@pytest.mark.parametrize("file", ["moves", "moves_flagged"])
def test_a_move_id_whose_digits_exceed_the_integer_limit_is_refused(tmp_path, default_digit_limit, file):
    """``MOVE-`` + 5,000 digits matches ``MOVE-[0-9]{4,}`` and its ``content_hash`` matches (SYNTHETIC record), but
    the server could not order it: the import refuses it as a record format violation and writes nothing (a fresh
    destination is not created; an installed one keeps active.json and its set byte for byte)."""
    records = PF.t2_records()
    planted = PF.make_move("MOVE-" + "1" * 5000, uniprot="P0SYN1")
    assert PF.K.hash_matches(planted)
    records[file].append(planted)
    info = assert_refused(tmp_path, build_kbase(tmp_path / "kbase", records=records), "records")
    assert "move_id" in str(info)
    edge = PF.t2_records()
    edge[file].append(PF.make_move("MOVE-" + "1" * default_digit_limit, uniprot="P0SYN1"))  # at the limit: kept
    result = run(build_kbase(tmp_path / "edge-kbase", records=edge), tmp_path / "edge-dest")
    assert result["verification"]["records_hash_verified"][file] == len(edge[file])


def _pubmed_tie(manifest):
    newest = next(s for s in manifest["snapshots"] if s["date"] == PUBMED_NEW)
    manifest["snapshots"].append({**newest, "snapshot_id": "SNAP-pubmed-synthetic-tie"})


def _pubmed_sha(manifest):
    newest = next(s for s in manifest["snapshots"] if s["date"] == PUBMED_NEW)
    newest["files"][0]["sha256"] = "sha256:" + "1" * 64


def _pubmed_rows(manifest):
    newest = next(s for s in manifest["snapshots"] if s["date"] == PUBMED_NEW)
    newest["files"][0]["rows"] += 1


def _pubmed_none(manifest):
    manifest["snapshots"] = [s for s in manifest["snapshots"] if s["source"] != "pubmed"]


def _pubmed_bad_date(manifest):
    manifest["snapshots"][0]["date"] = "2026/09/01"


def _pubmed_no_license(manifest):
    next(s for s in manifest["snapshots"] if s["date"] == PUBMED_NEW)["license"] = ""


def _pubmed_other_path(manifest):
    newest = next(s for s in manifest["snapshots"] if s["date"] == PUBMED_NEW)
    newest["files"][0]["path"] = f"pubmed/{PUBMED_NEW}/other.jsonl"


@pytest.mark.parametrize("patch", [_pubmed_tie, _pubmed_sha, _pubmed_rows, _pubmed_none, _pubmed_bad_date,
                                   _pubmed_no_license, _pubmed_other_path],
                         ids=["newest-date-twice", "sha256", "rows", "no-pubmed", "bad-date", "no-license",
                              "file-not-listed"])
def test_the_bibliography_snapshot_must_match_ref_manifest(tmp_path, patch):
    assert_refused(tmp_path, build_kbase(tmp_path / "kbase", ref_patch=patch), "bibliography")


@pytest.mark.parametrize("rows", [
    [{"data": {}, "id": "PMID-1", "status": "ok"}],
    [PF.make_pubmed_row("90000001"), PF.make_pubmed_row("90000001")],
], ids=["id-not-a-pmid", "id-twice"])
def test_bibliography_rows_need_unique_pmid_ids(tmp_path, rows):
    assert_refused(tmp_path, build_kbase(tmp_path / "kbase", pubmed_rows=rows), "bibliography")


@pytest.mark.parametrize("content", [
    b"", b"[]", b"{not json", b'{"files": [], "kb_version": "x"}', b'{"a": 1, "a": 2}',
    canonical({"files": {}, "kb_version": "x", "meta": {**PINS, "source_snapshots": []}}),
    canonical({"files": [], "kb_version": 1, "meta": {**PINS, "source_snapshots": []}}),
    canonical({"files": [], "kb_version": "x", "meta": {**PINS, "source_snapshots": "SNAP"}}),
], ids=["empty", "list", "not-json", "no-meta", "duplicate-key", "files-not-list", "kb-version-not-string",
        "source-snapshots-not-list"])
def test_an_unreadable_dist_manifest_is_refused(tmp_path, content):
    kbase = build_kbase(tmp_path / "kbase")
    (kbase / "dist" / "manifest.json").write_bytes(content)
    assert_refused(tmp_path, kbase, "dist_manifest")


def test_pins_are_checked_before_the_rest_of_the_dist_manifest(tmp_path):
    kbase = build_kbase(tmp_path / "kbase")
    (kbase / "dist" / "manifest.json").write_bytes(canonical({"files": {}, "meta": {}}))
    assert_refused(tmp_path, kbase, "pins")


def test_a_dist_manifest_above_its_size_cap_is_refused(tmp_path, monkeypatch):
    dest = installed(tmp_path)
    before = tree(dest)
    kbase = build_kbase(tmp_path / "kbase")
    size = (kbase / "dist" / "manifest.json").stat().st_size
    monkeypatch.setattr(imp.K, "MAX_DIST_MANIFEST_BYTES", size - 1)  # the script's own copy of the constants
    with pytest.raises(imp.ImportRefused) as info:
        run(kbase, dest, now=LATER)
    assert info.value.kind == "dist_manifest" and tree(dest) == before
    monkeypatch.setattr(imp.K, "MAX_DIST_MANIFEST_BYTES", size)
    assert run(kbase, dest, now=LATER)["set_hash"]  # exactly at the cap is accepted


def test_a_missing_kbase_folder_is_refused(tmp_path):
    with pytest.raises(imp.ImportRefused) as info:
        run(tmp_path / "no-such-kbase", tmp_path / "dest")
    assert info.value.kind == "invalid_input"
    assert not (tmp_path / "dest").exists()


def test_a_foreign_pointer_or_a_linked_sets_folder_is_refused(tmp_path):
    kbase = build_kbase(tmp_path / "kbase")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "active.json").write_bytes(canonical({"schema": "reference_active@1", "set_hash": "a" * 64}))
    before = tree(dest)
    with pytest.raises(imp.ImportRefused) as info:
        run(kbase, dest)
    assert info.value.kind == "target_invalid" and tree(dest) == before
    (dest / "active.json").unlink()
    outside = tmp_path / "outside"
    outside.mkdir()
    (dest / "sets").symlink_to(outside, target_is_directory=True)
    with pytest.raises(imp.ImportRefused) as info:
        run(kbase, dest)
    assert info.value.kind == "target_invalid" and list(outside.iterdir()) == []


# --- atomic install ---------------------------------------------------------------------------------------------------

INSTALL_STEPS = ["write_moves", "write_moves_flagged", "write_references", "write_pubmed", "write_manifest",
                 "fsync_staging", "rename", "fsync_sets", "write_pointer", "replace_pointer"]


@pytest.mark.parametrize("step", INSTALL_STEPS)
def test_a_failure_at_any_install_step_leaves_active_json_and_earlier_sets(tmp_path, monkeypatch, step):
    kbase = build_kbase(tmp_path / "kbase")
    dest = tmp_path / "dest"
    first = run(kbase, dest, now=NOW)
    old_set = tree(dest / "sets" / first["set_hash"])
    old_pointer = (dest / "active.json").read_bytes()
    writes = {"n": 0}
    real_write, real_fsync = imp._write_file, imp._fsync_dir
    order = ["write_moves", "write_moves_flagged", "write_references", "write_pubmed", "write_manifest"]

    def write(path, data):
        if Path(path).name.startswith(".active.json"):
            if step == "write_pointer":
                real_write(path, data)  # the temporary pointer exists when the failure happens
                raise OSError("synthetic disk failure")
        else:
            writes["n"] += 1
            if step in order and writes["n"] == order.index(step) + 1:
                raise OSError("synthetic disk failure")
        return real_write(path, data)

    def fsync(path):
        path = Path(path)
        if step == "fsync_staging" and path.name.startswith(".staging-"):
            raise OSError("synthetic fsync failure")
        if step == "fsync_sets" and path == dest / "sets":
            raise OSError("synthetic fsync failure")
        return real_fsync(path)

    def fail(*args, **kwargs):
        raise OSError("synthetic failure")

    monkeypatch.setattr(imp, "_write_file", write)
    monkeypatch.setattr(imp, "_fsync_dir", fsync)
    if step == "rename":
        monkeypatch.setattr(imp.os, "rename", fail)
    if step == "replace_pointer":
        monkeypatch.setattr(imp.os, "replace", fail)
    with pytest.raises(imp.ImportRefused) as info:
        run(kbase, dest, now=LATER)
    assert info.value.kind == "install_failed"
    assert (dest / "active.json").read_bytes() == old_pointer
    assert tree(dest / "sets" / first["set_hash"]) == old_set
    names = {p.name for p in (dest / "sets").iterdir()}
    assert not any(n.startswith(".staging-") for n in names)
    assert sorted(p.name for p in dest.iterdir()) == ["active.json", "sets"]
    if INSTALL_STEPS.index(step) < INSTALL_STEPS.index("fsync_sets"):
        assert names == {first["set_hash"]}
    else:  # the complete new set was renamed into place before the failure but is not active
        assert len(names) == 2


def test_the_pointer_swap_happens_once_after_the_new_set_is_complete(tmp_path, monkeypatch):
    kbase = build_kbase(tmp_path / "kbase")
    dest = tmp_path / "dest"
    first = run(kbase, dest, now=NOW)
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        if Path(dst).name == "active.json":
            pending = json.loads(Path(src).read_bytes())["set_hash"]
            raw = (dest / "sets" / pending / "manifest.json").read_bytes()
            assert sha(raw) == pending
            manifest = json.loads(raw)
            for entry in [*manifest["files"], manifest["bibliography"]["file"]]:
                assert sha((dest / "sets" / pending / entry["path"]).read_bytes()) == entry["sha256"]
            assert json.loads((dest / "active.json").read_bytes())["set_hash"] == first["set_hash"]
            seen.append(pending)
        return real_replace(src, dst)

    monkeypatch.setattr(imp.os, "replace", spy)
    second = run(kbase, dest, now=LATER)
    assert seen == [second["set_hash"]]


def test_staged_files_are_created_exclusively_without_following_links(tmp_path, monkeypatch):
    flags = []
    real_open = os.open

    def spy(path, flag, *args, **kwargs):
        staged_file = ".staging-" in str(path) and Path(path).suffix in (".jsonl", ".json")
        if staged_file or Path(path).name.startswith(".active.json"):
            flags.append(flag)
        return real_open(path, flag, *args, **kwargs)

    monkeypatch.setattr(imp.os, "open", spy)
    run(build_kbase(tmp_path / "kbase"), tmp_path / "dest")
    want = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    assert len(flags) == 6 and all(flag & want == want for flag in flags)  # 4 files, manifest, pointer


# --- confirmation and command line ------------------------------------------------------------------------------------

def test_the_confirmation_screen_and_a_refusal_answer_write_nothing(tmp_path, capsys):
    kbase = build_kbase(tmp_path / "kbase")
    head = git(kbase, "rev-parse", "HEAD").strip()
    dest = tmp_path / "dest"
    prompts = []
    with pytest.raises(imp.ImportRefused) as info:
        run(kbase, dest, yes=False, input_fn=lambda prompt: prompts.append(prompt) or "n")
    assert info.value.kind == "cancelled" and len(prompts) == 1
    assert not dest.exists()
    out = capsys.readouterr().out
    for text in (str(kbase.resolve()), head, "dirty", "false", "dist/moves.jsonl",
                 f"{(kbase / 'dist' / 'moves.jsonl').stat().st_size} bytes", f"pubmed/{PUBMED_NEW}/documents.jsonl",
                 str(dest)):
        assert text in out, text
    for answer in ("", "no", "yes please"):
        with pytest.raises(imp.ImportRefused):
            run(kbase, dest, yes=False, input_fn=lambda prompt, a=answer: a)
    assert not dest.exists()

    def eof(prompt):
        raise EOFError

    with pytest.raises(imp.ImportRefused):
        run(kbase, dest, yes=False, input_fn=eof)
    assert not dest.exists()
    result = run(kbase, dest, yes=False, input_fn=lambda prompt: "y")
    assert (dest / "sets" / result["set_hash"]).is_dir()


def test_cli_options_are_exactly_from_dest_and_yes():
    parser = imp.build_parser()
    options = sorted(opt for action in parser._actions for opt in action.option_strings)
    assert options == sorted(["--from", "--dest", "--yes", "-h", "--help"])
    assert parser.allow_abbrev is False
    assert all(action.option_strings for action in parser._actions)  # no positional arguments


@pytest.mark.parametrize("option", ["--host", "--url", "--base-url", "--remote", "--fetch", "--download", "--proxy",
                                    "--scheme", "--fr", "--de"])
def test_cli_has_no_host_or_url_option(option, capsys):
    with pytest.raises(SystemExit) as info:
        imp.main([option, "x", "--from", "x", "--yes"])
    assert info.value.code == 2


def test_cli_needs_from(capsys):
    with pytest.raises(SystemExit) as info:
        imp.main(["--yes"])
    assert info.value.code == 2


def test_dest_resolution():
    default = REPO / ".deps" / "precedent_reference"
    assert imp.resolve_dest(None, None) == default
    assert imp.resolve_dest(None, "") == default
    assert imp.resolve_dest(None, "qa/precedent") == REPO / "qa" / "precedent"
    assert imp.resolve_dest("other", "qa/precedent") == REPO / "other"
    assert imp.resolve_dest("/abs/x", "qa/precedent") == Path("/abs/x")


def test_cli_installs_into_the_environment_folder_and_reports_refusals(tmp_path, monkeypatch, capsys):
    kbase = build_kbase(tmp_path / "kbase")
    monkeypatch.setenv("MW_PRECEDENT_REFERENCE_DIR", str(tmp_path / "env-dest"))
    assert imp.main(["--from", str(kbase), "--yes"]) == 0
    assert (tmp_path / "env-dest" / "active.json").is_file()
    assert "설치 완료" in capsys.readouterr().out
    bad = build_kbase(tmp_path / "bad", meta_patch=lambda meta: meta.update(schema_version="2"))
    assert imp.main(["--from", str(bad), "--dest", str(tmp_path / "other"), "--yes"]) == 1
    err = capsys.readouterr().err
    assert "pins" in err and "거절" in err and "refused" in err
    assert not (tmp_path / "other").exists()


def test_the_script_runs_in_a_child_with_sockets_and_network_modules_blocked(tmp_path):
    # A child process where importing mw or a network module fails and any socket use exits: the script loads the
    # constants by file path and completes a real import (local files + read-only git) from a synthetic kbase.
    from mw import precedent_snapshots

    kbase = build_kbase(tmp_path / "kbase")
    dest = tmp_path / "dest"
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "MW_PRECEDENT_REFERENCE_DIR": str(dest)}
    code = ("import sys, socket, runpy\n"
            "BLOCKED = ('mw', 'httpx', 'requests', 'http', 'ssl', 'urllib3', 'aiohttp', 'ftplib', 'smtplib')\n"
            "class Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in BLOCKED or name == 'urllib.request':\n"
            "            raise ImportError('blocked import ' + name)\n"
            "sys.meta_path.insert(0, Block())\n"
            "def no(*a, **k):\n"
            "    raise SystemExit('network used')\n"
            "socket.socket.connect = no\nsocket.socket.connect_ex = no\nsocket.getaddrinfo = no\n"
            "socket.create_connection = no\n"
            "sys.argv = [sys.argv[1], *sys.argv[2:]]\n"
            "try:\n"
            "    runpy.run_path(sys.argv[0], run_name='__main__')\n"
            "finally:\n"
            "    loaded = [m for m in ('mw', 'ssl', 'http.client', 'urllib.request') if m in sys.modules]\n"
            "    print('LOADED', loaded)\n")
    help_run = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPT), "--help"], env=env, cwd=tmp_path,
                              capture_output=True, text=True, timeout=60, check=False)
    assert help_run.returncode == 0 and "--from" in help_run.stdout, help_run.stderr
    done = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPT), "--from", str(kbase), "--yes"], env=env,
                          cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    assert "network used" not in done.stderr + done.stdout and "LOADED []" in done.stdout
    pointer = json.loads((dest / "active.json").read_bytes())
    assert precedent_snapshots.pin_active_set(dest).set_hash == pointer["set_hash"]


# --- static checks ----------------------------------------------------------------------------------------------------

NETWORK_ROOTS = {"socket", "ssl", "http", "urllib", "urllib3", "httpx", "requests", "aiohttp", "ftplib", "smtplib",
                 "poplib", "imaplib", "telnetlib", "xmlrpc", "asyncio", "websocket", "websockets", "pycurl"}


def _imports(path: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append("." * node.level + (node.module or ""))
    return names


def test_script_and_constants_import_no_network_module_and_no_mw():
    for path in (SCRIPT, CONSTANTS):
        for name in _imports(path):
            root = name.split(".")[0]
            assert not name.startswith("."), (path.name, name)
            assert root not in NETWORK_ROOTS and root != "mw", (path.name, name)
            if path == CONSTANTS:
                assert root != "subprocess", name
    source = SCRIPT.read_text(encoding="utf-8")
    assert "precedent_constants.py" in source and "spec_from_file_location" in source
    assert "://" not in source  # no URL anywhere in the command


def test_subprocess_is_used_only_by_the_git_helper():
    tree_ = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    helper = next(n for n in tree_.body if isinstance(n, ast.FunctionDef) and n.name == "_git")
    inside = {id(child) for child in ast.walk(helper)}
    uses = [n for n in ast.walk(tree_) if isinstance(n, ast.Name) and n.id == "subprocess"]
    assert uses and all(id(n) in inside for n in uses)
    calls = [n for n in ast.walk(tree_) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_git"]
    commands = sorted(ast.literal_eval(call.args[1]) for call in calls)
    assert commands == ["log", "rev-parse", "status"]
