# M2 runtime contract

Design: GPT-6 Astra, 2026-09-24. This refines the already selected M2 phase; it does not add an agent framework, external model dependency, or production job runner. M4 owns actual subprocess/queue cancellation and hard timeouts. Read ARCHITECTURE.md and the current M1 API contract first. Implementation remains GPT-6 Sol after the M1 gate.

## 1. One validated execution path

Keep Run.call as the common human/workflow entry point. A backward-compatible signature can add execution_mode (human | autonomous) and branch_id; decided_by (human | rule | jev | frontier) is provenance, not an authorization or loop-control switch. Default execution_mode to human for direct API compatibility; a caller starting an autonomous driver must provide a stable branch_id. The HTTP command route chooses human explicitly. A deterministic pipeline or autonomous driver chooses autonomous explicitly. A caller cannot gain approval by putting decided_by=human in a JSON body.

Normalize effective parameters, including defaults, before computing a versioned call key. Include run seed, dry-run mode and any input-content fingerprint relevant to execution. Preserve the M0 source-byte-aware load key. A cache hit is valid only when its output objects can be resolved and hash-verified. Unknown/unimplemented tools, scalar/collection shape mistakes, nonfinite numeric parameters, invalid enums and wrong handle kinds return a typed failure before the implementation runs. A handle-list parameter must declare that cardinality; do not accept a list where a scalar handle is expected.

Suggested internal state, names adaptable to existing code:

- CallRequest: tool, normalized args, call_key, mode, branch_id, decided_by.
- Attempt: call_id, root_call_id, parent_call_id, attempt_kind (initial | transient_retry | argument_repair | prerequisite | prerequisite_retry), attempt number, key, status, output or failure.
- RecoveryContext: root_call_id, transient_retries_used, argument_repairs_used, prerequisite_repairs_used, declared prerequisite evidence.
- BranchState: branch_id, proposal counts by key, recent proposal keys, consecutive_no_progress, seen_output_handles, stopped reason.
- RunState: immutable initial config, current budget limits/usage, approved gates, calls, branches, cancellation/checkpoint state.

Validation errors are recorded as failed proposals with no implementation invocation. An exception from a tool that is not already ToolFailure becomes fatal with a local diagnostic; it must not escape as an unclassified API crash or cause a retry. KeyboardInterrupt/SystemExit are not ordinary scientific failures and must trigger cleanup/recovery rather than broad BaseException swallowing.

## 2. Finite recovery policy

The runtime owns counters; recursive calls must not reset them. A retry chain is one root request plus its explicitly linked recovery actions. Each physical execution receives a unique call_id. Read-only inspection does not create a fresh recovery allowance.

| Outcome | Allowed behavior within one root request |
|---|---|
| success / null_result | Finish done. A scientific empty result never triggers retries or cutoff changes. |
| transient | At most 3 additional executions across the entire chain, after 2, 4, 8 seconds. Initial execution plus these retries is at most 4 when no other repair occurs. Check budget and cancellation before sleeping and before each retry. |
| input_invalid | No blind automatic rerun. One explicitly supplied corrected argument set is allowed; normalized effective arguments must differ. Validate first. Same arguments or a second correction stop the recovery chain. |
| precondition | One declared prerequisite repair is allowed. Resolve an allowlisted conversion/prerequisite, validate it, execute it once, and require a successful output of the required kind. Retry the original tool once with the prerequisite output bound to its declared input. No recursive prerequisite chain in this MVP. |
| resource_exceeded | Terminal for this request; retain evidence and suggest a reduced request without executing it. |
| fatal | Terminal; no automatic retry. |
| cancelled / interrupted | Terminal attempt state, not scientific_null and not a fresh transient allowance. Resume rules below apply. |

The root request therefore permits at most six executions of the requested tool (initial + 3 transient + 1 argument repair + 1 prerequisite retry), plus at most one prerequisite execution. The prerequisite does not get its own nested retries. Most requests need only the initial attempt. If both repair types are applicable, their counters remain shared under the same root; switching failure categories cannot create an unbounded recursion.

A suitable recovery API is repair_call(failed_call_id, corrected_args) and satisfy_precondition(failed_call_id). These may remain internal Python methods driven by a deterministic test/driver; adding a conversational UI is not required. Both consume the original context, reject a nonterminal or unrelated call, record their relationship, and preserve consumed allowances across reopen. Prerequisite evidence includes prerequisite call_id, output handle, accepted kind, target argument and the original failed call_id. A freeform error fix field is a suggestion, never authority to execute an arbitrary tool.

