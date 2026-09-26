# M7 process identity correction

GPT-6 Astra design, 2026-09-24. Required correction; this document is not implementation approval. GPT-6 Sol implements and tests it. It supersedes only the public `psutil.Process.create_time()` identity prescription in `JOBS_POSIX_ADDENDUM.md` sections 2–3 for new owned launches. The queue, reservation, handshake, cancellation, cleanup, scientific protocols and completed MVP specifications retain their existing contracts. Historical review reports are not rewritten as though this correction existed earlier.

## Evidence and cause

The actual host M7 checkpoint/production tests failed twice: a worker's public creation time differed from its authenticated STARTED observation by exactly 2 seconds, and a new guardian failed identity authentication. A third parent-loss test passed. Evidence: `/tmp/protview-qa/m7-initial-checkpoint-host-failure.json` (pytest temporary suite 2330). These are real failures, not accepted skips.

Installed psutil 7.2.2 on Darwin adjusts its public creation time using the importing process's `INIT_BOOT_TIME` and the current boot time. Its own PID-reuse identity uses the unadjusted internal `create_time(monotonic=True)` instead. The public method has no public monotonic argument. This behavior is verified in the pinned upstream [Darwin implementation](https://raw.githubusercontent.com/giampaolo/psutil/release-7.2.2/psutil/_psosx.py) and [Process identity implementation](https://raw.githubusercontent.com/giampaolo/psutil/release-7.2.2/psutil/__init__.py).

`/tmp/protview-qa/m7-astra-psutil-identity-probe.py` and its `-results.json` independently reproduce the difference by changing only interpreter-local `INIT_BOOT_TIME` by ±2 seconds. The same live PID's public value changes by 2 seconds, while its raw identity remains exactly equal, including a separate interpreter's read. The probe changes neither the OS clock nor process ownership and sends no signals. It establishes the failure mechanism; it does not establish which external time synchronization event occurred during the failed host tests.

## New identity representation and adapter

Use a small shared, explicitly version-bound adapter, with psutil pinned to **7.2.2** in the backend dependency. Support only tested Darwin and Linux paths. Obtain the raw start value from a fresh `psutil.Process(pid)._proc.create_time(monotonic=True)`, the same underlying path used by this version's PID-reuse identity. This private dependency is deliberate, isolated and tested; do not scatter private access across callers. Do not replace it with process age, event timestamps, public creation time, rounding, tolerance, hash(Process), or PID alone.

Persist this exact JSON-compatible record wherever a process identity is authenticated:

```json
{"kind":"psutil_raw_start_v1","platform":"darwin","psutil_version":"7.2.2","value":123.456}
```

The example value is illustrative, not a real identity. `platform` is exactly `darwin` or `linux` as appropriate; `value` is a positive finite numeric value, excluding bool. Treat the raw number as an opaque exact identity component, not a timestamp for display. Validate all fixed keys/types and the complete record before comparison. Preserve the JSON round-trip value without conversion or truncation. Missing internal API, wrong psutil version, unsupported platform, access denial, malformed/nonfinite value or unsupported record kind fails closed. There is no public-time fallback. New scientific dispatch must not advertise working supervision if this prerequisite is unavailable.

Use `start_identity` for this record in bootstrap receipts, HELLO/launch identity, STARTED/worker observations and every captured cleanup cohort member. A public `create_time` may remain diagnostic only; it must never authorize signaling or establish identity equality for a new-format record. Receipt and authenticated-channel identities must agree exactly. New identity records must not be mixed with old public-time records.

## Preserve the complete ownership proof

Raw start identity replaces one identity component; it does not replace the existing authorization checks. Continue to verify actual Popen PID, same UID, PGID, session, fresh-session leader condition, private nonce, receipt and authenticated control channel. Use fresh process reads rather than cached process_iter information. Capture/revalidate identity around the other ownership reads where needed to reject a process changing between observations. Recheck the exact raw identity and same-user/group ownership immediately before each signal.

Maintain the M4 cleanup rule unchanged: new members may enter a cohort only while the original guardian anchor is verified both before and after enumeration. After anchor loss, escalation is limited to independently reverified identities already captured in that cohort. A fresh process discovered under a reused PGID is not authorized. AccessDenied is not an empty group. Preserve the post-spawn finally cleanup, STOP/RESULT drain, direct-child reap attestation, bounded TERM/KILL escalation, parent-death cleanup, and unresolved-cleanup admission block. Never send a blind kill because a comparison failed.

## Old records and restart

Completed old job/events/report records remain readable and keep their exact bytes. Their historical `create_time` fields do not need migration. Do not rerun science or rewrite old events on read.

For an old active receipt/attempt without the new identity record, do not reinterpret its public time as raw time, subtract an inferred offset or silently grant signal authority. Existing ownership locks and authenticated live supervision remain authoritative while held. After owner loss, an old live or indeterminate group remains `cleanup_pending` and blocks replacement unless absence/cleanup can be established by the existing conservative mechanism without signaling an unverified identity. Mere age, a missing receipt, a changed PID or permission failure does not establish successful cleanup. A verified absence can be reconciled under the existing rules; no automatic retry or new reservation follows. There is no new scheduler or interactive migration feature in this correction.

## Implementation and test migration

Expected changes are bounded to a shared process-identity helper under `backend/mw/jobs/`, `guardian.py`, `queue.py`, `backend/pyproject.toml`, affected `test_jobs.py`/`test_openmm.py` tests, and implementation documentation. The isolated guardian must load the same trusted helper in its existing fixed launch context; do not add arbitrary path or environment loading. Update all capture, receipt parsing, HELLO/STARTED validation, cohort keys, restart and signal checks consistently. Include new identity data in worker-started events so host tests compare the same authenticated value. Test fixtures with synthetic identity dictionaries must explicitly declare their fixture nature and use the new schema. Do not weaken assertions by making PID/identity evidence optional.

Required focused evidence, in addition to the existing actual host supervision tests:

1. Deterministic process-local public-clock offsets of 0, +2 and -2 seconds: public values may differ; the new raw identity for the same live PID must remain exactly equal. Separate interpreters must independently agree. Do not adjust the OS clock.
2. Paired forged record: keep PID/UID/PGID/session/nonce unchanged but change the raw start value. Authentication must fail and a mocked signal recorder must contain zero calls. Also reject wrong kind/version/platform, missing values, bool, NaN and infinity. Label this as a deterministic PID-reuse-policy test, not observed OS PID reuse.
3. Retain the existing old-anchor/new-stranger zero-signal test and known-survivor TERM/KILL test using the new identity representation. Public-time agreement must not rescue a raw identity mismatch.
4. Real owned launches must complete the handshake and actual worker execution; real timeout, mid-worker cancellation and parent-loss cases must prove cleanup/reap and conserved accounting. Retain valid checkpoint ingestion after verified cleanup. The earlier failed physical tests must pass without conditional assertions or broad sandbox skips being presented as host evidence.
5. Old completed events/report reads remain exact and engine-free; a crafted old active record cannot acquire signal authority or admit replacement through reinterpretation. Wrong psutil version/platform/internal API must fail closed before unsafe dispatch.

Independent scientific energy reconstruction and frontend boundary fixes remain separate M7 evidence. Passing these process-identity tests alone does not approve M7.
