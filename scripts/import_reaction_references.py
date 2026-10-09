"""Import the M26 reaction reference set (M-CSA, UniProt function, Rhea) from the three public servers.

Usage: python scripts/import_reaction_references.py [--accession ACC]... [--accessions-file PATH] [--no-kinases]
                                                     [--reference-dir PATH] [--yes]

This user-run command is the only ProtView code that uses the network (spec 4). It sends HTTPS GET requests only, to
exactly the hosts of ``reaction_knowledge_constants.ALLOWED_HOSTS`` (``www.ebi.ac.uk``, ``rest.uniprot.org``,
``www.rhea-db.org``), with the fixed headers ``User-Agent: ProtView-reaction-import/1`` and ``Accept-Encoding:
identity`` only: no cookies, credentials, keys or user data (the only data sent is the URL query: page numbers,
accession lists, column names). Environment proxies are ignored and redirects are never followed (a 3xx answer is a
failure). Every URL is built here and checked by ``validate_url`` before its request; links found in responses (the
M-CSA ``next``) are never followed. No command-line option or environment variable changes a host or the scheme.

Requests, in this order (spec 4.2-4.3):

1. M-CSA ``.../api/entries/?format=json&page=P&page_size=100`` for P = 1..ceil(count/100): the first page gives
   ``count``; every page must repeat it and hold exactly its share of entries, ``mcsa_id`` must be unique.
2. The accession union = every accession an M-CSA entry names ∪ the local M15 kinase list (``status: ok`` rows of the
   active M15 UniProt snapshot, read from ``MW_REFERENCE_DIR`` or ``<repo>/.deps/reference``; ``--no-kinases`` leaves
   it out; a missing or unreadable M15 set is recorded as ``absent`` and does not stop the import) ∪ the accessions
   named with ``--accession`` / ``--accessions-file`` (format-checked before any request). ``MAX_ACCESSIONS`` is
   checked right after the M-CSA pages and before any UniProt request (and before any request at all when the local
   parts alone exceed it).
3. UniProt ``/uniprotkb/accessions?accessions=...`` in ascending batches of at most 1000. Every accession missing from
   the results is classified with one ``/uniprotkb/{acc}.json?fields=accession`` request (``obsolete`` / ``merged`` /
   ``demerged`` / ``not_found`` / ``fetch_failed``). More than ``MAX_SKIPPED`` missing derived accessions stops the
   import before any classification. Any missing user-named accession refuses the whole command (reason and target
   accessions are printed, nothing is installed, nothing is replaced automatically); those are not counted against
   ``MAX_SKIPPED``.
4. Rhea ``/rhea?query=&columns=rhea-id,equation,chebi,chebi-id,ec&format=tsv&limit=20000`` (one request).

Only 429 and 5xx answers are retried, at most twice per request with exponential waits; one host is asked at most once
per ``min_interval`` seconds. Every attempt is one row of ``files/request_log.jsonl`` (seq, source, method, url,
status, bytes, sha256 of the body; an attempt that got no response is status 0 with 0 bytes and the SHA-256 of the
empty body). A source's ``raw_sha256_digest`` / ``raw_response_count`` cover its log rows in request order. Response
headers are dropped as soon as a response arrives; they are never logged, stored or printed.

Layout written under the reference folder (``--reference-dir``, else ``MW_REACTION_REFERENCE_DIR``, else
``<repo>/.deps/reaction_reference``; a relative value is taken from the repository root)::

    active.json                                {"schema":"reaction_active@1","set_hash":"<hex64>"} (one rename)
    sets/<set_hash>/manifest.json              canonical JSON reaction_reference_set@1; set_hash = sha256(bytes)
    sets/<set_hash>/files/<source>/<name>      mcsa/entries.jsonl, uniprot_function/entries.jsonl, rhea/reactions.jsonl
    sets/<set_hash>/files/request_log.jsonl

Nothing is written until every response has arrived and passed the format checks. The set is then staged in
``sets/.staging-<uuid>``, read back and verified, renamed to ``sets/<set_hash>``, and only then is ``active.json``
replaced (temporary file + ``os.replace``). A failure removes only the staging folder or the temporary pointer;
``active.json`` and every earlier set stay as they were, and earlier sets are never deleted. ``imported_at`` is inside
the manifest, so importing the same content again gives a new set hash (``compare_manifests`` checks reproduction by
the processed file hashes, spec 4.5).

Row formats, canonical JSON, the set hash and the manifest check are those of
``backend/mw/reaction_knowledge_constants.py``, loaded here by file path: this script never imports ``mw``.
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
import sys
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONSTANTS_PATH = ROOT / "backend" / "mw" / "reaction_knowledge_constants.py"


def _load_constants():
    """``reaction_knowledge_constants.py`` by file path (standard library only; the ``mw`` package is not imported)."""
    spec = importlib.util.spec_from_file_location("protview_reaction_import_constants", CONSTANTS_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {CONSTANTS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


K = _load_constants()
FormatError = K.FormatError

DEFAULT_REFERENCE_DIR = ROOT.joinpath(*K.DEFAULT_DIR_PARTS)
M15_ENV_VAR = "MW_REFERENCE_DIR"
DEFAULT_M15_DIR = ROOT / ".deps" / "reference"
M15_POINTER_SCHEMA = "reference_active@1"
M15_SET_SCHEMA = "reference_snapshot_set@1"

USER_AGENT = "ProtView-reaction-import/" + K.IMPORTER_VERSION.split("/", 1)[1]
MCSA_PAGE_SIZE = 100
UNIPROT_BATCH = 1000
UNIPROT_FIELDS = "accession,id,protein_name,organism_name,length,ec,ft_act_site,ft_binding,ft_site,cc_catalytic_activity"
RHEA_LIMIT = 20000
RHEA_URL = ("https://www.rhea-db.org/rhea?query=&columns=rhea-id,equation,chebi,chebi-id,ec&format=tsv"
            f"&limit={RHEA_LIMIT}")
RHEA_HEADER = ("Reaction identifier", "Equation", "ChEBI name", "ChEBI identifier", "EC number")

# Adjustable defaults (spec 4.3 / 11.2); the command line does not change them.
MAX_RETRIES = 2
BACKOFF_SECONDS = 2.0
MIN_INTERVAL_SECONDS = 1.0
TIMEOUT_SECONDS = 120.0
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_ACCESSIONS_FILE_BYTES = 4 * 1024 * 1024
# Missing user-named accessions are classified (one request each) for the refusal message only up to this many; they
# are never counted against MAX_SKIPPED, the bound only keeps a refused command's request count small.
MAX_USER_NAMED_CHECKS = K.MAX_SKIPPED

REFUSAL_KINDS = ("invalid_input", "target_invalid", "too_many_accessions", "cancelled", "fetch_failed",
                 "format_error", "too_many_skipped", "user_named_unavailable", "set_exists", "install_failed")


class ImportRefused(Exception):
    """The import stopped; ``active.json`` and every earlier set are unchanged. ``kind`` is one of REFUSAL_KINDS."""

    def __init__(self, kind: str, message: str, details: Iterable[str] = ()) -> None:
        if kind not in REFUSAL_KINDS:
            raise ValueError(f"unknown refusal kind {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.details = list(details)


class UrlRefused(ValueError):
    """A URL that is not an allowed request URL; nothing was sent."""


class TransportError(Exception):
    """A request got no usable response (connection, timeout, size cap, encoding)."""


# ------------------------------------------------------------------------------------------- URLs

_URL_TAIL = re.compile(r"/[A-Za-z0-9._/?=&,-]*\Z")


def validate_url(url: Any) -> str:
    """The host of an allowed request URL: ``https://`` + a host exactly in ALLOWED_HOSTS + a path, nothing else.

    Refused: any other scheme or spelling of it, any other host (look-alikes, other case, a trailing dot), user
    information, a port, a fragment, a missing path, non-ASCII or any character outside ``[A-Za-z0-9._/?=&,-]``.
    """
    if type(url) is not str or not url.isascii():
        raise UrlRefused("the URL must be an ASCII string")
    if not url.startswith("https://"):
        raise UrlRefused(f"only https:// URLs are allowed: {url!r}")
    rest = url[len("https://"):]
    if "#" in rest:
        raise UrlRefused(f"URL fragments are not allowed: {url!r}")
    authority = rest.split("/", 1)[0]
    if "@" in authority:
        raise UrlRefused(f"user information is not allowed in a URL: {url!r}")
    if ":" in authority:
        raise UrlRefused(f"ports are not allowed in a URL: {url!r}")
    if authority not in K.ALLOWED_HOSTS:
        raise UrlRefused(f"host {authority!r} is not one of {', '.join(K.ALLOWED_HOSTS)}")
    if not _URL_TAIL.fullmatch(rest[len(authority):]):
        raise UrlRefused(f"unexpected URL path or characters: {url!r}")
    return authority


def mcsa_page_url(page: int) -> str:
    if type(page) is not int or page < 1:
        raise ValueError("page numbers start at 1")
    return f"https://www.ebi.ac.uk/thornton-srv/m-csa/api/entries/?format=json&page={page}&page_size={MCSA_PAGE_SIZE}"


def _accessions_only(values: Iterable[str]) -> list[str]:
    values = list(values)
    if not values or not all(K.is_accession(v) for v in values):
        raise ValueError("only UniProt accessions go into a UniProt URL")
    return values


def uniprot_batch_url(accessions: Iterable[str]) -> str:
    values = _accessions_only(accessions)
    if len(values) > UNIPROT_BATCH:
        raise ValueError(f"at most {UNIPROT_BATCH} accessions per request")
    return (f"https://rest.uniprot.org/uniprotkb/accessions?accessions={','.join(values)}&fields={UNIPROT_FIELDS}"
            "&format=json")


def uniprot_entry_url(accession: str) -> str:
    (value,) = _accessions_only([accession])
    return f"https://rest.uniprot.org/uniprotkb/{value}.json?fields=accession"


# ------------------------------------------------------------------------------------------- the real transport

_LOOPBACK_URL = re.compile(r"http://127\.0\.0\.1:[0-9]{1,5}/[A-Za-z0-9._/?=&,-]*\Z")
_CHUNK = 64 * 1024


class UrllibTransport:
    """The real transport: one GET with the standard library ``urllib`` per call, ``(status, headers, body)``.

    The opener is built by hand (not ``build_opener``, which would add a proxy handler reading the environment) with
    one ``HTTPSHandler`` (certificate verification on) only: no proxy handler (environment proxies are never
    consulted), no redirect handler (a 3xx answer is returned as it is and the importer treats it as a failure), no
    error processor (4xx/5xx are returned, not raised), no cookie processor, no ``http``/``ftp``/``file``/``data``
    handlers, and no default ``User-agent``. Headers sent: ``User-Agent`` and ``Accept-Encoding:
    identity`` (``urllib`` adds ``Host`` and ``Connection: close``). ``timeout`` bounds each socket operation and the
    whole request; the body is read in chunks and refused past ``max_bytes`` or when it arrives encoded.

    ``_allow_insecure_loopback=True`` is a test-only library argument: the transport then accepts only
    ``http://127.0.0.1:<port>/`` URLs (and nothing else) for tests against a local server. The command line has no way
    to set it.
    """

    def __init__(self, *, timeout: float = TIMEOUT_SECONDS, max_bytes: int = MAX_RESPONSE_BYTES,
                 _allow_insecure_loopback: bool = False) -> None:
        import ssl
        import urllib.request

        if not timeout > 0 or not max_bytes > 0:
            raise ValueError("timeout and max_bytes must be positive")
        self.timeout = float(timeout)
        self.max_bytes = int(max_bytes)
        self._loopback = _allow_insecure_loopback is True
        opener = urllib.request.OpenerDirector()
        opener.addheaders = []
        if self._loopback:
            opener.add_handler(urllib.request.HTTPHandler())
        else:
            opener.add_handler(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self._opener = opener

    def _check(self, url: str) -> None:
        import urllib.parse

        if self._loopback:
            if type(url) is not str or not _LOOPBACK_URL.fullmatch(url):
                raise UrlRefused("the loopback test transport accepts only http://127.0.0.1:<port>/ URLs")
            return
        host = validate_url(url)
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme, parts.hostname, parts.port, parts.username, parts.password, parts.fragment) != (
                "https", host, None, None, None, ""):
            raise UrlRefused(f"the URL does not parse to the checked host: {url!r}")

    def fetch(self, url: str) -> tuple[int, list[tuple[str, str]], bytes]:
        import http.client
        import urllib.error
        import urllib.request

        self._check(url)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
                                         method="GET")
        deadline = time.monotonic() + self.timeout
        try:
            response = self._opener.open(request, timeout=self.timeout)
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            raise TransportError(f"no response ({type(exc).__name__}: {exc})") from None
        with response:
            try:
                status = response.status
                headers = list(response.headers.items())
                encoding = (response.headers.get("Content-Encoding") or "identity").strip().lower()
                if encoding != "identity":
                    raise TransportError(f"the response arrived encoded ({encoding}); identity was asked")
                length = (response.headers.get("Content-Length") or "").strip()
                if length.isdigit() and int(length) > self.max_bytes:
                    raise TransportError(f"the response is larger than {self.max_bytes} bytes")
                chunks, total = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise TransportError(f"the request took longer than {self.timeout} s")
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise TransportError(f"the response is larger than {self.max_bytes} bytes")
                    chunks.append(chunk)
            except (http.client.HTTPException, OSError) as exc:
                raise TransportError(f"the response broke off ({type(exc).__name__}: {exc})") from None
        return status, headers, b"".join(chunks)

    __call__ = fetch


# ------------------------------------------------------------------------------------------- requests and the log

class _Requests:
    """Every GET of one import: URL check, per-host interval, 429/5xx retries, one log row per attempt."""

    def __init__(self, transport: Callable[[str], Any], *, sleep: Callable[[float], None], clock: Callable[[], float],
                 max_retries: int, backoff: float, min_interval: float) -> None:
        self.transport, self.sleep, self.clock = transport, sleep, clock
        self.max_retries, self.backoff, self.min_interval = max_retries, backoff, min_interval
        self.rows: list[dict[str, Any]] = []
        self.last_error = ""
        self._last: dict[str, float] = {}

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            remaining = self.min_interval - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last[host] = self.clock()

    def _attempt(self, url: str) -> tuple[int, bytes]:
        try:
            status, _headers, body = self.transport(url)  # headers are dropped here, never logged or printed
        except UrlRefused as exc:  # the transport's own check refused it: nothing was sent
            raise ImportRefused("fetch_failed", f"요청하지 않은 URL / URL refused before any request: {exc}") from None
        except (TransportError, OSError) as exc:
            self.last_error = str(exc)
            return 0, b""
        if type(status) is not int or not 100 <= status <= 599 or type(body) is not bytes:
            raise TypeError("a transport returns (int status, headers, bytes body)")
        return status, body

    def get(self, source: str, url: str) -> tuple[int, bytes]:
        try:
            host = validate_url(url)
        except UrlRefused as exc:
            raise ImportRefused("fetch_failed", f"요청하지 않은 URL / URL refused before any request: {exc}") from None
        retries = 0
        while True:
            self._wait(host)
            status, body = self._attempt(url)
            row = {"seq": len(self.rows) + 1, "source": source, "method": "GET", "url": url, "status": status,
                   "bytes": len(body), "sha256": K.sha256_hex(body)}
            K.validate_request_log_row(row)
            self.rows.append(row)
            shown = url.split("?", 1)[0]
            print(f"  [{row['seq']}] {source} GET {shown} -> {status or 'no response'} ({len(body)} B)", flush=True)
            if (status == 429 or 500 <= status <= 599) and retries < self.max_retries:
                self.sleep(self.backoff * 2 ** retries)
                retries += 1
                continue
            return status, body

    def require_ok(self, source: str, url: str, what: str) -> bytes:
        status, body = self.get(source, url)
        if status != 200:
            reason = f"HTTP {status}" if status else f"응답 없음 / no response: {self.last_error}"
            raise ImportRefused("fetch_failed", f"{what}: {reason}")
        return body


# ------------------------------------------------------------------------------------------- response parsing

def _reject_constant(value: str) -> Any:
    raise FormatError(f"non-finite number {value}")


def _json(body: bytes, what: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in items:
            if key in obj:
                raise FormatError(f"{what}: duplicate JSON key {key!r}")
            obj[key] = value
        return obj

    try:
        return json.loads(body.decode("utf-8"), object_pairs_hook=pairs, parse_constant=_reject_constant)
    except FormatError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise FormatError(f"{what}: not JSON ({type(exc).__name__})") from None


def _obj(value: Any, where: str, required: Iterable[str], *, optional: Iterable[str] = (),
         dropped: Iterable[str] = ()) -> dict[str, Any]:
    """An object with every required field and no field outside required ∪ optional ∪ dropped."""
    if type(value) is not dict:
        raise FormatError(f"{where}: expected an object")
    required, optional, dropped = set(required), set(optional), set(dropped)
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional - dropped)
    if missing:
        raise FormatError(f"{where}: missing fields {missing}")
    if unknown:
        raise FormatError(f"{where}: unknown fields {unknown}")
    return value


def _list(value: Any, where: str) -> list[Any]:
    if type(value) is not list:
        raise FormatError(f"{where}: expected a list")
    return value


def _sorted_strings(values: Any, where: str) -> list[str]:
    values = _list(values, where)
    if not all(type(v) is str for v in values):
        raise FormatError(f"{where}: expected strings")
    return sorted(values)


def _copy(obj: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: obj[key] for key in keys}


# M-CSA (spec 3.3/3.4): copied fields, and the fields the T1 measurement saw that are dropped. Anything else stops.
_MCSA_ENTRY = ("mcsa_id", "enzyme_name", "reference_uniprot_id", "all_ecs", "reaction", "residues")
_MCSA_ENTRY_DROPPED = ("is_reference_uniprot_id", "url", "description", "protein")
_MCSA_REACTION = ("ec", "compounds")
_MCSA_REACTION_DROPPED = ("mechanisms", "is_polymeric")
_MCSA_COMPOUND = ("type", "chebi_id", "name")
_MCSA_COMPOUND_DROPPED = ("count", "mol_file")
_MCSA_RESIDUE = ("roles_summary", "function_location_abv", "ptm", "roles", "residue_chains", "residue_sequences")
_MCSA_RESIDUE_DROPPED = ("mcsa_id", "main_annotation")
_MCSA_ROLE = ("group_function", "function_type", "function", "emo")
_MCSA_CHAIN = ("pdb_id", "chain_name", "assembly_chain_name", "assembly", "code", "resid", "auth_resid", "is_reference")
_MCSA_CHAIN_DROPPED = ("domain_name", "domain_cath_id")
_MCSA_SEQUENCE = ("uniprot_id", "code", "is_reference")
_MCSA_SEQUENCE_DROPPED = ("resid",)


def mcsa_row(raw: Any) -> dict[str, Any]:
    """One M-CSA ``entries`` result -> one ``mcsa/entries.jsonl`` row (strings verbatim, ``assembly`` "" -> null)."""
    _obj(raw, "M-CSA entry", _MCSA_ENTRY, dropped=_MCSA_ENTRY_DROPPED)
    where = f"M-CSA entry {raw['mcsa_id']!r}"
    reaction = _obj(raw["reaction"], f"{where}.reaction", _MCSA_REACTION, dropped=_MCSA_REACTION_DROPPED)
    compounds = []
    for i, compound in enumerate(_list(reaction["compounds"], f"{where}.reaction.compounds")):
        _obj(compound, f"{where}.reaction.compounds[{i}]", _MCSA_COMPOUND, dropped=_MCSA_COMPOUND_DROPPED)
        compounds.append(_copy(compound, _MCSA_COMPOUND))
    residues = []
    for i, residue in enumerate(_list(raw["residues"], f"{where}.residues")):
        rw = f"{where}.residues[{i}]"
        _obj(residue, rw, _MCSA_RESIDUE, dropped=_MCSA_RESIDUE_DROPPED)
        roles = [_copy(_obj(role, f"{rw}.roles[{j}]", _MCSA_ROLE), _MCSA_ROLE)
                 for j, role in enumerate(_list(residue["roles"], f"{rw}.roles"))]
        chains = []
        for j, chain in enumerate(_list(residue["residue_chains"], f"{rw}.residue_chains")):
            _obj(chain, f"{rw}.residue_chains[{j}]", _MCSA_CHAIN, dropped=_MCSA_CHAIN_DROPPED)
            item = _copy(chain, _MCSA_CHAIN)
            if type(item["assembly"]) is str and item["assembly"] == "":
                item["assembly"] = None  # spec 3.3: the response's empty string becomes null
            chains.append(item)
        sequences = [_copy(_obj(seq, f"{rw}.residue_sequences[{j}]", _MCSA_SEQUENCE, dropped=_MCSA_SEQUENCE_DROPPED),
                           _MCSA_SEQUENCE)
                     for j, seq in enumerate(_list(residue["residue_sequences"], f"{rw}.residue_sequences"))]
        residues.append({"roles_summary": residue["roles_summary"],
                         "function_location_abv": residue["function_location_abv"], "ptm": residue["ptm"],
                         "roles": roles, "residue_chains": chains, "residue_sequences": sequences})
    row = {"mcsa_id": raw["mcsa_id"], "enzyme_name": raw["enzyme_name"],
           "reference_uniprot_id": raw["reference_uniprot_id"],
           "all_ecs": _sorted_strings(raw["all_ecs"], f"{where}.all_ecs"),
           "reaction": {"ec": reaction["ec"], "compounds": compounds}, "residues": residues}
    K.validate_row("mcsa", row)
    return row


# UniProt (spec 3.4): strict on the objects whose fields are copied; other containers are only read from.
_UNIPROT_TOP = ("primaryAccession", "uniProtkbId", "organism", "sequence")
_UNIPROT_TOP_OPTIONAL = ("proteinDescription", "features", "comments")
_UNIPROT_TOP_DROPPED = ("entryType", "extraAttributes")
_FEATURE_OPTIONAL = ("description", "ligand")
_FEATURE_DROPPED = ("evidences", "featureCrossReferences", "ligandPart")
_LIGAND_DROPPED = ("label", "note")
_ACTIVITY_DROPPED = ("physiologicalReactions", "molecule", "evidences")
_REACTION_OPTIONAL = ("ecNumber", "reactionCrossReferences")
_REACTION_DROPPED = ("evidences",)
_RHEA_REACTION_ID = re.compile(K.RHEA_ID_PATTERN + r"\Z")
CATALYTIC_ACTIVITY = "CATALYTIC ACTIVITY"


def _full_name(name: Any, where: str) -> str:
    full = name.get("fullName") if type(name) is dict else None
    if type(full) is not dict or type(full.get("value")) is not str:
        raise FormatError(f"{where}: no fullName.value")
    return full["value"]


def _protein_name(description: dict[str, Any], where: str) -> str | None:
    if "recommendedName" in description:
        return _full_name(description["recommendedName"], f"{where}.recommendedName")
    names = description.get("submissionNames")
    if names is None or names == []:
        return None
    return _full_name(_list(names, f"{where}.submissionNames")[0], f"{where}.submissionNames[0]")


def _ec_values(node: Any, where: str, found: set[str]) -> None:
    """Every ``ecNumbers[].value`` anywhere in ``proteinDescription`` (recommended, alternative, includes, contains,
    submission names)."""
    if type(node) is dict:
        for key, value in node.items():
            if key == "ecNumbers":
                for i, ec in enumerate(_list(value, f"{where}.ecNumbers")):
                    if type(ec) is not dict or type(ec.get("value")) is not str:
                        raise FormatError(f"{where}.ecNumbers[{i}]: no value")
                    found.add(ec["value"])
            else:
                _ec_values(value, f"{where}.{key}", found)
    elif type(node) is list:
        for i, item in enumerate(node):
            _ec_values(item, f"{where}[{i}]", found)


def _position(location: dict[str, Any], key: str, where: str) -> int:
    point = _obj(location[key], f"{where}.location.{key}", ("modifier",), optional=("value",))
    if point["modifier"] != "EXACT" or type(point.get("value")) is not int:
        raise FormatError(f"{where}: the {key} position is not an exact integer (modifier {point['modifier']!r}); "
                          "the import stops")
    return point["value"]


def uniprot_row(raw: Any, requested: set[str] | frozenset[str],
                isoform_sites: list[str] | None = None) -> dict[str, Any]:
    """One UniProt ``accessions`` result -> one ``uniprot_function/entries.jsonl`` row (spec 3.4).

    A site whose ``location.sequence`` is ``<this accession>-<n>`` (an isoform of the same entry, not a canonical
    position; user decision 2026-10-09) is not stored: its accession is appended to ``isoform_sites`` instead. Any
    other ``sequence`` value or location key is a format error."""
    _obj(raw, "UniProt result", _UNIPROT_TOP, optional=_UNIPROT_TOP_OPTIONAL, dropped=_UNIPROT_TOP_DROPPED)
    accession = raw["primaryAccession"]
    if type(accession) is not str or accession not in requested:
        raise FormatError(f"UniProt result: primaryAccession {accession!r} was not requested")
    where = f"UniProt {accession}"
    organism, sequence = raw["organism"], raw["sequence"]
    if type(organism) is not dict or "scientificName" not in organism:
        raise FormatError(f"{where}.organism: no scientificName")
    if type(sequence) is not dict or "length" not in sequence:
        raise FormatError(f"{where}.sequence: no length")
    description = raw.get("proteinDescription", {})
    if type(description) is not dict:
        raise FormatError(f"{where}.proteinDescription: expected an object")
    ecs: set[str] = set()
    _ec_values(description, f"{where}.proteinDescription", ecs)
    features = []
    for i, feature in enumerate(_list(raw.get("features", []), f"{where}.features")):
        fw = f"{where}.features[{i}]"
        if type(feature) is not dict:
            raise FormatError(f"{fw}: expected an object")
        if feature.get("type") not in K.SITE_TYPES:
            continue  # only Active site, Binding site and Site are copied
        _obj(feature, fw, ("type", "location"), optional=_FEATURE_OPTIONAL, dropped=_FEATURE_DROPPED)
        if type(feature["location"]) is dict and "sequence" in feature["location"]:
            isoform = _obj(feature["location"], f"{fw}.location", ("start", "end", "sequence"))["sequence"]
            if type(isoform) is not str or not re.fullmatch(re.escape(accession) + r"-[0-9]+", isoform):
                raise FormatError(f"{fw}.location.sequence {isoform!r} is not an isoform of {accession}")
            if isoform_sites is not None:
                isoform_sites.append(accession)
            continue  # an isoform position, not a canonical one: not stored (spec 3.4)
        location = _obj(feature["location"], f"{fw}.location", ("start", "end"))
        ligand_name = ligand_id = None
        if "ligand" in feature:
            ligand = _obj(feature["ligand"], f"{fw}.ligand", ("name",), optional=("id",), dropped=_LIGAND_DROPPED)
            ligand_name, ligand_id = ligand["name"], ligand.get("id")
        features.append({"type": feature["type"], "start": _position(location, "start", fw),
                         "end": _position(location, "end", fw), "description": feature.get("description", ""),
                         "ligand_name": ligand_name, "ligand_id": ligand_id})
    activities = []
    for i, comment in enumerate(_list(raw.get("comments", []), f"{where}.comments")):
        cw = f"{where}.comments[{i}]"
        if type(comment) is not dict:
            raise FormatError(f"{cw}: expected an object")
        if comment.get("commentType") != CATALYTIC_ACTIVITY:
            continue
        _obj(comment, cw, ("commentType", "reaction"), dropped=_ACTIVITY_DROPPED)
        reaction = _obj(comment["reaction"], f"{cw}.reaction", ("name",), optional=_REACTION_OPTIONAL,
                        dropped=_REACTION_DROPPED)
        rhea, chebi = [], []
        for j, xref in enumerate(_list(reaction.get("reactionCrossReferences", []),
                                       f"{cw}.reaction.reactionCrossReferences")):
            _obj(xref, f"{cw}.reaction.reactionCrossReferences[{j}]", ("database", "id"))
            if xref["database"] == "Rhea" and type(xref["id"]) is str and _RHEA_REACTION_ID.fullmatch(xref["id"]):
                rhea.append(xref["id"])  # reaction IDs only; RHEA-COMP: polymer IDs are dropped
            elif xref["database"] == "ChEBI":
                chebi.append(xref["id"])
        activities.append({"reaction_name": reaction["name"], "ec_number": reaction.get("ecNumber"),
                           "rhea_ids": _sorted_strings(rhea, f"{cw}.rhea_ids"),
                           "chebi_ids": _sorted_strings(chebi, f"{cw}.chebi_ids")})
    row = {"accession": accession, "entry_name": raw["uniProtkbId"],
           "protein_name": _protein_name(description, f"{where}.proteinDescription"),
           "organism": organism["scientificName"], "sequence_length": sequence["length"],
           "ec_numbers": sorted(ecs), "catalytic_activities": activities, "features": features}
    K.validate_row("uniprot_function", row)
    return row


def rhea_rows(body: bytes) -> list[dict[str, Any]]:
    """The Rhea REST TSV -> ``rhea/reactions.jsonl`` rows in ``rhea_id`` integer order (spec 3.4)."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise FormatError("Rhea: the table is not UTF-8") from None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    lines = [line.removesuffix("\r") for line in lines]
    if not lines or tuple(lines[0].split("\t")) != RHEA_HEADER:
        raise FormatError(f"Rhea: the header is not exactly {' | '.join(RHEA_HEADER)}")
    data = lines[1:]
    if len(data) >= RHEA_LIMIT:
        raise FormatError(f"Rhea: {len(data)} rows reach the request limit {RHEA_LIMIT} (the table may be cut)")
    rows, seen = [], set()
    for number, line in enumerate(data, start=2):
        cells = line.split("\t")
        if len(cells) != len(RHEA_HEADER):
            raise FormatError(f"Rhea line {number}: {len(cells)} columns, expected {len(RHEA_HEADER)}")
        rhea_id, equation, names, ids, ecs = cells
        ec_numbers = []
        if ecs != "":
            for part in ecs.split(";"):
                if not part.startswith("EC:"):
                    raise FormatError(f"Rhea line {number}: EC value {part!r} has no EC: prefix")
                ec_numbers.append(part[len("EC:"):])
        if ids == "" and names == "":
            participants = []
        else:
            id_list, name_list = ids.split(";"), names.split(";")
            if len(id_list) != len(name_list):
                raise FormatError(f"Rhea line {number}: {len(id_list)} ChEBI identifiers but {len(name_list)} names")
            participants = [{"chebi_id": c, "name": n} for c, n in zip(id_list, name_list)]
        row = {"rhea_id": rhea_id, "equation": equation, "ec_numbers": sorted(ec_numbers),
               "participants": participants}
        K.validate_row("rhea", row)
        if rhea_id in seen:
            raise FormatError(f"Rhea line {number}: {rhea_id} appears twice")
        seen.add(rhea_id)
        rows.append(row)
    rows.sort(key=lambda r: K.row_sort_key("rhea", r))
    return rows