## 3. Cache and autonomous progress

Human repeated reads and repeated identical successful commands are safe cache hits and do not trip autonomous loop guards. They do not consume an expensive-call unit again. Record cache_hit separately rather than writing another physical tool_succeeded attempt with the same call_id.

The cache event must remain usable by the existing M1 viewer: include a unique observation/proposal ID, tool, normalized effective input references, validated output handle and source_call_id (the original physical successful call). Reopening must still resolve original input provenance. Adapt frontend event normalization/timeline and latest-pipeline lineage selection when this event is introduced: a cached user request can become the latest displayed result or input intent, but it must be labeled a cache read with no invented physical duration/success/charge. Preserve both event order of the read and the original scientific call linkage; do not weaken this cache contract to keep the old tool_succeeded-only UI unchanged.

For an autonomous branch, observe each proposed call before returning a cache hit. Built-in transient retries and approved prerequisite steps are internal recovery attempts, not new proposals. Use normalized call keys, not just tool names, for proposal history. Restore this history on reopen.

- repeated_call_hash=2 permits two proposals with a key; the third checkpoints the branch before execution/cache return.
- no_progress_steps=4 checkpoints after four completed proposals yielding no previously unseen output handle. A cache hit is no new progress. Different arguments returning the same known handle are no new progress. Failed proposals also do not manufacture progress. A recorded scientific_null is still successful completion of its tool; a driver should finish the intended inspection rather than search for nonempty output.
- oscillation_window=6 recognizes repeated A/B call-key cycles with no new output progress in the window. Alternating two tool names while producing useful new objects is not by itself oscillation.

A proposal creating a new output resets consecutive no-progress. Initialize seen handles from durable branch events, not an empty set after restart. A stopped branch cannot silently restart by reopening the same run; an explicit new human request may create a new branch while retaining the run's budget.

## 4. Budget and elapsed time

Budget state is reconstructed from events, never reset from default config on reopen. Record initial limits, dry_run and seed in run_started. A differing seed/mode/limit supplied while reopening must be rejected or handled by an explicit recorded configuration change; silently overriding it is forbidden.

Expensive units are reserved and durably charged immediately before each real physical expensive attempt starts. Success, a thrown error, timeout or interruption does not refund that attempt. Input rejection, a cache hit, a dry-run plan or approval denial consumes no expensive unit. The first real expensive attempt requires a persisted approval event. Reopen restores that approval; it does not infer approval from previous numeric output. Record budget exhaustion as checkpoint with the axis, usage, limit and pending action. Approval alone does not replenish budget; a new limit requires an explicit recorded limit update.

wall_clock_s means cumulative time spent in active runtime work, including a tool, active job wait and retry backoff. It excludes completed idle time, waiting at a human approval/checkpoint, and downtime after a cleanly recorded idle/checkpoint state. In one process measure elapsed time with a monotonic clock, never by summing caller-provided durations. Keep UTC timestamps only for restart reconciliation and audit. No new execution begins when used time is at or above its limit. Before a backoff, require enough remaining time for that sleep; otherwise checkpoint immediately. Recheck after every physical attempt, including exceptions, and before returning into a continuation.

Persist an attempt-start reservation and attempt-finish time charge. On restart, a previously active attempt without a terminal event is interrupted, never done. Charge its unaccounted elapsed UTC interval conservatively up to its recorded deadline/remaining run allowance, mark that recovery charge explicitly, and checkpoint if exhausted. Clamp negative elapsed to zero and record clock anomaly; never grant extra allowance because the system clock moved backward. A cleanly idle run reopening after a long shutdown consumes zero additional wall time. This distinction makes both downtime treatment and crash treatment explicit.

M2 enforces dispatch/deadline checks and post-attempt accounting for synchronous structural tools. It does not pretend it can forcibly stop arbitrary Python/C code in the middle of an in-process call. The attempt context exposes remaining time/deadline/cancellation checks for cooperative work. M4 supplies hard process termination for isolated expensive workers. M2 timeout tests can use deterministic fake clocks or a cooperative failing tool; they must not claim OS-process timeout validation.

external_tokens and usd fields remain durable budget axes but ordinary M2 local work charges zero. M3's external adapter must reserve/check its bounded request and settle actual usage; no invented model usage is charged by M2. Financial estimation or a billing system is not added here.

## 5. Dry-run outputs

