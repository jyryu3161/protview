"""API-level cases and the judgement of the UI cases of the M29 structure repair acceptance (.dryforge/spec.md 10).

The ``Lab`` reaches the product only over the loopback API (``m29_common.Api``: GET, run / upload / command / report
creation and job submission, approval and start POSTs; never a limit-raising or ``/jev`` / ``/jev_loops`` write) and
reads the run's ``events.jsonl`` read-only. Expectations come from ``m29_oracle`` (the input files and the installed
template) and the documents in ``m29_common``; never from a product answer. This module never imports ``mw``.

Entry points (the runner calls them in this order; each returns plain dicts it writes as evidence):
  ``Lab.table(names)``                spec 10.1 / R5: every structure x water policy (new run each): upload, load,
                                      prepare, the free preflight read vs the oracle; in_scope rows go on through the
                                      repair job, the stored record and bytes vs the oracle, an M20 set on the repaired
                                      structure and the M21 admission (completed for the ``completes`` band, else the
                                      queued job is cancelled); out_of_scope rows are submitted once and must be refused
                                      with the classified code and no job or unit.
  ``r1_case`` / ``r3_setup`` / ``r3_case`` / ``r4a_case`` / ``r8_case`` / ``r10_case``  the UI cases (harness rows)
  ``r2_case`` / ``r5_case`` / ``r7_case`` / ``r6_api`` / ``r4b_case``   the API cases
  ``reopen_reads`` / ``r9_case``      events-only reopen (the runner restarts the backend between the two reads)
  ``r11_case``                        the wording scan of the new texts
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import m29_common as c
import m29_oracle as oracle

TERMINAL = ("done", "failed", "cancelled", "interrupted")
POCKET_TIMEOUT_S = 120          # the M12 job's bound
PREPARE = {"altloc": "highest_occupancy", "hydrogens": "strip", "missing_residues": "leave_gaps",
           "symmetry_mates": "ignore"}


def claim_value(manifest: dict, statement: str, field_path: str) -> Any:
    """The exact value of the one claim of ``statement`` citing ``field_path`` (None when there is not exactly one)."""
    found = [claim.get("exact_value") for claim in manifest.get("claims") or []
             if claim.get("statement_id") == statement and claim.get("field_path") == field_path]
    return found[0] if len(found) == 1 else None


def _fail_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:400]


class Lab:
    def __init__(self, api: c.Api, runs: Path, code: Path, record: Callable[..., None] | None = None) -> None:
        self.api, self.runs, self.code = api, Path(runs), Path(code)
        self.record = record or (lambda *args, **kwargs: None)
        self.tpl = oracle.templates()
        self._oracle: dict[tuple[str, str], dict] = {}
        self.rows: dict[tuple[str, str], dict] = {}

    # ----- inputs --------------------------------------------------------------------------------------------
    def path(self, name: str) -> Path:
        return self.code / c.FIXTURES / f"public_{name}.cif"

    def oracle(self, name: str, waters: str, path: Path | None = None) -> dict:
        key = (str(path or name), waters)
        if key not in self._oracle:
            self._oracle[key] = oracle.classify((path or self.path(name)).read_bytes(), waters, self.tpl)
        return self._oracle[key]

    # ----- product calls ---------------------------------------------------------------------------------------
    def new_run(self, goal: str) -> str:
        status, made = self.api.post("/runs", {"goal": goal, "context": [], "dry_run": False, "egress": "local_only"})
        if status not in (200, 201) or not isinstance(made, dict):
            raise RuntimeError(f"POST /runs answered {status}")
        return made["run_id"]

    def command(self, rid: str, tool: str, args: dict) -> tuple[int, Any]:
        return self.api.post(f"/runs/{rid}/commands", {"tool": tool, "args": args})

    def load_prepare(self, rid: str, path: Path, waters: str) -> dict:
        raw = path.read_bytes()
        status, upload = self.api.post(f"/runs/{rid}/uploads?filename={c.enc(path.name)}", raw,
                                       "application/octet-stream")
        if status != 201:
            raise RuntimeError(f"upload {path.name}: {status} {_fail_text(upload)}")
        status, loaded = self.command(rid, "load_structure", {"source": upload["upload_id"], "model_index": 0})
        if status != 200 or not loaded.get("ok"):
            raise RuntimeError(f"load {path.name}: {status} {_fail_text(loaded)}")
        args = {"structure": loaded["handle"]["handle"], "waters": waters, **PREPARE}
        status, prepared = self.command(rid, "prepare_structure", args)
        if status != 200 or not prepared.get("ok"):
            raise RuntimeError(f"prepare {path.name}: {status} {_fail_text(prepared)}")
        return {"run": rid, "source": loaded["handle"]["handle"], "prepared": prepared["handle"]["handle"],
                "inputSha256": c.sha256(raw), "inputBytes": len(raw), "waters": waters}

    def preflight(self, rid: str, structure: str) -> dict:
        status, body = self.api.get(f"/runs/{rid}/structure_repair/preflight?structure={c.enc(structure)}")
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f"preflight answered {status}: {_fail_text(body)}")
        return body

    def read(self, path: str) -> Any:
        """A GET whose answer must be 200 (any other status raises: a refused or failed read is never read as a
        value)."""
        status, body = self.api.get(path)
        if status != 200:
            raise RuntimeError(f"GET {path.split('?', 1)[0]} answered {status}: {_fail_text(body)}")
        return body

    def budget(self, rid: str) -> dict:
        return self.read(f"/runs/{rid}/budget")

    def used_units(self, rid: str) -> int:
        return self.budget(rid)["expensive_calls"]["used"]

    def jobs(self, rid: str) -> list[dict]:
        return self.read(f"/runs/{rid}/jobs")

    def job(self, rid: str, job_id: str) -> dict:
        return self.read(f"/runs/{rid}/jobs/{job_id}")

    def submit(self, rid: str, protocol: str, args: dict, timeout_s: float) -> tuple[int, Any]:
        return self.api.post(f"/runs/{rid}/jobs", {"protocol_id": protocol, "args": args, "timeout_s": timeout_s})

    def start(self, rid: str, job_id: str, wait_s: float = 900) -> tuple[dict, bool]:
        """Start (approving the run's first expensive call when the start asks), then wait for a terminal state."""
        approved = False
        status, body = self.api.post(f"/runs/{rid}/jobs/{job_id}/start")
        if status == 409 and isinstance(body, dict) and (body.get("approval") or {}).get("gate") == \
                "expensive_first_call":
            approved = self.api.post(f"/runs/{rid}/jobs/approve")[0] == 200
            self.api.post(f"/runs/{rid}/jobs/{job_id}/start")
        deadline = time.monotonic() + wait_s
        job = self.job(rid, job_id)
        while job.get("status") not in TERMINAL and time.monotonic() < deadline:
            time.sleep(1)
            job = self.job(rid, job_id)
        return job, approved

    def repair(self, rid: str, prepared: str) -> dict:
        status, job = self.submit(rid, c.REPAIR_PROTOCOL, {"structure": prepared, "repair_policy": c.REPAIR_POLICY},
                                  c.REPAIR_TIMEOUT_S)
        if status != 200:
            return {"submitStatus": status, "submit": job, "job": None}
        done, approved = self.start(rid, job["job_id"])
        handles = done.get("output_handles") or []
        return {"submitStatus": status, "job": done, "approved": approved,
                "record": handles[0] if len(handles) == 2 else None,
                "repaired": handles[1] if len(handles) == 2 else None}

    def repair_detail(self, rid: str, record: str) -> dict:
        status, body = self.api.get(f"/runs/{rid}/structure_repairs/{c.enc(record)}")
        if status != 200:
            raise RuntimeError(f"repair detail {status}: {_fail_text(body)}")
        return body

    def repaired_bytes(self, rid: str, record: str) -> bytes:
        status, raw = self.api.get(f"/runs/{rid}/structure_repairs/{c.enc(record)}/structure", raw=True)
        if status != 200:
            raise RuntimeError(f"repaired structure download {status}")
        return raw

    def structure_bytes(self, rid: str, handle: str) -> bytes:
        status, raw = self.api.get(f"/runs/{rid}/structures/bytes?handle={c.enc(handle)}", raw=True)
        if status != 200:
            raise RuntimeError(f"structure bytes {status}")
        return raw

    def events(self, rid: str) -> list[dict]:
        return c.read_events(self.runs, rid)

    def report(self, rid: str, handle: str) -> dict:
        status, body = self.api.get(f"/runs/{rid}/reports/selected?handle={c.enc(handle)}")
        if status != 200:
            raise RuntimeError(f"report {status}: {_fail_text(body)}")
        return body

    # ----- one stored repair against the oracle ----------------------------------------------------------------
    def check_repair(self, rid: str, name: str, waters: str, prepared: str, record_handle: str,
                     path: Path | None = None) -> dict:
        """The stored record, the published event, the stored bytes and the record's counts against the oracle
        (spec 3.2-3.5). Returns ``{"ok", "problems", ...facts}``."""
        row = self.oracle(name, waters, path)
        problems: list[str] = []
        detail = self.repair_detail(rid, record_handle)
        record = detail["result"]
        events = self.events(rid)
        published = [event for event in events if event.get("type") == "structure_repair_published"
                     and event.get("record") == record_handle]
        if len(published) != 1 or published[0].get("prepared_structure") != detail["prepared_structure"]:
            problems.append("no single structure_repair_published event naming the record and the structure")
        if detail["source_structure"] != prepared:
            problems.append("the record's source is not the prepared structure that was repaired")
        counts = record["counts"]
        want = {"added_residues": row["expected_added_residues"], "added_atoms": row["expected_added_heavy_atoms"],
                "protein_heavy_atoms": row["protein_heavy_after"], "side_chain_residues": len(row["side_chain"]),
                "terminal_oxt": len(row["terminal_oxt"]), "gaps": len(row["gap_lengths"]),
                "replaced": len(row["nonstandard"])}
        for key, value in want.items():
            if counts.get(key) != value:
                problems.append(f"counts.{key} {counts.get(key)} != {value} (oracle)")
        if record["classes_applied"] != row["classes"]:
            problems.append(f"classes {record['classes_applied']} != {row['classes']} (oracle)")
        if sorted(gap["length"] for gap in record["gaps"]) != sorted(row["gap_lengths"]):
            problems.append("gap lengths differ from the file's listing")
        differs = any(end["first_is_sequence_start"] is False or end["last_is_sequence_end"] is False
                      for end in record["chain_ends"])
        oracle_differs = any(end["first_is_sequence_start"] is False or end["last_is_sequence_end"] is False
                             for end in row["chain_ends"])
        if differs != oracle_differs:
            problems.append("the chain-end flags differ from the file's sequence")
        if record["limitations"] != c.expected_limitations(row["classes"], oracle_differs):
            problems.append("limitations are not the RP sentences of the conditions")
        raw = self.repaired_bytes(rid, record_handle)
        if c.sha256(raw) != record["result"]["coordinates_sha256"]:
            problems.append("the downloaded bytes are not the recorded coordinates")
        invariance = oracle.repair_problems(row, self.structure_bytes(rid, prepared), raw, self.tpl)
        problems += invariance["problems"]
        if invariance["newAtoms"] != counts.get("added_atoms"):
            problems.append("calc_flag c atoms != counts.added_atoms")
        unchanged = record.get("unchanged") or {}
        if unchanged.get("atom_count") != invariance["inputAtoms"] or not 0 <= unchanged.get("max_delta_A", -1) <= \
                c.COORDINATE_TOLERANCE_A:
            problems.append(f"record unchanged {unchanged} vs {invariance['inputAtoms']} input atoms")
        return {"ok": not problems, "problems": problems, "record": record_handle,
                "repaired": detail["prepared_structure"], "counts": counts, "classes": record["classes_applied"],
                "limitations": len(record["limitations"]), "bytesSha256": c.sha256(raw), "invariance": invariance,
                "replaced": record["replaced"], "published": len(published)}

    # ----- R5 table ---------------------------------------------------------------------------------------------
    def table(self, names: tuple[str, ...] = c.STRUCTURES, waters: tuple[str, ...] = c.WATERS) -> list[dict]:
        rows = []
        for name in names:
            for policy in waters:
                started = time.monotonic()
                try:
                    row = self._row(name, policy)
                except Exception as exc:  # noqa: BLE001 - one structure's crash is that row's fail, never the table's
                    row = {"structure": name, "waters": policy, "ok": False, "problems": [f"{type(exc).__name__}: {exc}"]}
                row["seconds"] = round(time.monotonic() - started, 1)
                self.rows[(name, policy)] = row
                self.record(f"table-{name}-{policy}", "pass" if row["ok"] else "fail", verdict=row.get("product"),
                            problems=row["problems"][:5])
                rows.append(row)
        return rows

    def _row(self, name: str, waters: str) -> dict:
        found = self.oracle(name, waters)
        expected = c.EXPECTED_TABLE[name][waters]
        band = c.band_for(name, found["protein_heavy_after"]) if found["verdict"] == c.IN else {"band": None,
                                                                                                    "source": None}
        row: dict[str, Any] = {"structure": name.upper(), "waters": waters, "documented": expected,
                               "oracle": oracle.summary(found), "m21Band": band, "problems": []}
        problems = row["problems"]
        if found["verdict"] != expected:
            problems.append(f"oracle {found['verdict']} != documented {expected}")
        rid = self.new_run(f"M29 acceptance R5 {name} {waters}")
        made = self.load_prepare(rid, self.path(name), waters)
        row.update(run=rid, prepared=made["prepared"], inputSha256=made["inputSha256"])
        pf = self.preflight(rid, made["prepared"])
        admission = pf.get("admission") or {}
        product = c.IN if pf.get("repairable") is True and admission.get("admitted") is True else (
            f"{c.OUT}({(pf.get('blockers') or [{}])[0].get('reason_code')})")
        row["product"] = product
        row["preflight"] = {"repairable": pf.get("repairable"), "admitted": admission.get("admitted"),
                            "admissionReason": admission.get("reason_code"),
                            "blockers": [item.get("reason_code") for item in pf.get("blockers") or []][:5],
                            "expectedAddedResidues": pf.get("expected_added_residues"),
                            "expectedAddedHeavyAtoms": pf.get("expected_added_heavy_atoms"),
                            "startsJob": pf.get("starts_job")}
        if product != found["verdict"]:
            problems.append(f"product {product} != oracle {found['verdict']}")
        if pf.get("starts_job") is not False:
            problems.append("the preflight read does not say starts_job false")
        if found["verdict"] == c.IN:
            problems += self._preflight_defects(pf, found)
            self._chain(row, rid, name, waters, found, band)
        else:
            self._refusal(row, rid, made["prepared"], found, pf)
        row["ok"] = not problems
        return row

    @staticmethod
    def _preflight_defects(pf: dict, found: dict) -> list[str]:
        problems = []
        defects = pf.get("defects") or {}
        want = {"expected_added_residues": found["expected_added_residues"],
                "expected_added_heavy_atoms": found["expected_added_heavy_atoms"]}
        for key, value in want.items():
            if pf.get(key) != value:
                problems.append(f"preflight {key} {pf.get(key)} != {value} (oracle)")
        lists = {"side_chain_residues": [c.short_ref(item["ref"]) for item in found["side_chain"]],
                 "terminal_oxt": [c.short_ref(item["ref"]) for item in found["terminal_oxt"]],
                 "nonstandard": [c.short_ref(item["ref"]) for item in found["nonstandard"]]}
        for key, value in lists.items():
            shown = [c.short_ref(item["residue"]) for item in defects.get(key) or []]
            if shown != value:
                problems.append(f"preflight defects.{key} differ from the oracle ({len(shown)} vs {len(value)})")
        if sorted(gap["length"] for gap in defects.get("gaps") or []) != sorted(found["gap_lengths"]):
            problems.append("preflight gap lengths differ from the oracle")
        parts = {item["chain_auth"]: item["parts"] for item in defects.get("chain_parts") or []}
        if parts != {name: n for name, n in found["parts_per_chain"].items() if n > 1}:
            problems.append("preflight chain parts differ from the oracle")
        differs = any(end["first_is_sequence_start"] is False or end["last_is_sequence_end"] is False
                      for end in found["chain_ends"])
        if pf.get("statements") != c.expected_limitations(found["classes"], differs):
            problems.append("preflight statements are not the RP sentences of the conditions")
        if pf.get("blockers"):
            problems.append("an in_scope structure has blockers")
        return problems

    def _refusal(self, row: dict, rid: str, prepared: str, found: dict, pf: dict) -> None:
        problems = row["problems"]
        first = (pf.get("blockers") or [{}])[0]
        oracle_first = found["first_blocker"]
        if oracle_first is not None:
            residue = first.get("residue")
            shown = c.short_ref(residue) if isinstance(residue, dict) else None
            want = oracle.short(oracle_first["residue"]) if oracle_first["residue"] else None
            if want is not None and shown != want:
                problems.append(f"first blocker at {shown}, the oracle says {want}")
            if want is None and oracle_first["chain_auth"] and first.get("chain_auth") not in (
                    None, oracle_first["chain_auth"]):
                problems.append("first blocker chain differs from the oracle")
        jobs, units = len(self.jobs(rid)), self.used_units(rid)
        status, body = self.submit(rid, c.REPAIR_PROTOCOL, {"structure": prepared, "repair_policy": c.REPAIR_POLICY},
                                   c.REPAIR_TIMEOUT_S)
        detail = (body or {}).get("detail") or {} if isinstance(body, dict) else {}
        row["submit"] = {"status": status, "error": (body or {}).get("error") if isinstance(body, dict) else None,
                         "detailError": detail.get("error"), "reason": detail.get("reason_code"),
                         "jobsAdded": len(self.jobs(rid)) - jobs, "unitsAdded": self.used_units(rid) - units}
        if (status, row["submit"]["error"], detail.get("error"), detail.get("reason_code")) != (
                422, "input_invalid", "repair_not_possible", found["code"]):
            problems.append(f"submission not refused with {found['code']}: {_fail_text(row['submit'])}")
        if row["submit"]["jobsAdded"] or row["submit"]["unitsAdded"]:
            problems.append("a refused submission made a job or used a unit")
        if (pf.get("admission") or {}).get("reason_code") != found["code"]:
            problems.append("preflight admission reason differs from the classification")

    def _chain(self, row: dict, rid: str, name: str, waters: str, found: dict, band: dict) -> None:
        problems = row["problems"]
        made = self.repair(rid, row["prepared"])
        job = made.get("job") or {}
        row["repairJob"] = {"status": job.get("status"), "approved": made.get("approved"),
                            "failure": job.get("failure")}
        if job.get("status") != "done" or not made.get("record"):
            problems.append(f"repair job did not finish: {_fail_text(made.get('submit') or job.get('failure'))}")
            return
        checked = self.check_repair(rid, name, waters, row["prepared"], made["record"])
        row.update(record=made["record"], repaired=made["repaired"],
                   repair={key: checked[key] for key in ("counts", "classes", "published", "bytesSha256")},
                   invariance={key: checked["invariance"][key] for key in (
                       "inputAtoms", "outputAtoms", "newAtoms", "newResidues", "maxObservedDeltaA")},
                   replaced=checked["replaced"])
        problems += checked["problems"]
        residue = oracle.mutable_residue(found)
        if residue is None:
            problems.append("no residue to put a mutation on")
            return
        status, made_set = self.command(rid, "generate_mutation_candidates", {
            "structure": made["repaired"], "sources": {"pocket": None, "ligand_shell": None, "residues": [
                {key: residue[key] for key in ("model_number", "chain_auth", "seq_auth", "icode", "resname")}]}})
        if status != 200 or not made_set.get("ok"):
            problems.append(f"M20 on the repaired structure: {status} {_fail_text(made_set)}")
            return
        row["set"] = made_set["handle"]["handle"]
        row["setResidue"] = c.short_ref(residue)
        args = {"candidate_set": row["set"], "candidate_index": 0, "seed": 0, "selection_policy": "protein_only",
                "hydrogen_policy": "rebuild_pH7"}
        status, job = self.submit(rid, c.MODEL_PROTOCOL, args, c.M21_TIMEOUT_S)
        reason = ((job or {}).get("detail") or {}).get("reason_code") if isinstance(job, dict) else None
        row["m21Admission"] = {"status": status, "jobStatus": (job or {}).get("status") if isinstance(job, dict)
                               else None, "reason": reason}
        if status != 200 or job.get("status") != "queued":
            problems.append(f"M21 admission did not open: {status} {reason}")
            return
        if band["band"] == "completes":
            done, _approved = self.start(rid, job["job_id"], wait_s=c.M21_TIMEOUT_S + 300)
            row["m21Job"] = {"status": done.get("status"), "failure": done.get("failure"),
                             "model": (done.get("artifacts") or {}).get("mutation_model"),
                             "seconds": _job_seconds(self.events(rid), job["job_id"])}
            if done.get("status") != "done" or not row["m21Job"]["model"]:
                problems.append(f"M21 job of a completes structure did not finish: {_fail_text(done.get('failure'))}")
        else:
            status, _cancelled = self.api.post(f"/runs/{rid}/jobs/{job['job_id']}/cancel")
            row["m21Job"] = {"status": "cancelled_queued" if status == 200 else f"cancel {status}",
                             "requiredToComplete": False}


def _job_seconds(events: list[dict], job_id: str) -> float | None:
    times = [event["ts"] for event in events if event.get("job_id") == job_id and "ts" in event]
    return round(max(times) - min(times), 1) if len(times) > 1 else None


# ---------------------------------------------------------------------------------------------------- R2, R5, R7, R8
def r5_case(rows: list[dict], names: tuple[str, ...] = c.STRUCTURES) -> dict:
    parts = []
    for row in rows:
        parts.append(c.check(f"{row['structure']}-{row['waters']}", row.get("ok") is True and not row["problems"],
                             "; ".join(row["problems"][:3]) or "row_failed"))
    expected = {(name.upper(), policy) for name in names for policy in c.WATERS}
    covered = {(row["structure"], row["waters"]) for row in rows}
    parts.append(c.check("table_complete", covered == expected, f"rows missing: {sorted(expected - covered)}"))
    return c.case_record("R5", parts, refs=["evidence/classification-table.json"])


def r2_case(lab: Lab) -> dict:
    parts = []
    for policy in c.WATERS:
        row = lab.rows.get(("8vf6", policy))
        if row is None:
            parts.append(c.part(f"8VF6-{policy}", "not_observed", "prerequisite_failed:R5"))
            continue
        published = (row.get("repair") or {}).get("published") == 1
        admitted = (row.get("m21Admission") or {}).get("status") == 200 and \
            (row.get("m21Admission") or {}).get("reason") != "openmm_preflight_failed"
        parts.append(c.check(f"8VF6-{policy}", published and admitted and not row["problems"],
                             f"published {published}, M21 admission {row.get('m21Admission')}",
                             published=published, m21Admission=row.get("m21Admission")))
    return c.case_record("R2", parts, refs=["evidence/classification-table.json"])


SYNTHETIC = {"chain_identity_duplicate": "synthetic-chain-identity-duplicate.cif",
             "unsupported_residue": "synthetic-unsupported-residue.cif",
             "unexpected_atoms": "synthetic-unexpected-atoms.cif",
             "backbone_atoms_missing": "synthetic-backbone-atoms-missing.cif",
             "gap_listing_missing": "synthetic-gap-listing-missing.cif"}


def r7_case(lab: Lab, repaired: tuple[str, str] | None) -> dict:
    """Spec 10.3 R7: nothing_to_repair (1UBQ), already_repaired, gap_too_long (1S9I) and the five LABELLED SYNTHETIC
    small structures; each refused at the preflight read and the submission with its code, no job and no unit."""
    parts = []
    for name, code in (("1ubq", "nothing_to_repair"), ("1s9i", "gap_too_long")):
        row = lab.rows.get((name, "strip_all"))
        if row is None:
            parts.append(c.part(f"{name.upper()}-{code}", "not_observed", "prerequisite_failed:R5"))
            continue
        submit = row.get("submit") or {}
        ok = (row.get("product") == f"{c.OUT}({code})" and submit.get("reason") == code
              and not submit.get("jobsAdded") and not submit.get("unitsAdded") and not row["problems"])
        parts.append(c.check(f"{name.upper()}-{code}", ok, _fail_text(submit), submit=submit))
    for code, filename in SYNTHETIC.items():
        path = lab.code / c.FIXTURES / "structure_repair" / filename
        found = lab.oracle(filename, "strip_all", path)
        rid = lab.new_run(f"M29 acceptance R7 {code}")
        made = lab.load_prepare(rid, path, "strip_all")
        pf = lab.preflight(rid, made["prepared"])
        jobs, units = len(lab.jobs(rid)), lab.used_units(rid)
        status, body = lab.submit(rid, c.REPAIR_PROTOCOL, {"structure": made["prepared"],
                                                           "repair_policy": c.REPAIR_POLICY}, c.REPAIR_TIMEOUT_S)
        detail = (body.get("detail") or {}) if isinstance(body, dict) else {}
        first = (pf.get("blockers") or [{}])[0].get("reason_code")
        ok = (found["code"] == code and first == code and (pf.get("admission") or {}).get("reason_code") == code
              and status == 422 and detail.get("reason_code") == code and len(lab.jobs(rid)) == jobs
              and lab.used_units(rid) == units)
        parts.append(c.check(f"SYNTHETIC-{code}", ok, f"oracle {found['code']}, preflight {first}, submit "
                             f"{status} {detail.get('reason_code')}", file=filename, synthetic=True, run=rid,
                             oracle=found["code"], preflight=first, submit=status))
    if repaired is None:
        parts.append(c.part("already_repaired", "not_observed", "prerequisite_failed:R1"))
    else:
        rid, structure = repaired
        jobs, units = len(lab.jobs(rid)), lab.used_units(rid)
        pf = lab.preflight(rid, structure)
        status, body = lab.submit(rid, c.REPAIR_PROTOCOL, {"structure": structure, "repair_policy": c.REPAIR_POLICY},
                                  c.REPAIR_TIMEOUT_S)
        detail = (body.get("detail") or {}) if isinstance(body, dict) else {}
        ok = ((pf.get("admission") or {}).get("reason_code") == "already_repaired" and status == 422
              and detail.get("reason_code") == "already_repaired" and len(lab.jobs(rid)) == jobs
              and lab.used_units(rid) == units)
        parts.append(c.check("already_repaired", ok, f"submit {status} {detail.get('reason_code')}", run=rid))
    return c.case_record("R7", parts, refs=["evidence/r7.json"])


def r8_case(lab: Lab, ui_row: dict | None) -> dict:
    """Spec 10.3 R8 on the real 1RNH (three MSE): the record's replaced table against the file's MSE residues, RP5,
    and the screen's replaced table (harness mode r8)."""
    parts = []
    for policy in c.WATERS:
        row = lab.rows.get(("1rnh", policy))
        if row is None or not row.get("record"):
            parts.append(c.part(f"1RNH-{policy}", "not_observed", "prerequisite_failed:R5"))
            continue
        found = lab.oracle("1rnh", policy)
        want = [c.short_ref(item["ref"]) for item in found["nonstandard"]]
        replaced = row.get("replaced") or []
        got = [c.short_ref(item["from"]) for item in replaced]
        maps_ok = all(item["to"]["resname"] == "MET" and {"from": "SE", "to": "SD"} in item["atom_map"]
                      and item["record_type"] == {"from": "HETATM", "to": "ATOM"}
                      and {k: v for k, v in item["from"].items() if k != "resname"} ==
                      {k: v for k, v in item["to"].items() if k != "resname"} for item in replaced)
        detail = lab.repair_detail(row["run"], row["record"])["result"]
        ok = got == want and len(want) == 3 and maps_ok and c.FIXED["RP5"] in detail["limitations"] and \
            "nonstandard_replaced" in detail["classes_applied"]
        parts.append(c.check(f"1RNH-{policy}", ok, f"replaced {got} vs file MSE {want}, maps {maps_ok}",
                             replaced=got, fileMse=want))
    if ui_row is None:
        parts.append(c.part("screen", "not_observed", "prerequisite_failed:R5"))
    else:
        shown = (ui_row.get("observed") or {}).get("r8") or {}
        ok = ui_row.get("status") == "pass" and shown.get("replacedRows") == 3 and shown.get("rp5Shown") is True
        parts.append(c.check("screen", ok, f"harness {ui_row.get('status')}, rows {shown.get('replacedRows')}",
                             **{k: shown.get(k) for k in ("replacedRows", "rp5Shown", "record")}))
    return c.case_record("R8", parts, refs=["evidence/classification-table.json", "steps/r8"])


# ---------------------------------------------------------------------------------------------------- R6 API part
CAMERA = {"mode": "perspective", "fov": 0.8, "position": [1.0, 2.0, 40.0], "target": [0.0, 0.0, 0.0],
          "up": [0.0, 1.0, 0.0], "radius": 10.0, "radiusMax": 20.0, "fog": 50.0, "clipFar": True, "minNear": 0.0,
          "minFar": 0.0}
ACK = {"schema": "chemical_preparation_ack@1", "supplied_graph_complete": True, "supplied_hydrogens_complete": True,
       "use_supplied_protonation_tautomer": True, "infer_receptor_orders_charges": True,
       "description": "M29 acceptance R6", "ph_annotation": None}


def refusal_targets(rid: str, s: str, other: str, ligand: dict) -> list[tuple[str, str, str, Any]]:
    """Spec 5.2 consumers (the T6 test's list, ``backend/tests/test_structure_repair_refusals.py``): (name, method,
    path, body | query). ``annotate_reference_sites`` is blocked upstream (its numbering map of a repaired structure
    cannot be made) and is the inventory test's, as in T6."""
    import uuid
    atom = {"structure_handle": s, "residue": ligand, "atom_name": "C1", "altloc": ""}
    ids = {"client_instance_id": str(uuid.uuid4()), "viewer_session_id": str(uuid.uuid4()), "scene_generation": 1,
           "action_revision": 0, "request_id": str(uuid.uuid4())}
    view = {"structure_handle": s, "selection": None, "representation": "cartoon", "camera": CAMERA, "theme": "dark"}
    attach = {"schema": "chemical_prepare_request@1", "mode": "attach_existing", "complex_handle": s,
              "complex_model_number": 1}
    strict = {**attach, "selected_ligand": None, "connectivity": {"kind": "pdb_conect", "sidecar_handle": None},
              "ligand_sdf_handle": "obj://none", "sdf_record_index": 0, "hydrogen_policy": "map_existing",
              "mapping": [], "terminal_extensions": [], "acknowledgement": dict(ACK)}
    chains = [{"chain_auth": "A", "uniprot_accession": None}]
    commands = [
        ("compute_interactions", {"structure": s, "ligand": ligand, "cutoff_A": 4.0}),
        ("compute_interface_sasa", {"structure": s, "ligand": ligand}),
        ("measure_distance", {"structure": s, "first": atom, "second": atom}),
        ("align_structures", {"reference": s, "moving": other, "pairs": []}),
        ("align_structures", {"reference": other, "moving": s, "pairs": []}),
        ("compile_state", {"inputs": [other, s]}),
        ("map_residue_numbering", {"structure": s, "pdb_id": "1HSG", "chains": chains}),
        ("link_reaction_knowledge", {"structure": s, "pdb_id": "1HSG", "chains": chains}),
    ]
    zeros = "0" * 64
    out = [(f"command:{tool}", "POST", "/commands", {"tool": tool, "args": args}) for tool, args in commands]
    out += [
        ("M7 preflight read", "GET", "/jobs/preflight", {"structure": s}),
        ("M7 minimization job", "POST", "/jobs", {"protocol_id": "openmm_protein_minimize", "args": {
            "structure": s, "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}}),
        ("PyRosetta relax job", "POST", "/jobs", {"protocol_id": "relax", "args": {"structure": s}}),
        ("PyRosetta interface_analyzer job", "POST", "/jobs",
         {"protocol_id": "interface_analyzer", "args": {"structure": s, "interface": "A_B"}}),
        ("M12 pocket preflight read", "GET", "/pockets/preflight", {"structure": s}),
        ("M12 fpocket job", "POST", "/jobs", {"protocol_id": "fpocket_detect_v1", "args": {"structure": s,
                                                                                         "chains": None}}),
        ("M11 preview", "POST", "/chemical/preview", attach),
        ("M11 prolif_prepare_v1 job", "POST", "/jobs", {"protocol_id": "prolif_prepare_v1", "args": strict}),
        ("viewer session", "POST", "/viewer/sessions", {"client_instance_id": ids["client_instance_id"],
                                                        "scene_generation": 1, "structure_handle": s}),
        ("saved view", "POST", "/viewer/scenes", {"schema": "viewer_scene@1", "name": "view", **view, **ids}),
        ("figure", "POST", "/viewer/figures", {"schema": "viewer_figure@1",
                                               "scene_handle": f"obj://{rid}/viewer_scene/{zeros}", **view,
                                               "png_base64": "iVBORw0KGgo=", **ids}),
        ("inspection report", "POST", "/reports", {"interaction_handle": f"obj://{rid}/interaction_set/{zeros}",
                                                   "prepared_handle": s}),
        ("inspect_complex pipeline", "POST", "/inspect_complex", {"input_handle": s, "ligand": ligand}),
        ("M13 analysis plan", "POST", "/analysis/plans", {"request_id": str(uuid.uuid4()), "goal": "inspect_ligand",
                                                           "inputs": {"source": s, "ligand": ligand, "cutoff_A": 4.0,
                                                                      "types": ["contact"]}}),
    ]
    return out


def r6_api(lab: Lab) -> dict:
    """The refusal of every spec 5.2 target for the repaired 1HSG (strip_all row of R5): one code, the fixed message,
    nothing stored (no object, job, unit, plan, view or report)."""
    row = lab.rows.get(("1hsg", "strip_all"))
    if row is None or not row.get("repaired"):
        return {"ok": None, "reason": "prerequisite_failed:R5", "targets": []}
    rid, repaired, original = row["run"], row["repaired"], row["prepared"]
    ligands = lab.read(f"/runs/{rid}/structures/residues?handle={c.enc(original)}")["ligands"]
    ligand = {key: ligands[0][key] for key in ("model_number", "chain_auth", "seq_auth", "icode", "resname")
              if key in ligands[0]}
    ligand.setdefault("model_number", 1)
    before = _state(lab, rid)
    results = []
    for name, method, path, body in refusal_targets(rid, repaired, original, ligand):
        if method == "GET":
            query = "&".join(f"{key}={c.enc(value)}" for key, value in body.items())
            status, answer = lab.api.get(f"/runs/{rid}{path}?{query}")
        else:
            status, answer = lab.api.post(f"/runs/{rid}{path}", body)
        refused = (status == 422 and isinstance(answer, dict) and answer.get("error") == "input_invalid"
                   and answer.get("message") == c.REFUSED_MESSAGE
                   and answer.get("detail") == {"reason_code": c.REFUSED})
        results.append({"target": name, "status": status, "refused": refused})
    after = _state(lab, rid)
    stored = {key: after[key] == before[key] for key in ("objects", "jobs", "units", "plans", "scenes", "reports")}
    ok = all(item["refused"] for item in results) and all(stored.values())
    return {"ok": ok, "run": rid, "targets": results, "nothingStored": stored, "count": len(results)}


def _state(lab: Lab, rid: str) -> dict:
    events = lab.events(rid)
    return {"objects": sum(1 for event in events if event.get("type") == "object_created"),
            "jobs": len(lab.jobs(rid)), "units": lab.used_units(rid),
            "plans": json.dumps(lab.read(f"/runs/{rid}/analysis/plans"), sort_keys=True),
            "scenes": json.dumps(lab.read(f"/runs/{rid}/viewer/scenes"), sort_keys=True),
            "reports": len(lab.read(f"/runs/{rid}/reports"))}


def r6_case(api_part: dict, pytest_rows: list[dict], ui_row: dict | None) -> dict:
    parts = []
    if api_part.get("ok") is None:
        parts.append(c.part("api_targets", "not_observed", api_part.get("reason") or "prerequisite_failed:R5"))
    else:
        bad = [item["target"] for item in api_part["targets"] if not item["refused"]]
        parts.append(c.check("api_targets", api_part["ok"], f"not refused: {bad}; stored {api_part['nothingStored']}",
                             targets=api_part["count"], nothingStored=api_part["nothingStored"]))
    for item in pytest_rows:
        parts.append(c.check(f"pytest:{item['name']}", item["ok"], item["summary"], summary=item["summary"]))
    viewer = ((ui_row or {}).get("observed") or {}).get("viewer")
    if ui_row is None or viewer is None:
        parts.append(c.part("viewer_path", "not_observed", "prerequisite_failed:R3"))
    else:
        # the selects are read (they offer the original prepared structure) and none offers the repaired one
        ok = viewer.get("optionsWithRepaired") == 0 and viewer.get("viewerSource") != viewer.get("repaired") and \
            viewer.get("selects", 0) > 0 and viewer.get("optionsWithPrepared", 0) >= 1
        parts.append(c.check("viewer_path", ok, _fail_text(viewer), **viewer))
    return c.case_record("R6", parts, refs=["evidence/r6.json"])


# ---------------------------------------------------------------------------------------------------- R4b
def r4b_case(lab: Lab, leftovers: Callable[[], list[str]]) -> tuple[dict, dict]:
    """Spec 10.3 R4b: one M21 job on the repaired 8VF6 (strip_all row of R5; seed 1 so its call key differs from
    the admission job R5 cancelled), timeout_s 240, approved and started. Pass when the documented limit is what
    happens: the job fails with the timeout (resource_exceeded, "job timeout"), no output, no mutation_model object,
    the reserved unit is not refunded and no worker process is left. The docking part is not_observed
    ``no_model_time_limit`` (no model to dock)."""
    row = lab.rows.get(("8vf6", "strip_all"))
    if row is None or not row.get("set"):
        return c.case_record("R4b", [c.part("model_job", "not_observed", "prerequisite_failed:R5")]), {}
    rid = row["run"]
    events = lab.events(rid)
    models_before = c.kind_count(events, "mutation_model")
    args = {"candidate_set": row["set"], "candidate_index": 0, "seed": 1, "selection_policy": "protein_only",
            "hydrogen_policy": "rebuild_pH7"}
    status, job = lab.submit(rid, c.MODEL_PROTOCOL, args, c.M21_TIMEOUT_S)
    if status != 200 or job.get("status") != "queued":
        return c.case_record("R4b", [c.part("model_job", "fail", f"admission {status} {_fail_text(job)}")]), {}
    units_before = lab.used_units(rid)
    started = time.monotonic()
    done, approved = lab.start(rid, job["job_id"], wait_s=c.M21_TIMEOUT_S + 600)
    seconds = round(time.monotonic() - started, 1)
    units_after = lab.used_units(rid)
    models_after = c.kind_count(lab.events(rid), "mutation_model")
    left = [item for item in leftovers() if "openmm_mutation_worker" in item or "guardian" in item]
    facts = {"run": rid, "jobId": job["job_id"], "status": done.get("status"), "failure": done.get("failure"),
             "outputHandles": done.get("output_handles"), "artifacts": done.get("artifacts"),
             "unitsBefore": units_before, "unitsAfter": units_after, "modelsBefore": models_before,
             "modelsAfter": models_after, "seconds": seconds, "timeoutS": c.M21_TIMEOUT_S, "approvedNow": approved,
             "workersLeft": left, "repairedHeavyAtoms": (row.get("repair") or {}).get("counts", {}).get(
                 "protein_heavy_atoms")}
    failure = done.get("failure") or {}
    parts = [
        c.check("job_state", done.get("status") == "failed" and failure.get("error") == "resource_exceeded"
                and failure.get("message") == "job timeout", f"status {done.get('status')} {_fail_text(failure)}"),
        c.check("no_result", not done.get("output_handles") and not (done.get("artifacts") or {}).get(
            "mutation_model") and models_after == models_before, "a result or model object exists"),
        c.check("unit_not_refunded", units_after == units_before + 1, f"units {units_before} -> {units_after}"),
        c.check("worker_cleaned", not left, f"left: {left}"),
        c.check("timed_at_limit", seconds >= c.M21_TIMEOUT_S - 5, f"ended after {seconds} s"),
        c.part("docking", "not_observed", "no_model_time_limit"),
    ]
    return c.case_record("R4b", parts, refs=["evidence/r4b.json"], detail=facts), facts


# ---------------------------------------------------------------------------------------------------- UI cases
def _row_parts(row: dict | None, need: tuple[str, ...]) -> list[dict]:
    if row is None:
        return [c.part("harness", "fail", "harness_row_missing")]
    parts = [c.check("harness", row.get("status") == "pass" and row.get("externalRequestCount") == 0,
                     f"harness {row.get('status')}, external {row.get('externalRequestCount')}, "
                     f"error {str(row.get('error'))[:160]}")]
    for name in need:
        status = (row.get("parts") or {}).get(name)
        parts.append(c.check(f"ui:{name}", status == "pass", f"part {name} {status}"))
    return parts


def r1_case(lab: Lab, row: dict | None) -> tuple[dict, dict]:
    parts = _row_parts(row, ("r1-load", "r1-preflight", "r1-job", "r1-result", "r1-download", "r1-report"))
    seen = ((row or {}).get("observed") or {}).get("r1") or {}
    facts: dict[str, Any] = {}
    if seen.get("record"):
        rid = seen["run"]
        found = lab.oracle("8vf6", "strip_all")
        pf = seen.get("preflight") or {}
        parts.append(c.check("preflight_expected", pf.get("repairable") == "true" and pf.get("admitted") == "true"
                             and pf.get("sideChainRows") == len(found["side_chain"]) == 23
                             and pf.get("gapRows") == 2 and sorted(pf.get("gapLengths") or []) == [11, 13]
                             and pf.get("oxtRows") == len(found["terminal_oxt"]) == 2
                             and pf.get("chainPartRows") == sum(1 for n in found["parts_per_chain"].values() if n > 1)
                             and pf.get("blockerRows") == 0,
                             f"preflight shown {_fail_text(pf)}"))
        checked = lab.check_repair(rid, "8vf6", "strip_all", seen["prepared"], seen["record"])
        facts = {"record": seen["record"], "counts": checked["counts"], "invariance": checked["invariance"],
                 "problems": checked["problems"]}
        parts.append(c.check("record_vs_oracle", checked["ok"], "; ".join(checked["problems"][:3])))
        download = seen.get("download") or {}
        parts.append(c.check("download_bytes", download.get("sha256") == checked["bytesSha256"],
                             "downloaded bytes differ from the stored repaired structure"))
        report = seen.get("report") or {}
        saved = lab.report(rid, report["handle"]) if report.get("handle") else {}
        manifest = saved.get("manifest") or {}
        gap_atoms = sum(len(lab.tpl.expected(residue["resname"], terminal=False))
                        for gap in found["gaps"] for residue in gap["residues"])
        want = {("added_residue_count", "counts.added_residues"): found["expected_added_residues"],
                ("added_atom_count", "counts.added_atoms"): found["expected_added_heavy_atoms"],
                ("side_chain_residue_count", "counts.side_chain_residues"): len(found["side_chain"]),
                ("terminal_oxt_count", "counts.terminal_oxt"): len(found["terminal_oxt"]),
                ("gap_count", "counts.gaps"): len(found["gap_lengths"]),
                ("replaced_count", "counts.replaced"): len(found["nonstandard"]),
                ("unchanged_atom_count", "unchanged.atom_count"): checked["invariance"]["inputAtoms"]}
        origin = {"side_chain": found["side_chain_atoms"], "oxt": len(found["terminal_oxt"]), "gap_residue": gap_atoms}
        got = {key: claim_value(manifest, *key) for key in want}
        by_origin = {claim["row_selector"]["origin"]: claim["exact_value"] for claim in manifest.get("claims") or []
                     if claim.get("statement_id") == "added_atom_count" and claim.get("field_path") ==
                     "added_atoms[*].origin"}
        ok = (manifest.get("render_version") == "structure_repair_markdown@1" and manifest.get("result_handle") ==
              seen["record"] and got == want and by_origin == {key: n for key, n in origin.items() if n})
        parts.append(c.check("repair_report", ok, f"report {manifest.get('render_version')}; claims "
                             f"{[(k[0], v) for k, v in got.items() if v != want[k]]}; by origin {by_origin} vs {origin}"))
        facts["reportClaims"] = {"counts": {k[1]: v for k, v in got.items()}, "byOrigin": by_origin}
        facts["report"] = report.get("handle")
    return c.case_record("R1", parts, refs=["steps/r1", "evidence/r1.json"], detail=facts), facts


def r3_setup(lab: Lab, rid: str, prepared: str) -> dict:
    """The original structure's reference results the R3 hand-off uses, made through the product (commands and one
    fpocket job): numbering map (8VF6 A and B, Q9BYT3), annotation, pocket set; and the comparison set on the original
    structure (ligand shell 5.0 A around A1AAY A600, the map and annotation, the side-chain residue)."""
    chains = [{"chain_auth": name, "uniprot_accession": "Q9BYT3"} for name in ("A", "B")]
    status, numbering = lab.command(rid, "map_residue_numbering", {"structure": prepared, "pdb_id": "8VF6",
                                                                    "chains": chains})
    if status != 200 or not numbering.get("ok"):
        raise RuntimeError(f"numbering map: {status} {_fail_text(numbering)}")
    nm = numbering["handle"]["handle"]
    status, annotated = lab.command(rid, "annotate_reference_sites", {"numbering_map": nm, "contacts": None})
    if status != 200 or not annotated.get("ok"):
        raise RuntimeError(f"annotation: {status} {_fail_text(annotated)}")
    ann = annotated["handle"]["handle"]
    status, job = lab.submit(rid, "fpocket_detect_v1", {"structure": prepared, "chains": None}, POCKET_TIMEOUT_S)
    pocket, pocket_job = None, {"submitStatus": status, "error": None if status == 200 else _fail_text(job)}
    if status == 200:
        done, _ = lab.start(rid, job["job_id"], wait_s=600)
        pocket_job.update(status=done.get("status"), failure=done.get("failure"))
        pocket = (done.get("output_handles") or [None])[0] if done.get("status") == "done" else None
    found = lab.oracle("8vf6", "strip_all")
    side = next(item["ref"] for item in found["side_chain"] if item["ref"]["chain_auth"] == "A")
    gap = found["gaps"][0]["residues"][len(found["gaps"][0]["residues"]) // 2]
    fields = ("model_number", "chain_auth", "seq_auth", "icode", "resname")
    pocket_source = None if pocket is None else {"pocket_set": pocket, "ranks": [1]}
    status, original = lab.command(rid, "generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": pocket_source, "ligand_shell": {"radius_A": 5.0},
                                           "residues": [{key: side[key] for key in fields}]},
        "ligand": c.LIGAND_8VF6, "numbering_map": nm, "annotation": ann})
    if status != 200 or not original.get("ok"):
        raise RuntimeError(f"original-structure set: {status} {_fail_text(original)}")
    return {"numberingMap": nm, "annotation": ann, "pocketSet": pocket, "pocketRanks": [1], "pocketJob": pocket_job,
            "originalSet": original["handle"]["handle"],
            "sideChainResidue": {key: side[key] for key in fields}, "gapResidue": {key: gap[key] for key in fields},
            "ligand": c.LIGAND_8VF6, "radiusA": 5.0}


def _positions(lab: Lab, rid: str, handle: str, query: str = "") -> list[dict]:
    rows: list[dict] = []
    total = None
    while total is None or len(rows) < total:
        status, chunk = lab.api.get(f"/runs/{rid}/mutation_candidate_sets/{c.enc(handle)}/positions?{query}"
                                    f"{'&' if query else ''}offset={len(rows)}&limit=100")
        if status != 200:
            raise RuntimeError(f"positions {status}")
        total = chunk["total"]
        rows += chunk["rows"]
        if not chunk["rows"]:
            break
    return rows


def klifs_seven_part(repaired_set: dict, original_set: dict) -> tuple[dict, dict]:
    """Spec 5.3 / R3: the original structure's ``klifs_key_site`` exclusions are exactly the seven documented 8VF6
    sites, and the set on the repaired structure (same pocket, shell and maps of the original) excludes the same."""
    def klifs(item: dict) -> list[str]:
        return sorted(c.short_ref(p["residue"]) for p in item["positions"]
                      if "klifs_key_site" in p["exclusion_reasons"])
    facts = {"repaired": klifs(repaired_set), "original": klifs(original_set), "documented": list(c.KLIFS_SEVEN)}
    ok = facts["original"] == sorted(c.KLIFS_SEVEN) and facts["repaired"] == facts["original"]
    return c.check("klifs_seven", ok, _fail_text(facts)), facts


def r3_case(lab: Lab, row: dict | None, setup: dict | None) -> tuple[dict, dict]:
    parts = _row_parts(row, ("r3-m20", "r3-detail", "r3-report"))
    seen = ((row or {}).get("observed") or {}).get("r3") or {}
    facts: dict[str, Any] = {}
    if setup is None:
        parts.append(c.part("setup", "fail", "the original structure's reference results were not made"))
    if seen.get("set") and setup:
        rid = seen["run"]
        events = lab.events(rid)
        content = json.loads(c.stored_object(events, seen["set"]))
        original = json.loads(c.stored_object(events, setup["originalSet"]))
        part, facts["klifs"] = klifs_seven_part(content, original)
        parts.append(part)
        parts.append(c.check("pocket_handoff", setup.get("pocketSet") is not None, "no pocket set of the original"))
        parts.append(c.check("stored_set_bytes", c.handle_matches(events, seen["set"]),
                             "the stored set no longer hashes to its handle"))
        positions = _positions(lab, rid, seen["set"])
        stored_positions = content["positions"]
        record_rows = lab.repair_detail(rid, seen["record"])
        repaired_raw = lab.repaired_bytes(rid, seen["record"])
        want_basis = oracle.modeled_basis_expected(repaired_raw, stored_positions, content["parameters"])
        got_basis = [item.get("modeled_basis") for item in positions]
        facts["modeledBasis"] = {"true": sum(1 for v in got_basis if v), "positions": len(got_basis),
                                 "expectedTrue": sum(1 for v in want_basis if v)}
        parts.append(c.check("modeled_basis", got_basis == want_basis, _fail_text(facts["modeledBasis"])))
        gap_key = c.short_ref(setup["gapResidue"])
        gap_rows = [(read, stored) for read, stored in zip(positions, stored_positions, strict=True)
                    if c.short_ref(stored["residue"]) == gap_key]
        gap_ok = len(gap_rows) == 1 and set(gap_rows[0][0].get("reference_not_checked") or []) >= {
            "numbering", "klifs_sites"} and gap_rows[0][1]["protection"]["klifs_sites"] == [] and \
            gap_rows[0][1]["numbering"]["status"] == "not_in_map"
        facts["gapResidue"] = {"residue": gap_key, "readNotChecked": gap_rows[0][0].get("reference_not_checked")
                               if gap_rows else None}
        parts.append(c.check("modeled_residue_not_checked", gap_ok, _fail_text(facts["gapResidue"])))
        shown = seen.get("gapRow") or {}
        parts.append(c.check("modeled_residue_screen", shown.get("numbering") == "검사 안 함(모델링 잔기)"
                             and shown.get("klifs") == "검사 안 함(모델링 잔기)"
                             and shown.get("modeledBasis") == "모델링 원자·잔기 포함", _fail_text(shown)))
        statements = {item.get("id"): item.get("text") for item in seen.get("statements") or []}
        so_ok = seen.get("so1") == c.FIXED["SO1"] and statements.get("SO2") == c.FIXED["SO2"] and \
            statements.get("SO3") == c.FIXED["SO3"] and seen.get("originRecord") == seen.get("record")
        parts.append(c.check("so1_so3_shown", so_ok, f"SO1 {seen.get('so1') == c.FIXED['SO1']}, {list(statements)}"))
        references = content["parameters"]
        handed = {key: references.get(key) for key in ("numbering_map", "annotation")}
        pocket = (references.get("sources") or {}).get("pocket") or {}
        parts.append(c.check("original_references", handed == {"numbering_map": setup["numberingMap"],
                                                                "annotation": setup["annotation"]}
                             and (setup.get("pocketSet") is None or pocket.get("pocket_set") == setup["pocketSet"]),
                             f"set references {handed}, pocket {pocket}"))
        found = lab.oracle("8vf6", "strip_all")
        ok, text = _origin_report(lab, rid, seen.get("report"), "mutation_candidates_markdown@3", seen["record"], found)
        markdown = (lab.report(rid, seen["report"]).get("markdown") or "") if seen.get("report") else ""
        parts.append(c.check("m20_report_v3", ok and c.FIXED["SO3"] in markdown, text))
        facts.update(set=seen["set"], report=seen.get("report"), positions=len(positions),
                     recordCounts=record_rows["result"]["counts"])
    return c.case_record("R3", parts, refs=["steps/r3", "evidence/r3.json"], detail=facts), facts


def _origin_report(lab: Lab, rid: str, handle: str | None, version: str, record: str, found: dict) -> tuple[bool, str]:
    if not handle:
        return False, "no report"
    report = lab.report(rid, handle)
    manifest, markdown = report.get("manifest") or {}, report.get("markdown") or ""
    claims = (claim_value(manifest, "repair_added_residue_count", "counts.added_residues"),
              claim_value(manifest, "repair_added_atom_count", "counts.added_atoms"))
    origin = manifest.get("structure_origin") or {}
    ok = (manifest.get("render_version") == version and origin.get("repair_record") == record
          and "## 구조 출처" in markdown and "## Limitations" in markdown
          and markdown.index("## 구조 출처") < markdown.index("## Limitations") and c.FIXED["SO1"] in markdown
          and claims == (found["expected_added_residues"], found["expected_added_heavy_atoms"]))
    return ok, f"{manifest.get('render_version')} origin {origin.get('repair_record') == record} claims {claims}"


def is_receptor_limit_refusal(item: Any) -> bool:
    """One refused docking submission as the harness recorded it (``{status, error, reason, message}``) is exactly the
    M18 receptor atom cap refusal (``m29_common.RECEPTOR_ATOM_LIMIT_*``)."""
    return isinstance(item, dict) and item.get("status") == 422 and item.get("error") == "input_invalid" and \
        item.get("reason") == c.RECEPTOR_ATOM_LIMIT_REASON and item.get("message") == c.RECEPTOR_ATOM_LIMIT_MESSAGE


def receptor_limit_part(docking: dict, harness_part: str | None, lower_bound: int) -> dict:
    """Spec 10.3 R4a: the docking part may stay not_observed ``receptor_atom_limit`` only when the harness saw the
    product refuse the docking submissions, every refusal is exactly the M18 receptor atom cap refusal, and the oracle's
    lower bound of the model's receptor atoms (input file + installed template) is above the cap, so the refusal is what
    the input implies. Any other refusal, or the cap refusal on a receptor the bound keeps under the cap (1HSG: about
    3,100), is a fail."""
    refused = docking.get("refused") or []
    detail = {"refused": refused, "receptorAtomsLowerBound": lower_bound, "cap": c.M18_MAX_RECEPTOR_ATOMS}
    if docking.get("notObserved") != "receptor_atom_limit" or harness_part != "pass":
        return c.part("docking", "fail", f"docking refused (harness {harness_part}): {_fail_text(refused)}", **detail)
    if not refused or not all(is_receptor_limit_refusal(item) for item in refused):
        return c.part("docking", "fail", f"a refusal is not the receptor atom cap: {_fail_text(refused)}", **detail)
    if lower_bound <= c.M18_MAX_RECEPTOR_ATOMS:
        return c.part("docking", "fail", f"the receptor atom cap refusal is not implied by the input (receptor atoms "
                      f"lower bound {lower_bound} <= {c.M18_MAX_RECEPTOR_ATOMS})", **detail)
    return c.part("docking", "not_observed", "receptor_atom_limit", **detail)


def r4a_case(lab: Lab, row: dict | None) -> tuple[dict, dict]:
    parts = _row_parts(row, ("r4a-repair", "r4a-m20", "r4a-m21", "r4a-model-report"))
    seen = ((row or {}).get("observed") or {}).get("r4a") or {}
    facts: dict[str, Any] = {}
    if seen.get("record"):
        rid = seen["run"]
        found = lab.oracle("1hsg", "strip_all")
        checked = lab.check_repair(rid, "1hsg", "strip_all", seen["prepared"], seen["record"])
        parts.append(c.check("record_vs_oracle", checked["ok"], "; ".join(checked["problems"][:3])))
        job = seen.get("modelJob") or {}
        parts.append(c.check("m21_completed_240", job.get("status") == "done" and job.get("timeoutS") == 240
                             and bool(seen.get("model")), _fail_text(job)))
        parts.append(c.check("model_origin_shown", seen.get("modelSo1") == c.FIXED["SO1"]
                             and seen.get("modelOriginRecord") == seen["record"], "SO1 / record not shown on the model"))
        ok, text = _origin_report(lab, rid, seen.get("modelReport"), "mutation_model_markdown@2", seen["record"], found)
        parts.append(c.check("m21_report_v2", ok, text))
        docking = seen.get("docking") or {}
        if docking.get("notObserved") is not None or docking.get("refused"):
            parts.append(receptor_limit_part(docking, (row or {}).get("parts", {}).get("r4a-docking"),
                                             oracle.receptor_atoms_lower_bound(found, lab.tpl)))
        else:
            ok, text = _origin_report(lab, rid, docking.get("report"), "ligand_docking_markdown@2", seen["record"],
                                      found)
            done = docking.get("jobs") and all(item == "done" for item in docking["jobs"].values())
            parts.append(c.check("docking", (row or {}).get("parts", {}).get("r4a-docking") == "pass" and bool(done)
                                 and docking.get("so1") == c.FIXED["SO1"] and ok, f"jobs {docking.get('jobs')}; {text}",
                                 syntheticLigand="synthetic-phenol-ligand.sdf (SYNTHETIC-FIXTURE, mechanical path)"))
        facts = {"record": seen["record"], "model": seen.get("model"), "modelJob": job,
                 "dockingJobs": docking.get("jobs"), "dockingRefused": docking.get("refused"),
                 "counts": checked["counts"]}
    return c.case_record("R4a", parts, refs=["steps/r4a", "evidence/r4a.json"], detail=facts), facts


def r10_case(lab: Lab, row: dict | None, pytest_rows: list[dict], blob_check: dict, dispatch_total: int,
             fixture_calls: int) -> dict:
    parts = _row_parts(row, ("r10-jev", "r10-loop", "r10-m23"))
    seen = ((row or {}).get("observed") or {}).get("r10") or {}
    loop = seen.get("loop") or {}
    jw = c.FIXED["JW1"]
    for name, shown in (("jw1_preview", seen.get("previewWarning")), ("jw1_approval", seen.get("approvalWarning")),
                        ("jw1_loop_preview", loop.get("previewWarning")),
                        ("jw1_loop_approval", loop.get("approvalWarning"))):
        parts.append(c.check(name, (shown or {}).get("text") == jw and (shown or {}).get("id") == "JW1",
                             f"warning shown {shown}"))
    body_clean = seen.get("bodyMentions") == [] and loop.get("bodyMentions") == []
    parts.append(c.check("body_unchanged_wording", body_clean, f"body mentions {seen.get('bodyMentions')}"))
    # The page's own POSTs (every renderer request the harness saw): the JEV preview was built (the list does hold the
    # JEV writes) and no send route was ever requested.
    posts = (row or {}).get("requestedPostPaths")
    observed = isinstance(posts, list) and any(path.endswith("/jev/preview") for path in posts)
    send_posts = sorted(path for path in posts or [] if path.endswith(c.JEV_SEND_ROUTE))
    parts.append(c.check("no_send", dispatch_total == 0 and fixture_calls == 0 and observed and not send_posts
                         and seen.get("sends") == 0, f"dispatch {dispatch_total}, provider calls {fixture_calls}, "
                         f"send requests {send_posts}, preview request seen {observed}, sends {seen.get('sends')}"))
    parts.append(c.check("m23_screen", seen.get("m23Repaired") is True, f"M23 option {seen.get('m23Option')}"))
    for item in pytest_rows:
        parts.append(c.check(f"pytest:{item['name']}", item["ok"], item["summary"]))
    parts.append(c.check("m23_report_files", blob_check.get("ok") is True, _fail_text(blob_check)))
    return c.case_record("R10", parts, refs=["steps/r3", "evidence/r10.json"])


# ---------------------------------------------------------------------------------------------------- R9 reopen
def reopen_reads(api: c.Api, rid: str, record: str, reports: list[str]) -> dict:
    """The reads R9 compares before and after the events-only reopen (JSON values and byte digests)."""
    out: dict[str, Any] = {}
    out["list"] = api.get(f"/runs/{rid}/structure_repairs")
    out["detail"] = api.get(f"/runs/{rid}/structure_repairs/{c.enc(record)}")
    out["atoms"] = api.get(f"/runs/{rid}/structure_repairs/{c.enc(record)}/atoms?page=1&page_size=200")
    status, raw = api.get(f"/runs/{rid}/structure_repairs/{c.enc(record)}/structure", raw=True)
    out["structure"] = [status, c.sha256(raw) if status == 200 else None]
    for handle in reports:
        out[f"report:{handle}"] = api.get(f"/runs/{rid}/reports/selected?handle={c.enc(handle)}")
    return out


def _status(read: Any) -> Any:
    """The status of one ``reopen_reads`` value (``(status, body)`` or ``[status, sha256]``)."""
    return read[0] if isinstance(read, (list, tuple)) and read else None


def stored_reports(events: list[dict]) -> list[dict]:
    """Every saved method report of a log with its stored Markdown and manifest bytes (decoded from the events)."""
    out = []
    for event in events:
        if event.get("type") != "method_report_created":
            continue
        manifest = json.loads(c.stored_object(events, event["report_handle"]))
        out.append({"handle": event["report_handle"], "render": manifest.get("render_version"),
                    "markdown": c.stored_object(events, event["markdown_handle"]).decode(), "manifest": manifest})
    return out


def r9_case(before: dict | None, after: dict | None, saved: list[dict], pytest_rows: list[dict],
            missing_fixture: bool) -> dict:
    parts = []
    if before is None or after is None:
        parts.append(c.part("repair_events_only", "not_observed", "prerequisite_failed:R1"))
    else:
        diff = sorted(key for key in before if before[key] != after.get(key))
        # every read compared (list, detail, atoms, structure download, reports) answered 200 on both sides
        not_ok = sorted(f"{side}:{key}" for side, reads in (("before", before), ("after", after)) for key in before
                        if _status(reads.get(key)) != 200)
        parts.append(c.check("repair_events_only", not diff and not not_ok, f"reads that differ after the events-only "
                             f"reopen: {diff}; reads not 200: {not_ok}", reads=sorted(before)))
    if missing_fixture:
        parts.append(c.part("saved_reports", "not_observed", "saved_report_fixture_missing"))
    for item in saved:
        parts.append(c.check(f"saved:{item['render']}:{item['handle'][-12:]}", item["ok"], item["why"],
                             render=item["render"]))
    need = {"mutation_candidates_markdown@1", "mutation_candidates_markdown@2", "mutation_model_markdown@1"}
    seen = {item["render"] for item in saved if item["ok"]}
    if not missing_fixture:
        parts.append(c.check("saved_versions_covered", need <= seen, f"versions reopened {sorted(seen)}"))
    for item in pytest_rows:
        parts.append(c.check(f"pytest:{item['name']}", item["ok"], item["summary"]))
    return c.case_record("R9", parts, refs=["evidence/r9.json"])


# ---------------------------------------------------------------------------------------------------- R11
def r11_case(texts: dict[str, str], reports: dict[str, str], fixed_export: dict | None) -> tuple[dict, dict]:
    """Spec 10.3 R11 over the new screen texts (harness) and the new report text (the whole structure repair report,
    the "## 구조 출처" section of the downstream reports): no forbidden word outside fixed sentence lines, no key,
    placeholder or absolute path; the product's exported fixed sentences equal the spec text."""
    scans: dict[str, Any] = {}
    parts = []
    for name, text in texts.items():
        hits, leaks = c.forbidden_hits(text), c.leak_kinds(text)
        scans[f"screen:{name}"] = {"hits": hits, "leaks": leaks, "chars": len(text)}
    for name, text in reports.items():
        hits, leaks = c.forbidden_hits(text), c.leak_kinds(text)
        scans[f"report:{name}"] = {"hits": hits, "leaks": leaks, "chars": len(text)}
    bad = sorted(name for name, scan in scans.items() if scan["hits"] or scan["leaks"])
    parts.append(c.check("wording", bool(texts) and bool(reports) and not bad, f"texts with hits: {bad}",
                         scanned=len(scans)))
    exported = (fixed_export or {}).get("sentences") or {}
    differ = sorted(key for key, text in c.FIXED.items() if exported.get(key) != text)
    parts.append(c.check("fixed_sentences", fixed_export is not None and not differ,
                         f"product constants differ from the spec text: {differ}"))
    # The fixed sentences themselves (the spec text and the product's exported constants), WITHOUT the fixed-line
    # exemption the scans above use: a forbidden word in a fixed sentence fails here.
    own = c.forbidden_hits("\n".join([*c.FIXED.values(), *(str(text) for text in exported.values())]),
                           skip_fixed=False)
    parts.append(c.check("fixed_sentences_wording", fixed_export is not None and not own,
                         f"a fixed sentence holds a forbidden word: {[hit['words'] for hit in own]}"))
    return c.case_record("R11", parts, refs=["evidence/r11.json"]), scans


def report_section(markdown: str) -> str:
    """The "## 구조 출처" section of a downstream report (up to the next "## " heading)."""
    if "## 구조 출처" not in markdown:
        return ""
    rest = markdown.split("## 구조 출처", 1)[1]
    return "## 구조 출처" + rest.split("\n## ", 1)[0]
