# PROTOTYPE (M29 T1 (c)(f) measurement only; never product code, never imported by mw).
"""(c) new-atom marker candidates through the allowed consumers; (f) M7 preflight before publication.

    PYTHONPATH=backend .venv/bin/python docs/qa/m29-repair-20261013/probe/marker_and_preflight.py <runs-root> \
        [--additions docs/qa/m29-repair-20261013/probe/8vf6_additions.json]

``<runs-root>`` must be new and Git-ignored (e.g. ``runs/m29-t1-20261013/cf``), not under /tmp. It holds throwaway
runs only. 8VF6 is loaded and prepared with the unmodified product tools (waters strip_all and keep_all); repaired
mmCIF variants are spliced from the stored prepared coordinates + the PDBFixer-measured additions
(splice_prototype.build). Repaired objects are NEVER put into the base run: every consumer reads them through
read-only views.

(c) variants: full-precision vs 4-decimal new coordinates; marker calc_flag / extra category / second data block /
none. Consumers: product `_parse` (gemmi, M7/M20/M24 path), OpenMM `PDBxFile`, PDBFixer reader, product M7
`preflight`, gemmi read+write round trip, and the M21 PDBx hand-off precision (`PDBxFile.writeFile` writes %10.4f).
(f) methods for "M7 preflight before anything is stored": F1 read-only overlay store, F2 throwaway ObjectStore with
the same run id (copied inputs, deleted afterwards), F3 reference = really stored in a second root with the same run id
(handles are content hashes, so results must be byte-identical), F4 = store-then-fail (shows the orphan events).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netguard  # noqa: E402,F401
from splice_prototype import build  # noqa: E402

import gemmi  # noqa: E402
from openmm import app  # noqa: E402
from pdbfixer import PDBFixer  # noqa: E402

from mw.core.errors import ToolFailure  # noqa: E402
from mw.core.handles import HANDLE_PREFIX, ObjectStore, canonical_json, object_sha  # noqa: E402
from mw.tools.openmm_method import preflight  # noqa: E402
from mw.tools.registry import ToolContext  # noqa: E402
from mw.tools.structural import _parse  # noqa: E402
from mw.workspace import new_run  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
SOURCE = REPO / "runs" / "stk33-8vf6-20261013" / "8VF6.cif"
RUN_ID = "run_m29t1_cf"


def handle_for(run_id: str, kind: str, schema: str, raw: bytes) -> str:
    return f"{HANDLE_PREFIX}{run_id}/{kind}/{object_sha(kind, schema, raw)}"


class Overlay:
    """F1: read-only view = base store + in-memory pending objects (same handle rule, nothing written)."""

    def __init__(self, base: ObjectStore, pending: dict[str, dict]):
        self.base, self.pending = base, pending
        self.run_id, self.events = base.run_id, base.events

    def meta(self, handle: str) -> dict:
        if handle in self.pending:
            p = self.pending[handle]
            return {"handle": handle, "kind": p["kind"], "schema": p["schema"], "fmt": p["fmt"],
                    "size": len(p["raw"]), "summary": {}, "null_result": False, "produced_by": None,
                    "path": None}
        return self.base.meta(handle)

    def load(self, handle: str):
        if handle in self.pending:
            p = self.pending[handle]
            return json.loads(p["raw"]) if p["fmt"] == "json" else p["raw"]
        return self.base.load(handle)


def pending_objects(run_id: str, prepared: dict, manifest: dict, text: str) -> tuple[str, dict]:
    pending = {}

    def add(kind, schema, fmt, content):
        raw = content if isinstance(content, bytes) else canonical_json(content)
        h = handle_for(run_id, kind, schema, raw)
        pending[h] = {"kind": kind, "schema": schema, "fmt": fmt, "raw": raw, "content": content}
        return h

    coords = add("prepared_coordinates", "prepared_coordinates@1", "cif", text.encode())
    record = handle_for(run_id, "structure_repair", "structure_repair@1",
                        canonical_json({"placeholder": "T1 probe, never stored", "coordinates": coords}))
    repaired_manifest = {**manifest, "missing_residues": "modeled_internal_gaps",
                         "repair": {"record": record, "source": prepared["__handle__"]}}
    mh = add("preparation_manifest", "preparation_manifest@1", "json", repaired_manifest)
    sh = add("prepared_structure", "prepared_structure@1", "json",
             {"coordinates": coords, "manifest": mh, "model_index": prepared["model_index"],
              "model_number": prepared["model_number"]})
    return sh, pending


def outcome(fn):
    t0 = time.perf_counter()
    try:
        value = fn()
        return {"ok": True, "value": value, "seconds": round(time.perf_counter() - t0, 3)}
    except ToolFailure as exc:
        return {"ok": False, "failure": {"class": exc.cls.value, "message": exc.message,
                                         "reason_code": (exc.detail or {}).get("reason_code"),
                                         "residue": (exc.detail or {}).get("residue")},
                "seconds": round(time.perf_counter() - t0, 3)}
    except Exception as exc:  # noqa: BLE001  (probe: report any consumer error verbatim)
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "seconds": round(time.perf_counter() - t0, 3)}


def preflight_digest(result: dict) -> str:
    return hashlib.sha256(canonical_json(result)).hexdigest()


def store_state(store: ObjectStore) -> tuple[int, int]:
    events = sum(1 for _ in open(store.events.path)) if hasattr(store.events, "path") else -1
    return events, len(store.handles())


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--additions", type=Path,
                    default=REPO / "docs" / "qa" / "m29-repair-20261013" / "probe" / "8vf6_additions.json")
    args = ap.parse_args(argv)
    if str(args.root.resolve()).startswith(("/tmp", "/private/tmp")):
        raise SystemExit("root must not be under /tmp")
    args.root.mkdir(parents=True, exist_ok=False)
    additions = json.loads(args.additions.read_text())
    raw = SOURCE.read_bytes()
    run = new_run(args.root / "base", dry_run=False, run_id=RUN_ID)
    base = run.store
    source = run.call("load_structure", {"source": "8VF6.cif", "model_index": 0}, source_bytes=raw,
                      source_format="cif")
    prepared_by_policy = {}
    for waters in ("strip_all", "keep_all"):
        p = run.call("prepare_structure", {"structure": source.handle, "altloc": "highest_occupancy",
                                           "waters": waters, "hydrogens": "strip",
                                           "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
        prepared_by_policy[waters] = p.handle
    print(f"# base run: {RUN_ID}; input sha256 {hashlib.sha256(raw).hexdigest()[:16]}; {netguard.summary()}")
    report = {"c": [], "f": []}
    variants = [("full_precision", None, "calc_flag"), ("round4", 4, "calc_flag"), ("round4", 4, "category"),
                ("round4", 4, "second_block"), ("round4", 4, "none")]
    added_keys = {(json.dumps(a["residue"], sort_keys=True), a["atom_name"]): a["coordinates_A"]
                  for a in additions["added_atoms"]}
    for waters, ph in prepared_by_policy.items():
        prepared = base.load(ph)
        prepared["__handle__"] = ph
        manifest = base.load(prepared["manifest"])
        prepared_text = base.load(prepared["coordinates"]).decode()
        original = outcome(lambda: preflight(base, ph, seed=run.seed))
        print(f"\n## {waters}: original prepared structure M7 preflight -> "
              f"{'pass' if original['ok'] else original.get('failure') or original.get('error')}")
        for label, decimals, marker in variants:
            text = build(prepared_text, additions, decimals=decimals, marker=marker)
            sh, pending = pending_objects(RUN_ID, prepared, manifest, text)
            view = Overlay(base, pending)
            row = {"waters": waters, "coordinates": label, "marker": marker, "bytes": len(text.encode())}
            parsed = outcome(lambda: _parse(ToolContext(store=view, call_id="t1c"), sh))
            if parsed["ok"]:
                st = parsed["value"]
                atoms = [(ch, r, a) for ch in st[0] for r in ch for a in r]
                row["gemmi_parse"] = {"ok": True, "atoms": len(atoms), "chains": [ch.name for ch in st[0]],
                                      "calc_flag_c": sum(1 for *_, a in atoms
                                                         if a.calc_flag == gemmi.CalcFlag.Calculated)}
                got = {}
                for ch, r, a in atoms:
                    key = (json.dumps({"model_number": st[0].num, "chain_auth": ch.name, "seq_auth": r.seqid.num,
                                       "icode": r.seqid.icode.strip(), "chain_label": r.subchain or None,
                                       "seq_label": r.label_seq, "resname": r.name}, sort_keys=True), a.name)
                    got[key] = (a.pos.x, a.pos.y, a.pos.z, a.serial)
                row["new_coord_max_diff_vs_record_A"] = max(math.dist(got[k][:3], v) for k, v in added_keys.items())
                orig = _parse(ToolContext(store=base, call_id="t1c"), ph)
                deltas, missing, serial_changed = [], 0, 0
                for ch in orig[0]:
                    for r in ch:
                        for a in r:
                            k = (json.dumps({"model_number": orig[0].num, "chain_auth": ch.name,
                                             "seq_auth": r.seqid.num, "icode": r.seqid.icode.strip(),
                                             "chain_label": r.subchain or None, "seq_label": r.label_seq,
                                             "resname": r.name}, sort_keys=True), a.name)
                            if k in got:
                                deltas.append(math.dist(got[k][:3], (a.pos.x, a.pos.y, a.pos.z)))
                                serial_changed += got[k][3] != a.serial
                            else:
                                missing += 1
                row["observed_atoms"] = {"compared": len(deltas), "missing_in_repaired": missing,
                                         "max_delta_A": max(deltas), "atom_site_id_changed": serial_changed}
                four = [abs(float(f"{v:.4f}") - v) for xyz in got.values() for v in xyz[:3]]
                row["pdbx_writefile_4dp_roundtrip_max_A"] = max(four)
            else:
                row["gemmi_parse"] = {k: v for k, v in parsed.items() if k != "value"}
            ommp = outcome(lambda: app.PDBxFile(io.StringIO(text)))
            row["openmm_pdbxfile"] = ({"ok": True, "atoms": ommp["value"].topology.getNumAtoms(),
                                       "chains": ommp["value"].topology.getNumChains()} if ommp["ok"] else ommp)

            def fixer_read():
                fx = PDBFixer(pdbxfile=io.StringIO(text))
                fx.findMissingResidues()
                tails = {k: len(v) for k, v in fx.missingResidues.items()}
                fx.findMissingAtoms()
                return {"missing_residue_blocks": len(tails), "missing_residues": sum(tails.values()),
                        "missing_atom_residues": len(fx.missingAtoms),
                        "missing_terminals": len(fx.missingTerminals)}
            fx = outcome(fixer_read)
            row["pdbfixer_reader"] = fx["value"] if fx["ok"] else fx
            m7 = outcome(lambda: preflight(view, sh, seed=run.seed))
            row["m7_preflight_overlay"] = ({"ok": True, "heavy_atom_count": m7["value"]["heavy_atom_count"],
                                            "excluded": len(m7["value"]["excluded"]),
                                            "chains": [c["chain_auth"] for c in m7["value"]["protein"]],
                                            "digest": preflight_digest(m7["value"])[:16], "seconds": m7["seconds"]}
                                           if m7["ok"] else m7)
            rt = outcome(lambda: gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
                         .make_mmcif_document().as_string())
            if rt["ok"]:
                again = rt["value"]
                row["gemmi_roundtrip"] = {"calc_flag_column": "_atom_site.calc_flag" in again,
                                          "category_kept": "_protview_repair_added_atom" in again}
            else:
                row["gemmi_roundtrip"] = rt
            report["c"].append(row)
            print(json.dumps(row, sort_keys=True, default=str))
    # ---------------- (f) ----------------
    print("\n## (f) M7 preflight before publication (strip_all, round4 + calc_flag; plus a broken variant)")
    ph = prepared_by_policy["strip_all"]
    prepared = base.load(ph)
    prepared["__handle__"] = ph
    manifest = base.load(prepared["manifest"])
    prepared_text = base.load(prepared["coordinates"]).decode()
    broken = json.loads(json.dumps(additions))
    broken["added_atoms"] = [a for a in broken["added_atoms"]
                             if not (a["residue"]["chain_auth"] == "A" and a["residue"]["seq_auth"] == 100
                                     and a["atom_name"] == "NZ")]
    cases = {"repaired_round4": additions, "broken_missing_A100_NZ": broken}
    for name, adds in cases.items():
        text = build(prepared_text, adds, decimals=4, marker="calc_flag")
        sh, pending = pending_objects(RUN_ID, prepared, manifest, text)
        before = store_state(base)
        f1 = outcome(lambda: preflight(Overlay(base, pending), sh, seed=run.seed))
        after_f1 = store_state(base)
        scratch_dir = args.root / f"scratch_{name}"

        def f2():
            scratch = ObjectStore(scratch_dir, RUN_ID)
            needed = [source.handle, base.load(source.handle)["source"]]
            for h in needed:
                m = base.meta(h)
                content = base.load(h)
                copied = scratch.put(m["kind"], m["schema"], content, fmt=m["fmt"])
                assert copied.handle == h
            for h, p in pending.items():
                put = scratch.put(p["kind"], p["schema"], p["content"], fmt=p["fmt"])
                assert put.handle == h
            try:
                return preflight(scratch, sh, seed=run.seed)
            finally:
                scratch.db.close()
        f2r = outcome(f2)
        shutil.rmtree(scratch_dir)
        after_f2 = store_state(base)
        ref_run = new_run(args.root / f"reference_{name}", dry_run=False, run_id=RUN_ID)
        rs = ref_run.call("load_structure", {"source": "8VF6.cif", "model_index": 0}, source_bytes=raw,
                          source_format="cif")
        rp = ref_run.call("prepare_structure", {"structure": rs.handle, "altloc": "highest_occupancy",
                                                "waters": "strip_all", "hydrogens": "strip",
                                                "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
        same_inputs = rs.handle == source.handle and rp.handle == ph
        ref_before = store_state(ref_run.store)
        for h, p in sorted(pending.items(), key=lambda kv: ["prepared_coordinates", "preparation_manifest",
                                                           "prepared_structure"].index(kv[1]["kind"])):
            assert ref_run.store.put(p["kind"], p["schema"], p["content"], fmt=p["fmt"]).handle == h
        ref_after_put = store_state(ref_run.store)
        f3 = outcome(lambda: preflight(ref_run.store, sh, seed=run.seed))

        def digest(o):
            if o["ok"]:
                return "pass:" + preflight_digest(o["value"])[:16]
            return "fail:" + json.dumps(o.get("failure") or o.get("error"), sort_keys=True)
        line = {"case": name, "F1_overlay": digest(f1), "F1_seconds": f1["seconds"],
                "F2_scratch_store": digest(f2r), "F2_seconds": f2r["seconds"],
                "F3_stored_reference": digest(f3), "identical_F1_F2_F3": digest(f1) == digest(f2r) == digest(f3),
                "base_run_events_objects_before_after_F1_F2": [before, after_f1, after_f2],
                "reference_same_input_handles": same_inputs,
                "F4_store_then_check_new_events_objects": [ref_after_put[0] - ref_before[0],
                                                           ref_after_put[1] - ref_before[1]]}
        report["f"].append(line)
        print(json.dumps(line, sort_keys=True))
    print(f"\n# {netguard.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