Real cheap/moderate local structure inspection may run in dry_run; expensive execution may not. Before an expensive call, return a plan handle (for example planned_call@1) with tool, normalized arguments, declared cost class and unmet conditions. It has no scientific energy measurements and cannot satisfy an accepts: relaxed_structure or energy_table contract. A dependent dry-run step records planned/unresolved dependency instead of passing the plan as a real scientific object.

A custom stub may supply planning detail only. If no stub exists, use a generic plan or return a typed unavailable/precondition result; never fall through to the real expensive function. The existing archive relax/ddG stubs and tests asserting rounds_REU must be replaced. Even deterministically generated numbers are fabricated scientific evidence when presented as an energy result. Dry-run and real call caches must be separated so a plan cannot satisfy a later real request.

## 6. Reopen, ownership and events

Reopen materializes the M0 objects and reconstructs RunState from the ordered event stream. Required durable information: config, physical attempts, cache references, recovery counters/links, approvals, budget reservations/charges, branch proposals/progress/checkpoints and cancellation. SQLite remains a disposable index. Corrupt payloads, broken event sequencing and incompatible run identity fail clearly; do not ignore them to obtain a green resume.

Serialize mutation per run across threads and processes. A process-local RLock alone is insufficient if the API is started twice. Use a run-directory advisory execution lock (or an equivalent transactional owner) for a whole mutating call/repair so two Run objects cannot both pass the same cache/budget check. After acquiring ownership, reread new events before deciding. Protect event sequence allocation and append independently, and flush durable events before releasing ownership. A busy owner returns a bounded busy/transient result without starting duplicate work. Read-only object reads need not hold the execution lock.

A lock filename or running event alone does not prove a worker is live. The OS lock or the M4 process/job handle is authoritative. A second process that acquires ownership may reconcile an unclosed attempt as interrupted. It must not label a live owner terminal merely because observation timed out. M2 never starts a second physical attempt while a first owner still holds the run lock.

For M2, cancellation is checked before dispatch/retry/backoff and at cooperative checkpoints; record a cancelled attempt/branch and stop continuation. The M4 queue owns cancellation of an already running subprocess and waits for confirmed termination before a retry or restart. Do not block cancellation forever behind the long-running execution lock: the cancellation request/token is separately signalable, while final state/events are serialized by the execution owner. An elaborate frontend cancellation flow is not required by M2.

## 7. Required M2 evidence

Use injected monotonic/UTC clocks and sleeper functions for deterministic policy tests. Retain a small real multi-process test for lock ownership. At minimum, the selected gate must cover:

1. Unknown tool, unimplemented tool, wrong scalar/list handle shape and nonfinite args are classified before implementation.
2. Wrong handle kind gives a declared actionable prerequisite; invalid selection and invalid policy do not invoke a tool.
3. A perpetually transient tool executes exactly four times and sleeps 2/4/8; reopening cannot reset its spent retries.
4. Same-argument repair is rejected; one changed valid repair succeeds or terminates; a second repair is refused.
5. An allowed prerequisite runs once and provides the actual bound handle; missing, wrong-kind, cyclic or undeclared prerequisite cannot recurse.
6. resource_exceeded and fatal each execute once; scientific_null succeeds once with no retry.
7. Repeated human cache reads remain safe; the same requests in an autonomous branch hit repeat/no-progress guards, including after reopen. The frontend normalizes cache_hit into a labeled read/result observation, resolves original input lineage and updates selected/latest viewer intent without inventing a new physical success.
8. A/B no-progress oscillation stops; useful A/B work with new handles does not stop merely because names alternate.
9. Failed expensive attempts consume units; input rejection/denial/cache/dry-run do not; persisted approval and usage survive reopen.
10. Backoff/time-on-failure uses wall budget; an idle offline gap is free; an orphan active interval receives the documented conservative charge and interruption state.
11. Dry-run with no stub never invokes the real function; no synthetic energy handle is emitted; its plan cannot enter a real energy tool or real cache path.
12. Events-only reopen restores results, config, recovery/progress counters and budget; changing defaults cannot silently alter the reopened run.
13. Two concurrent owners cannot both execute one cache key or overspend the last expensive unit; sequence IDs are unique and ordered.
14. Cancellation before a retry prevents further execution and remains terminal on reopen. No test claims hard-worker cancellation before M4.

The existing step2 AC commands remain sufficient entry points when these cases are added to test_runtime.py. Tests assert behavioral counts/state and scientific distinctions, not incidental implementation structure.
