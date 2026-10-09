"""Tests for scripts/import_reaction_references.py (M26 T3, spec 4).

Every server response here is a SYNTHETIC FIXTURE (backend/tests/fixtures/reaction/t3/, SYNTHETIC-PROVENANCE-t3.md;
the isoform-located sites of T9a: reaction/t9a/, SYNTHETIC-PROVENANCE-t9a.md) served by an in-process fake transport
function. The real transport (``UrllibTransport``) is tested only against a
``127.0.0.1`` server opened by these tests. An autouse guard makes every other socket connection and every name lookup
fail, so no test can reach a public server.
"""
from __future__ import annotations

import ast
import copy
import datetime as dt
import hashlib
import http.server
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from scripts import import_reaction_references as imp

K = imp.K
REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "backend" / "tests" / "fixtures" / "reaction" / "t3"
SCRIPT = Path(imp.__file__).resolve()
NOW = dt.datetime(2026, 10, 8, 12, 0, 0, tzinfo=dt.timezone.utc)
LATER = dt.datetime(2026, 10, 8, 12, 0, 5, tzinfo=dt.timezone.utc)
SENTINEL = "SENTINEL-TOKEN-7f3a9c1b"
HEADERS = [("Content-Type", "application/json"), ("Set-Cookie", f"sid={SENTINEL}; Path=/"),
           ("Authorization", f"Bearer {SENTINEL}"), ("X-Api-Key", SENTINEL)]

# The request forms of spec 3.4 / 4.3, written out independently of the script's own URL builders.
MCSA = "https://www.ebi.ac.uk/thornton-srv/m-csa/api/entries/?format=json&page={}&page_size=100"
FIELDS = "accession,id,protein_name,organism_name,length,ec,ft_act_site,ft_binding,ft_site,cc_catalytic_activity"
BATCH = "https://rest.uniprot.org/uniprotkb/accessions?accessions={}&fields=" + FIELDS + "&format=json"
ENTRY = "https://rest.uniprot.org/uniprotkb/{}.json?fields=accession"
RHEA = "https://www.rhea-db.org/rhea?query=&columns=rhea-id,equation,chebi,chebi-id,ec&format=tsv&limit=20000"


# --- no public network --------------------------------------------------------------------------------------------

_LOOPBACK_PORTS: set[int] = set()


