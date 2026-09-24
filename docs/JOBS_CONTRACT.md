# M4 local jobs contract

Design: GPT-6 Astra, 2026-09-24. This refines the selected M4 queue, supervision and capability boundary. Implementation remains GPT-6 Sol after M3 acceptance. Read RUNTIME_CONTRACT.md for the existing recovery, approval, budget, ownership and dry-run rules. No cloud queue, remote execution, generic shell runner or proprietary engine installation is added.

## 1. Deliverable and capability truth

A complete M4 can provide a durable, tested local supervisor while every optional energy protocol remains unavailable. D07 explicitly permits that outcome. The parent checked the project .venv: importlib.find_spec('pyrosetta') returned false, and rosetta_scripts was not found on the checked executable path. These are observations about this runtime, not a finding about all installations or the user's license. Probe the actual backend interpreter when reporting capabilities. Do not import/initialize a heavy engine during ordinary API capability reads.

Represent each protocol with stable fields: protocol_id, tool_id, engine_id, engine_detected, implementation_status (unimplemented | implemented), validation_status (not_validated | validated with evidence/version), available, reason_code and a local human-readable explanation. A positive import-discovery probe establishes engine_detected only. available requires the configured engine, an allowlisted implementation, compatible version and relevant real validation. A simulated import success or fixture-worker success cannot satisfy those conditions. Missing engine and unimplemented protocol may both be reported; neither is fatal corruption of the run.

| Requested tool / protocol | Production MVP behavior unless actually implemented and validated |
|---|---|
| relax_structure / relax | unavailable; no relaxed_structure and no total_REU |
| estimate_stability / cartesian_ddg | unavailable; no energy_table, mutation ranking or simulated rounds |
| score_interface / interface_analyzer | unavailable; no interface scores |
| residue_energies / residue_energies | unavailable; no residue-energy table |
| Unknown protocol or caller-supplied executable | input_invalid; never dispatch |

rosetta_scripts discovery is separate information; it is not an automatic substitute for a PyRosetta adapter. A future real supported result must bind exact input handles, preparation/model identity, normalized protocol parameters, seed, engine/version, score function, implementation version and native units to its semantic object identity and event provenance. Rosetta scores remain REU; no arbitrary kcal/mol conversion. Advertise no additional protocol merely because an enum or placeholder exists.

Known unavailable requests return the existing typed precondition/unavailable contract with reason_code, without creating a physical attempt or numeric result. Dry-run may describe the unavailable protocol in planned_call@1, but cannot satisfy relaxed_structure/energy_table inputs. This remains distinct from measured scientific_null.

## 2. Public and internal boundaries

Suggested functions (names may follow the implementation):

- protocol_capabilities() returns the protocol matrix without spawning scientific workers.
- submit_job(run, tool_request) validates typed handles/normalized parameters and returns a job reference, a planning handle, or a typed unavailable/approval/checkpoint response.
- claim_next(owner_id) atomically claims an eligible queued job; it does not authorize execution on its own.
- execute_claim(run, job_id, owner_token) performs the shared M2 dispatch checks, records a unique physical attempt, and supervises the fixed worker.
- request_cancel(run_id, job_id) durably signals cancellation without waiting for the whole execution lock. It is idempotent.
- get_job/list_jobs read durable state; reconcile_run rebuilds indices and resolves interrupted ownership without silently restarting physical work.

Production submission accepts protocol IDs and scientific parameters, never argv, shell text, Python module names, environment overrides, user output directories or executable paths. The dispatch map is code-owned and points only to implemented production adapters. Validate again inside the worker boundary. Use the project interpreter, shell=False, a fixed module entry point and a run-owned job directory with the same no-symlink/path-confinement protections as M1. Pass bounded JSON through a private input file or stdin; do not put raw structures, credentials or arbitrary user text in command-line arguments. Input files come from verified immutable handle bytes. No API key or inherited optional-model secret is required by a local scientific worker: construct a minimal worker environment and exclude such credentials.

Test worker factories may be injected into the internal supervisor in test_jobs.py. They are never registered as production scientific protocols, selected by request data or enabled through an HTTP flag. Their outputs describe lifecycle fixtures; they must not produce production energy evidence. A production protocol check occurs before budget reservation, so this release can honestly have a working queue and zero dispatchable energy protocols.

Expose minimal loopback job list/detail/cancel behavior through the existing API style if needed to exercise the workflow; no general job-management UI is required. Responses show status, protocol, linked call/attempt, elapsed/deadline, blocked reason and actual output handles. Queued/running/failed/cancelled/interrupted jobs have no inferred energy values.

## 3. Durable job record and transitions

A job identifies one normalized requested computation; an attempt identifies one physical launch reservation. Suggested persisted record:

