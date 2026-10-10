"""Import the M27 kinase precedent reference set from a local kbase_kinase checkout (no network).

Usage: python scripts/import_precedent_snapshots.py --from <kbase_kinase path> [--dest PATH] [--yes]

This user-run command copies, byte for byte, the three processed files ``dist/moves.jsonl``,
``dist/moves_flagged.jsonl`` and ``dist/references.jsonl`` and the newest ``ref/pubmed`` bibliography snapshot of a
local kbase_kinase checkout into the precedent reference folder that the server reads (spec 3-4). It uses no network:
only local file reads and three read-only ``git -C <kbase>`` subprocesses (``rev-parse HEAD``,
``log -1 --format=%H%n%cI -- dist``, ``status --porcelain -- dist ref/pubmed``; 60 s each, no optional locks, the
inherited ``GIT_*`` variables dropped and discovery stopped at the kbase folder so another repository is never read,
and ``-c core.fsmonitor=false -c protocol.allow=never`` so no fsmonitor command runs and a partial clone's lazy fetch
of a missing object fails instead of reaching a remote).
No option or environment variable names a host or an address. The kbase code is never imported or run.

Checks, in this order; any failure refuses the import and nothing is written (spec 4.2):

1. ``dist/manifest.json`` (size cap) and the three pinned ``meta`` values (``KBASE_PINS``).
2. The bytes, SHA-256 and line count of the three dist files against the kbase manifest's ``bytes`` / ``sha256`` /
   ``records`` (every line ends with a newline).
3. Every record's format and ``content_hash`` (``validate_dist_files``: ``move_id`` unique over both move files).
4. The newest ``pubmed`` snapshot of ``ref/manifest.json``: the file's bytes, SHA-256 and rows, then its rows
   (``id`` a unique PMID). PMIDs the snapshot does not cover are not an error.
5. git: the HEAD commit (required), the last commit touching ``dist`` (or null) and whether ``dist/`` or
   ``ref/pubmed/`` has uncommitted or untracked changes (``dirty``, recorded, never a refusal).

Layout written under the destination (``--dest``, else ``MW_PRECEDENT_REFERENCE_DIR``, else
``<repo>/.deps/precedent_reference``; a relative value is taken from the repository root like the server does)::

    active.json                                 {"schema":"precedent_active@1","set_hash":"<hex64>"} (one rename)
    sets/<set_hash>/manifest.json               canonical JSON precedent_reference_set@1; set_hash = sha256(bytes)
    sets/<set_hash>/files/dist/<name>.jsonl     the three dist files as they were
    sets/<set_hash>/files/pubmed/<date>/documents.jsonl

The set is written in ``sets/.staging-<uuid>`` (exclusive creates without following links, fsync), renamed to
``sets/<set_hash>`` and only then is ``active.json`` replaced (temporary file + ``os.replace``). A failure removes only
the staging folder or the temporary pointer; ``active.json`` and every earlier set stay as they were, and earlier sets
are never deleted. ``imported_at`` (whole seconds) is inside the manifest, so importing the same input again gives a
new set hash; the same second again gives the same hash and is refused because the folder exists.

Record rules, canonical JSON, the set hash, the manifest and pointer checks are those of
``backend/mw/precedent_constants.py``, loaded here by file path: this script never imports ``mw``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONSTANTS_PATH = ROOT / "backend" / "mw" / "precedent_constants.py"


def _load_constants():
    """``precedent_constants.py`` by file path (standard library only; the ``mw`` package is not imported)."""
    spec = importlib.util.spec_from_file_location("protview_precedent_import_constants", CONSTANTS_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {CONSTANTS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


K = _load_constants()

DEFAULT_DEST = ROOT.joinpath(*K.DEFAULT_DIR_PARTS)
GIT_TIMEOUT_SECONDS = 60  # adjustable default (spec 9.2)
PUBMED_SOURCE = "pubmed"

REFUSAL_KINDS = ("invalid_input", "target_invalid", "dist_manifest", "pins", "dist_files", "records", "bibliography",
                 "git", "manifest_invalid", "cancelled", "set_exists", "install_failed")


class ImportRefused(Exception):
    """The import stopped; ``active.json`` and every earlier set are unchanged. ``kind`` is one of REFUSAL_KINDS."""

    def __init__(self, kind: str, message: str) -> None:
        if kind not in REFUSAL_KINDS:
            raise ValueError(f"unknown refusal kind {kind!r}")
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------------------------------- local reads

def _read_limited(path: Path, limit: int) -> bytes:
    """A regular file (the last component is not followed if it is a link) of at most ``limit`` bytes."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError(f"not a regular file of at most {limit} bytes")
        chunks, total = [], 0
        while chunk := os.read(fd, 1 << 20):
            total += len(chunk)
            if total > limit:
                raise ValueError(f"grew beyond {limit} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _read(path: Path, limit: int, kind: str) -> bytes:
    try:
        return _read_limited(path, limit)
    except (OSError, ValueError) as exc:
        raise ImportRefused(kind, f"cannot read {path}: {exc}") from None


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate key {key!r}")
        obj[key] = value
    return obj


def _no_constant(value: str) -> Any:
    raise ValueError(f"non-finite number {value}")


def _json_object(raw: bytes, what: str, kind: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (ValueError, RecursionError) as exc:
        raise ImportRefused(kind, f"{what} is not one JSON object: {exc}") from None
    if type(value) is not dict:
        raise ImportRefused(kind, f"{what} is not a JSON object")
    return value


def _kbase_file(entries: list[Any], key: str, value: str, what: str, kind: str) -> dict[str, Any]:
    """The one manifest entry whose ``key`` is ``value``, with a ``sha256:<hex>`` string and integer counts."""
    found = [e for e in entries if type(e) is dict and e.get(key) == value]
    if len(found) != 1:
        raise ImportRefused(kind, f"{what} lists {value} {len(found)} times (expected once)")
    return found[0]


def _check_file(data: bytes, name: str, entry: dict[str, Any], rows_key: str, kind: str) -> dict[str, Any]:
    """Bytes, SHA-256 and line count of one kbase file against its kbase manifest entry; the set's file record."""
    try:
        record = K.file_record(name, data)  # refuses a last line without a newline
    except K.FormatError as exc:
        raise ImportRefused(kind, str(exc)) from None
    if type(entry.get("bytes")) is not int or entry["bytes"] != record["bytes"]:
        raise ImportRefused(kind, f"{name}: {record['bytes']} bytes, kbase manifest says {entry.get('bytes')!r}")
    if type(entry.get("sha256")) is not str or entry["sha256"] != record["kbase_sha256"]:
        raise ImportRefused(kind, f"{name}: {record['kbase_sha256']}, kbase manifest says {entry.get('sha256')!r}")
    if type(entry.get(rows_key)) is not int or entry[rows_key] != record["rows"]:
        raise ImportRefused(kind, f"{name}: {record['rows']} lines, kbase manifest says {entry.get(rows_key)!r}")
    record["kbase_sha256"] = entry["sha256"]  # the kbase string as it is (equal to "sha256:" + sha256 here)
    return record


# ------------------------------------------------------------------------------------------- checks (spec 4.2)

def _dist_manifest(kbase: Path) -> dict[str, Any]:
    """Step 1: the dist manifest within its cap and the three pinned values."""
    path = kbase / "dist" / "manifest.json"
    manifest = _json_object(_read(path, K.MAX_DIST_MANIFEST_BYTES, "dist_manifest"), str(path), "dist_manifest")
    meta = manifest.get("meta")
    if type(meta) is not dict:
        raise ImportRefused("dist_manifest", f"{path} has no meta object")
    try:
        K.check_kbase_pins(meta)
    except K.FormatError as exc:
        raise ImportRefused("pins", f"{exc} (pinned {K.KBASE_PINS}); changing the pins needs a user decision") \
            from None
    snapshots = meta.get("source_snapshots")
    if type(manifest.get("kb_version")) is not str:
        raise ImportRefused("dist_manifest", f"{path}: kb_version is not a string")
    if type(snapshots) is not list or not all(type(s) is str for s in snapshots):
        raise ImportRefused("dist_manifest", f"{path}: meta.source_snapshots is not a list of strings")
    if type(manifest.get("files")) is not list:
        raise ImportRefused("dist_manifest", f"{path}: files is not a list")
    return manifest


def _dist_files(kbase: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Step 2: the three dist files against the dist manifest (``files[].name`` is the bare file name)."""
    records, payloads = [], {}
    for name in K.DIST_FILE_NAMES:
        bare = name.split("/", 1)[1]
        entry = _kbase_file(manifest["files"], "name", bare, "dist/manifest.json", "dist_files")
        data = _read(kbase / name, K.MAX_FILE_BYTES, "dist_files")
        records.append(_check_file(data, name, entry, "records", "dist_files"))
        payloads[name] = data
    return records, payloads


def _bibliography(kbase: Path) -> tuple[dict[str, Any], bytes]:
    """Step 4: the newest pubmed snapshot of ``ref/manifest.json`` and its file (rows parsed, PMID ids unique)."""
    path = kbase / "ref" / "manifest.json"
    manifest = _json_object(_read(path, K.MAX_REF_MANIFEST_BYTES, "bibliography"), str(path), "bibliography")
    if type(manifest.get("snapshots")) is not list:
        raise ImportRefused("bibliography", f"{path} has no snapshots list")
    mine = [s for s in manifest["snapshots"] if type(s) is dict and s.get("source") == PUBMED_SOURCE]
    if not mine:
        raise ImportRefused("bibliography", f"{path} has no pubmed snapshot")
    for snapshot in mine:
        if type(snapshot.get("date")) is not str or not re.fullmatch(K.DATE_PATTERN, snapshot["date"]):
            raise ImportRefused("bibliography", f"a pubmed snapshot has an invalid date {snapshot.get('date')!r}")
    newest = max(s["date"] for s in mine)
    chosen = [s for s in mine if s["date"] == newest]
    if len(chosen) != 1:
        raise ImportRefused("bibliography", f"{len(chosen)} pubmed snapshots share the newest date {newest}")
    snapshot = chosen[0]
    for key in ("snapshot_id", "license"):
        if type(snapshot.get(key)) is not str or not snapshot[key]:
            raise ImportRefused("bibliography", f"pubmed snapshot {newest} has no {key}")
    if type(snapshot.get("files")) is not list:
        raise ImportRefused("bibliography", f"pubmed snapshot {newest} has no files list")
    name = K.pubmed_file_name(newest)
    entry = _kbase_file(snapshot["files"], "path", name, f"pubmed snapshot {newest}", "bibliography")
    data = _read(kbase / "ref" / name, K.MAX_FILE_BYTES, "bibliography")
    record = _check_file(data, name, entry, "rows", "bibliography")
    try:
        K.parse_pubmed(data)
    except K.FormatError as exc:
        raise ImportRefused("bibliography", f"{name}: {exc}") from None
    return {"snapshot_id": snapshot["snapshot_id"], "date": newest, "license": snapshot["license"],
            "origin": K.BIBLIOGRAPHY_ORIGIN, "file": record}, data


def _git(kbase: Path, command: str, *args: str) -> str:
    """One read-only ``git -C <kbase>`` command; a failure refuses the import."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_CEILING_DIRECTORIES"] = str(kbase.parent)  # the kbase folder itself must be the repository
    # no configured fsmonitor command runs, and no transport is allowed (a partial clone's lazy fetch fails)
    cmd = ["git", "-C", str(kbase), "-c", "core.fsmonitor=false", "-c", "protocol.allow=never", command, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False,
                              stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImportRefused("git", f"cannot run git {command} in {kbase}: {exc}") from None
    if proc.returncode != 0:
        raise ImportRefused("git", f"git {command} failed in {kbase} (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def read_git_info(kbase: Path) -> dict[str, Any]:
    """Step 5: ``commit`` (required), ``dist_commit`` and its ``%cI`` date (null without a commit), ``dirty``."""
    commit = _git(kbase, "rev-parse", "HEAD").strip()
    if not re.fullmatch(K.HEX40_PATTERN, commit):
        raise ImportRefused("git", f"git rev-parse HEAD gave {commit!r}, not a 40-character commit id")
    lines = _git(kbase, "log", "-1", "--format=%H%n%cI", "--", "dist").split()
    if not lines:
        dist_commit = dist_commit_date = None
    elif (len(lines) == 2 and re.fullmatch(K.HEX40_PATTERN, lines[0])
          and re.fullmatch(K.GIT_DATE_PATTERN, lines[1])):
        dist_commit, dist_commit_date = lines
    else:
        raise ImportRefused("git", f"unexpected git log output {lines!r}")
    status = _git(kbase, "status", "--porcelain", "--untracked-files=normal", "--", "dist", "ref/pubmed")
    return {"commit": commit, "dist_commit": dist_commit, "dist_commit_date": dist_commit_date,
            "dirty": bool(status.strip())}


def _check_target(dest: Path) -> None:
    """The destination must be a folder (or absent), ``sets`` a plain folder, and ``active.json`` not another
    snapshot family's pointer (for example the M15 or M26 folder named by mistake)."""
    try:
        if not stat.S_ISDIR(os.stat(dest).st_mode):
            raise ImportRefused("target_invalid", f"{dest} is not a folder")
    except FileNotFoundError:
        return
    try:
        if not stat.S_ISDIR(os.lstat(dest / K.SETS_DIR).st_mode):
            raise ImportRefused("target_invalid", f"{dest / K.SETS_DIR} is not a plain folder (links are refused)")
    except FileNotFoundError:
        pass
    try:
        pointer = json.loads(_read_limited(dest / K.ACTIVE_NAME, K.MAX_POINTER_BYTES))
    except (OSError, ValueError):
        return  # no pointer, or an unreadable one that the new pointer replaces
    if type(pointer) is dict and pointer.get("schema") != K.POINTER_SCHEMA:
        raise ImportRefused("target_invalid", f"{dest / K.ACTIVE_NAME} belongs to another snapshot family "
                                              f"({pointer.get('schema')!r}); choose the precedent reference folder")


# ------------------------------------------------------------------------------------------- the import

def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _timestamp(moment: _dt.datetime) -> str:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("the clock must give a time-zone aware datetime")
    return moment.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _confirm(*, kbase: Path, dest: Path, git: dict[str, Any], kb_version: str, files: list[dict[str, Any]],
             yes: bool, input_fn: Callable[[str], str]) -> None:
    dist_commit = (f"{git['dist_commit']} ({git['dist_commit_date']})" if git["dist_commit"] is not None
                   else "없음 / none")
    lines = [
        "키나아제 전례 참조 스냅샷 가져오기 (M27) / Kinase precedent reference import",
        "- 네트워크 사용 안 함: 로컬 파일과 읽기 전용 git만 / no network: local files and read-only git only",
        f"- kbase 경로 / kbase path: {kbase}",
        f"- kbase 커밋 / commit (HEAD): {git['commit']}",
        f"- dist 커밋 / dist commit: {dist_commit}",
        f"- dirty (dist/·ref/pubmed/의 커밋되지 않은 변경 / uncommitted changes): {str(git['dirty']).lower()}",
        f"- kb_version: {kb_version}",
        "- 가져올 파일 / files to import:",
        *(f"    {f['name']}  {f['bytes']} bytes, {f['rows']} rows" for f in files),
        f"- 쓸 폴더 / target folder: {dest}",
    ]
    print("\n".join(lines), flush=True)
    if yes:
        return
    try:
        answer = input_fn("계속할까요? / Continue? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        raise ImportRefused("cancelled", "취소됨 / cancelled by the user")


def run_import(kbase_dir: str | os.PathLike, dest: str | os.PathLike, *, yes: bool = False,
               now: Callable[[], _dt.datetime] | None = None,
               input_fn: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Verify (spec 4.2), confirm, then install one new set and point ``active.json`` at it (spec 4.3).

    ``now`` (a time-zone aware clock) defaults to the UTC wall clock and ``input_fn`` to ``input``. Every refusal is
    ``ImportRefused`` and leaves the destination as it was. Returns the printed summary as a dict.
    """
    now = now or _utc_now
    input_fn = input_fn or input
    kbase = Path(kbase_dir).resolve()
    dest = Path(dest)
    if not kbase.is_dir():
        raise ImportRefused("invalid_input", f"{kbase} is not a folder")
    _check_target(dest)
    dist_manifest = _dist_manifest(kbase)
    files, payloads = _dist_files(kbase, dist_manifest)
    try:
        dist = K.validate_dist_files(*(payloads[name] for name in K.DIST_FILE_NAMES))
    except K.FormatError as exc:
        raise ImportRefused("records", f"record format or content_hash check failed: {exc}") from None
    bibliography, pubmed = _bibliography(kbase)
    git = read_git_info(kbase)
    meta = dist_manifest["meta"]
    kbase_block = {**git, "kb_version": dist_manifest["kb_version"],
                   **{key: meta[key] for key in K.KBASE_PINS}, "source_snapshots": list(meta["source_snapshots"]),
                   "origin": K.KBASE_ORIGIN}
    _confirm(kbase=kbase, dest=dest, git=git, kb_version=dist_manifest["kb_version"],
             files=[*files, bibliography["file"]], yes=yes, input_fn=input_fn)
    manifest = {"schema": K.SET_SCHEMA, "imported_at": _timestamp(now()), "importer_version": K.IMPORTER_VERSION,
                "kbase": kbase_block, "files": files, "bibliography": bibliography,
                "verification": dist.verification}
    try:
        raw = K.manifest_bytes(manifest)
    except K.FormatError as exc:
        raise ImportRefused("manifest_invalid", f"the set manifest would not be valid: {exc}") from None
    set_hash = K.set_hash_of(raw)
    staged = {K.file_path(name): data for name, data in payloads.items()}
    staged[bibliography["file"]["path"]] = pubmed
    set_dir, warnings = install_set(dest, raw, set_hash, staged)
    result = {"set_hash": set_hash, "set_dir": str(set_dir), "dest": str(dest), "imported_at": manifest["imported_at"],
              "kbase": kbase_block, "rows": {f["name"]: f["rows"] for f in [*files, bibliography["file"]]},
              "verification": dist.verification, "dirty": git["dirty"], "warnings": warnings}
    print(format_summary(result), flush=True)
    return result


# ------------------------------------------------------------------------------------------- atomic install (4.3)

def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def install_set(dest: Path, manifest_raw: bytes, set_hash: str, payloads: dict[str, bytes]) -> tuple[Path, list[str]]:
    """Stage the files and the manifest, rename into ``sets/<set_hash>``, then replace ``active.json``.

    Returns (set folder, warnings). On a failure only the staging folder or the temporary pointer is removed;
    ``active.json`` and earlier sets are untouched (after the set rename the complete new set stays, inactive).
    """
    dest = Path(dest)
    sets = dest / K.SETS_DIR
    final = sets / set_hash
    _check_target(dest)
    if os.path.lexists(final):
        raise ImportRefused("set_exists", f"set folder {final} already exists (same content imported in the same "
                                          "second); nothing changed")
    staging = sets / f".staging-{uuid.uuid4().hex}"
    try:
        sets.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        for rel, data in payloads.items():
            _write_file(staging / rel, data)
        _write_file(staging / K.MANIFEST_NAME, manifest_raw)
        folders = {staging}
        for rel in payloads:
            parent = (staging / rel).parent
            while parent != staging:
                folders.add(parent)
                parent = parent.parent
        for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
            _fsync_dir(folder)
        if os.path.lexists(final):
            raise ImportRefused("set_exists", f"set folder {final} appeared during the import; nothing changed")
        os.rename(staging, final)
        _fsync_dir(sets)
    except BaseException as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, OSError):
            raise ImportRefused("install_failed", f"설치 실패, active.json·이전 세트는 그대로 / install failed, "
                                                  f"active.json and earlier sets unchanged: {exc}") from exc
        raise
    pointer_tmp = dest / f".{K.ACTIVE_NAME}.{uuid.uuid4().hex}.tmp"
    try:
        _write_file(pointer_tmp, K.pointer_bytes(set_hash))
        os.replace(pointer_tmp, dest / K.ACTIVE_NAME)
    except BaseException as exc:
        try:
            pointer_tmp.unlink()
        except FileNotFoundError:
            pass
        if isinstance(exc, OSError):
            raise ImportRefused("install_failed", f"active.json을 바꾸지 못함, 이전 활성 세트 그대로 / active.json was "
                                                  f"not replaced, the previous active set is unchanged (the complete "
                                                  f"new set {final} stays inactive): {exc}") from exc
        raise
    warnings = []
    try:
        _fsync_dir(dest)
    except OSError as exc:  # the rename is done; only its durability flush failed
        warnings.append(f"active.json was replaced but the folder flush failed: {exc}")
    return final, warnings


# ------------------------------------------------------------------------------------------- command line

def resolve_dest(option: str | os.PathLike | None, env_value: str | None) -> Path:
    """The option, else the environment value, else the default folder; a relative value is taken from the
    repository root (the server's rule for MW_PRECEDENT_REFERENCE_DIR)."""
    for value in (option, env_value):
        if value:
            path = Path(value).expanduser()
            return path if path.is_absolute() else ROOT / path
    return DEFAULT_DEST


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="import_precedent_snapshots.py", description=__doc__.split("\n\n")[0],
                                     allow_abbrev=False)
    parser.add_argument("--from", dest="kbase", required=True, metavar="PATH",
                        help="local kbase_kinase checkout (read only; its git HEAD is recorded)")
    parser.add_argument("--dest", metavar="PATH",
                        help=f"precedent reference folder (default ${K.ENV_VAR} or {DEFAULT_DEST}; a relative path "
                             "is taken from the repository root)")
    parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    return parser


def format_summary(result: dict[str, Any]) -> str:
    verified = result["verification"]["records_hash_verified"]
    lines = [
        "설치 완료 / Installed",
        f"- 폴더 / folder: {result['set_dir']}",
        f"- 세트 해시 / set hash: {result['set_hash']}",
        f"- 가져온 시각 / imported at: {result['imported_at']}",
        "- 행 수 / rows: " + ", ".join(f"{name} {rows}" for name, rows in result["rows"].items()),
        ("- 레코드 해시 재계산 일치 / verification: records_hash_verified "
         + ", ".join(f"{name} {count}" for name, count in verified.items())
         + f"; references_without_hash {result['verification']['references_without_hash']}"),
        f"- dirty: {str(result['dirty']).lower()} (kbase dist/·ref/pubmed/의 커밋되지 않은 변경 / uncommitted changes)",
    ]
    lines += [f"- 경고 / warning: {text}" for text in result["warnings"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dest = resolve_dest(args.dest, os.environ.get(K.ENV_VAR))
    try:
        run_import(Path(args.kbase), dest, yes=args.yes)  # prints the confirmation screen and the summary
    except ImportRefused as exc:
        print(f"가져오기 거절({exc.kind}), active.json·이전 세트는 그대로: {exc}\n"
              f"Import refused ({exc.kind}); active.json and earlier sets are unchanged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