@pytest.fixture(autouse=True)
def no_public_network(monkeypatch):
    """Only the loopback servers these tests open may be connected to; every name lookup but 127.0.0.1 fails."""
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def allowed(address) -> bool:
        return isinstance(address, tuple) and address[0] == "127.0.0.1" and address[1] in _LOOPBACK_PORTS

    def connect(self, address):
        if not allowed(address):
            raise AssertionError(f"a test tried to connect to {address!r}")
        return real_connect(self, address)

    def connect_ex(self, address):
        raise AssertionError(f"a test tried to connect to {address!r}")

    def getaddrinfo(host, *args, **kwargs):
        if host != "127.0.0.1":
            raise AssertionError(f"a test tried to resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


# --- synthetic fake public servers --------------------------------------------------------------------------------

def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def acc(n: int) -> str:
    """A synthetic 10-character accession (spec 4.1 format, prefix A0SYN, not a real entry)."""
    return f"A0SYN{(n // 1000) % 10}T{n % 1000:03d}"


def ok_json(obj, status: int = 200):
    return status, list(HEADERS), json.dumps(obj).encode()


def ok_bytes(body: bytes, status: int = 200):
    return status, list(HEADERS), body


class FakeServer:
    """Exact URL -> queued responses (the last one repeats). Any other URL fails the test."""

    def __init__(self):
        self.routes: dict[str, list] = {}
        self.calls: list[str] = []

    def add(self, url: str, *responses) -> None:
        self.routes.setdefault(url, []).extend(responses)

    def replace(self, url: str, *responses) -> None:
        assert url in self.routes, url
        self.routes[url] = list(responses)

    def body(self, url: str):
        return json.loads(self.routes[url][0][2])

    def mutate(self, url: str, change) -> None:
        obj = self.body(url)
        change(obj)
        self.replace(url, ok_json(obj))

    def __call__(self, url: str):
        self.calls.append(url)
        queue = self.routes.get(url)
        assert queue, f"unexpected request {url}"
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        return item


def mcsa_pair(mcsa_id: int, ref: str, seq1: str, seq3: str):
    """Raw M-CSA entry and its hand-written processed row (templates with identifiers substituted)."""
    raw, want = load("mcsa_entry_raw.json"), load("mcsa_entry_processed.json")
    for obj in (raw, want):
        obj["mcsa_id"] = mcsa_id
        obj["reference_uniprot_id"] = ref
        obj["residues"][0]["residue_sequences"][0]["uniprot_id"] = seq1
        obj["residues"][2]["residue_sequences"][0]["uniprot_id"] = seq3
    for residue in raw["residues"]:
        residue["mcsa_id"] = mcsa_id
    return raw, want


def uniprot_pair(accession: str, *, trembl: bool = False):
    stem = "uniprot_entry_trembl" if trembl else "uniprot_entry"
    raw, want = load(f"{stem}_raw.json"), load(f"{stem}_processed.json")
    raw["primaryAccession"] = accession
    want["accession"] = accession
    return raw, want


def inactive(accession: str, kind: str):
    body = load("uniprot_inactive.json")[kind]
    if "primaryAccession" in body:
        body["primaryAccession"] = accession
    return ok_json(body, status=404 if kind == "NOT_FOUND" else 200)


class World:
    """A synthetic world: M-CSA entries, a UniProt with some missing accessions, the Rhea table."""

    def __init__(self, *, n_mcsa: int = 2, kinase=(), user=(), missing=None, trembl=(), page_reversed=False):
        self.server = FakeServer()
        entries = [mcsa_pair(7, "Q0SYT1, P0SYT2", "Q0SYT1", "Q0SYT3")]
        for i in range(1, n_mcsa):
            entries.append(mcsa_pair(10 * i + 3, acc(i), acc(i), acc(1000 + i)))
        self.mcsa_raw = [raw for raw, _ in entries]
        self.mcsa_rows = sorted((want for _, want in entries), key=lambda row: row["mcsa_id"])
        pages = -(-n_mcsa // 100)
        for page in range(1, pages + 1):
            results = self.mcsa_raw[(page - 1) * 100:page * 100]
            if page_reversed:
                results = results[::-1]
            nxt = MCSA.format(page + 1) if page < pages else None
            self.server.add(MCSA.format(page), ok_json({"count": n_mcsa, "next": nxt, "previous": None,
                                                        "results": results}))
        self.mcsa_accessions = sorted({a for row in self.mcsa_rows for a in K.entry_accessions(row)})
        self.kinase = sorted(set(kinase))
        self.user = sorted(set(user))
        self.union = sorted(set(self.mcsa_accessions) | set(self.kinase) | set(self.user))
        self.missing = dict(missing or {})
        self.uniprot_rows = []
        self.batches = [self.union[i:i + 1000] for i in range(0, len(self.union), 1000)]
        for chunk in self.batches:
            results = []
            for a in chunk:
                if a in self.missing:
                    continue
                raw, want = uniprot_pair(a, trembl=a in trembl)
                results.append(raw)
                self.uniprot_rows.append(want)
            self.server.add(BATCH.format(",".join(chunk)), ok_json({"results": results}))
        for a, responses in self.missing.items():
            self.server.add(ENTRY.format(a), *responses)
        self.rhea_tsv = (FIX / "rhea_reactions.tsv").read_bytes()
        self.rhea_rows = load("rhea_reactions_processed.json")
        self.server.add(RHEA, ok_bytes(self.rhea_tsv))

    def expected_calls(self, classified=None):
        pages = [MCSA.format(p) for p in range(1, -(-len(self.mcsa_raw) // 100) + 1)]
        batches = [BATCH.format(",".join(chunk)) for chunk in self.batches]
        classified = sorted(self.missing) if classified is None else classified
        return [*pages, *batches, *(ENTRY.format(a) for a in classified), RHEA]


class FakeTime:
    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def no_input(prompt):
    raise AssertionError("no confirmation expected with yes=True")


def params(tmp_path: Path, **kw):
    base = {"reference_dir": tmp_path / "reaction_reference", "m15_reference_dir": tmp_path / "m15-absent",
            "yes": True}
    base.update(kw)
    return imp.ImportParams(**base)


def run(world_or_server, p, *, now=NOW, timer=None, input_fn=no_input):
    server = world_or_server.server if isinstance(world_or_server, World) else world_or_server
    timer = timer or FakeTime()
    return imp.run_import(p, transport=server, sleep=timer.sleep, clock=timer.clock, now=lambda: now,
                          input_fn=input_fn)


def tree(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def manifest_of(ref: Path, set_hash: str) -> dict:
    return json.loads((ref / "sets" / set_hash / "manifest.json").read_bytes())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_m15(root: Path, accessions, *, tamper: str | None = None) -> str:
    """A synthetic M15 reference folder (reference_active@1 + reference_snapshot_set@1 + uniprot entries.jsonl)."""
    rows = [{"data": {"accession": a, "name": "SYNTHETIC kinase"}, "id": a, "reason": None, "status": "ok"}
            for a in accessions]
    rows.append({"data": None, "id": "Q0SYK9", "reason": "synthetic lookup failure", "status": "lookup_failed"})
    data = b"".join(K.jsonl_line(row) for row in rows)
    rel = "uniprot/2026-09-15/entries.jsonl"
    manifest = {"schema": "reference_snapshot_set@1", "imported_at": "2026-09-30T00:00:00.000000Z",
                "kbase_repo": {"commit": "0" * 40, "dirty": False},
                "sources": [{"source": "uniprot", "snapshot_id": "SYNTHETIC", "date": "2026-09-15",
                             "version_hint": None, "license": "CC-BY-4.0", "origin": "synthetic", "url_count": 0,
                             "raw_sha256": [],
                             "files": [{"name": "entries.jsonl", "path": rel, "sha256": sha(data),
                                        "bytes": len(data), "rows": len(rows), "use": "product"}]}]}
    raw = K.canonical_json(manifest)
    set_hash = sha(raw)
    set_dir = root / "sets" / set_hash
    (set_dir / "files" / rel).parent.mkdir(parents=True)
    (set_dir / "files" / rel).write_bytes(data + (b"x" if tamper == "file" else b""))
    (set_dir / "manifest.json").write_bytes(raw + (b" " if tamper == "manifest" else b""))
    (root / "active.json").write_bytes(K.canonical_json({"schema": "reference_active@1", "set_hash": set_hash}))
    return set_hash


def big_world(**kw) -> World:
    """250 M-CSA entries (3 pages), 600+ kinase accessions, user-named ones: more than 1000 accessions (2 batches)."""
    missing = {acc(5): [inactive(acc(5), "DELETED")], acc(6): [inactive(acc(6), "MERGED")],
               acc(7): [inactive(acc(7), "NOT_FOUND")], acc(8): [ok_bytes(b"synthetic error", 500)],
               acc(2005): [inactive(acc(2005), "DEMERGED")]}
    kinase = [acc(n) for n in range(2000, 2600)] + [acc(1), acc(2)]
    base = {"n_mcsa": 250, "kinase": kinase, "user": [acc(3000), acc(1)], "missing": missing,
            "trembl": {acc(9), "P0SYT2"}, "page_reversed": True}
    base.update(kw)
    return World(**base)


# --- validate_url ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [MCSA.format(1), BATCH.format("P0SYT2,Q0SYT1"), ENTRY.format("Q0SYT1"), RHEA])
def test_validate_url_accepts_the_request_forms(url):
    assert imp.validate_url(url) in K.ALLOWED_HOSTS


@pytest.mark.parametrize("url", [
    "http://www.ebi.ac.uk/thornton-srv/m-csa/api/entries/",           # not https
    "HTTPS://www.ebi.ac.uk/thornton-srv/m-csa/api/entries/",          # scheme spelled differently
    "ftp://www.ebi.ac.uk/x", "file:///etc/passwd", "//www.ebi.ac.uk/x", "www.ebi.ac.uk/x",
    "https://evil.example/x",                                          # foreign host
    "https://ftp.expasy.org/databases/rhea/", "https://api.rhea-db.org/x", "https://files.rcsb.org/download/1S9I.cif",
    "https://ebi.ac.uk/x", "https://www.ebi.ac.uk.evil.example/x", "https://evilwww.ebi.ac.uk/x",
    "https://www-ebi.ac.uk/x", "https://rest.uniprot.org.evil.example/x",
    "https://WWW.EBI.AC.UK/x", "https://Rest.UniProt.org/x",           # case differs
    "https://www.ebi.ac.uk./x", "https://rest.uniprot.org./x",          # trailing dot
    "https://user@www.ebi.ac.uk/x", "https://user:pw@rest.uniprot.org/x", "https://www.ebi.ac.uk@evil.example/x",
    "https://www.ebi.ac.uk:443/x", "https://www.ebi.ac.uk:8443/x", "https://rest.uniprot.org:/x",
    "https://www.ebi.ac.uk/x#fragment", "https://www.ebi.ac.uk/#",
    "https://www.ebi.ac.uk", "https://www.ebi.ac.uk?x=1", "https://", "",
    "https://www.ebi.ac.uk/x y", "https://www.ebi.ac.uk/x\n", "https://www.ebi.ac.uk\\@evil.example/",
    "https://www.ebi.ac.uk/%2e%2e/", "https://www.ebi.ac.uk/@evil.example", "https://www.ebi.ac.uk/x;y",
    "https://www.ebı.ac.uk/x",                                          # non-ASCII look-alike
    "https://[::1]/x", "https://127.0.0.1/x", "http://127.0.0.1:8000/x",
])
def test_validate_url_refuses(url):
    with pytest.raises(imp.UrlRefused):
        imp.validate_url(url)


def test_validate_url_refuses_non_strings():
    for value in (None, b"https://www.ebi.ac.uk/x", 1):
        with pytest.raises(imp.UrlRefused):
            imp.validate_url(value)


def test_url_builders_match_the_spec_forms():
    assert imp.mcsa_page_url(3) == MCSA.format(3)
    assert imp.uniprot_batch_url(["P0SYT2", "Q0SYT1"]) == BATCH.format("P0SYT2,Q0SYT1")
    assert imp.uniprot_entry_url("Q0SYT1") == ENTRY.format("Q0SYT1")
    assert imp.RHEA_URL == RHEA
    with pytest.raises(ValueError):
        imp.uniprot_entry_url("q0syt1/../x")


# --- normal import ----------------------------------------------------------------------------------------------------

def test_normal_import_pages_batches_three_sources_and_installs(tmp_path, capsys):
    world = big_world()
    m15 = tmp_path / "m15"
    kinase_hash = write_m15(m15, world.kinase)
    p = params(tmp_path, m15_reference_dir=m15, accessions=(acc(3000), acc(1), acc(3000)))
    result = run(world, p)
    ref = p.reference_dir
    # Requests: pages 1..3, two ascending batches (1000 + rest), one classification per missing accession (the
    # 500 one three times), Rhea once. Nothing else.
    assert len(world.union) > 1000 and [len(b) for b in world.batches] == [1000, len(world.union) - 1000]
    classified = [acc(5), acc(6), acc(7), acc(8), acc(8), acc(8), acc(2005)]
    assert world.server.calls == world.expected_calls(classified)
    set_hash = result["set_hash"]
    assert json.loads((ref / "active.json").read_bytes()) == {"schema": "reaction_active@1", "set_hash": set_hash}
    raw = (ref / "sets" / set_hash / "manifest.json").read_bytes()
    assert sha(raw) == set_hash and raw == K.canonical_json(json.loads(raw))
    manifest = json.loads(raw)
    K.validate_manifest(manifest)
    assert manifest["imported_at"] == "2026-10-08T12:00:00Z" and manifest["importer_version"] == "reaction_import/1"
    for record in manifest["sources"]:
        assert (record["date"], record["license"], record["license_url"], record["origin"]) == (
            "2026-10-08", "CC-BY-4.0", "https://creativecommons.org/licenses/by/4.0/", "public server import")
    # Processed rows are exactly the hand-written expectations, in the fixed order, and round-trip.
    set_dir = ref / "sets" / set_hash
    files = {s["source"]: s["files"][0] for s in manifest["sources"]}
    assert [f["path"] for f in files.values()] == ["files/mcsa/entries.jsonl", "files/uniprot_function/entries.jsonl",
                                                    "files/rhea/reactions.jsonl"]
    expected = {"mcsa": world.mcsa_rows, "uniprot_function": sorted(world.uniprot_rows, key=lambda r: r["accession"]),
                "rhea": world.rhea_rows}
    for source, entry in files.items():
        data = (set_dir / entry["path"]).read_bytes()
        assert (entry["sha256"], entry["bytes"], entry["rows"]) == (sha(data), len(data), len(expected[source]))
        assert K.decode_jsonl(source, data) == expected[source]
        assert data == b"".join(K.jsonl_line(row) for row in expected[source])
    # requested / skipped accessions
    req = manifest["requested_accessions"]
    assert req == {"from_mcsa": len(world.mcsa_accessions), "union_count": len(world.union),
                   "from_m15_kinase_set": {"set_hash": kinase_hash, "count": len(world.kinase)},
                   "m15_kinase_list": "present", "user_named": [acc(1), acc(3000)], "dropped_previous_user_named": []}
    assert manifest["skipped_accessions"] == [
        {"accession": acc(5), "reason": "obsolete", "target_accessions": []},
        {"accession": acc(6), "reason": "merged", "target_accessions": ["Q0SYU9"]},
        {"accession": acc(7), "reason": "not_found", "target_accessions": []},
        {"accession": acc(8), "reason": "fetch_failed", "target_accessions": []},
        {"accession": acc(2005), "reason": "demerged", "target_accessions": ["P0SYU1", "Q0SYU2"]},
    ]
    # Request log: one row per attempt, in request order; raw digests per source over the body hashes.
    log_bytes = (set_dir / "files" / "request_log.jsonl").read_bytes()
    log = [json.loads(line) for line in log_bytes.splitlines()]
    assert manifest["request_log"] == {"name": "request_log.jsonl", "path": "files/request_log.jsonl",
                                       "sha256": sha(log_bytes), "bytes": len(log_bytes), "rows": len(log)}
    assert [row["url"] for row in log] == world.server.calls
    assert [row["seq"] for row in log] == list(range(1, len(log) + 1))
    assert all(set(row) == {"seq", "source", "method", "url", "status", "bytes", "sha256"} for row in log)
    assert {row["method"] for row in log} == {"GET"}
    assert [row["status"] for row in log] == [200] * 5 + [200, 200, 404, 500, 500, 500, 200, 200]
    bodies = [world.server.routes[url][0][2] for url in world.server.calls]
    assert [(row["bytes"], row["sha256"]) for row in log] == [(len(b), sha(b)) for b in bodies]
    for record in manifest["sources"]:
        mine = [row["sha256"] for row in log if row["source"] == record["source"]]
        assert record["raw_response_count"] == len(mine)
        assert record["raw_sha256_digest"] == sha("\n".join(mine).encode())
    assert [r["raw_response_count"] for r in manifest["sources"]] == [3, 9, 1]
    # Output: folder, set hash, rows per source, skipped list, request count.
    out = capsys.readouterr().out
    for text in (str(set_dir), set_hash, "mcsa 250", f"uniprot_function {len(world.uniprot_rows)}", "rhea 3",
                 f"{acc(6)} merged", "Q0SYU9", "13", "MAX_ACCESSIONS"):
        assert text in out, text
    assert result["request_count"] == 13 and result["rows"] == {"mcsa": 250, "uniprot_function": len(world.union) - 5,
                                                                 "rhea": 3}
    assert not any(p.name.startswith(".") for p in (ref / "sets").iterdir())
    assert not any(p.name.endswith(".tmp") for p in ref.iterdir())


def test_installed_set_pins_and_indexes_on_the_server_modules(tmp_path):
    from mw import reaction_knowledge, reaction_snapshots

    world = World(n_mcsa=3)
    p = params(tmp_path)
    result = run(world, p)
    pinned = reaction_snapshots.pin_active_set(p.reference_dir)
    assert pinned.set_hash == result["set_hash"]
    pinned2, index = reaction_knowledge.pin_and_index(p.reference_dir)
    assert pinned2.set_hash == result["set_hash"]
    assert [e["mcsa_id"] for e in reaction_knowledge.pdb_entries(index, "0SY7")] == [7, 13, 23]


def test_canonical_json_is_the_core_handles_formula():
    from mw.core.handles import canonical_json

    for obj in ({"b": [1, 2.5, None], "a": "촉매 é ☃", "c": {"z": True, "y": ""}}, [], "x", {"k": -0.0}):
        assert imp.K.canonical_json(obj) == canonical_json(obj)


def test_mapping_functions_match_hand_written_rows():
    raw, want = mcsa_pair(7, "Q0SYT1, P0SYT2", "Q0SYT1", "Q0SYT3")
    assert imp.mcsa_row(raw) == want
    for trembl in (False, True):
        raw, want = uniprot_pair("Q0SYT1", trembl=trembl)
        assert imp.uniprot_row(raw, {"Q0SYT1"}) == want
    assert imp.rhea_rows((FIX / "rhea_reactions.tsv").read_bytes()) == load("rhea_reactions_processed.json")
    # Windows line ends and a missing final newline give the same rows.
    tsv = (FIX / "rhea_reactions.tsv").read_bytes()
    assert imp.rhea_rows(tsv.replace(b"\n", b"\r\n")) == imp.rhea_rows(tsv.rstrip(b"\n")) == imp.rhea_rows(tsv)
    # Header only: no rows. Both ChEBI columns empty: no participants (verbatim, nothing invented).
    assert imp.rhea_rows(TSV_HEADER) == []
    assert imp.rhea_rows(TSV_HEADER + b"RHEA:5\tsynthetic = synthetic\t\t\t\n") == [
        {"rhea_id": "RHEA:5", "equation": "synthetic = synthetic", "ec_numbers": [], "participants": []}]


def test_same_responses_give_the_same_processed_bytes_and_a_new_set_hash(tmp_path):
    world = World(n_mcsa=120, page_reversed=True, missing={acc(5): [inactive(acc(5), "DELETED")]})
    p = params(tmp_path, accessions=("Q0SYT1",))
    first = run(world, p, now=NOW)
    second = run(world, p, now=LATER)
    assert first["set_hash"] != second["set_hash"]
    ref = p.reference_dir
    a, b = manifest_of(ref, first["set_hash"]), manifest_of(ref, second["set_hash"])
    assert a["imported_at"] != b["imported_at"]
    assert {**b, "imported_at": a["imported_at"]} == a  # only imported_at differs
    comparison = imp.compare_manifests(a, b)
    assert comparison["reproduced"] is True and comparison["raw_differences"] == []
    assert [f["same"] for f in comparison["files"]] == [True, True, True]
    for name in ("mcsa/entries.jsonl", "uniprot_function/entries.jsonl", "rhea/reactions.jsonl"):
        assert ((ref / "sets" / first["set_hash"] / "files" / name).read_bytes()
                == (ref / "sets" / second["set_hash"] / "files" / name).read_bytes())
    # The first set is still there, untouched; the second is active.
    assert sorted(p.name for p in (ref / "sets").iterdir()) == sorted([first["set_hash"], second["set_hash"]])
    assert json.loads((ref / "active.json").read_bytes())["set_hash"] == second["set_hash"]


def test_compare_manifests_reports_raw_differences_without_failing(tmp_path):
    world = World(n_mcsa=2)
    p = params(tmp_path)
    first = run(world, p, now=NOW)
    # Same content, different raw bytes (key order / white space of the JSON page): processed rows are the same.
    page = world.server.body(MCSA.format(1))
    world.server.replace(MCSA.format(1), ok_bytes(json.dumps(page, indent=1, sort_keys=True).encode()))
    second = run(world, p, now=LATER)
    a, b = manifest_of(p.reference_dir, first["set_hash"]), manifest_of(p.reference_dir, second["set_hash"])
    comparison = imp.compare_manifests(a, b)
    assert comparison["reproduced"] is True
    assert [d["source"] for d in comparison["raw_differences"]] == ["mcsa"]
    # A changed processed file is not a reproduction.
    third_world = World(n_mcsa=3)
    third = run(third_world, p, now=LATER + dt.timedelta(seconds=1))
    c = manifest_of(p.reference_dir, third["set_hash"])
    comparison = imp.compare_manifests(a, c)
    assert comparison["reproduced"] is False
    assert [f["same"] for f in comparison["files"]] == [False, False, True]
    with pytest.raises(K.FormatError):
        imp.compare_manifests(a, {**c, "schema": "x"})


# --- retries, back-off, host interval -------------------------------------------------------------------------------

def test_429_and_5xx_are_retried_with_exponential_backoff_and_host_interval(tmp_path):
    world = World(n_mcsa=250)
    world.server.routes[MCSA.format(2)][0:0] = [ok_bytes(b"busy", 503), ok_bytes(b"slow down", 429)]
    timer = FakeTime()
    result = run(world, params(tmp_path), timer=timer)
    pages = [MCSA.format(1), MCSA.format(2), MCSA.format(2), MCSA.format(2), MCSA.format(3)]
    assert world.server.calls[:5] == pages
    # page 2 waits the host interval, then backs off 2 s and 4 s; page 3 waits the interval; other hosts do not wait.
    assert timer.sleeps == [1.0, 2.0, 4.0, 1.0]
    log_path = tmp_path / "reaction_reference" / "sets" / result["set_hash"] / "files" / "request_log.jsonl"
    log = [json.loads(line) for line in log_path.read_bytes().splitlines()]
    assert [row["status"] for row in log[:5]] == [200, 503, 429, 200, 200]
    assert len(log) == len(world.server.calls) == 7


def test_requests_to_one_host_keep_the_minimum_interval(tmp_path):
    world = World(n_mcsa=2, missing={"Q0SYT3": [inactive("Q0SYT3", "DELETED")],
                                     "P0SYT2": [inactive("P0SYT2", "DELETED")]})
    timer = FakeTime()
    run(world, params(tmp_path, min_interval_seconds=3.0), timer=timer)
    # mcsa (no wait), uniprot batch (other host), two classifications on the UniProt host (3 s each), rhea.
    assert timer.sleeps == [3.0, 3.0]


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retry_limit_then_abort_and_nothing_written(tmp_path, status):
    world = World(n_mcsa=2)
    world.server.replace(RHEA, ok_bytes(b"synthetic failure", status))
    timer = FakeTime()
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path), timer=timer)
    assert info.value.kind == "fetch_failed"
    assert world.server.calls.count(RHEA) == 3  # one request + two retries
    assert timer.sleeps[-2:] == [2.0, 4.0]
    assert not (tmp_path / "reaction_reference").exists()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 400, 403, 404, 410])
def test_other_statuses_are_not_retried(tmp_path, status):
    world = World(n_mcsa=2)
    world.server.replace(MCSA.format(1), ok_bytes(b"synthetic", status))
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path))
    assert info.value.kind == "fetch_failed" and world.server.calls == [MCSA.format(1)]
    assert not (tmp_path / "reaction_reference").exists()