- job_id, run_id, root_call_id, call_key, tool/protocol and implementation version, input handles, normalized parameters, seed, created time;
- status, blocked_reason, cancellation-requested flag, owner_token and attempt_id;
- attempt ordinal, reservation_id, approval event reference, configured timeout and remaining run allowance at dispatch;
- supervisor identity and process identity record (PID, process group, start identity/launch token), started/finished timestamps;
- terminal failure class/reason or validated output handles, wall-time accounting reference, cleanup status.

Run events are the source of truth for job intent, reservations, transitions and result handles. SQLite provides durable query/claim indices and may be reconstructed. Append and flush the authoritative event before updating its corresponding row, under the run/queue ownership discipline. A unique event sequence/attempt ID makes row replay idempotent. If a crash occurs between event append and row update, reopening applies the missing event; a stale row cannot authorize another launch. Use a SQLite transaction (BEGIN IMMEDIATE or equivalent compare-and-swap) for claim, and also acquire the M2 run execution owner before budget/cache/dispatch decisions. After acquiring ownership, reconcile events before acting. A claim race must not start two processes or consume the final budget unit twice.

| From | Event/condition | To |
|---|---|---|
| queued | durable cancellation before reservation | cancelled, no expensive charge |
| queued | approval absent or budget unavailable | queued with blocked reason/checkpoint; no launch |
| queued | owner claim plus durable allowed attempt reservation | running, dispatch pending/started recorded explicitly |
| running | valid output persisted and worker/group cleanup confirmed | done |
| running | launch/protocol/result failure and cleanup confirmed | failed |
| running | timeout and cleanup confirmed | failed with resource_exceeded/timeout |
| running | cancellation accepted and cleanup confirmed | cancelled |
| running | lost owner/restart and cleanup confirmed | interrupted |

Terminal transitions are compare-and-swap against the active attempt and recorded once. A late success message cannot overwrite cancellation/timeout or publish a result from an obsolete attempt. The execution owner arbitrates races: if a durable terminal success already exists, later cancel returns already_terminal; otherwise a cancellation observed before terminal commit wins. Duplicate finish/cancel requests are harmless.

If cleanup cannot be confirmed, retain running with cleanup_pending/interruption_pending and a precise reason. It is not terminal, not a cache result and not eligible for another attempt. Do not mark it cancelled merely because a signal was sent. This fail-closed condition must be observable and recoverable by subsequent reconciliation rather than hidden behind a successful response.

Queued jobs survive clean restart. A stale running row alone neither proves a live worker nor proves it died. Check the OS ownership lock and the recorded live supervisor/process identity. If the owner is still alive, a second process observes it and does not steal or terminate its work. If ownership is lost, finish cleanup of the verified recorded group before recording interrupted; never silently change it to done or requeue it. An explicit later recovery request uses the M2 finite counters and creates a fresh attempt/reservation. No automatic infinite requeue after restart.

## 4. Supervision, timeout and cancellation

The supported deployment for this gate is the local POSIX environment. Launch with a fresh process session/group and retain the Popen handle. Scientific workers and their helpers must stay in that group; the production API exposes no means to escape it. General containment of hostile arbitrary executables is outside this contract because they cannot be submitted.

The hard deadline is the smaller of the configured protocol timeout and remaining M2 wall allowance. Use a monotonic clock while supervising. Poll cancellation through a separately signalable token/channel; the long-running run owner must not prevent a cancel request from being delivered. Read bounded worker output without deadlocking on full stdout/stderr pipes. Reject empty, malformed, truncated or oversized result payloads and wrong job/attempt/schema IDs. Reject nonfinite scientific fields; an exit code of zero is insufficient to publish results. Store bounded local diagnostics without copying credentials/environment or uncontrolled worker text into UI/events.

On timeout, cancellation or failed supervision:

1. Stop accepting scientific results and signal SIGTERM to the owned process group.
2. After a bounded documented grace (for example one second), send SIGKILL to any surviving owned group members. A leader exiting promptly does not prove its children exited. Escalation must still cover a SIGTERM-ignoring grandchild even if the leader exited and all output pipes closed.
3. Reap the direct child with wait/communicate, close pipes, and verify the known group no longer contains live processes. Descendants are reaped by their parent or the OS; do not claim the Python supervisor can waitpid arbitrary adopted grandchildren on every POSIX platform.
4. Only then commit terminal state, settle time and release execution ownership. Cancellation/timeout cannot trigger a new attempt while a previous worker remains alive.

Apply descendant cleanup on normal leader exit as well: a successfully returned payload does not authorize leaving helper processes behind. Persistent unexpected helpers must be stopped before accepting the result or reported as a worker protocol failure. No indefinite pipe-drain wait is permitted.

