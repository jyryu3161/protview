# M24 JEV science egress fixtures (T1 measurements, oracle and golden)

Made locally for ProtView M24 (JEV science data egress channel) on 2026-10-06, before any M24 product code existed.
Nothing in this folder is a scientific result, a provider response, a measured binding or an API credential. The
measurement record that quotes these files is `docs/qa/m24-jev-20261006/preflight.txt`.

Inputs reused from other fixture folders (not copied): the public structures `../public_1ubq.cif` and
`../public_1mq4.cif` (+ `../public_1mq4.provenance.json`), the labelled synthetic M22 pool inputs
`../ligand_ga/synthetic-ga-pool2000-blocks.smi`, `../ligand_ga/synthetic-ga-pool2000-rules.json`,
`../ligand_ga/synthetic-ga-small-blocks.smi` with the public-derived parent `../docking/public-derived-parent-record0.sdf`
(see those folders' `SYNTHETIC-PROVENANCE.md`), the committed real product outputs
`../ligand_ga/m17-candidate-set-small-pool.json` and `../sequence_ga/m20-candidate-set-1ubq-8pos.json`, `../mini_complex.pdb`,
and the committed M8 live evidence `docs/qa/m8/raw/live-v1-events.json` / `live-v1.jsonl` (read only).

| File | What it is |
|---|---|
| `independent_neighbors.py` | ORACLE. gemmi + standard library only (no `mw` import, no NumPy). Neighbor residues (heavy-atom minimum distance <= 5.0 A, protein = gemmi `het_flag "A"`, any chain, structure order), the +/- 5 residue sequence window (one-letter by the M20 `one_letter` name rule, any other name `X`, `contiguous`) and the ligand heavy-atom minimum distance, per the spec 3 wording. Its readings of the open points are the `assumptions` W1, W2, N1, N2, N3, D1 written into `expected.json` (W2 and N3 fixed as rules in M24 T3, see the change log below). `.venv/bin/python backend/tests/fixtures/jev/independent_neighbors.py --check` exits 0 only if `expected.json` equals a fresh run. |
| `expected.json` | ORACLE output: for 1UBQ (chain A 1, 2, 44, 48, 72, 76) and 1MQ4 (chain A 126, 143, 162, 211, 274, 283, 285, 288, 290, 388; ADP A2001) the neighbor lists, boundary margins, windows and ligand distances, plus the neighbor count of every protein residue. Not product output. |
| `golden_egress_events.json` | GOLDEN. Event / audit shapes the EXISTING `EgressGate.request_jev` (M3) and `mw.egress.viewer.request_viewer` (M8, and once through the HTTP route) write with a scripted `httpx.MockTransport` and an inert sentinel credential: per event its type, field names in on-disk order with JSON value types, and the values of closed / constant fields only. Ids, times, hashes and elapsed seconds are reduced to their type. Later tasks show "existing behaviour unchanged" with `.venv/bin/python backend/tests/fixtures/jev/prototype_golden_egress.py --check`. Not provider output. |
| `prototype_golden_egress.py` | Recorder for the golden file (`--write` checks that two fresh recordings are identical first; `--check` compares). Never product code. |
| `golden_science_m24.json` | GOLDEN (added in M25 T1, 2026-10-07, before any M25 change). What the EXISTING M24 science path answers, stores and writes through the product app with a scripted `httpx.MockTransport` science gate and an inert sentinel credential: the `build_jev_projection` command and the stored `jev_projection@1`, consent, `jev_preview@1`, `jev_send@1` (completed, replayed, rejected `consent_off` / `missing_credential` / `egress_stopped`, failed `provider_http_error` / `response_invalid` / `model_mismatch`, the `send_id_conflict` / `preview_mismatch` 409s, the dry-run refusals), the send list and detail, the stored `jev_choice@1`, every appended event (the science audit rows included), `/jev/status`, the `jev_choice` report and `/capabilities` `methods.jev_choice`, for fixed-id runs (public 1UBQ M20 set; the labelled synthetic methacetin M17 run of `ligand_job_fixture.standard_run`). Random audit / call / attempt / report ids and the handles of objects whose content holds them are ordered markers, times, sequence numbers and elapsed seconds `<number>`; strings over 200 characters (bodies, Markdown, stored object JSON) sit once in `texts` by SHA-256. Later M25 tasks show "M24 bytes unchanged" with `.venv/bin/python backend/tests/fixtures/jev/golden_science_m24.py --check`. Not provider output. |
| `golden_science_m24.py` | Recorder for `golden_science_m24.json` (`--write` checks that two fresh recordings are identical first; `--check` compares and names the differing cases). Work runs go under the Git-excluded `runs/` and are deleted. Never product code. |
| `prototype_body_size.py` | PROTOTYPE. Runs the real M20 tool on 1UBQ / 1MQ4 and real M17 jobs on the synthetic pools in a throw-away runs root, builds the spec 3 wire dicts by hand and measures the spec 4 body bytes of 20-candidate selections, plus byte arithmetic for the widest allowed shapes. Its question instructions are a PROTOTYPE English text, not the T2 constant. |
| `prototype_boundary_margin.py` | PROTOTYPE. How close 1UBQ / 1MQ4 residue pairs come to 5.0 A and whether `math.dist` and an M20-style NumPy minimum agree. |
| `prototype_budget_replay.py` | PROTOTYPE. Writes spec 5 shaped reservation / settlement / refund / new `jev_*` events with the real `Run` methods and reopens the run from its event log. The `jev_*` names are the spec names, used here only for replay tolerance. |
| `prototype_late_response.py` | PROTOTYPE. A throw-away FastAPI app mounting the product app, one async route shaped like `request_viewer`, a blocking MockTransport; `Run.cancel()` / consent-off arrive mid-request, then the audit, `jev_*` events and an object are written and reopened events-only. |
| `prototype_event_log_read.py` | PROTOTYPE. Read-only timing of one existing large log (optional) and of synthetic 5 MB / 50 MB logs (labelled synthetic padding objects) for read, append, open, `_mutation` and status/preview-shaped reads. |
| `prototype_field_map.py` | PROTOTYPE. Prints the stored key sets and closed values of the committed real M17 / M20 objects and the validators' key sets (where each wire field comes from). |
| `prototype_pains_names.py` | PROTOTYPE. Run with `.deps/prolif/venv-locked/bin/python` (RDKit only): every PAINS A/B/C entry name against the spec 3 wire pattern. |
| `prototype_token_ratio.py` | PROTOTYPE. Rebuilds (approximately; the M8-time bytes were not reproduced, see the report) the three real M8 request bodies from committed evidence and divides by the provider-reported input tokens, to calibrate the science reservation formula. No call is made. |

Throw-away runs roots (`_work_*` next to the scripts) are deleted at the end of each script and never committed.

## Change log

- M24 T3 (2026-10-06): two oracle readings became fixed rules and `expected.json` was rewritten with `--write`, so its
  SHA-256 changed from `113aecccb3691213b5124dec82138ed45e40a33a43d4c9fc80c4cb7d2cf94c06` (51,907 B, the value quoted
  in `docs/qa/m24-jev-20261006/preflight.txt`) to `c1b3e61cdbb333e36f65ab6fd95c85f1d320eda6970d7841a0f10c4b52fa4127`
  (52,095 B). W2: window letters follow the M20 position `one_letter` rule (the 20 standard names plus the ten mapped
  names HID/HIE/HIP/HSD/HSE/HSP -> H, CYX -> C, ASH -> D, GLH -> E, LYN -> K; anything else X), so a window letter never
  disagrees with the same position's `one_letter`; the mapping is written out in the oracle, not imported. N3 (new): a
  target residue without heavy atoms has neighbors `null` (not computed), never `[]`. Only the `assumptions` block
  changed: every `structures` value (neighbors, margins, windows, distances, neighbor counts) is identical, because
  public 1UBQ and 1MQ4 contain no mapped residue name and no protein residue without heavy atoms.
- M25 T1 (2026-10-07): added `golden_science_m24.json` (SHA-256 `78d4cf12078c443b7525d16c6af3df7afcc3be135a49de431bf0f7616fee482c`,
  209,001 B) and its recorder `golden_science_m24.py`, recorded from the M24 code at main `b8866a8` with no `backend/mw`
  change. No existing file in this folder changed apart from this table and change log.
- M26 T1 (2026-10-08): `golden_science_m24.py` no longer runs the M20 tool (which builds v2 sets since M26); it puts the STORED v1 candidate-set content of `../reaction/t1/m20-v1-candidate-set-<run id>.json` (made once by the unmodified v1 tool, see `../reaction/t1/SYNTHETIC-PROVENANCE-t1.md`) inside the same `Run.call` envelope, so `golden_science_m24.json` is unchanged and `--check` exits 0 before and after (`docs/qa/m26-reaction-20261008/v1-baseline/checks/`).

## Not claimed

Neighbor lists, windows and distances are geometry from stored coordinates, not interactions. Body sizes are byte
counts of a prototype encoding, not the final product bytes (the T2 constants may change the instruction text). The
golden file pins today's gate behaviour only; it says nothing about the provider.