def test_transport_failure_is_not_retried(tmp_path):
    world = World(n_mcsa=2)
    world.server.replace(BATCH.format(",".join(world.union)), imp.TransportError("synthetic timeout"))
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path))
    assert info.value.kind == "fetch_failed"
    assert world.server.calls.count(BATCH.format(",".join(world.union))) == 1
    assert not (tmp_path / "reaction_reference").exists()


def test_a_url_the_transport_refuses_is_a_refusal_not_a_request(tmp_path):
    world = World(n_mcsa=2)
    world.server.replace(RHEA, imp.UrlRefused("synthetic refusal"))
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path))
    assert info.value.kind == "fetch_failed" and not (tmp_path / "reaction_reference").exists()


def test_a_transport_failure_on_a_classification_is_a_logged_fetch_failed_skip(tmp_path):
    world = World(n_mcsa=2, missing={"Q0SYT3": [imp.TransportError("synthetic reset")]})
    result = run(world, params(tmp_path))
    manifest = manifest_of(tmp_path / "reaction_reference", result["set_hash"])
    assert manifest["skipped_accessions"] == [{"accession": "Q0SYT3", "reason": "fetch_failed",
                                               "target_accessions": []}]
    log = (tmp_path / "reaction_reference" / "sets" / result["set_hash"] / "files" / "request_log.jsonl").read_bytes()
    row = [json.loads(line) for line in log.splitlines()][-2]
    assert (row["url"], row["status"], row["bytes"], row["sha256"]) == (ENTRY.format("Q0SYT3"), 0, 0, sha(b""))