Retain enough launch identity to avoid signaling an unrelated process after PID reuse. A PID/PGID integer or timestamp alone is not authorization to kill on restart. Use an actual live supervisor handle/lock and verified process-start identity, or an equivalent authenticated local ownership mechanism. Persist dispatch intent before spawning and a confirmed identity immediately after launch. Address the spawn/identity-record crash window explicitly (for example a worker bootstrap handshake that cannot begin scientific work before the supervisor records its identity, with a bounded parent-loss exit). If identity is indeterminate, block a replacement attempt and report cleanup_pending; never guess a PID or declare successful cleanup. Tests must exercise the chosen restart mechanism, not just change a database row by hand.

## 5. M2 integration: one approval and accounting authority

The queue must use the existing run approval/budget ledger, not a second counter. M2's first-expensive-call approval is an explicit persisted application action scoped to the run and gate. A submitted JSON flag, decided_by=human, job retry or restart cannot create approval. Reopen restores the real event. Approval does not restore spent units or override exhausted wall budget.

Reserve/charge one expensive unit with a unique attempt/reservation ID immediately before each real launch attempt, after validation, capability, cache, cancellation, approval and available-budget checks. The run owner and durable reservation precede Popen. Launch failure, worker failure, timeout, cancellation after reservation and interrupted dispatch retain that charge. If a crash leaves it unknowable whether Popen was reached, conservatively retain the reservation and label dispatch_outcome_unknown; do not refund and silently launch again. No reservation for unavailable protocols, invalid input, denied approval, queued cancellation, cache hits or dry-run planning. Retrying after a failed physical attempt requires a new unit and must consume the M2 root recovery allowance, not reset it.

Do not charge both Run.call and queue dispatch for the same attempt. Route both synchronous expensive calls and queued calls through the same reservation primitive and event ID. Replaying the event cannot charge twice. Queue submission alone does not charge execution time or an expensive unit.

Wall time follows RUNTIME_CONTRACT.md: active supervision/wait and cleanup/backoff count; ordinary queue idle time and clean offline time do not. Avoid double-counting a Run.call wait interval plus its nested supervisor duration: use one owner interval, with nested intervals contributing no duplicate charge. Timeout cleanup can run beyond a scientific deadline to terminate workers safely; record actual elapsed/overrun, checkpoint the run and do not launch continuation. On orphan recovery use the documented bounded conservative UTC charge for the unclosed interval, then actual active cleanup time, each recorded once. Budget exhaustion must not prevent cleanup.

## 6. Focused M4 acceptance evidence

Add these behavioral groups to test_jobs.py and relevant shared-runtime tests. Use temporary runs and deterministic barriers/fake clocks for state/accounting, plus actual subprocesses for OS lifecycle. Keep process tests bounded and always clean them up in finally blocks.

1. Capability matrix for missing engine, detectable but unimplemented protocol, unknown protocol and fixture-only adapter. None advertises validated energy support or emits numeric energy handles. No live-engine validation is claimed.
2. Production request cannot choose an executable/module/env/path or invoke a fixture worker. Unavailable/invalid/dry-run requests spawn no process; dry-run yields only planning data.
3. Queue submit, atomic claim, finish and list/reopen work; simultaneous claims dispatch once. Delete SQLite and rebuild queued/terminal records and handle references from events without source files.
4. Persisted approval is required before launch, restored on reopen and never inferred from caller provenance. Denial/exhaustion/cache/dry-run/queued cancellation charge zero; launch failure and each failed physical retry consume exactly one durable unit, with no duplicate Run.call/queue charge.
5. A normal fixture returns a bounded schema-valid lifecycle payload. Nonzero exit, malformed/oversized output, wrong attempt identity and invalid result data cannot become done or scientific_null.
6. Actual timeout fixture spawns a grandchild that ignores SIGTERM; also test a leader exiting and closing pipes while the grandchild remains. Verify known PIDs are no longer alive, direct child is reaped and resource_exceeded is durable. This is process evidence only.
7. Actual cancellation follows the same cleanup path, reaches cancelled only after termination, and is prompt while the execution owner is held. Cancellation queued before launch starts no process; repeated cancel and completion/cancel races produce one consistent terminal outcome.
8. Restart while another live supervisor owns the job does not steal/duplicate it. Actual supervisor interruption exercises the selected launch-identity/cleanup path, preserves charges and reaches interrupted only after verified cleanup; an unverified/stale PID is never signaled or relabeled done.
9. Inject failures between durable reservation/event append, row update, launch handshake, result-object persistence and terminal commit. Reopen neither double-charges nor silently retries; no terminal success references an absent/unverified result.
10. Active wait/backoff/cleanup and failed attempts consume wall allowance once; queued idle/clean offline gaps are free. Timeout overrun performs cleanup and blocks further work. M2 recovery counters persist across job retries and restart.

Record interpreter/platform, real child/grandchild termination evidence and whether any real scientific protocol was tested in the phase review. Lifecycle fixtures prove supervision, not Rosetta initialization, energy accuracy, ΔΔG calibration or biological validity. A release with the documented unavailable protocol matrix can pass this gate without installing or simulating PyRosetta.
