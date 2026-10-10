"""Independent oracle for the M27 precedent linking rules (spec .dryforge/spec.md 3.5, 5.3-5.6), written in task T2.

Standard library only (``json``, ``hashlib``, ``argparse``, ``collections``): no ``mw`` import and no product
function. It reads the LABELLED SYNTHETIC fixtures next to it (``dist/*.jsonl``, ``pubmed/documents.jsonl``,
``numbering_maps.json``) and restates the spec in its own code:

* chains (5.3): the selected chains in the numbering map's ``chains[]`` order (request order ignored); ``accessions`` =
  sorted distinct ``uniprot_accession`` of that chain's ``rows[]`` whose ``status`` is ``mapped`` (unmapped and
  conflict rows never count); one -> ``linked``, none -> ``not_linked``/``no_mapped_residues``, two or more ->
  ``not_linked``/``multiple_accessions``; total = mapped + unmapped + conflict of the map's ``counts``.
* targets (5.4): one per distinct linked accession (ascending), its linked chains ascending; records = ``moves`` with
  ``target.uniprot`` equal to the accession, plus ``moves_flagged`` when ``include_flagged``; never a record whose
  target accession is null or different (names and ``effects[].target_ref`` are never matched); ordered by the integer
  after ``MOVE-``; status ``precedents_found`` (any record) / ``none_in_included_files`` (none, references exist) /
  ``not_in_kbase_references`` (none, no reference); ``excluded_flagged`` = the accession's ``moves_flagged`` count when
  not included (0 stays 0), else null; references = the 7 listed keys, ``ref_id`` ascending.
* record copies (5.5): the record minus ``source.parser`` and ``checks.cross_parser_numbers.measurements`` only;
  integrity = hash recomputed (own canonical JSON + SHA-256), ``str.split()`` word counts, every quote <= 25 words,
  every location page an integer >= 1.
* counts, bibliography, set summary, null result (5.6): counted here from the files; ``moves_flagged`` counts are null
  when not included and the excluded counts are null when included.

``python3 independent_match.py --check`` recomputes every case and exits 0 only if ``expected.json`` is equal;
``--write`` rewrites it. The ``precedent_set`` block is not part of the oracle (it depends on the fixture set's import
time and file hashes). Labelled ORACLE output, not product output; see SYNTHETIC-PROVENANCE-t2.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "expected.json"
LIMIT_WORDS = 25
NAMES_SHOWN = 100
LIMITATIONS = [
    "전례는 kbase_kinase가 논문에서 기계로 추출한 미검수 기록이며 ProtView가 계산하거나 판정한 것이 아니다.",
    ("방향과 크기는 kbase 규칙 v1이 숫자 또는 본문에서 산출한 값이며 논문의 결론도 ProtView의 판정도 아니고, "
     "측정 변화마다 대상 역할(on_target·off_target·not_applicable)이 함께 있다."),
    ("kbase 기계 검사는 kbase가 만들 때 한 결과를 그대로 보인 것이며 ProtView는 논문 원문과 대조하지 않았다. "
     "파일 이름(moves·moves_flagged)은 모든 검사의 통과 여부를 뜻하지 않는다."),
    ("전례가 없다는 표시는 포함한 파일에 기록이 없다는 뜻이며 선행 연구가 없다는 뜻이 아니다. 포함하지 않은 "
     "파일의 전례와 표적이 해석되지 않은 전례는 이 결과에 연결하지 않았다."),
    ("표적(UniProt)이 같은 전례만 연결했다. 다른 키나아제의 전례는 연결하지 않았고, 변이·리간드·구조와의 "
     "일치는 판단하지 않았다."),
    "전례 개수와 목록 순서는 순위·추천·유망도·성공률을 뜻하지 않는다.",
]

# (case name, map name, requested chains or None, include_flagged)
CASES = (
    ("main_all_excluded", "main", None, False),
    ("main_all_included", "main", None, True),
    ("main_subset_reordered", "main", ["B", "C"], False),
    ("main_same_accession_included", "main", ["C", "A"], True),
    ("refs_only_excluded", "refs_only", None, False),
    ("refs_only_included", "refs_only", None, True),
    ("unlinked_only", "unlinked", None, False),
)


def read_lines(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_bytes().split(b"\n"):
        if line:
            out.append(json.loads(line))
    return out


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def record_hash(record: dict[str, Any]) -> str:
    body = dict(record)
    body.pop("content_hash", None)
    return "sha256:" + hashlib.sha256(canonical(body)).hexdigest()


def number_of(move_id: str) -> int:
    return int(move_id[len("MOVE-"):])


def tally(values: list[str], label: str) -> list[dict[str, Any]]:
    counter = Counter(values)
    return [{label: value, "count": counter[value]} for value in sorted(counter)]


# ------------------------------------------------------------------------------------------- 5.3 chains

def judge_chains(numbering_map: dict[str, Any], requested: list[str] | None) -> list[dict[str, Any]]:
    wanted = None if requested is None else set(requested)
    chains = []
    for chain in numbering_map["chains"]:
        name = chain["chain_auth"]
        if wanted is not None and name not in wanted:
            continue
        found = set()
        for row in numbering_map["rows"]:
            if row["residue"]["chain_auth"] == name and row["status"] == "mapped":
                found.add(row["uniprot_accession"])
        accessions = sorted(found)
        if len(accessions) == 1:
            status, reason, accession = "linked", None, accessions[0]
        elif len(accessions) == 0:
            status, reason, accession = "not_linked", "no_mapped_residues", None
        else:
            status, reason, accession = "not_linked", "multiple_accessions", None
        counts = chain["counts"]
        chains.append({"chain_auth": name,
                       "total_residue_count": counts["mapped"] + counts["unmapped"] + counts["conflict"],
                       "mapped_residue_count": counts["mapped"], "cross_check": chain["cross_check"],
                       "cross_check_absent_reason": chain["cross_check_absent_reason"], "status": status,
                       "reason": reason, "accession": accession, "accessions": accessions})
    return chains


# ------------------------------------------------------------------------------------------- 5.5 copies

def stored_copy(record: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(record))
    if "parser" in out["source"]:
        del out["source"]["parser"]
    numbers = out["checks"]["cross_parser_numbers"]
    if "measurements" in numbers:
        del numbers["measurements"]
    return out


def integrity_of(record: dict[str, Any]) -> dict[str, Any]:
    observation_words = len(record["observation"]["quote"].split())
    tradeoff_words = []
    for tradeoff in record["tradeoffs"]:
        tradeoff_words.append(None if tradeoff["quote"] is None else len(tradeoff["quote"].split()))
    every = [observation_words] + [w for w in tradeoff_words if w is not None]
    pages = [loc.get("page") for loc in record["source"]["locations"]]
    return {"hash_verified": record_hash(record) == record["content_hash"],
            "observation_quote_words": observation_words,
            "tradeoff_quote_words": tradeoff_words,
            "quotes_within_limit": max(every) <= LIMIT_WORDS,
            "locations_have_page": all(type(p) is int and p >= 1 for p in pages)}


# ------------------------------------------------------------------------------------------- 5.4 targets

def reference_view(reference: dict[str, Any]) -> dict[str, Any]:
    keys = ("ref_id", "gene", "klifs_name", "group", "family", "coverage", "content_hash")
    return {key: reference[key] for key in keys}


def judge_targets(chains: list[dict[str, Any]], data: dict[str, Any], include_flagged: bool) -> list[dict[str, Any]]:
    by_accession: dict[str, list[str]] = {}
    for chain in chains:
        if chain["status"] == "linked":
            by_accession.setdefault(chain["accession"], []).append(chain["chain_auth"])
    targets = []
    for accession in sorted(by_accession):
        picked = []
        for file_name in ("moves", "moves_flagged"):
            if file_name == "moves_flagged" and not include_flagged:
                continue
            for record in data[file_name]:
                if record["target"]["uniprot"] == accession:
                    picked.append((number_of(record["move_id"]), file_name, record))
        picked.sort(key=lambda item: item[0])
        references = sorted((r for r in data["references"] if r["uniprot"] == accession), key=lambda r: r["ref_id"])
        flagged_here = sum(1 for r in data["moves_flagged"] if r["target"]["uniprot"] == accession)
        if picked:
            status = "precedents_found"
        elif references:
            status = "none_in_included_files"
        else:
            status = "not_in_kbase_references"
        records = [{"file": file_name, "integrity": integrity_of(record), "record": stored_copy(record)}
                   for _, file_name, record in picked]
        site, goal, tactic = [], [], []
        for _, _, record in picked:
            site.extend(set(record["tags"]["site"]))
            goal.extend(set(record["tags"]["goal"]))
            tactic.extend(set(record["tags"]["tactic"]))
        counts = {
            "moves": sum(1 for _, f, _ in picked if f == "moves"),
            "moves_flagged": sum(1 for _, f, _ in picked if f == "moves_flagged") if include_flagged else None,
            "variants": tally([record["target"]["variant"] for _, _, record in picked], "variant"),
            "tags": {"site": tally(site, "term"), "goal": tally(goal, "term"), "tactic": tally(tactic, "term")},
            "resolution_basis": tally([record["target"]["resolution_basis"] for _, _, record in picked], "basis"),
        }
        targets.append({"accession": accession, "chains": sorted(by_accession[accession]), "status": status,
                        "references": [reference_view(r) for r in references],
                        "excluded_flagged": None if include_flagged else flagged_here,
                        "records": records, "counts": counts})
    return targets


# ------------------------------------------------------------------------------------------- 5.6 the rest

def bibliography_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    fields = ("title", "journal", "year", "doi", "pmc")
    out = {}
    for row in rows:
        payload = row.get("data")
        if row.get("status") != "ok" or not isinstance(payload, dict) or payload.get("pmid") != row["id"]:
            continue
        if all(field in payload and (payload[field] is None or isinstance(payload[field], str)) for field in fields):
            out[row["id"]] = {field: payload[field] for field in fields}
    return out


def summary_of(data: dict[str, Any]) -> dict[str, Any]:
    unresolved = {"moves": 0, "moves_flagged": 0}
    names: dict[Any, dict[str, int]] = {}
    bases: dict[str, dict[str, int]] = {}
    for file_name in ("moves", "moves_flagged"):
        for record in data[file_name]:
            target = record["target"]
            if target["uniprot"] is None:
                unresolved[file_name] += 1
                slot = names.setdefault(target["name_as_written"], {"moves": 0, "moves_flagged": 0})
                slot[file_name] += 1
            else:
                slot = bases.setdefault(target["resolution_basis"], {"moves": 0, "moves_flagged": 0})
                slot[file_name] += 1
    listed = sorted(names.items(), key=lambda kv: (-(kv[1]["moves"] + kv[1]["moves_flagged"]),
                                                   0 if kv[0] is None else 1, kv[0] or ""))
    return {
        "records": {"moves": len(data["moves"]), "moves_flagged": len(data["moves_flagged"])},
        "references": len(data["references"]),
        "unresolved_target_records": unresolved,
        "unresolved_names": [{"name_as_written": name, "moves": c["moves"], "moves_flagged": c["moves_flagged"]}
                             for name, c in listed[:NAMES_SHOWN]],
        "unresolved_names_total": len(names),
        "resolution_basis_counts": [{"basis": basis, "moves": bases[basis]["moves"],
                                     "moves_flagged": bases[basis]["moves_flagged"]} for basis in sorted(bases)],
    }


def expected_result(map_handle: str, numbering_map: dict[str, Any], requested: list[str] | None,
                    include_flagged: bool, data: dict[str, Any]) -> dict[str, Any]:
    chains = judge_chains(numbering_map, requested)
    targets = judge_targets(chains, data, include_flagged)
    books = bibliography_rows(data["pubmed"])
    pmids = sorted({item["record"]["source"]["pmid"] for target in targets for item in target["records"]})
    included = sum(len(target["records"]) for target in targets)
    linked = sum(1 for chain in chains if chain["status"] == "linked")
    return {
        "schema": "kinase_precedents@1",
        "method_version": "mw.kinase_precedents/v1",
        "numbering_map": {"handle": map_handle},
        "structure": dict(numbering_map["structure"]),
        "pdb_id": numbering_map["pdb_id"],
        "include_flagged": include_flagged,
        "record_format": "kbase_record_minus_2_paths@1",
        "chains": chains,
        "targets": targets,
        "bibliography": {pmid: books.get(pmid) for pmid in pmids},
        "set_summary": summary_of(data),
        "counts": {
            "chains": len(chains),
            "linked_chains": linked,
            "not_linked_chains": len(chains) - linked,
            "targets": len(targets),
            "records": {"moves": sum(t["counts"]["moves"] for t in targets),
                        "moves_flagged": (sum(t["counts"]["moves_flagged"] for t in targets) if include_flagged
                                          else None)},
            "excluded_moves_flagged": None if include_flagged else sum(t["excluded_flagged"] for t in targets),
        },
        "null_result": included == 0,
        "limitations": list(LIMITATIONS),
    }


def compute() -> dict[str, Any]:
    data = {"moves": read_lines(HERE / "dist" / "moves.jsonl"),
            "moves_flagged": read_lines(HERE / "dist" / "moves_flagged.jsonl"),
            "references": read_lines(HERE / "dist" / "references.jsonl"),
            "pubmed": read_lines(HERE / "pubmed" / "documents.jsonl")}
    maps = json.loads((HERE / "numbering_maps.json").read_text(encoding="utf-8"))
    cases = {}
    for name, map_name, requested, include_flagged in CASES:
        cases[name] = {"map": map_name, "chains": requested, "include_flagged": include_flagged,
                       "result": expected_result(maps["map_handles"][map_name], maps["maps"][map_name], requested,
                                                 include_flagged, data)}
    return {"_oracle": ("합성(SYNTHETIC) fixture의 ORACLE output of independent_match.py (not product output); "
                        "see SYNTHETIC-PROVENANCE-t2.md"), "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    fresh = compute()
    if args.write:
        EXPECTED.write_text(json.dumps(fresh, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        return 0
    stored = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if canonical(stored) != canonical(fresh):
        print("expected.json differs from a fresh oracle run", file=sys.stderr)
        return 1
    print("expected.json matches a fresh oracle run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