# --- format errors: nothing is written -------------------------------------------------------------------------------

def _page1(change):
    return lambda world: world.server.mutate(MCSA.format(1), change)


def _first_entry(change):
    return _page1(lambda page: change(page["results"][0]))


def _batch(change):
    return lambda world: world.server.mutate(BATCH.format(",".join(world.union)), change)


def _first_result(change):
    return _batch(lambda body: change(body["results"][0]))


def _rhea(text: bytes):
    return lambda world: world.server.replace(RHEA, ok_bytes(text))


def _feature(change):
    return _first_result(lambda result: change(result["features"][0]))


TSV_HEADER = b"Reaction identifier\tEquation\tChEBI name\tChEBI identifier\tEC number\n"

FORMAT_ERRORS = {
    # M-CSA
    "mcsa_not_json": lambda w: w.server.replace(MCSA.format(1), ok_bytes(b"<html>synthetic</html>")),
    "mcsa_nan": lambda w: w.server.replace(MCSA.format(1), ok_bytes(b'{"count": NaN}')),
    "mcsa_duplicate_key": lambda w: w.server.replace(
        MCSA.format(1), ok_bytes(b'{"count":1,"count":2,"next":null,"previous":null,"results":[]}')),
    "mcsa_envelope_unknown_key": _page1(lambda page: page.update(extra=1)),
    "mcsa_envelope_missing_key": _page1(lambda page: page.pop("previous")),
    "mcsa_zero_count": _page1(lambda page: page.update(count=0, results=[])),
    "mcsa_count_bool": _page1(lambda page: page.update(count=True)),
    "mcsa_short_page": _page1(lambda page: page["results"].pop()),
    "mcsa_entry_unknown_field": _first_entry(lambda entry: entry.update(new_field="x")),
    "mcsa_entry_missing_field": _first_entry(lambda entry: entry.pop("enzyme_name")),
    "mcsa_residue_unknown_field": _first_entry(lambda entry: entry["residues"][0].update(extra="")),
    "mcsa_chain_missing_field": _first_entry(lambda entry: entry["residues"][0]["residue_chains"][0].pop("code")),
    "mcsa_assembly_text": _first_entry(lambda entry: entry["residues"][0]["residue_chains"][0].update(assembly="2")),
    "mcsa_pdb_upper_case": _first_entry(lambda entry: entry["residues"][0]["residue_chains"][0].update(pdb_id="0SY7")),
    "mcsa_bad_reference_accession": _first_entry(lambda entry: entry.update(reference_uniprot_id="Q0SYT1, nope")),
    "mcsa_bad_sequence_accession": _first_entry(
        lambda entry: entry["residues"][0]["residue_sequences"][0].update(uniprot_id="q0syt1")),
    "mcsa_id_float": _first_entry(lambda entry: entry.update(mcsa_id=7.0)),
    "mcsa_compound_unknown_field": _first_entry(lambda entry: entry["reaction"]["compounds"][0].update(smiles="C")),
    "mcsa_duplicate_id": _first_entry(lambda entry: entry.update(mcsa_id=13)),
    # UniProt
    "uniprot_not_json": lambda w: w.server.replace(BATCH.format(",".join(w.union)), ok_bytes(b"synthetic")),
    "uniprot_envelope_extra": _batch(lambda body: body.update(failedIds=[])),
    "uniprot_unexpected_accession": _first_result(lambda result: result.update(primaryAccession="Q0SYZ9")),
    "uniprot_duplicate_accession": _batch(lambda body: body["results"].append(copy.deepcopy(body["results"][0]))),
    "uniprot_unknown_top_field": _first_result(lambda result: result.update(secondaryAccessions=["Q0SYZ8"])),
    "uniprot_missing_entry_name": _first_result(lambda result: result.pop("uniProtkbId")),
    "uniprot_feature_outside": _feature(lambda f: f["location"]["start"].update(modifier="OUTSIDE")),
    "uniprot_feature_unknown_position": _feature(lambda f: f["location"].update(end={"modifier": "UNKNOWN"})),
    "uniprot_feature_text_position": _feature(lambda f: f["location"]["end"].update(value="40")),
    "uniprot_feature_isoform": _feature(lambda f: f["location"].update(sequence="Q0SYT1-2")),
    "uniprot_feature_unknown_field": _feature(lambda f: f.update(alternativeSequence={})),
    "uniprot_feature_start_after_end": _feature(lambda f: f["location"]["start"].update(value=41)),
    "uniprot_ligand_unknown_field": _first_result(lambda r: r["features"][1]["ligand"].update(extra="x")),
    "uniprot_activity_unknown_field": _first_result(lambda r: r["comments"][0].update(note="x")),
    "uniprot_xref_unknown_field": _first_result(
        lambda r: r["comments"][0]["reaction"]["reactionCrossReferences"][0].update(extra="x")),
    "uniprot_bad_chebi": _first_result(
        lambda r: r["comments"][0]["reaction"]["reactionCrossReferences"].append({"database": "ChEBI", "id": "993"})),
    "uniprot_length_text": _first_result(lambda result: result["sequence"].update(length="120")),
    # Rhea
    "rhea_header": _rhea(TSV_HEADER.replace(b"EC number", b"EC") + b"RHEA:1\tx = y\ta\tCHEBI:1\t\n"),
    "rhea_header_order": _rhea(TSV_HEADER.replace(b"ChEBI name\tChEBI identifier", b"ChEBI identifier\tChEBI name")),
    "rhea_four_columns": _rhea(TSV_HEADER + b"RHEA:1\tx = y\ta\tCHEBI:1\n"),
    "rhea_six_columns": _rhea(TSV_HEADER + b"RHEA:1\tx = y\ta\tCHEBI:1\t\textra\n"),
    "rhea_pairing": _rhea(TSV_HEADER + b"RHEA:1\tx = y\ta;b\tCHEBI:1\t\n"),
    "rhea_ec_prefix": _rhea(TSV_HEADER + b"RHEA:1\tx = y\ta\tCHEBI:1\t9.99.3.1\n"),
    "rhea_bad_id": _rhea(TSV_HEADER + b"RHEA-COMP:1\tx = y\ta\tCHEBI:1\t\n"),
    "rhea_duplicate": _rhea(TSV_HEADER + b"RHEA:1\tx = y\ta\tCHEBI:1\t\nRHEA:1\tx = y\ta\tCHEBI:1\t\n"),
    "rhea_blank_line": _rhea(TSV_HEADER + b"RHEA:1\tx = y\ta\tCHEBI:1\t\n\nRHEA:2\tx = y\ta\tCHEBI:1\t\n"),
    "rhea_not_utf8": _rhea(TSV_HEADER + b"RHEA:1\tx \xff y\ta\tCHEBI:1\t\n"),
    "rhea_empty": _rhea(b""),
    "rhea_rows_at_limit": _rhea(TSV_HEADER + b"".join(b"RHEA:%d\tx = y\ta\tCHEBI:1\t\n" % n
                                                      for n in range(1, 20001))),
}


@pytest.mark.parametrize("name", sorted(FORMAT_ERRORS))
def test_format_errors_abort_and_write_nothing(tmp_path, name):
    world = World(n_mcsa=2)
    FORMAT_ERRORS[name](world)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path))
    assert info.value.kind == "format_error", info.value
    assert not (tmp_path / "reaction_reference").exists()


def test_count_mismatch_between_pages_and_short_total_abort(tmp_path):
    for change in (lambda page: page.update(count=251), lambda page: page["results"].pop()):
        world = World(n_mcsa=250)
        world.server.mutate(MCSA.format(2), change)
        with pytest.raises(imp.ImportRefused) as info:
            run(world, params(tmp_path))
        assert info.value.kind == "format_error"
        assert not (tmp_path / "reaction_reference").exists()


