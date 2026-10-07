# M25 JEV design loop fixtures (T1 preflight measurements)

Made locally for ProtView M25 (JEV design loop) on 2026-10-07 in task T1, before any M25 product code existed. Nothing
in this folder is a scientific result, a provider response, a measured binding value, an affinity, a stability or an
API credential. The measurement record that quotes these scripts is `docs/qa/m25-jev-loop-20261007/preflight.txt`.

Every script here is a PROTOTYPE (first docstring line says so): it calls the unmodified product code (`Run.call`,
`JobQueue`, the M17 / M18 / M19 / M20 / M21 / M24 modules) in throw-away runs and prints one JSON report. They are
never imported by product code or by the pytest suites. Their readings of the M25 spec (loop request shapes, the
`sha256_order_v1` order, the loop wire and body, the loop event payloads) are prototypes of later tasks (T2-T6), not
the constants those tasks will write.

Inputs reused from other fixture folders (read only, not copied): the public structures `../public_1ubq.cif` and
`../public_1mq4.cif`; the public prepared docking example receptor `../chemical/prolif-vina-rec.pdb` (not
experimental validation); the public-derived parent `../docking/public-derived-parent-record0.sdf`; the labelled
synthetic block / rule inputs `../ligand_ga/synthetic-ga-small-blocks.smi`, `../ligand_ga/synthetic-ga-pool2000-blocks.smi`,
`../ligand_ga/synthetic-ga-pool2000-rules.json`; the labelled synthetic phenol `../mutation_model/synthetic-phenol-ligand.sdf`;
the M24 oracle neighbor counts `../jev/expected.json`. See those folders' provenance files.

| File | What it measures (preflight item) |
|---|---|
| `prototype_queue_semantics.py` | (a), (e) locks, (l): real M21 jobs on 1UBQ I44 through the unmodified `JobQueue`: cancel before start, first-expensive-call approval block then cancel, block then a server restart (`reconcile_run`) then a retry outside any loop, block then approve then done (event order, owner / mutation / submit / cancel probes from another thread while it runs), a cancel in the window between `budget_reserved` and `job_dispatch_intent` (a measurement-process wrapper on that `Run` instance's `reserve_attempt`), a 1 s timeout failure then a retry, and lock reentrancy. |
| `prototype_engine_calls.py` | (b), (f), (h): the loop's ligand request (`docking_batch_inputs.row_request` with `mode: "free"`) and protein requests (M21 arguments, the M18 `receptor_source` request) against the M19 / M22 / M23 / standalone M18 / M21 paths (normalized bytes and call keys), real M17 jobs, real M18 / M19 / M21 jobs (engine time), `published_m18_results` lookups, a prototype M21 call key -> model lookup, the M21 pair read of a mutant-only docking, and whether 1MQ4 passes M21 admission. |
| `prototype_loop_body_size.py` | (d): the largest loop request bodies from real M20 sets (1UBQ, 1MQ4) and a real M17 2,000-candidate set, built with the unmodified M24 wire builders and then re-ordered / extended per this reading of spec 4.3-4.5 (both goals, 0 or 18 computed candidates, a one-decimal and the widest finite score repr), plus byte arithmetic for the widest allowed shapes. |
| `prototype_loop_read.py` | (e): a one-read derivation prototype (one event snapshot behind a read view; job fold, M18 reuse index, validated stored results) against the per-candidate re-reading path, on the real ligand run copied events-only and on the same log padded with labelled synthetic 48 KiB objects to about 5 MB and 50 MB. |
| `prototype_loop_events.py` | (g): two events-only copies of the real ligand run go through consent, a real `build_jev_projection`, one approved science send with a fixture `httpx.MockTransport` gate and an inert sentinel credential, and a simulated crash with an unsettled science reservation; one copy also gets spec-shaped `jev_loop_*` events. Replay, settlement, reconciliation, job states, the reuse index, the M24 send records and status, an events-only rebuild and the GET route status codes are compared. |
| `prototype_m24_branch_points.py` | (c): a real M24 projection and a labelled synthetic loop-shaped object in a throw-away run; which unmodified M24 functions accept or refuse each (kind check, validator, instructions table, `parse_choice` alias set, send record kind, proposal check). Nothing is sent. |

Work folders default to `runs/m25-t1-preflight/<name>` (Git-excluded) and are deleted at the end of each script
unless `--keep`; the T1 measurements used a session scratch directory. No script opens a socket to anything but the
in-process test client, reads `.env` or prints a credential. qvina scores the scripts print are observations
(kcal/mol, Vina-family scoring function values, not affinities); nothing is ranked or compared between receptors.

The M24 science-send golden made in the same task lives with the other M24 goldens:
`../jev/golden_science_m24.json` and its recorder `../jev/golden_science_m24.py` (see `../jev/SYNTHETIC-PROVENANCE.md`).