# ------------------------------------------------------------------------------------------- local reads

def _read_limited(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("not a regular file within the size limit")
        chunks, total = [], 0
        while chunk := os.read(fd, 1 << 20):
            total += len(chunk)
            if total > limit:
                raise ValueError("file grew beyond the size limit")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def read_m15_kinase_accessions(root: Path) -> tuple[str, list[str]] | None:
    """(M15 set hash, sorted ``status: ok`` UniProt accessions) of the active M15 set, or None when there is no
    readable, hash-consistent set (recorded as ``absent``; never a refusal). Local files only; M15 code untouched."""
    try:
        root = Path(root)
        pointer = json.loads(_read_limited(root / "active.json", K.MAX_POINTER_BYTES))
        if (type(pointer) is not dict or set(pointer) != {"schema", "set_hash"}
                or pointer["schema"] != M15_POINTER_SCHEMA or type(pointer["set_hash"]) is not str
                or not re.fullmatch(K.HEX64_PATTERN, pointer["set_hash"])):
            raise ValueError("unknown M15 pointer")
        set_dir = root / "sets" / pointer["set_hash"]
        raw = _read_limited(set_dir / "manifest.json", K.MAX_MANIFEST_BYTES)
        if K.sha256_hex(raw) != pointer["set_hash"]:
            raise ValueError("M15 manifest hash differs from its pointer")
        manifest = json.loads(raw)
        if manifest.get("schema") != M15_SET_SCHEMA:
            raise ValueError("unknown M15 manifest")
        [entry] = [f for s in manifest["sources"] if s.get("source") == "uniprot" for f in s["files"]
                   if f.get("name") == "entries.jsonl"]
        path = set_dir / "files" / entry["path"]
        if not path.resolve(strict=True).is_relative_to(set_dir.resolve(strict=True)):
            raise ValueError("M15 file outside its set folder")
        data = _read_limited(path, K.MAX_FILE_BYTES)
        if len(data) != entry["bytes"] or K.sha256_hex(data) != entry["sha256"]:
            raise ValueError("M15 file hash mismatch")
        accessions = set()
        for line in data.split(b"\n"):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") == "ok":
                if not K.is_accession(row["data"]["accession"]):
                    raise ValueError("M15 row without a UniProt accession")
                accessions.add(row["data"]["accession"])
        return pointer["set_hash"], sorted(accessions)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _previous_set(ref: Path) -> tuple[str | None, list[str]]:
    """(hash, user_named) of the previous active reaction set; (None, []) when there is none or it is unreadable."""
    try:
        set_hash = K.validate_pointer(json.loads(_read_limited(ref / K.ACTIVE_NAME, K.MAX_POINTER_BYTES)))
        raw = _read_limited(ref / K.SETS_DIR / set_hash / K.MANIFEST_NAME, K.MAX_MANIFEST_BYTES)
        if K.set_hash_of(raw) != set_hash:
            raise ValueError("manifest hash differs from the pointer")
        manifest = json.loads(raw, parse_constant=_reject_constant)
        K.validate_manifest(manifest)
        return set_hash, list(manifest["requested_accessions"]["user_named"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, []


def _check_target(ref: Path) -> None:
    """The reference folder must be a folder, ``sets`` a plain folder (not a link) and ``active.json`` not another
    snapshot family's pointer (for example an M15 folder named by mistake)."""
    try:
        if not stat.S_ISDIR(os.stat(ref).st_mode):
            raise ImportRefused("target_invalid", f"{ref} is not a folder")
    except FileNotFoundError:
        return
    try:
        if not stat.S_ISDIR(os.lstat(ref / K.SETS_DIR).st_mode):
            raise ImportRefused("target_invalid", f"{ref / K.SETS_DIR} is not a plain folder (links are refused)")
    except FileNotFoundError:
        pass
    try:
        pointer = json.loads(_read_limited(ref / K.ACTIVE_NAME, K.MAX_POINTER_BYTES))
    except (OSError, ValueError):
        return  # no pointer, or an unreadable one that the new pointer will replace
    if type(pointer) is dict and pointer.get("schema") != K.POINTER_SCHEMA:
        raise ImportRefused("target_invalid", f"{ref / K.ACTIVE_NAME} belongs to another snapshot family "
                                              f"({pointer.get('schema')!r}); choose the reaction reference folder")


def _user_named(params: ImportParams) -> list[str]:
    values = list(params.accessions)
    if params.accessions_file is not None:
        path = Path(params.accessions_file)
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_ACCESSIONS_FILE_BYTES + 1)
        except OSError as exc:
            raise ImportRefused("invalid_input", f"accession 파일을 읽을 수 없음 / cannot read {path}: {exc}") from None
        if len(data) > MAX_ACCESSIONS_FILE_BYTES:
            raise ImportRefused("invalid_input", f"{path} is larger than {MAX_ACCESSIONS_FILE_BYTES} bytes")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ImportRefused("invalid_input", f"{path} is not UTF-8 text") from None
        values.extend(line.strip() for line in text.splitlines() if line.strip())
    bad = [value for value in values if not K.is_accession(value)]
    if bad:
        shown = ", ".join(repr(v) for v in bad[:10])
        raise ImportRefused("invalid_input", f"UniProt accession 형식이 아님 / not UniProt accessions: {shown}")
    return sorted(set(values))


# ------------------------------------------------------------------------------------------- the import

@dataclass(frozen=True)
class ImportParams:
    """Inputs of one import. ``main`` fills the folders from the command line and environment; the caps and timing
    values are the adjustable defaults of spec 4.3/11.2 (library arguments only, no command-line option)."""

    reference_dir: Path
    m15_reference_dir: Path
    accessions: tuple[str, ...] = ()
    accessions_file: Path | None = None
    no_kinases: bool = False
    yes: bool = False
    max_accessions: int = K.MAX_ACCESSIONS
    max_skipped: int = K.MAX_SKIPPED
    max_retries: int = MAX_RETRIES
    backoff_seconds: float = BACKOFF_SECONDS
    min_interval_seconds: float = MIN_INTERVAL_SECONDS


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _timestamp(moment: _dt.datetime) -> str:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("the clock must give a time-zone aware datetime")
    return moment.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _confirm(*, ref: Path, user: list[str], kinase_state: str, kinase: list[str], kinase_hash: str | None,
             previous: str | None, dropped: list[str], params: ImportParams, input_fn: Callable[[str], str]) -> None:
    kinase_text = {"present": f"{len(kinase)}개 / accessions (M15 set {kinase_hash})",
                   "absent": "absent (M15 세트 없음·읽을 수 없음 / no readable M15 set)",
                   "disabled": "disabled (--no-kinases)"}[kinase_state]
    lines = [
        "반응 참조 스냅샷 가져오기 (M26) / Reaction reference import",
        f"- 허용 호스트 / allowed hosts (HTTPS GET only): {', '.join(K.ALLOWED_HOSTS)}",
        ("- 출처 / sources: M-CSA entries API (page_size=100), UniProt REST (≤1000 accessions per request, one "
         "request per missing accession), Rhea REST TSV (limit=20000)"),
        "- 예상 accession 수 / expected accessions:",
        "    M-CSA: M-CSA 쪽을 받은 뒤 셈 / counted from the M-CSA pages",
        f"    M15 kinase list: {kinase_text}",
        f"    직접 지정 / user-named: {len(user)}",
        (f"- 상한 / caps: MAX_ACCESSIONS={params.max_accessions} (M-CSA 쪽 직후, UniProt 요청 전에 확인 / checked "
         f"right after the M-CSA pages, before any UniProt request), MAX_SKIPPED={params.max_skipped}"),
        f"- 쓸 폴더 / target folder: {ref}",
        f"- 이전 활성 세트 / previous active set: {previous or '없음 / none'}",
        f"- 이번에 빠진 이전 직접 지정 / previous user-named not given again: {', '.join(dropped) or '없음 / none'}",
    ]
    print("\n".join(lines), flush=True)
    if params.yes:
        return
    try:
        answer = input_fn("계속할까요? / Continue? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        raise ImportRefused("cancelled", "취소됨 / cancelled by the user")


def _fetch_mcsa(requests: _Requests) -> list[dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    count = pages = None
    page = 1
    while pages is None or page <= pages:
        what = f"M-CSA page {page}"
        body = _json(requests.require_ok("mcsa", mcsa_page_url(page), what), what)
        _obj(body, what, ("count", "next", "previous", "results"))
        if type(body["count"]) is not int or body["count"] < 1:
            raise FormatError(f"{what}: count {body['count']!r} is not a positive integer")
        if any(body[key] is not None and type(body[key]) is not str for key in ("next", "previous")):
            raise FormatError(f"{what}: next/previous are not strings")  # never followed, only type-checked
        if count is None:
            count = body["count"]
            pages = -(-count // MCSA_PAGE_SIZE)
        elif body["count"] != count:
            raise FormatError(f"{what}: count {body['count']} differs from the first page's {count}")
        expected = min(MCSA_PAGE_SIZE, count - MCSA_PAGE_SIZE * (page - 1))
        results = _list(body["results"], f"{what}.results")
        if len(results) != expected:
            raise FormatError(f"{what}: {len(results)} entries, expected {expected} of count {count}")
        for raw in results:
            row = mcsa_row(raw)
            if row["mcsa_id"] in rows:
                raise FormatError(f"{what}: mcsa_id {row['mcsa_id']} appears twice")
            rows[row["mcsa_id"]] = row
        page += 1
    if len(rows) != count:
        raise FormatError(f"M-CSA: received {len(rows)} entries, count is {count}")
    return [rows[key] for key in sorted(rows)]


def _fetch_uniprot(requests: _Requests, union: list[str]) -> tuple[list[dict[str, Any]], list[str], int]:
    rows: dict[str, dict[str, Any]] = {}
    isoform_sites: list[str] = []
    for start in range(0, len(union), UNIPROT_BATCH):
        chunk = union[start:start + UNIPROT_BATCH]
        what = f"UniProt batch {start // UNIPROT_BATCH + 1} ({len(chunk)} accessions)"
        body = _json(requests.require_ok("uniprot_function", uniprot_batch_url(chunk), what), what)
        _obj(body, what, ("results",))
        wanted = frozenset(chunk)
        for raw in _list(body["results"], f"{what}.results"):
            row = uniprot_row(raw, wanted, isoform_sites)
            if row["accession"] in rows:
                raise FormatError(f"{what}: {row['accession']} appears twice")
            rows[row["accession"]] = row
    missing = [a for a in union if a not in rows]
    return [rows[key] for key in sorted(rows)], missing, len(isoform_sites)


def _inactive_reason(body: bytes, accession: str) -> tuple[str, list[str]]:
    try:
        obj = _json(body, f"UniProt {accession}")
    except FormatError:
        return "fetch_failed", []
    if type(obj) is not dict or obj.get("entryType") != "Inactive" or obj.get("primaryAccession") != accession:
        return "fetch_failed", []
    info = obj.get("inactiveReason")
    kind = info.get("inactiveReasonType") if type(info) is dict else None
    if kind == "DELETED":
        return "obsolete", []
    targets = info.get("mergeDemergeTo") if type(info) is dict else None
    bounds = {"MERGED": ("merged", 1, 1), "DEMERGED": ("demerged", 1, 3)}.get(kind)
    if (bounds is not None and type(targets) is list and all(K.is_accession(t) for t in targets)
            and len(set(targets)) == len(targets) and bounds[1] <= len(targets) <= bounds[2]):
        return bounds[0], sorted(targets)
    return "fetch_failed", []


def _classify(requests: _Requests, accession: str) -> dict[str, Any]:
    """One ``/uniprotkb/{acc}.json`` request: obsolete / merged / demerged / not_found / fetch_failed (spec 4.3)."""
    status, body = requests.get("uniprot_function", uniprot_entry_url(accession))
    if status == 404:
        reason, targets = "not_found", []
    elif status == 200:
        reason, targets = _inactive_reason(body, accession)
    else:
        reason, targets = "fetch_failed", []
    return {"accession": accession, "reason": reason, "target_accessions": targets}


def _skip_text(item: dict[str, Any]) -> str:
    targets = item["target_accessions"]
    return f"{item['accession']} {item['reason']}" + (f" -> {', '.join(targets)}" if targets else "")


def run_import(params: ImportParams, *, transport: Callable[[str], Any], sleep: Callable[[float], None] | None = None,
               clock: Callable[[], float] | None = None, now: Callable[[], _dt.datetime] | None = None,
               input_fn: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Run one import with an injected ``transport(url) -> (status, headers, body)``; returns the summary.

    Raises ``ImportRefused`` (nothing changed) on every refusal. ``sleep``/``clock``/``now``/``input_fn`` default to
    ``time.sleep``, ``time.monotonic``, the UTC wall clock and ``input``.
    """
    try:
        return _run_import(params, transport=transport, sleep=sleep or time.sleep, clock=clock or time.monotonic,
                           now=now or _utc_now, input_fn=input_fn or input)
    except FormatError as exc:
        raise ImportRefused("format_error", f"응답 형식이 다름, 설치하지 않음 / unexpected response format, nothing "
                                            f"installed: {exc}") from None


def _run_import(params: ImportParams, *, transport: Callable[[str], Any], sleep: Callable[[float], None],
                clock: Callable[[], float], now: Callable[[], _dt.datetime],
                input_fn: Callable[[str], str]) -> dict[str, Any]:
    user = _user_named(params)
    ref = Path(params.reference_dir)
    _check_target(ref)
    previous, previous_user = _previous_set(ref)
    dropped = sorted(set(previous_user) - set(user))
    if params.no_kinases:
        kinase_state, kinase_hash, kinase = "disabled", None, []
    else:
        found = read_m15_kinase_accessions(Path(params.m15_reference_dir))
        kinase_state, kinase_hash, kinase = ("absent", None, []) if found is None else ("present", *found)
    local = set(kinase) | set(user)
    if len(local) > params.max_accessions:
        raise ImportRefused("too_many_accessions", f"M15 kinase + user-named accessions ({len(local)}) exceed "
                                                   f"MAX_ACCESSIONS={params.max_accessions}; no request was sent")
    _confirm(ref=ref, user=user, kinase_state=kinase_state, kinase=kinase, kinase_hash=kinase_hash,
             previous=previous, dropped=dropped, params=params, input_fn=input_fn)
    requests = _Requests(transport, sleep=sleep, clock=clock, max_retries=params.max_retries,
                         backoff=params.backoff_seconds, min_interval=params.min_interval_seconds)

    mcsa = _fetch_mcsa(requests)
    from_mcsa = sorted({a for row in mcsa for a in K.entry_accessions(row)})
    union = sorted(set(from_mcsa) | local)
    print(f"accession 합집합 / union: {len(union)} (M-CSA {len(from_mcsa)}, M15 kinase {len(kinase)}, user-named "
          f"{len(user)}); MAX_ACCESSIONS={params.max_accessions}", flush=True)
    if len(union) > params.max_accessions:
        raise ImportRefused("too_many_accessions", f"the accession union ({len(union)}) exceeds MAX_ACCESSIONS="
                                                   f"{params.max_accessions}; stopped after the M-CSA pages, before "
                                                   "any UniProt request")

    uniprot, missing, isoform_sites_skipped = _fetch_uniprot(requests, union)
    named = set(user)
    user_missing = [a for a in missing if a in named]
    derived_missing = [a for a in missing if a not in named]
    if len(derived_missing) > params.max_skipped:
        raise ImportRefused("too_many_skipped", f"{len(derived_missing)} derived accessions are missing from UniProt, "
                                                f"more than MAX_SKIPPED={params.max_skipped}; nothing installed, no "
                                                "classification request sent",
                            [", ".join(derived_missing)] + ([f"user-named missing: {', '.join(user_missing)}"]
                                                            if user_missing else []))
    if user_missing:
        if len(user_missing) > MAX_USER_NAMED_CHECKS:
            details = [f"{a} (not classified)" for a in user_missing]
        else:
            details = [_skip_text(_classify(requests, a)) for a in user_missing]
        raise ImportRefused("user_named_unavailable", "직접 지정한 accession을 받지 못함, 명령 전체 거절(대체 없음) / "
                                                      "a user-named accession was not received; the whole command "
                                                      "is refused (no replacement)", details)
    skipped = [_classify(requests, a) for a in derived_missing]

    rhea = rhea_rows(requests.require_ok("rhea", RHEA_URL, "Rhea table"))

    imported_at = _timestamp(now())
    payloads: dict[str, bytes] = {}
    sources = []
    for source, rows in (("mcsa", mcsa), ("uniprot_function", uniprot), ("rhea", rhea)):
        (name,) = K.SOURCE_FILES[source]
        data = K.encode_jsonl(source, rows)
        if K.decode_jsonl(source, data) != rows:
            raise FormatError(f"{source}: processed rows do not round-trip")
        path = f"{K.FILES_DIR}/{source}/{name}"
        payloads[path] = data
        digests = [row["sha256"] for row in requests.rows if row["source"] == source]
        sources.append({"source": source, "date": imported_at[:10], "license": K.LICENSE,
                        "license_url": K.LICENSE_URL, "origin": K.ORIGIN, "files": [K.file_record(path, name, data)],
                        "raw_response_count": len(digests), "raw_sha256_digest": K.raw_sha256_digest(digests)})
    log = b"".join(K.jsonl_line(row) for row in requests.rows)
    payloads[K.REQUEST_LOG_PATH] = log
    requested = {"from_mcsa": len(from_mcsa),
                 "from_m15_kinase_set": {"set_hash": kinase_hash, "count": len(kinase)},
                 "m15_kinase_list": kinase_state, "user_named": user, "dropped_previous_user_named": dropped,
                 "union_count": len(union)}
    manifest = {"schema": K.SET_SCHEMA, "imported_at": imported_at, "importer_version": K.IMPORTER_VERSION,
                "sources": sources, "requested_accessions": requested, "skipped_accessions": skipped,
                "request_log": K.file_record(K.REQUEST_LOG_PATH, K.REQUEST_LOG_NAME, log)}
    K.validate_manifest(manifest)
    set_hash, set_dir, warnings = install_set(ref, manifest, payloads)
    result = {"set_hash": set_hash, "set_dir": str(set_dir), "reference_dir": str(ref), "imported_at": imported_at,
              "rows": {s["source"]: s["files"][0]["rows"] for s in sources},
              "skipped_accessions": skipped, "isoform_sites_skipped": isoform_sites_skipped,
              "request_count": len(requests.rows),
              "requested_accessions": requested, "previous_set": previous, "warnings": warnings}
    print(format_summary(result), flush=True)
    return result


# ------------------------------------------------------------------------------------------- atomic install

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


def _listed(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for record in manifest["sources"] for entry in record["files"]] + [manifest["request_log"]]


def _verify_staged(staging: Path, manifest: dict[str, Any]) -> None:
    """Read every staged file back (no links) and compare bytes, SHA-256 and line count with the manifest."""
    for entry in _listed(manifest):
        data = _read_limited(staging / entry["path"], K.MAX_FILE_BYTES)
        if (len(data) != entry["bytes"] or K.sha256_hex(data) != entry["sha256"] or data.count(b"\n") != entry["rows"]
                or (data and not data.endswith(b"\n"))):
            raise FormatError(f"staged file {entry['path']} does not match its manifest record")


def install_set(reference_dir: Path, manifest: dict[str, Any],
                payloads: dict[str, bytes]) -> tuple[str, Path, list[str]]:
    """Stage, verify, rename into ``sets/<set_hash>``, then replace ``active.json`` (spec 4.4).

    Returns (set hash, set folder, warnings). On a failure only the staging folder or the temporary pointer is removed;
    ``active.json`` and earlier sets are untouched (after the set rename the complete new set stays, inactive).
    """
    raw = K.canonical_json(manifest)
    set_hash = K.set_hash_of(raw)
    ref = Path(reference_dir)
    sets = ref / K.SETS_DIR
    final = sets / set_hash
    _check_target(ref)
    if os.path.lexists(final):
        raise ImportRefused("set_exists", f"set folder {final} already exists; nothing changed")
    staging = sets / f".staging-{uuid.uuid4().hex}"
    try:
        sets.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        for rel, data in payloads.items():
            _write_file(staging / rel, data)
        _verify_staged(staging, manifest)
        _write_file(staging / K.MANIFEST_NAME, raw)
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
        if isinstance(exc, (OSError, FormatError)):
            raise ImportRefused("install_failed", f"설치 실패, active.json·이전 세트는 그대로 / install failed, "
                                                  f"active.json and earlier sets unchanged: {exc}") from exc
        raise
    pointer_tmp = ref / f".{K.ACTIVE_NAME}.{uuid.uuid4().hex}.tmp"
    try:
        _write_file(pointer_tmp, K.pointer_bytes(set_hash))
        os.replace(pointer_tmp, ref / K.ACTIVE_NAME)
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
        _fsync_dir(ref)
    except OSError as exc:  # the rename is done; only its durability flush failed
        warnings.append(f"active.json was replaced but the folder flush failed: {exc}")
    return set_hash, final, warnings


# ------------------------------------------------------------------------------------------- reproduction (spec 4.5)

def compare_manifests(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Two imports reproduce when every processed file has the same ``files[].sha256`` (``imported_at``, the request
    log and the raw digests are ignored). Raw-digest differences are reported, never a failure."""
    K.validate_manifest(first)
    K.validate_manifest(second)
    files, raw = [], []
    for a, b in zip(first["sources"], second["sources"]):
        for fa, fb in zip(a["files"], b["files"]):
            files.append({"source": a["source"], "name": fa["name"], "first_sha256": fa["sha256"],
                          "second_sha256": fb["sha256"], "same": fa["sha256"] == fb["sha256"]})
        if (a["raw_sha256_digest"], a["raw_response_count"]) != (b["raw_sha256_digest"], b["raw_response_count"]):
            raw.append({"source": a["source"], "first_raw_sha256_digest": a["raw_sha256_digest"],
                        "second_raw_sha256_digest": b["raw_sha256_digest"],
                        "first_raw_response_count": a["raw_response_count"],
                        "second_raw_response_count": b["raw_response_count"]})
    return {"reproduced": all(item["same"] for item in files), "files": files, "raw_differences": raw,
            "imported_at": [first["imported_at"], second["imported_at"]]}


# ------------------------------------------------------------------------------------------- command line

def resolve_dir(option: str | os.PathLike | None, env_value: str | None, default: Path) -> Path:
    """The option, else the environment value, else the default; a relative value is taken from the repository
    root (the server's rule for MW_REACTION_REFERENCE_DIR)."""
    for value in (option, env_value):
        if value:
            path = Path(value).expanduser()
            return path if path.is_absolute() else ROOT / path
    return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="import_reaction_references.py", description=__doc__.split("\n\n")[0],
                                     allow_abbrev=False)
    parser.add_argument("--accession", action="append", default=[], metavar="ACC",
                        help="UniProt accession to import as well (repeatable; must be received or nothing is "
                             "installed)")
    parser.add_argument("--accessions-file", type=Path, metavar="PATH",
                        help="file with one UniProt accession per line (blank lines ignored)")
    parser.add_argument("--no-kinases", action="store_true", help="leave out the local M15 kinase accession list")
    parser.add_argument("--reference-dir", metavar="PATH",
                        help=f"reaction reference folder (default ${K.ENV_VAR} or {DEFAULT_REFERENCE_DIR}; a "
                             "relative path is taken from the repository root)")
    parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    return parser


def format_summary(result: dict[str, Any]) -> str:
    rows = result["rows"]
    skipped = result["skipped_accessions"]
    dropped = result["requested_accessions"]["dropped_previous_user_named"]
    lines = [
        "설치 완료 / Installed",
        f"- 폴더 / folder: {result['set_dir']}",
        f"- 세트 해시 / set hash: {result['set_hash']}",
        f"- 가져온 시각 / imported at: {result['imported_at']}",
        "- 행 수 / rows: " + ", ".join(f"{source} {count}" for source, count in rows.items()),
        f"- 건너뜀 / skipped: {len(skipped)}" + ("".join(f"\n    {_skip_text(item)}" for item in skipped)),
        (f"- 동형체 위치라 저장하지 않은 부위 / isoform-located sites not stored: {result['isoform_sites_skipped']} "
         "(세트에는 남기지 않음 / not recorded in the set)"),
        f"- 요청 수 / requests: {result['request_count']}",
        f"- 이번에 다시 주지 않은 이전 직접 지정 / previous user-named not given again: {', '.join(dropped) or '없음 / none'}",
        f"- M15 kinase list: {result['requested_accessions']['m15_kinase_list']}",
    ]
    lines += [f"- 경고 / warning: {text}" for text in result["warnings"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    params = ImportParams(
        reference_dir=resolve_dir(args.reference_dir, os.environ.get(K.ENV_VAR), DEFAULT_REFERENCE_DIR),
        m15_reference_dir=resolve_dir(None, os.environ.get(M15_ENV_VAR), DEFAULT_M15_DIR),
        accessions=tuple(args.accession), accessions_file=args.accessions_file, no_kinases=args.no_kinases,
        yes=args.yes)
    try:
        run_import(params, transport=UrllibTransport())  # prints the confirmation screen, progress and summary
    except ImportRefused as exc:
        print(f"가져오기 거절({exc.kind}), active.json·이전 세트는 그대로: {exc}\n"
              f"Import refused ({exc.kind}); active.json and earlier sets are unchanged.", file=sys.stderr)
        for line in exc.details:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