def test_duplicate_mcsa_id_across_pages_aborts(tmp_path):
    world = World(n_mcsa=150)
    world.server.mutate(MCSA.format(2), lambda page: page["results"][0].update(mcsa_id=7))
    with pytest.raises(imp.ImportRefused, match="mcsa_id") as info:
        run(world, params(tmp_path))
    assert info.value.kind == "format_error"


def test_next_links_are_never_followed(tmp_path):
    world = World(n_mcsa=150)
    world.server.mutate(MCSA.format(1), lambda page: page.update(next="https://evil.example/page2"))
    run(world, params(tmp_path))
    assert world.server.calls[:2] == [MCSA.format(1), MCSA.format(2)]


def test_format_error_leaves_an_existing_set_untouched(tmp_path):
    p = params(tmp_path)
    run(World(n_mcsa=2), p, now=NOW)
    before = tree(p.reference_dir)
    world = World(n_mcsa=2)
    FORMAT_ERRORS["uniprot_feature_outside"](world)
    with pytest.raises(imp.ImportRefused):
        run(world, p, now=LATER)
    assert tree(p.reference_dir) == before


def test_dropped_raw_fields_never_reach_the_processed_files(tmp_path):
    world = World(n_mcsa=2)
    result = run(world, params(tmp_path))
    set_dir = tmp_path / "reaction_reference" / "sets" / result["set_hash"]
    text = b"".join(tree(set_dir).values()).decode()
    for dropped in ("mol_file", "SYNTHETIC mol block", "mechanisms", "is_polymeric", "main_annotation", "domain_name",
                    "9.99.99.99", "is_reference_uniprot_id", "fixture.invalid", "dropped by the importer",
                    "physiologicalReactions", "RHEA:93003", "RHEA-COMP", "ligandPart", "CHEBI:993199",
                    "synthetic note", "Synthetic isoform 2", "evidences", "ECO:9999999", "UPISYNTHETIC",
                    "taxonId", "synthetic fixture organism", "UniProtKB reviewed", "featureCrossReferences"):
        assert dropped not in text, dropped


# --- isoform-located sites (T9a, user decision 2026-10-09; fixtures/reaction/t9a, SYNTHETIC-PROVENANCE-t9a.md) ----

FIX_T9A = REPO / "backend" / "tests" / "fixtures" / "reaction" / "t9a"


def _isoform_pair():
    raw = json.loads((FIX_T9A / "uniprot_entry_isoform_raw.json").read_text(encoding="utf-8"))
    want = json.loads((FIX_T9A / "uniprot_entry_isoform_processed.json").read_text(encoding="utf-8"))
    return raw, want


def _with_entry(world: World, raw, want=None) -> None:
    """Replace the batch result of ``raw``'s accession by ``raw`` (and its expected row by ``want``)."""
    def change(body):
        (i,) = [n for n, r in enumerate(body["results"]) if r["primaryAccession"] == raw["primaryAccession"]]
        body["results"][i] = raw

    world.server.mutate(BATCH.format(",".join(world.union)), change)
    if want is not None:
        world.uniprot_rows = [want if r["accession"] == want["accession"] else r for r in world.uniprot_rows]


def test_isoform_located_sites_of_the_same_accession_are_skipped_and_counted():
    raw, want = _isoform_pair()
    skipped: list[str] = []
    assert imp.uniprot_row(copy.deepcopy(raw), {"Q0SYT1"}, skipped) == want
    assert skipped == ["Q0SYT1", "Q0SYT1"]
    assert imp.uniprot_row(raw, {"Q0SYT1"}) == want


def test_an_import_with_isoform_located_sites_installs_the_rest_and_prints_only_the_count(tmp_path, capsys):
    world = World(n_mcsa=2)
    _with_entry(world, *_isoform_pair())
    result = run(world, params(tmp_path))
    assert result["isoform_sites_skipped"] == 2
    set_dir = tmp_path / "reaction_reference" / "sets" / result["set_hash"]
    data = (set_dir / "files" / "uniprot_function" / "entries.jsonl").read_bytes()
    assert K.decode_jsonl("uniprot_function", data) == sorted(world.uniprot_rows, key=lambda r: r["accession"])
    assert "isoform-located sites not stored: 2" in capsys.readouterr().out
    K.validate_manifest(manifest_of(tmp_path / "reaction_reference", result["set_hash"]))  # fixed key set
    text = b"".join(tree(set_dir).values()).decode()
    for absent in ("Q0SYT1-2", "Q0SYT1-3", "isoform_sites", "Synthetic isoform-only site text"):
        assert absent not in text, absent


def test_the_isoform_count_is_printed_as_zero_when_nothing_is_skipped(tmp_path, capsys):
    result = run(World(n_mcsa=2), params(tmp_path))
    assert result["isoform_sites_skipped"] == 0
    assert "isoform-located sites not stored: 0" in capsys.readouterr().out


@pytest.mark.parametrize("index, change", [
    pytest.param(1, lambda loc: loc.update(sequence="P0SYT2-2"), id="isoform_of_another_accession"),
    pytest.param(1, lambda loc: loc.update(sequence="Q0SYT1"), id="no_isoform_number"),
    pytest.param(1, lambda loc: loc.update(sequence="Q0SYT1-2a"), id="malformed_isoform"),
    pytest.param(1, lambda loc: loc.update(sequence="q0syt1-2"), id="other_case"),
    pytest.param(1, lambda loc: loc.update(sequence=2), id="not_a_string"),
    pytest.param(1, lambda loc: loc.update(extra="x"), id="extra_key_beside_the_isoform"),
    pytest.param(0, lambda loc: loc.update(extra="x"), id="extra_key_on_a_canonical_site"),
])
def test_other_isoform_values_and_unknown_location_keys_stay_format_errors(tmp_path, index, change):
    world = World(n_mcsa=2)
    raw, _ = _isoform_pair()
    change(raw["features"][index]["location"])
    _with_entry(world, raw)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path))
    assert info.value.kind == "format_error", info.value
    assert not (tmp_path / "reaction_reference").exists()


# --- user-named accessions --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["q0syt1", "Q0SYT", "Q0SYT1 ", "P0SYT2,Q0SYT1", "", "Q0SYT1/../x", "ABC123"])
def test_user_named_format_is_checked_before_any_request(tmp_path, bad):
    world = World(n_mcsa=2)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path, accessions=("Q0SYT1", bad)))
    assert info.value.kind == "invalid_input" and world.server.calls == []


def test_accessions_file_is_read_validated_and_merged(tmp_path):
    good = tmp_path / "named.txt"
    good.write_text("Q0SYT1\n\n  P0SYT2  \nQ0SYT1\n", encoding="utf-8")
    world = World(n_mcsa=2, user=["Q0SYT1", "P0SYT2", acc(3000)])
    result = run(world, params(tmp_path, accessions=(acc(3000),), accessions_file=good))
    assert result["requested_accessions"]["user_named"] == sorted(["P0SYT2", "Q0SYT1", acc(3000)])
    bad = tmp_path / "bad.txt"
    bad.write_text("Q0SYT1\nnot-an-accession\n", encoding="utf-8")
    other = World(n_mcsa=2)
    for path in (bad, tmp_path / "missing.txt"):
        with pytest.raises(imp.ImportRefused) as info:
            run(other, params(tmp_path, accessions_file=path))
        assert info.value.kind == "invalid_input"
    assert other.server.calls == []


@pytest.mark.parametrize("kind,reason,targets", [
    ("DELETED", "obsolete", []), ("MERGED", "merged", ["Q0SYU9"]), ("DEMERGED", "demerged", ["P0SYU1", "Q0SYU2"]),
    ("NOT_FOUND", "not_found", []), ("UNKNOWN_REASON", "fetch_failed", []),
])
def test_a_missing_user_named_accession_refuses_the_whole_command(tmp_path, capsys, kind, reason, targets):
    named = acc(3001)
    world = World(n_mcsa=2, user=[named], missing={named: [inactive(named, kind)],
                                                    "Q0SYT3": [inactive("Q0SYT3", "DELETED")]})
    p = params(tmp_path, accessions=(named,))
    with pytest.raises(imp.ImportRefused) as info:
        run(world, p)
    assert info.value.kind == "user_named_unavailable"
    text = str(info.value) + "\n".join(info.value.details)
    assert named in text and reason in text and all(t in text for t in targets)
    # No automatic replacement, no install, and the derived missing accession was not even classified.
    assert ENTRY.format("Q0SYT3") not in world.server.calls and ENTRY.format(named) in world.server.calls
    assert RHEA not in world.server.calls
    assert not (tmp_path / "reaction_reference").exists()


def test_user_named_failures_do_not_count_against_the_skip_cap(tmp_path):
    named = acc(3001)
    world = World(n_mcsa=2, user=[named], missing={named: [inactive(named, "MERGED")]})
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path, accessions=(named,), max_skipped=0))
    assert info.value.kind == "user_named_unavailable"


def test_many_missing_user_named_accessions_are_refused_without_classifying_them(tmp_path, monkeypatch):
    named = [acc(3001), acc(3002)]
    world = World(n_mcsa=2, user=named, missing={a: [inactive(a, "DELETED")] for a in named})
    monkeypatch.setattr(imp, "MAX_USER_NAMED_CHECKS", 1)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path, accessions=tuple(named)))
    assert info.value.kind == "user_named_unavailable" and all(a in "\n".join(info.value.details) for a in named)
    assert not any(url.endswith("?fields=accession") for url in world.server.calls)
    assert imp.MAX_USER_NAMED_CHECKS == 1 and K.MAX_SKIPPED == 50


