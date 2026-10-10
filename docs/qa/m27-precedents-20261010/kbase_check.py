"""M27 T1 (a)/(b)/(d) PROTOTYPE (measurement only; never product code): validate the real kbase dist against spec 3.4
and measure cost / result sizes.

Standard library, plus PyYAML only inside ``vocab_compare`` to read the kbase vocab YAML files. No ``mw`` import, no
kbase code import, no network. Prints counts, hashes, IDs and closed codes only -- never quote, observation, title or
target-name text; run outputs (from real kbase data) stay outside the repository.
Usage: python kbase_check.py validate|cost|sizes|m15 <kbase_dir> [m15_ref_root]
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import re
import resource
import sys
import time
from pathlib import Path

KB = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/Users/jaeyongryu/Projects/kbase_kinase")

KBASE_PINS = {
    "schema_version": "1",
    "effect_rules_version": "1",
    "vocab_version": "contact_class@1+goal@1+interaction@1+site@2+tactic@1+target_aliases@2:"
                     "024a47d5a62eab2a1ad1a52a0bb8f8e2740cbe3f8ad279bc6c62055c778cc11e",
}
MOVE_KEYS = frozenset("review_status, schema_version, move_id, source, target, structure_ref, structure_link_reason, "
                      "structure_ref_from, structure_links, interactions, observation, change, effects, tradeoffs, "
                      "mutations, tags, proposed_tags, figures, checks, extraction, content_hash".split(", "))
EFFECT_KEYS = frozenset("metric, assay, assay_context, target_ref, target_role, before, after, direction, "
                        "direction_basis, magnitude_bucket, comparable, comparability_reason, fold_change, "
                        "chembl_crosscheck, evidence".split(", "))
CHECK_NAMES = frozenset("qualifier_consistency, tag_vocab, schema, target_in_reference, quote_in_source, "
                        "cross_parser_numbers, chembl_crosscheck, pmid_exists, structure_ref_exists, "
                        "duplicate".split(", "))
TARGET_KEYS = frozenset({"gene", "uniprot", "name_as_written", "resolution_basis", "candidates", "variant"})
RESOLUTION_BASIS = frozenset({"gene", "klifs_gene_name", "klifs_name", "alias", "ambiguous", "unmapped", "absent",
                              "name_token", "pubmed_title", "notation"})
TARGET_ROLE = frozenset({"on_target", "off_target", "not_applicable"})
DIRECTION = frozenset({"improved", "worsened", "unchanged", "unknown"})
DIRECTION_BASIS = frozenset({"numeric", "text", "none"})
MAGNITUDE = frozenset({"small", "moderate", "large", "unknown"})
CHECK_STATUS = frozenset({"pass", "fail", "not_applicable", "lookup_failed"})
LOC_KIND = frozenset({"table", "figure", "text"})
LINK_BASIS = frozenset({"pdb_title", "paper_context", "sole_candidate"})
REF_KEYS = frozenset({"ref_id", "gene", "klifs_name", "uniprot", "group", "family", "coverage", "content_hash",
                      "review_status", "schema_version"})
SITE_TERMS = ("bp_I_A, bp_I_B, bp_II_in, bp_II_A_in, bp_II_B_in, bp_II_B, bp_II_out, bp_III, bp_IV, bp_V, fp_I, "
              "fp_II, front, back, gate, allosteric_non_atp, myristoyl_pocket, substrate_site, solvent_exposed, "
              "not_site_specific").split(", ")
GOAL_TERMS = ("potency, selectivity, mutant_coverage, binding_kinetics, solubility, permeability, "
              "metabolic_stability, oral_exposure, cns_penetration, safety_offtarget, chemical_stability, "
              "synthetic_accessibility").split(", ")
TACTIC_TERMS = ("add_hydrophobic_bulk, truncate_substituent, vector_extension, ring_fusion, scaffold_hop, "
                "heteroatom_swap, bioisostere_replacement, halogen_substitution, hbond_engagement, "
                "salt_bridge_engagement, covalent_warhead, conformational_restriction, macrocyclization, "
                "stereochemistry_change, polar_group_add, lipophilicity_reduction, prodrug_masking, "
                "degrader_conversion").split(", ")
VOCAB = {"site": frozenset(SITE_TERMS), "goal": frozenset(GOAL_TERMS), "tactic": frozenset(TACTIC_TERMS)}
ACC = re.compile(r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})\Z")
MOVE_ID = re.compile(r"MOVE-\d{4,}\Z")
DIGITS = re.compile(r"\d+\Z")
FILES = ("moves.jsonl", "moves_flagged.jsonl", "references.jsonl")
MIB = 1 << 20


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "content_hash"}
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def is_int(v) -> bool:
    return type(v) is int


def parse_jsonl(data: bytes) -> list[dict]:
    rows = []
    for line in data.split(b"\n"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def validate_move(rec: dict) -> list[str]:
    errs = []
    if set(rec) != MOVE_KEYS:
        errs.append("top_keys")
        return errs
    if rec["review_status"] != "unreviewed":
        errs.append("review_status")
    if not is_int(rec["schema_version"]) or rec["schema_version"] != 1:
        errs.append("schema_version")
    if type(rec["move_id"]) is not str or not MOVE_ID.fullmatch(rec["move_id"]):
        errs.append("move_id")
    src = rec["source"]
    if type(src) is not dict or type(src.get("pmid")) is not str or not DIGITS.fullmatch(src["pmid"]):
        errs.append("source.pmid")
    locs = src.get("locations") if type(src) is dict else None
    if type(locs) is not list or not locs:
        errs.append("source.locations")
    else:
        for loc in locs:
            if type(loc) is not dict or loc.get("kind") not in LOC_KIND:
                errs.append("location.kind")
            if type(loc) is not dict or not is_int(loc.get("page")) or loc["page"] < 1:
                errs.append("location.page")
    tgt = rec["target"]
    if type(tgt) is not dict or not TARGET_KEYS <= set(tgt):
        errs.append("target.keys")
    else:
        if tgt["uniprot"] is not None and (type(tgt["uniprot"]) is not str or not ACC.fullmatch(tgt["uniprot"])):
            errs.append("target.uniprot")
        if tgt["resolution_basis"] not in RESOLUTION_BASIS:
            errs.append("target.resolution_basis")
    tags = rec["tags"]
    if type(tags) is not dict or set(tags) != {"site", "goal", "tactic"}:
        errs.append("tags.keys")
    else:
        for axis, terms in tags.items():
            if type(terms) is not list or any(type(t) is not str for t in terms):
                errs.append("tags.type")
            elif any(t not in VOCAB[axis] for t in terms):
                errs.append(f"tags.vocab.{axis}")
    effects = rec["effects"]
    if type(effects) is not list or not effects:
        errs.append("effects.empty")
    else:
        for e in effects:
            if type(e) is not dict or not EFFECT_KEYS <= set(e):
                errs.append("effect.keys")
                continue
            if e["target_role"] not in TARGET_ROLE:
                errs.append("effect.target_role")
            if e["direction"] not in DIRECTION:
                errs.append("effect.direction")
            if e["direction_basis"] not in DIRECTION_BASIS:
                errs.append("effect.direction_basis")
            if e["magnitude_bucket"] not in MAGNITUDE:
                errs.append("effect.magnitude_bucket")
    obs = rec["observation"]
    if type(obs) is not dict or not {"text", "quote", "quote_truncated", "evidence"} <= set(obs):
        errs.append("observation.keys")
    elif type(obs["quote"]) is not str:
        errs.append("observation.quote")
    if type(rec["tradeoffs"]) is not list:
        errs.append("tradeoffs.type")
    else:
        for t in rec["tradeoffs"]:
            if type(t) is not dict or not {"text", "quote", "quote_truncated", "evidence"} <= set(t):
                errs.append("tradeoff.keys")
            elif t["quote"] is not None and type(t["quote"]) is not str:
                errs.append("tradeoff.quote")
    checks = rec["checks"]
    if type(checks) is not dict or not CHECK_NAMES <= set(checks):
        errs.append("checks.names")
    else:
        for name in CHECK_NAMES:
            if type(checks[name]) is not dict or checks[name].get("status") not in CHECK_STATUS:
                errs.append(f"checks.status.{name}")
    if type(rec["structure_links"]) is not list:
        errs.append("structure_links.type")
    else:
        for link in rec["structure_links"]:
            if type(link) is not dict or link.get("basis") not in LINK_BASIS:
                errs.append("structure_links.basis")
    ext = rec["extraction"]
    if type(ext) is not dict or not {"model", "provider", "prompt_version", "run_at"} <= set(ext):
        errs.append("extraction.keys")
    return errs


def validate_reference(rec: dict) -> list[str]:
    errs = []
    if not REF_KEYS <= set(rec):
        errs.append("keys")
        return errs
    if rec["review_status"] != "unreviewed":
        errs.append("review_status")
    if not is_int(rec["schema_version"]) or rec["schema_version"] != 1:
        errs.append("schema_version")
    if type(rec["uniprot"]) is not str or not ACC.fullmatch(rec["uniprot"]):
        errs.append("uniprot")
    return errs


def load_all():
    dist = KB / "dist"
    man_raw = (dist / "manifest.json").read_bytes()
    man = json.loads(man_raw)
    raw = {name: (dist / name).read_bytes() for name in FILES}
    ref_man_raw = (KB / "ref" / "manifest.json").read_bytes()
    ref_man = json.loads(ref_man_raw)
    pubs = [s for s in ref_man["snapshots"] if s["source"] == "pubmed"]
    latest = max(pubs, key=lambda s: s["date"])
    [pfile] = latest["files"]
    praw = (KB / "ref" / pfile["path"]).read_bytes()
    return man_raw, man, raw, ref_man_raw, latest, pfile, praw


def strip_two(rec: dict) -> dict:
    r = copy.deepcopy(rec)
    del r["source"]["parser"]
    del r["checks"]["cross_parser_numbers"]["measurements"]
    return r


def cmd_validate() -> dict:
    out: dict = {}
    man_raw, man, raw, ref_man_raw, latest, pfile, praw = load_all()
    meta = man["meta"]
    out["dist_manifest_bytes"] = len(man_raw)
    out["dist_manifest_sha256"] = hashlib.sha256(man_raw).hexdigest()
    out["dist_manifest_top_keys"] = sorted(man)
    out["ref_manifest_bytes"] = len(ref_man_raw)
    out["ref_manifest_sha256"] = hashlib.sha256(ref_man_raw).hexdigest()
    out["pins"] = {k: {"actual": meta.get(k), "match": meta.get(k) == v} for k, v in KBASE_PINS.items()}
    out["kb_version"] = man.get("kb_version")
    out["source_snapshots"] = meta.get("source_snapshots")
    files = {f["name"]: f for f in man["files"]}
    rows = {}
    out["files"] = {}
    for name in FILES:
        data = raw[name]
        lines = [ln for ln in data.split(b"\n") if ln.strip()]
        sha = "sha256:" + hashlib.sha256(data).hexdigest()
        ent = files[name]
        out["files"][name] = {
            "bytes": len(data), "lines": len(lines), "sha256": sha,
            "manifest": {"bytes": ent["bytes"], "records": ent["records"], "sha256": ent["sha256"]},
            "match": ent["bytes"] == len(data) and ent["records"] == len(lines) and ent["sha256"] == sha,
            "ends_with_newline": data.endswith(b"\n"),
            "within_64MiB": len(data) <= 64 * MIB, "within_100k_lines": len(lines) <= 100_000,
        }
        rows[name] = parse_jsonl(data)
    # pubmed
    plines = [ln for ln in praw.split(b"\n") if ln.strip()]
    prows = [json.loads(ln) for ln in plines]
    psha = "sha256:" + hashlib.sha256(praw).hexdigest()
    ids = [r.get("id") for r in prows]
    out["pubmed"] = {
        "snapshot_id": latest["snapshot_id"], "date": latest["date"], "license": latest["license"],
        "path": pfile["path"], "bytes": len(praw), "rows": len(plines), "sha256": psha,
        "manifest": {"bytes": pfile["bytes"], "rows": pfile["rows"], "sha256": pfile["sha256"]},
        "match": pfile["bytes"] == len(praw) and pfile["rows"] == len(plines) and pfile["sha256"] == psha,
        "all_pubmed_dates": sorted(s["date"] for s in json.loads(ref_man_raw)["snapshots"] if s["source"] == "pubmed"),
        "ids_digits": all(type(i) is str and DIGITS.fullmatch(i) for i in ids),
        "ids_unique": len(ids) == len(set(ids)),
        "row_keysets": collections.Counter(",".join(sorted(r)) for r in prows),
        "data_keysets": collections.Counter(",".join(sorted(r["data"])) for r in prows if type(r.get("data")) is dict),
        "status": collections.Counter(r.get("status") for r in prows),
        "biblio_eligible": sum(1 for r in prows if r.get("status") == "ok" and type(r.get("data")) is dict
                               and r["data"].get("pmid") == r.get("id")),
        "pmid_key_equals_id": sum(1 for r in prows if "pmid" in r and r["pmid"] == r["id"]),
        "year_not_int_string": sum(1 for r in prows if type(r.get("data")) is dict
                                   and not (type(r["data"].get("year")) is str and DIGITS.fullmatch(r["data"]["year"]))),
    }
    # record hashes
    out["records_hash_verified"] = {}
    out["references_without_hash"] = 0
    for name in FILES:
        ok = bad = 0
        for rec in rows[name]:
            if name == "references.jsonl" and rec.get("content_hash") is None:
                out["references_without_hash"] += 1
                continue
            if rec.get("content_hash") == content_hash(rec):
                ok += 1
            else:
                bad += 1
        out["records_hash_verified"][name] = {"verified": ok, "mismatch": bad}
    # move validation
    moves, flagged, refs = rows["moves.jsonl"], rows["moves_flagged.jsonl"], rows["references.jsonl"]
    out["move_validation"] = {}
    for name, rs in (("moves", moves), ("moves_flagged", flagged)):
        errc = collections.Counter()
        for rec in rs:
            for e in set(validate_move(rec)):
                errc[e] += 1
        out["move_validation"][name] = {
            "records": len(rs), "failing_records": sum(1 for r in rs if validate_move(r)),
            "error_counts": dict(errc),
            "top_keysets": len({frozenset(r) for r in rs}),
            "top_keys_count": sorted({len(r) for r in rs}),
            "has_source_parser": sum(1 for r in rs if "parser" in r["source"]),
            "has_cpn_measurements": sum(1 for r in rs if "measurements" in r["checks"]["cross_parser_numbers"]),
        }
    all_ids = [r["move_id"] for r in moves + flagged]
    out["move_id_unique_across_both"] = len(all_ids) == len(set(all_ids))
    out["move_id_total"] = len(all_ids)
    # extra nested keys info (shape only)
    extra = collections.Counter()
    for rec in moves + flagged:
        for k in set(rec["target"]) - TARGET_KEYS:
            extra[f"target.{k}"] += 1
        for e in rec["effects"]:
            for k in set(e) - EFFECT_KEYS:
                extra[f"effects[].{k}"] += 1
        for k in set(rec["checks"]) - CHECK_NAMES:
            extra[f"checks.{k}"] += 1
        for k in set(rec["observation"]) - {"text", "quote", "quote_truncated", "evidence"}:
            extra[f"observation.{k}"] += 1
        for k in set(rec["extraction"]) - {"model", "provider", "prompt_version", "run_at"}:
            extra[f"extraction.{k}"] += 1
        for k in set(rec["source"]) - {"pmid", "locations"}:
            extra[f"source.{k}"] += 1
    out["nested_keys_beyond_required"] = dict(sorted(extra.items()))
    # closed value sets observed
    obs = {k: collections.Counter() for k in ("resolution_basis", "target_role", "direction", "direction_basis",
                                               "magnitude_bucket", "check_status", "loc_kind", "link_basis")}
    for rec in moves + flagged:
        obs["resolution_basis"][rec["target"]["resolution_basis"]] += 1
        for e in rec["effects"]:
            obs["target_role"][e["target_role"]] += 1
            obs["direction"][e["direction"]] += 1
            obs["direction_basis"][e["direction_basis"]] += 1
            obs["magnitude_bucket"][e["magnitude_bucket"]] += 1
        for name in CHECK_NAMES:
            obs["check_status"][rec["checks"][name]["status"]] += 1
        for loc in rec["source"]["locations"]:
            obs["loc_kind"][loc["kind"]] += 1
        for link in rec["structure_links"]:
            obs["link_basis"][link["basis"]] += 1
    out["closed_values_observed"] = {k: dict(sorted(v.items())) for k, v in obs.items()}
    # references
    ref_errs = collections.Counter()
    for rec in refs:
        for e in validate_reference(rec):
            ref_errs[e] += 1
    ref_ids = [r["ref_id"] for r in refs]
    by_uni = collections.Counter(r["uniprot"] for r in refs)
    out["references"] = {
        "records": len(refs), "error_counts": dict(ref_errs), "ref_id_unique": len(ref_ids) == len(set(ref_ids)),
        "distinct_uniprot": len(by_uni), "uniprot_with_multiple_refs": sum(1 for v in by_uni.values() if v > 1),
        "max_refs_per_uniprot": max(by_uni.values()),
        "keysets": len({frozenset(r) for r in refs}),
        "coverage_values": dict(collections.Counter(r["coverage"] for r in refs)),
    }
    # vocab yaml (kbase) vs spec 9.2
    out["vocab"] = vocab_compare()
    tags_used = {axis: collections.Counter() for axis in ("site", "goal", "tactic")}
    for rec in moves + flagged:
        for axis in tags_used:
            for t in rec["tags"][axis]:
                tags_used[axis][t] += 1
    out["vocab"]["tags_used_distinct"] = {a: len(c) for a, c in tags_used.items()}
    out["vocab"]["tags_used_outside_vocab"] = {a: sorted(set(c) - VOCAB[a]) for a, c in tags_used.items()}
    # facts listed in handoff
    ref_uni = set(by_uni)
    facts = {}
    for name, rs in (("moves", moves), ("moves_flagged", flagged)):
        unres = [r for r in rs if r["target"]["uniprot"] is None]
        res = [r for r in rs if r["target"]["uniprot"] is not None]
        facts[name] = {
            "unresolved": len(unres),
            "unresolved_basis": dict(collections.Counter(r["target"]["resolution_basis"] for r in unres)),
            "resolved": len(res),
            "resolved_basis": dict(sorted(collections.Counter(r["target"]["resolution_basis"] for r in res).items())),
            "resolved_uniprot_not_in_references": sorted({r["target"]["uniprot"] for r in res} - ref_uni),
            "distinct_targets": len({r["target"]["uniprot"] for r in res}),
            "duplicate_check_fail": sum(1 for r in rs if r["checks"]["duplicate"]["status"] == "fail"),
            "observation_quote_truncated": sum(1 for r in rs if r["observation"]["quote_truncated"] is True),
            "tradeoff_quote_truncated": sum(1 for r in rs for t in r["tradeoffs"] if t["quote_truncated"] is True),
            "tradeoff_quote_null": sum(1 for r in rs for t in r["tradeoffs"] if t["quote"] is None),
            "tradeoffs_total": sum(len(r["tradeoffs"]) for r in rs),
            "quote_assembled_in_checks": sum(1 for r in rs if "quote_assembled" in json.dumps(r["checks"]["quote_in_source"])),
            "records_with_structure_links": sum(1 for r in rs if r["structure_links"]),
            "smiles_nonnull": sum(1 for r in rs if r["change"].get("smiles_from") or r["change"].get("smiles_to")),
            "quotes_over_25_words_records": sum(1 for r in rs if quote_words_over(r)),
            "effects_total": sum(len(r["effects"]) for r in rs),
            "effects_off_target": sum(1 for r in rs for e in r["effects"] if e["target_role"] == "off_target"),
            "fold_change_null": sum(1 for r in rs for e in r["effects"] if e["fold_change"] is None),
            "pmids_distinct": len({r["source"]["pmid"] for r in rs}),
        }
    names = collections.Counter()
    for rec in moves + flagged:
        if rec["target"]["uniprot"] is None:
            names[rec["target"]["name_as_written"]] += 1
    facts["unresolved_distinct_names_incl_null"] = len(names)
    facts["unresolved_null_name_records"] = names.get(None, 0)
    facts["unresolved_distinct_nonnull_names"] = len([n for n in names if n is not None])
    pdbs_moves = set()
    pdbs_all = set()
    for name, rs in (("moves", moves), ("moves_flagged", flagged)):
        for r in rs:
            for link in r["structure_links"]:
                pid = link.get("pdb_id") or link.get("pdb")
                if pid:
                    pdbs_all.add(pid)
                    if name == "moves":
                        pdbs_moves.add(pid)
    facts["structure_link_distinct_pdb"] = {"moves": len(pdbs_moves), "both": len(pdbs_all)}
    facts["structure_link_key_sets"] = sorted({",".join(sorted(link)) for r in moves + flagged
                                               for link in r["structure_links"]})
    pmids = {r["source"]["pmid"] for r in moves + flagged}
    bib = {r["id"] for r in prows if r.get("status") == "ok" and type(r.get("data")) is dict
           and r["data"].get("pmid") == r["id"]}
    facts["pmids_distinct_both"] = len(pmids)
    facts["pmids_covered_by_latest_pubmed"] = len(pmids & bib)
    m_t = collections.Counter(r["target"]["uniprot"] for r in moves if r["target"]["uniprot"])
    f_t = collections.Counter(r["target"]["uniprot"] for r in flagged if r["target"]["uniprot"])
    facts["targets_only_in_flagged"] = len(set(f_t) - set(m_t))
    facts["targets_only_in_flagged_without_reference"] = len((set(f_t) - set(m_t)) - ref_uni)
    facts["flagged_uniprot_not_in_references"] = sorted(set(f_t) - ref_uni)
    per = {}
    for acc, label in (("P00533", "EGFR"), ("Q06187", "BTK"), ("P24941", "CDK2"), ("O14965", "AURKA")):
        per[label] = {"accession": acc, "moves": m_t.get(acc, 0), "moves_flagged": f_t.get(acc, 0),
                      "references": by_uni.get(acc, 0),
                      "moves_variants": dict(sorted(collections.Counter(
                          repr(r["target"]["variant"]) for r in moves if r["target"]["uniprot"] == acc).items())),
                      "moves_without_on_target_effect": sum(
                          1 for r in moves if r["target"]["uniprot"] == acc
                          and not any(e["target_role"] == "on_target" for e in r["effects"]))}
    facts["per_target"] = per
    out["facts"] = facts
    return out


def quote_words_over(rec: dict) -> bool:
    qs = [rec["observation"]["quote"]] + [t["quote"] for t in rec["tradeoffs"] if t["quote"] is not None]
    return any(len(q.split()) > 25 for q in qs)


def vocab_compare() -> dict:
    import yaml  # only for reading kbase vocab files in this prototype (not product code)
    vdir = KB / "src" / "domains" / "kinase" / "vocab"
    res = {}
    versions = {}
    for axis, spec in (("site", SITE_TERMS), ("goal", GOAL_TERMS), ("tactic", TACTIC_TERMS)):
        data = yaml.safe_load((vdir / f"{axis}.yaml").read_text(encoding="utf-8"))
        terms = [t["id"] for t in data["terms"]]
        res[axis] = {"yaml_count": len(terms), "spec_count": len(spec), "equal_in_order": terms == spec,
                     "equal_as_set": set(terms) == set(spec), "yaml_version": data["version"],
                     "yaml_sha256": hashlib.sha256((vdir / f"{axis}.yaml").read_bytes()).hexdigest()}
    for axis in ("contact_class", "goal", "interaction", "site", "tactic"):
        versions[axis] = yaml.safe_load((vdir / f"{axis}.yaml").read_text(encoding="utf-8"))["version"]
    alias_raw = (vdir / "target_aliases.yaml").read_bytes()
    alias_ver = yaml.safe_load(alias_raw)["version"]
    recomputed = ("+".join(f"{a}@{versions[a]}" for a in sorted(versions))
                  + f"+target_aliases@{alias_ver}:" + hashlib.sha256(alias_raw).hexdigest())
    res["vocab_version_recomputed_from_yaml"] = recomputed
    res["vocab_version_recomputed_equals_pin"] = recomputed == KBASE_PINS["vocab_version"]
    return res


# ------------------------------------------------------------------------------------------------- (b) cost
def cmd_cost() -> dict:
    t0 = time.perf_counter()
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    man_raw, man, raw, ref_man_raw, latest, pfile, praw = load_all()
    t_read = time.perf_counter()
    for name in FILES:
        hashlib.sha256(raw[name]).hexdigest()
    hashlib.sha256(praw).hexdigest()
    t_sha = time.perf_counter()
    rows = {name: parse_jsonl(raw[name]) for name in FILES}
    prows = parse_jsonl(praw)
    t_parse = time.perf_counter()
    for name in ("moves.jsonl", "moves_flagged.jsonl"):
        for rec in rows[name]:
            validate_move(rec)
    for rec in rows["references.jsonl"]:
        validate_reference(rec)
    t_valid = time.perf_counter()
    for name in FILES:
        for rec in rows[name]:
            content_hash(rec)
    t_hash = time.perf_counter()
    idx = build_index(rows, prows)
    t_index = time.perf_counter()
    rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"read_s": round(t_read - t0, 4), "file_sha256_s": round(t_sha - t_read, 4),
            "parse_s": round(t_parse - t_sha, 4), "validate_s": round(t_valid - t_parse, 4),
            "content_hash_s": round(t_hash - t_valid, 4), "index_s": round(t_index - t_hash, 4),
            "total_s": round(t_index - t0, 4), "maxrss_start_bytes": rss0, "maxrss_end_bytes": rss1,
            "index_sizes": {k: len(v) for k, v in idx.items() if hasattr(v, "__len__")}}


def build_index(rows, prows) -> dict:
    by_uniprot = collections.defaultdict(list)
    for file_name, label in (("moves.jsonl", "moves"), ("moves_flagged.jsonl", "moves_flagged")):
        for rec in rows[file_name]:
            if rec["target"]["uniprot"] is not None:
                by_uniprot[rec["target"]["uniprot"]].append((label, rec))
    refs_by = collections.defaultdict(list)
    for rec in rows["references.jsonl"]:
        refs_by[rec["uniprot"]].append(rec)
    for v in refs_by.values():
        v.sort(key=lambda r: r["ref_id"])
    bib = {}
    for r in prows:
        if r.get("status") == "ok" and type(r.get("data")) is dict and r["data"].get("pmid") == r.get("id"):
            d = r["data"]
            bib[r["id"]] = {k: d.get(k) for k in ("title", "journal", "year", "doi", "pmc")}
    unresolved = collections.Counter()
    unresolved_names = collections.defaultdict(lambda: [0, 0])
    basis_counts = collections.defaultdict(lambda: [0, 0])
    for i, file_name in enumerate(("moves.jsonl", "moves_flagged.jsonl")):
        for rec in rows[file_name]:
            if rec["target"]["uniprot"] is None:
                unresolved[file_name] += 1
                unresolved_names[rec["target"]["name_as_written"]][i] += 1
            else:
                basis_counts[rec["target"]["resolution_basis"]][i] += 1
    return {"by_uniprot": by_uniprot, "references_by_uniprot": refs_by, "bibliography": bib,
            "unresolved": unresolved, "unresolved_names": unresolved_names, "resolution_basis_counts": basis_counts}


# ------------------------------------------------------------------------------------------------- (b) sizes
LIMITATIONS = [
    "전례는 kbase_kinase가 논문에서 기계로 추출한 미검수 기록이며 ProtView가 계산하거나 판정한 것이 아니다.",
    "방향과 크기는 kbase 규칙 v1이 숫자 또는 본문에서 산출한 값이며 논문의 결론도 ProtView의 판정도 아니고, "
    "측정 변화마다 대상 역할(on_target·off_target·not_applicable)이 함께 있다.",
    "kbase 기계 검사는 kbase가 만들 때 한 결과를 그대로 보인 것이며 ProtView는 논문 원문과 대조하지 않았다. "
    "파일 이름(moves·moves_flagged)은 모든 검사의 통과 여부를 뜻하지 않는다.",
    "전례가 없다는 표시는 포함한 파일에 기록이 없다는 뜻이며 선행 연구가 없다는 뜻이 아니다. "
    "포함하지 않은 파일의 전례와 표적이 해석되지 않은 전례는 이 결과에 연결하지 않았다.",
    "표적(UniProt)이 같은 전례만 연결했다. 다른 키나아제의 전례는 연결하지 않았고, 변이·리간드·구조와의 일치는 "
    "판단하지 않았다.",
    "전례 개수와 목록 순서는 순위·추천·유망도·성공률을 뜻하지 않는다.",
]


def integrity(rec: dict) -> dict:
    tw = [None if t["quote"] is None else len(t["quote"].split()) for t in rec["tradeoffs"]]
    ow = len(rec["observation"]["quote"].split())
    return {"hash_verified": True, "observation_quote_words": ow, "tradeoff_quote_words": tw,
            "quotes_within_limit": ow <= 25 and all(w is None or w <= 25 for w in tw),
            "locations_have_page": all(is_int(loc.get("page")) and loc["page"] >= 1
                                       for loc in rec["source"]["locations"])}


def target_entry(acc, chains, recs_m, recs_f, include_flagged, refs, ) -> dict:
    included = [("moves", r) for r in recs_m] + ([("moves_flagged", r) for r in recs_f] if include_flagged else [])
    included.sort(key=lambda x: int(x[1]["move_id"].split("-")[1]))
    records = [{"file": f, "integrity": integrity(r), "record": strip_two(r)} for f, r in included]
    variants = collections.Counter(r["target"]["variant"] for _, r in included)
    tags = {a: collections.Counter(t for _, r in included for t in r["tags"][a]) for a in ("site", "goal", "tactic")}
    basis = collections.Counter(r["target"]["resolution_basis"] for _, r in included)
    if included:
        status = "precedents_found"
    elif refs:
        status = "none_in_included_files"
    else:
        status = "not_in_kbase_references"
    return {"accession": acc, "chains": chains, "status": status,
            "references": [{k: r[k] for k in ("ref_id", "gene", "klifs_name", "group", "family", "coverage",
                                              "content_hash")} for r in refs],
            "excluded_flagged": None if include_flagged else len(recs_f), "records": records,
            "counts": {"moves": len(recs_m), "moves_flagged": len(recs_f) if include_flagged else None,
                       "variants": [{"variant": v, "count": c} for v, c in
                                    sorted(variants.items(), key=lambda x: (x[0] is not None, str(x[0])))],
                       "tags": {a: [{"term": t, "count": c} for t, c in sorted(tags[a].items())] for a in tags},
                       "resolution_basis": [{"basis": b, "count": c} for b, c in sorted(basis.items())]}}


def result_for(accs: list[str], include_flagged: bool, idx: dict, man: dict, pfile, latest, praw_rows) -> dict:
    targets = []
    chains = []
    for i, acc in enumerate(accs):
        cid = chr(ord("A") + i)
        recs = idx["by_uniprot"].get(acc, [])
        rm = [r for f, r in recs if f == "moves"]
        rf = [r for f, r in recs if f == "moves_flagged"]
        targets.append(target_entry(acc, [cid], rm, rf, include_flagged, idx["references_by_uniprot"].get(acc, [])))
        chains.append({"chain_auth": cid, "total_residue_count": 330, "mapped_residue_count": 310,
                       "cross_check": "agree", "cross_check_absent_reason": None, "status": "linked",
                       "reason": None, "accession": acc, "accessions": [acc]})
    pmids = sorted({rec["record"]["source"]["pmid"] for t in targets for rec in t["records"]})
    bib = {p: idx["bibliography"].get(p) for p in pmids}
    names = sorted(idx["unresolved_names"].items(), key=lambda kv: (-(kv[1][0] + kv[1][1]), kv[0] is not None,
                                                                   kv[0] or ""))
    set_summary = {"records": {"moves": 891, "moves_flagged": 885}, "references": 555,
                   "unresolved_target_records": {"moves": idx["unresolved"]["moves.jsonl"],
                                                 "moves_flagged": idx["unresolved"]["moves_flagged.jsonl"]},
                   "unresolved_names": [{"name_as_written": n, "moves": c[0], "moves_flagged": c[1]}
                                        for n, c in names[:100]],
                   "unresolved_names_total": len(names),
                   "resolution_basis_counts": [{"basis": b, "moves": c[0], "moves_flagged": c[1]}
                                               for b, c in sorted(idx["resolution_basis_counts"].items())]}
    files = [{"name": f"dist/{n}", "path": f"files/dist/{n}", "sha256": "0" * 64, "bytes": 1, "rows": 1}
             for n in FILES]
    precedent_set = {"set_hash": "0" * 64, "imported_at": "2026-10-10T00:00:00Z",
                     "importer_version": "precedent_import/1",
                     "kbase": {"commit": "0" * 40, "dist_commit": "0" * 40,
                               "dist_commit_date": "2026-09-21T00:05:28+09:00", "dirty": False,
                               "kb_version": man["kb_version"], "schema_version": "1", "effect_rules_version": "1",
                               "vocab_version": KBASE_PINS["vocab_version"],
                               "source_snapshots": man["meta"]["source_snapshots"],
                               "origin": "kbase_kinase processed dist"},
                     "files": files,
                     "bibliography_snapshot": {"snapshot_id": latest["snapshot_id"], "date": latest["date"],
                                               "license": latest["license"],
                                               "origin": "kbase_kinase processed ref/pubmed",
                                               "file": {"name": f"pubmed/{latest['date']}/documents.jsonl",
                                                        "path": "files/pubmed/x/documents.jsonl",
                                                        "sha256": "0" * 64, "bytes": 1, "rows": 1}}}
    rec_m = sum(t["counts"]["moves"] for t in targets)
    rec_f = sum(t["counts"]["moves_flagged"] for t in targets) if include_flagged else None
    return {"schema": "kinase_precedents@1", "method_version": "mw.kinase_precedents/v1",
            "numbering_map": {"handle": "obj_" + "0" * 60}, "structure": {"handle": "obj_" + "1" * 60,
                                                                        "structure_kind": "prepared_structure",
                                                                        "model_number": 1},
            "pdb_id": "XXXX", "include_flagged": include_flagged, "record_format": "kbase_record_minus_2_paths@1",
            "precedent_set": precedent_set, "chains": chains, "targets": targets, "bibliography": bib,
            "set_summary": set_summary,
            "counts": {"chains": len(chains), "linked_chains": len(chains), "not_linked_chains": 0,
                       "targets": len(targets), "records": {"moves": rec_m, "moves_flagged": rec_f},
                       "excluded_moves_flagged": None if include_flagged else sum(t["excluded_flagged"]
                                                                                 for t in targets)},
            "null_result": rec_m + (rec_f or 0) == 0, "limitations": LIMITATIONS}


def cmd_sizes() -> dict:
    man_raw, man, raw, ref_man_raw, latest, pfile, praw = load_all()
    rows = {name: parse_jsonl(raw[name]) for name in FILES}
    prows = parse_jsonl(praw)
    idx = build_index(rows, prows)
    out = {"limit_bytes": MIB, "per_target": {}, "largest": {}}
    # every target with include_flagged true/false
    sizes = {}
    for acc in idx["by_uniprot"]:
        for inc in (False, True):
            res = result_for([acc], inc, idx, man, pfile, latest, prows)
            sizes[(acc, inc)] = len(canonical_json(res).encode("utf-8"))
    for acc, label in (("Q06187", "BTK"), ("P00533", "EGFR"), ("P24941", "CDK2")):
        out["per_target"][label] = {"accession": acc, "excluded_flagged_bytes": sizes[(acc, False)],
                                    "include_flagged_bytes": sizes[(acc, True)]}
    for inc in (False, True):
        best = max((a for a, i in sizes if i == inc), key=lambda a: sizes[(a, inc)])
        recs = idx["by_uniprot"][best]
        out["largest"]["include_flagged" if inc else "excluded_flagged"] = {
            "accession": best, "bytes": sizes[(best, inc)],
            "moves": sum(1 for f, _ in recs if f == "moves"), "moves_flagged": sum(1 for f, _ in recs
                                                                                   if f == "moves_flagged")}
    top = sorted(((a, sizes[(a, True)]) for a, i in sizes if i), key=lambda x: -x[1])[:5]
    out["top5_include_flagged"] = [{"accession": a, "bytes": b} for a, b in top]
    out["over_limit_targets"] = {"excluded_flagged": sum(1 for (a, i), b in sizes.items() if not i and b > MIB),
                                 "include_flagged": sum(1 for (a, i), b in sizes.items() if i and b > MIB)}
    out["targets_measured"] = len(idx["by_uniprot"])
    # two largest targets together (two chains, different accessions)
    a1, a2 = top[0][0], top[1][0]
    for inc in (False, True):
        res = result_for([a1, a2], inc, idx, man, pfile, latest, prows)
        out.setdefault("two_largest_together", {})["include_flagged" if inc else "excluded_flagged"] = {
            "accessions": [a1, a2], "bytes": len(canonical_json(res).encode("utf-8"))}
    # full original records (no paths removed) for BTK flagged, for comparison
    full = sum(len(canonical_json(r).encode("utf-8")) for _, r in idx["by_uniprot"]["Q06187"])
    stripped = sum(len(canonical_json(strip_two(r)).encode("utf-8")) for _, r in idx["by_uniprot"]["Q06187"])
    out["btk_records_only_bytes"] = {"full_records": full, "minus_2_paths": stripped}
    return out


# ------------------------------------------------------------------------------------------------- (d) M15 kinases
def read_limited(path: Path, limit: int) -> bytes:
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError("too large")
    return data


def cmd_m15() -> dict:
    root = Path(sys.argv[3])
    pointer = json.loads(read_limited(root / "active.json", 4096))
    assert set(pointer) == {"schema", "set_hash"} and pointer["schema"] == "reference_active@1"
    set_dir = root / "sets" / pointer["set_hash"]
    mraw = read_limited(set_dir / "manifest.json", 1 << 20)
    assert hashlib.sha256(mraw).hexdigest() == pointer["set_hash"]
    [entry] = [f for s in json.loads(mraw)["sources"] if s["source"] == "uniprot"
               for f in s["files"] if f["name"] == "entries.jsonl"]
    data = read_limited(set_dir / "files" / entry["path"], 512 << 20)
    assert len(data) == entry["bytes"] and hashlib.sha256(data).hexdigest() == entry["sha256"]
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    ok = sorted({r["data"]["accession"] for r in rows if r.get("status") == "ok"})
    refs = parse_jsonl((KB / "dist" / "references.jsonl").read_bytes())
    ref_uni = {r["uniprot"] for r in refs}
    return {"m15_set_hash": pointer["set_hash"], "uniprot_file": entry["path"], "rows": len(rows),
            "status_counts": dict(collections.Counter(r.get("status") for r in rows)),
            "ok_accessions": len(ok), "ok_in_kbase_references": len(set(ok) & ref_uni),
            "ok_missing_from_kbase_references": sorted(set(ok) - ref_uni),
            "kbase_reference_uniprot_distinct": len(ref_uni),
            "kbase_reference_uniprot_not_in_m15_ok": len(ref_uni - set(ok))}


if __name__ == "__main__":
    cmd = sys.argv[1]
    result = {"validate": cmd_validate, "cost": cmd_cost, "sizes": cmd_sizes, "m15": cmd_m15}[cmd]()
    print(json.dumps(result, indent=1, ensure_ascii=False, default=lambda o: dict(o)))