def test_a_missing_user_named_accession_that_m_csa_also_names_still_refuses(tmp_path):
    world = World(n_mcsa=2, user=["Q0SYT3"], missing={"Q0SYT3": [inactive("Q0SYT3", "DELETED")]})
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path, accessions=("Q0SYT3",)))
    assert info.value.kind == "user_named_unavailable"


# --- derived skips and caps -------------------------------------------------------------------------------------------

def test_classification_outcomes_for_derived_accessions(tmp_path):
    missing = {
        acc(1): [inactive(acc(1), "DELETED")],
        acc(2): [inactive(acc(2), "MERGED")],
        acc(3): [inactive(acc(3), "DEMERGED")],
        acc(4): [inactive(acc(4), "NOT_FOUND")],
        acc(5): [inactive(acc(5), "UNKNOWN_REASON")],
        acc(6): [ok_bytes(b"", 302)],
        acc(7): [ok_bytes(b"synthetic", 503), ok_bytes(b"synthetic", 503), ok_bytes(b"synthetic", 503)],
        acc(8): [ok_bytes(b"not json")],
        acc(9): [ok_json({**load("uniprot_inactive.json")["MERGED"], "primaryAccession": "Q0SYZZ"})],
        acc(10): [ok_json({**load("uniprot_inactive.json")["DEMERGED"], "primaryAccession": acc(10),
                           "inactiveReason": {"inactiveReasonType": "DEMERGED", "mergeDemergeTo": []}})],
        acc(11): [ok_json({**load("uniprot_inactive.json")["MERGED"], "primaryAccession": acc(11),
                           "inactiveReason": {"inactiveReasonType": "MERGED", "mergeDemergeTo": ["Q0SYU1", "Q0SYU2"]}})],
        acc(12): [ok_json({"entryType": "UniProtKB reviewed (Swiss-Prot)", "primaryAccession": acc(12)})],
        acc(13): [ok_bytes(b"synthetic", 429), inactive(acc(13), "DELETED")],
    }
    world = World(n_mcsa=14, missing=missing)
    result = run(world, params(tmp_path))
    skipped = {s["accession"]: (s["reason"], s["target_accessions"]) for s in result["skipped_accessions"]}
    assert skipped == {
        acc(1): ("obsolete", []), acc(2): ("merged", ["Q0SYU9"]), acc(3): ("demerged", ["P0SYU1", "Q0SYU2"]),
        acc(4): ("not_found", []), acc(5): ("fetch_failed", []), acc(6): ("fetch_failed", []),
        acc(7): ("fetch_failed", []), acc(8): ("fetch_failed", []), acc(9): ("fetch_failed", []),
        acc(10): ("fetch_failed", []), acc(11): ("fetch_failed", []), acc(12): ("fetch_failed", []),
        acc(13): ("obsolete", []),
    }
    assert [s["accession"] for s in result["skipped_accessions"]] == sorted(skipped)
    assert world.server.calls.count(ENTRY.format(acc(6))) == 1      # a redirect is not followed or retried
    assert world.server.calls.count(ENTRY.format(acc(7))) == 3
    assert world.server.calls.count(ENTRY.format(acc(13))) == 2


def test_more_derived_skips_than_the_cap_stop_before_classifying(tmp_path):
    missing = {a: [inactive(a, "DELETED")] for a in ("Q0SYT3", "P0SYT2", acc(1))}
    world = World(n_mcsa=2, missing=missing)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path, max_skipped=2))
    assert info.value.kind == "too_many_skipped"
    assert not any(url.startswith("https://rest.uniprot.org/uniprotkb/") and url.endswith("?fields=accession")
                   for url in world.server.calls)
    assert not (tmp_path / "reaction_reference").exists()
    # Exactly at the cap is accepted.
    world = World(n_mcsa=2, missing=missing)
    result = run(world, params(tmp_path, max_skipped=3))
    assert len(result["skipped_accessions"]) == 3


def test_union_over_max_accessions_stops_after_m_csa_before_uniprot(tmp_path, capsys):
    world = World(n_mcsa=150)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path, max_accessions=len(world.union) - 1))
    assert info.value.kind == "too_many_accessions"
    assert world.server.calls == [MCSA.format(1), MCSA.format(2)]
    assert not (tmp_path / "reaction_reference").exists()
    world = World(n_mcsa=150)
    run(world, params(tmp_path, max_accessions=len(world.union)))


def test_local_parts_over_max_accessions_stop_before_any_request(tmp_path):
    m15 = tmp_path / "m15"
    write_m15(m15, [acc(n) for n in range(2000, 2010)])
    world = World(n_mcsa=2)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path, m15_reference_dir=m15, accessions=(acc(3000),), max_accessions=10))
    assert info.value.kind == "too_many_accessions" and world.server.calls == []


# --- M15 kinase list and dropped user-named accessions -----------------------------------------------------------------

def test_m15_kinase_list_present_absent_disabled(tmp_path):
    kinase = [acc(2000), acc(2001), "Q0SYT1"]
    m15 = tmp_path / "m15"
    kinase_hash = write_m15(m15, kinase)
    cases = {
        "present": (m15, False, {"set_hash": kinase_hash, "count": 3}),
        "disabled": (m15, True, {"set_hash": None, "count": 0}),
        "absent": (tmp_path / "no-m15", False, {"set_hash": None, "count": 0}),
    }
    for state, (folder, disabled, part) in cases.items():
        world = World(n_mcsa=2, kinase=kinase if state == "present" else ())
        out = tmp_path / f"ref-{state}"
        result = run(world, params(tmp_path, reference_dir=out, m15_reference_dir=folder, no_kinases=disabled))
        req = result["requested_accessions"]
        assert req["m15_kinase_list"] == state and req["from_m15_kinase_set"] == part
        assert req["union_count"] == len(world.union)
        requested = world.server.calls[1].split("accessions=", 1)[1].split("&", 1)[0].split(",")
        assert requested == world.union
        assert (acc(2000) in requested) is (state == "present")


@pytest.mark.parametrize("tamper", ["file", "manifest", "pointer", "schema", "row"])
def test_an_unreadable_m15_set_is_absent_not_a_refusal(tmp_path, tamper):
    m15 = tmp_path / "m15"
    write_m15(m15, [acc(2000)], tamper=tamper if tamper in ("file", "manifest") else None)
    if tamper == "pointer":
        (m15 / "active.json").write_bytes(b"{not json")
    if tamper == "schema":
        (m15 / "active.json").write_bytes(K.canonical_json({"schema": "reaction_active@1", "set_hash": "0" * 64}))
    if tamper == "row":
        write_m15(tmp_path / "m15b", ["not-an-accession"])
        m15 = tmp_path / "m15b"
    world = World(n_mcsa=2)
    result = run(world, params(tmp_path, m15_reference_dir=m15))
    assert result["requested_accessions"]["m15_kinase_list"] == "absent"


def test_dropped_previous_user_named_is_recorded_and_printed(tmp_path, capsys):
    p1 = params(tmp_path, accessions=("Q0SYT1", acc(3000)))
    run(World(n_mcsa=2, user=["Q0SYT1", acc(3000)]), p1, now=NOW)
    capsys.readouterr()
    p2 = params(tmp_path, accessions=("Q0SYT1",))
    result = run(World(n_mcsa=2, user=["Q0SYT1"]), p2, now=LATER)
    assert result["requested_accessions"]["user_named"] == ["Q0SYT1"]
    assert result["requested_accessions"]["dropped_previous_user_named"] == [acc(3000)]
    assert acc(3000) in capsys.readouterr().out
    # Without a readable previous set the list is empty.
    (p2.reference_dir / "active.json").write_bytes(b"{broken")
    result = run(World(n_mcsa=2), params(tmp_path), now=LATER + dt.timedelta(seconds=1))
    assert result["requested_accessions"]["dropped_previous_user_named"] == []


# --- target folder and atomic install ----------------------------------------------------------------------------------

INSTALL_STEPS = ["write_mcsa", "write_uniprot", "write_rhea", "write_request_log", "verify_staged", "write_manifest",
                 "fsync_staging", "rename", "fsync_sets", "write_pointer", "replace_pointer"]


@pytest.mark.parametrize("step", INSTALL_STEPS)
def test_a_failure_at_any_install_step_leaves_active_json_and_old_sets(tmp_path, monkeypatch, step):
    p = params(tmp_path)
    first = run(World(n_mcsa=2), p, now=NOW)
    ref = p.reference_dir
    old_set = tree(ref / "sets" / first["set_hash"])
    old_pointer = (ref / "active.json").read_bytes()
    writes = {"n": 0}
    real_write, real_fsync = imp._write_file, imp._fsync_dir
    order = ["write_mcsa", "write_uniprot", "write_rhea", "write_request_log", "write_manifest"]

    def write(path, data):
        name = Path(path).name
        if name.startswith(".active.json"):
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
        if step == "fsync_sets" and path == ref / "sets":
            raise OSError("synthetic fsync failure")
        return real_fsync(path)

    def fail(*args, **kwargs):
        raise OSError("synthetic failure")

    monkeypatch.setattr(imp, "_write_file", write)
    monkeypatch.setattr(imp, "_fsync_dir", fsync)
    if step == "verify_staged":
        monkeypatch.setattr(imp, "_verify_staged", fail)
    if step == "rename":
        monkeypatch.setattr(imp.os, "rename", fail)
    if step == "replace_pointer":
        monkeypatch.setattr(imp.os, "replace", fail)
    with pytest.raises(imp.ImportRefused) as info:
        run(World(n_mcsa=2), p, now=LATER)
    assert info.value.kind == "install_failed"
    assert (ref / "active.json").read_bytes() == old_pointer
    assert tree(ref / "sets" / first["set_hash"]) == old_set
    names = {q.name for q in (ref / "sets").iterdir()}
    assert not any(n.startswith(".staging-") for n in names)
    assert not any(q.name.endswith(".tmp") for q in ref.iterdir())
    if INSTALL_STEPS.index(step) < INSTALL_STEPS.index("fsync_sets"):
        assert names == {first["set_hash"]}
    else:  # the complete new set was renamed into place but is not active
        assert len(names) == 2


def test_the_pointer_swap_happens_once_after_the_set_is_complete(tmp_path, monkeypatch):
    p = params(tmp_path)
    first = run(World(n_mcsa=2), p, now=NOW)
    ref = p.reference_dir
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        if Path(dst).name == "active.json":
            pending = json.loads(Path(src).read_bytes())["set_hash"]
            raw = (ref / "sets" / pending / "manifest.json").read_bytes()
            assert sha(raw) == pending
            manifest = json.loads(raw)
            for record in [*(f for s in manifest["sources"] for f in s["files"]), manifest["request_log"]]:
                assert sha((ref / "sets" / pending / record["path"]).read_bytes()) == record["sha256"]
            assert json.loads((ref / "active.json").read_bytes())["set_hash"] == first["set_hash"]
            seen.append(pending)
        return real_replace(src, dst)

    monkeypatch.setattr(imp.os, "replace", spy)
    second = run(World(n_mcsa=2), p, now=LATER)
    assert seen == [second["set_hash"]]


def test_an_existing_final_set_folder_is_refused_without_change(tmp_path):
    p = params(tmp_path)
    run(World(n_mcsa=2), p, now=NOW)
    before = tree(p.reference_dir)
    with pytest.raises(imp.ImportRefused) as info:
        run(World(n_mcsa=2), p, now=NOW)  # same responses and the same second: the same set hash
    assert info.value.kind == "set_exists"
    assert tree(p.reference_dir) == before


def test_a_foreign_pointer_or_a_linked_sets_folder_is_refused_before_any_request(tmp_path):
    ref = tmp_path / "reaction_reference"
    ref.mkdir()
    (ref / "active.json").write_bytes(K.canonical_json({"schema": "reference_active@1", "set_hash": "a" * 64}))
    world = World(n_mcsa=2)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path))
    assert info.value.kind == "target_invalid" and world.server.calls == []
    (ref / "active.json").unlink()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ref / "sets").symlink_to(outside, target_is_directory=True)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path))
    assert info.value.kind == "target_invalid" and world.server.calls == []
    assert list(outside.iterdir()) == []
    (ref / "sets").unlink()
    (ref / "sets").write_text("not a folder")
    with pytest.raises(imp.ImportRefused):
        run(world, params(tmp_path))
    assert world.server.calls == []


def test_the_import_writes_only_inside_the_reference_folder(tmp_path):
    p = params(tmp_path, reference_dir=tmp_path / "a" / "ref")
    before = {q for q in tmp_path.rglob("*")}
    run(World(n_mcsa=2), p)
    created = {q for q in tmp_path.rglob("*")} - before
    assert created and all(q == tmp_path / "a" or q.is_relative_to(p.reference_dir) for q in created)


def test_confirmation_screen_and_cancel(tmp_path, capsys):
    prompts = []
    world = World(n_mcsa=2)
    with pytest.raises(imp.ImportRefused) as info:
        run(world, params(tmp_path, yes=False), input_fn=lambda prompt: prompts.append(prompt) or "n")
    assert info.value.kind == "cancelled" and world.server.calls == [] and len(prompts) == 1
    screen = capsys.readouterr().out
    for text in (*K.ALLOWED_HOSTS, "M-CSA", "UniProt", "Rhea", str(tmp_path / "reaction_reference"), "absent",
                 "MAX_ACCESSIONS", "20000", "MAX_SKIPPED"):
        assert text in screen, text

    def eof(prompt):
        raise EOFError

    with pytest.raises(imp.ImportRefused):
        run(world, params(tmp_path, yes=False), input_fn=eof)
    assert world.server.calls == []
    run(world, params(tmp_path, yes=False), input_fn=lambda prompt: "yes")
    assert world.server.calls


# --- secrets ---------------------------------------------------------------------------------------------------------

def test_headers_and_tokens_never_reach_files_or_output(tmp_path, capsys):
    world = big_world(n_mcsa=3, kinase=(), user=(), missing={"Q0SYT3": [inactive("Q0SYT3", "MERGED")]})
    p = params(tmp_path)
    result = run(world, p)
    out = capsys.readouterr()
    written = b"".join(tree(p.reference_dir).values())
    for text in (SENTINEL, "Set-Cookie", "Authorization", "Bearer", "X-Api-Key", "sid="):
        assert text.encode() not in written and text not in out.out and text not in out.err, text
        assert text not in json.dumps(result)
    log = (p.reference_dir / "sets" / result["set_hash"] / "files" / "request_log.jsonl").read_bytes()
    assert all(set(json.loads(line)) == {"seq", "source", "method", "url", "status", "bytes", "sha256"}
               for line in log.splitlines())


# --- command line -------------------------------------------------------------------------------------------------------

def test_cli_options_are_exactly_the_spec_set():
    parser = imp.build_parser()
    options = sorted(opt for action in parser._actions for opt in action.option_strings)
    assert options == sorted(["--accession", "--accessions-file", "--no-kinases", "--reference-dir", "--yes", "-h",
                              "--help"])
    assert parser.allow_abbrev is False
    assert all(action.option_strings for action in parser._actions)  # no positional arguments


@pytest.mark.parametrize("option", ["--host", "--hosts", "--scheme", "--url", "--base-url", "--insecure", "--http",
                                    "--proxy", "--allow-insecure-loopback", "--_allow_insecure_loopback",
                                    "--allow_insecure_loopback", "--loopback", "--ref", "--acc"])
def test_cli_has_no_host_or_scheme_override(option, capsys):
    with pytest.raises(SystemExit) as info:
        imp.main([option, "x", "--yes"])
    assert info.value.code == 2


def test_cli_hostile_environment_does_not_change_hosts_or_scheme(tmp_path, monkeypatch, capsys):
    world = World(n_mcsa=2)
    made = []

    class Recording:
        def __init__(self, *args, **kwargs):
            made.append((args, kwargs))

        def __call__(self, url):
            return world.server(url)

    hostile = {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://x:9",
               "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "NO_PROXY": "*",
               "MW_REACTION_HOSTS": "evil.example", "MW_REACTION_SCHEME": "http", "MW_REACTION_IMPORT_HOST": "x",
               "MW_REACTION_ALLOW_INSECURE_LOOPBACK": "1", "ALLOW_INSECURE_LOOPBACK": "1", "MW_EGRESS_MODE": "on",
               "MW_REACTION_REFERENCE_DIR": str(tmp_path / "env-ref"), "MW_REFERENCE_DIR": str(tmp_path / "none")}
    for key, value in hostile.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(imp, "UrllibTransport", Recording)
    monkeypatch.setattr(imp.time, "sleep", lambda seconds: None)
    assert imp.main(["--yes"]) == 0
    assert made == [((), {})]
    assert world.server.calls == world.expected_calls()
    assert all(url.startswith("https://") and imp.validate_url(url) in K.ALLOWED_HOSTS for url in world.server.calls)
    assert (tmp_path / "env-ref" / "active.json").is_file()  # MW_REACTION_REFERENCE_DIR only picks the folder
    out = capsys.readouterr().out
    assert "absent" in out


def test_the_real_transport_ignores_the_environment(monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:9")
    transport = imp.UrllibTransport()
    # One HTTPS handler only: no proxy, redirect, cookie, error-raising, http/ftp/file/data handler.
    assert [type(h).__name__ for h in transport._opener.handlers] == ["HTTPSHandler"]
    assert set(transport._opener.handle_open) == {"https"}
    assert transport._opener.process_response == {}  # no error processor, no cookie processor
    assert [type(h).__name__ for hs in transport._opener.process_request.values() for h in hs] == ["HTTPSHandler"]
    assert transport._opener.addheaders == []
    assert transport._loopback is False
    test_only = imp.UrllibTransport(_allow_insecure_loopback=True)
    assert [type(h).__name__ for h in test_only._opener.handlers] == ["HTTPHandler"]


def test_reference_dir_resolution():
    default = imp.DEFAULT_REFERENCE_DIR
    assert default == REPO / ".deps" / "reaction_reference"
    assert imp.resolve_dir(None, None, default) == default
    assert imp.resolve_dir(None, "", default) == default
    assert imp.resolve_dir(None, "qa/ref", default) == REPO / "qa" / "ref"
    assert imp.resolve_dir("other", "qa/ref", default) == REPO / "other"
    assert imp.resolve_dir("/abs/x", "qa/ref", default) == Path("/abs/x")
    assert imp.DEFAULT_M15_DIR == REPO / ".deps" / "reference"


def test_the_script_runs_directly_without_the_mw_package(tmp_path):
    # A child process where importing mw/httpx/requests fails and any socket use exits: the script must load the
    # constants by file path, print its help, and refuse an invalid accession before any request.
    import subprocess
    import sys

    env = {"PATH": os.environ.get("PATH", ""), "MW_REACTION_REFERENCE_DIR": str(tmp_path / "ref"),
           "MW_REFERENCE_DIR": str(tmp_path / "none")}
    code = ("import sys, socket, runpy\n"
            "class Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in ('mw', 'httpx', 'requests'):\n"
            "            raise ImportError('blocked import ' + name)\n"
            "sys.meta_path.insert(0, Block())\n"
            "def no(*a, **k):\n"
            "    raise SystemExit('network used')\n"
            "socket.socket.connect = no\nsocket.getaddrinfo = no\n"
            "sys.argv = [sys.argv[1], *sys.argv[2:]]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n")
    help_run = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPT), "--help"], env=env, cwd=tmp_path,
                              capture_output=True, text=True, timeout=60, check=False)
    assert help_run.returncode == 0 and "--reference-dir" in help_run.stdout, help_run.stderr
    bad = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPT), "--yes", "--accession", "nope"], env=env,
                         cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False)
    assert bad.returncode == 1 and "invalid_input" in bad.stderr and "network used" not in bad.stderr
    assert not (tmp_path / "ref").exists()


def test_cli_refusal_exit_code_and_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MW_REACTION_REFERENCE_DIR", str(tmp_path / "ref"))
    assert imp.main(["--yes", "--accession", "not-valid"]) == 1
    err = capsys.readouterr().err
    assert "not-valid" in err and "거절" in err and "refused" in err
    assert not (tmp_path / "ref").exists()


# --- static checks ------------------------------------------------------------------------------------------------------

def _inside(tree_: ast.AST, class_name: str) -> set[int]:
    ids = set()
    for node in ast.walk(tree_):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            ids.update(id(child) for child in ast.walk(node))
    return ids


def test_script_imports_no_mw_httpx_or_requests_and_urllib_only_in_the_transport():
    tree_ = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    transport = _inside(tree_, "UrllibTransport")
    assert transport
    network = ("urllib", "http", "socket", "ssl")
    for node in ast.walk(tree_):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            assert root not in ("mw", "httpx", "requests", "aiohttp", "urllib3", "pycurl", "subprocess"), name
            if root in network:
                assert id(node) in transport, f"{name} imported outside UrllibTransport"
    for node in ast.walk(tree_):
        if isinstance(node, ast.Name) and node.id in network:
            assert id(node) in transport, node.id
    source = SCRIPT.read_text(encoding="utf-8")
    assert "reaction_knowledge_constants.py" in source and "spec_from_file_location" in source


def test_the_loopback_argument_is_reachable_only_inside_the_transport_class():
    tree_ = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    transport = _inside(tree_, "UrllibTransport")
    word = "_allow_insecure_loopback"
    for node in ast.walk(tree_):
        hit = ((isinstance(node, ast.arg) and node.arg == word) or (isinstance(node, ast.keyword) and node.arg == word)
               or (isinstance(node, ast.Name) and node.id == word)
               or (isinstance(node, ast.Attribute) and node.attr == word)
               or (isinstance(node, ast.Constant) and isinstance(node.value, str) and word in node.value))
        if hit:
            assert id(node) in transport, ast.dump(node)
    main = next(n for n in tree_.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "UrllibTransport"]
    assert len(calls) == 1 and calls[0].args == [] and calls[0].keywords == []


# --- the real transport against a 127.0.0.1 server ---------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        self.server.seen.append((self.command, path, dict(self.headers.items())))
        try:
            self.server.routes[path](self)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


def _reply(status: int, body: bytes = b"", headers=(), length: bool = True):
    def handler(h):
        h.send_response(status)
        for key, value in headers:
            h.send_header(key, value)
        if length:
            h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)
    return handler


@pytest.fixture
def loopback():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.seen = []
    server.routes = {}
    port = server.server_address[1]
    _LOOPBACK_PORTS.add(port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.url = lambda path: f"http://127.0.0.1:{port}{path}"
    yield server
    server.shutdown()
    server.server_close()
    _LOOPBACK_PORTS.discard(port)


def test_transport_sends_only_the_fixed_headers_and_no_cookies(loopback):
    loopback.routes["/ok"] = _reply(200, b"synthetic loopback body", [("Set-Cookie", f"sid={SENTINEL}")])
    transport = imp.UrllibTransport(_allow_insecure_loopback=True)
    status, headers, body = transport(loopback.url("/ok?x=1"))
    assert (status, body) == (200, b"synthetic loopback body")
    assert ("Set-Cookie", f"sid={SENTINEL}") in headers  # returned to the caller; the importer drops them
    transport(loopback.url("/ok"))
    assert len(loopback.seen) == 2
    for method, _path, sent in loopback.seen:
        names = {key.lower() for key in sent}
        assert method == "GET" and names <= {"host", "user-agent", "accept-encoding", "connection"}, names
        assert sent["User-Agent"] == "ProtView-reaction-import/1" and sent["Accept-Encoding"] == "identity"
        assert "cookie" not in names and "authorization" not in names


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_transport_does_not_follow_redirects(loopback, status):
    loopback.routes["/moved"] = _reply(status, b"", [("Location", "/target")])
    loopback.routes["/target"] = _reply(200, b"must not be fetched")
    got, _headers, _body = imp.UrllibTransport(_allow_insecure_loopback=True)(loopback.url("/moved"))
    assert got == status
    assert [path for _m, path, _h in loopback.seen] == ["/moved"]


def test_transport_returns_error_statuses(loopback):
    loopback.routes["/busy"] = _reply(503, b"synthetic busy")
    assert imp.UrllibTransport(_allow_insecure_loopback=True)(loopback.url("/busy"))[0] == 503


def test_transport_response_size_cap(loopback):
    loopback.routes["/declared"] = _reply(200, b"x" * 5000)
    loopback.routes["/streamed"] = _reply(200, b"y" * 5000, length=False)
    loopback.routes["/fits"] = _reply(200, b"z" * 1000, length=False)
    transport = imp.UrllibTransport(max_bytes=1000, _allow_insecure_loopback=True)
    for path in ("/declared", "/streamed"):
        with pytest.raises(imp.TransportError, match="large"):
            transport(loopback.url(path))
    assert transport(loopback.url("/fits"))[2] == b"z" * 1000


def test_transport_refuses_encoded_bodies(loopback):
    loopback.routes["/gz"] = _reply(200, b"\x1f\x8b synthetic", [("Content-Encoding", "gzip")])
    with pytest.raises(imp.TransportError, match="encod"):
        imp.UrllibTransport(_allow_insecure_loopback=True)(loopback.url("/gz"))


def test_transport_timeout(loopback):
    def slow(h):
        time.sleep(1.5)
        _reply(200, b"late")(h)

    loopback.routes["/slow"] = slow
    start = time.monotonic()
    with pytest.raises(imp.TransportError):
        imp.UrllibTransport(timeout=0.3, _allow_insecure_loopback=True)(loopback.url("/slow"))
    assert time.monotonic() - start < 1.2


def test_transport_ignores_environment_proxies(loopback, monkeypatch):
    proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    proxy.seen, proxy.routes = [], {}
    _LOOPBACK_PORTS.add(proxy.server_address[1])
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        address = f"http://127.0.0.1:{proxy.server_address[1]}"
        for key in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(key, address)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        loopback.routes["/ok"] = _reply(200, b"direct")
        assert imp.UrllibTransport(_allow_insecure_loopback=True)(loopback.url("/ok"))[2] == b"direct"
        assert proxy.seen == [] and len(loopback.seen) == 1
    finally:
        proxy.shutdown()
        proxy.server_close()
        _LOOPBACK_PORTS.discard(proxy.server_address[1])


def test_transport_url_checks_happen_before_any_connection(loopback):
    loopback.routes["/ok"] = _reply(200, b"x")
    default = imp.UrllibTransport()
    for url in (loopback.url("/ok"), "https://evil.example/x", "https://www.ebi.ac.uk:443/x"):
        with pytest.raises(imp.UrlRefused):
            default(url)
    test_only = imp.UrllibTransport(_allow_insecure_loopback=True)
    port = loopback.server_address[1]
    for url in (MCSA.format(1), f"http://localhost:{port}/ok", f"http://127.0.0.2:{port}/ok",
                f"https://127.0.0.1:{port}/ok", f"http://user@127.0.0.1:{port}/ok", f"http://127.0.0.1:{port}/ok#x"):
        with pytest.raises(imp.UrlRefused):
            test_only(url)
    assert loopback.seen == []
