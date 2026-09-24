# M2 runtime implementation

M2 executes local tools through `Run.call`. Human API commands pass
`execution_mode="human"` explicitly. Autonomous drivers must supply a durable
`branch_id`; `decided_by` records provenance and grants no permission. A
run's seed, dry mode, budget limits, and guard thresholds are recorded in its
first event. Reopening with a different seed or dry mode fails. An explicitly
different supplied limit set fails; a default caller may reopen a run with its
recorded limits. `update_limits` is the only recorded limit change.

## Execution and recovery

Arguments are validated before implementation. Defaults are filled before the
call key is computed. The key includes tool version, normalized arguments, run
seed, dry mode, and, for structure import, the SHA-256 of the exact bytes used
by the tool. Original calls and argument repairs use one source-byte
normalizer. Local bytes are read once after format validation; the API's
verified upload bytes are retained. The importer receives the same bound bytes
and format used for the key. Missing paths and unsupported formats fail before
dispatch. Scalar and collection handle parameters keep their declared
shapes. Accepted handles are loaded and hash-verified. Unknown or unregistered
tools, invalid parameters, and wrong kinds produce typed failures and no
physical invocation.

A physical attempt has a unique call ID and a root/parent relationship.
Transient failures get at most three additional attempts with 2/4/8 second
backoffs. Recovery counters are reconstructed from the event log by root ID.
Each backoff has a durable start with root, failed attempt, retry index,
requested delay, remaining allowance and UTC deadline. Completion records a
monotonic wall charge and terminal backoff event. A new owner marks an
unfinished backoff interrupted, charges its unaccounted UTC interval once up
to its recorded and current run allowances, and checkpoints when exhausted.
Negative UTC movement charges zero and records `clock_anomaly`. Completed
backoffs and clean idle/offline intervals accrue no recovery charge.
`repair_call` permits one changed, valid argument set after an input failure.
`satisfy_precondition` permits one allowlisted `prepare_structure` action
for a declared `prepared_structure` input, records the actual prerequisite
handle, and retries the original tool with that handle bound to its input.
Prerequisites have no nested recovery. Resource and fatal failures stop.
Unexpected ordinary exceptions become fatal with a local diagnostic.
`scientific_null` is a completed result. Cancellation and interrupted
attempts are terminal; they are not transient failures.

Cache reads verify the output object hash, kind, schema, summary and null
status. They append `cache_hit` with a unique observation ID, normalized
arguments, verified output and original physical `source_call_id`. They do
not append a second physical success or charge expense. The frontend checks
that source call and its noncached success agree on key, tool, ordered sequence,
canonical JSON arguments and output before using a cache observation. Duplicate
or colliding observation IDs are not selectable. The frontend joins pipeline
inputs through the original call arguments and labels the timeline entry
`cache read`. It still reads legacy M1 cached `tool_succeeded` observations
for existing runs. Cache observation order can change the latest view intent.
Displayed interaction structure is resolved from immutable object metadata;
Mol* focus remains gated on matching canvas readiness and acknowledgement.

Autonomous proposals are recorded before cache lookup. Per-branch key counts,
seen handles and no-progress count rebuild from events. The third identical
proposal stops, four completed proposals with no new output handle stop, and
a six-key A/B cycle without intervening new handle progress stops. Human cache
reads have no branch guard. A checkpointed branch stays stopped after reopen;
a distinct branch can be started explicitly.

## Budgets, ownership, and recovery ordering

An approved real expensive attempt reserves and charges a unit immediately
before `tool_called`. Failed, interrupted and successful attempts all retain
that charge. Validation failures, cache reads, approval waits and dry-run plans
charge none. Approval, reservations, wall charges, limits and checkpoints are
event backed. Before each retry sleep, both the next expensive unit and the
whole backoff interval must fit. External token and USD axes remain at zero for
M2 local work.

Wall time uses a monotonic clock during attempts and backoff. The active
in-process snapshot includes elapsed time before the next charge event. Idle
and clean offline time are free. A later owner reconciles a started attempt
without a terminal event as interrupted. It charges its unaccounted UTC
interval, capped by the attempt's recorded remaining allowance. Negative UTC
movement is clamped to zero and emits `clock_anomaly`. A live owner is never
reconciled by a read-only constructor. For legacy M0/M1 events without a
recorded remaining allowance, the remaining run wall limit is the cap.

An OS advisory lock covers each complete mutating call or repair across
processes, with a local thread lock for the same process. A competing owner
gets a typed, immediate busy result. After acquiring ownership, the runtime
rebuilds the disposable object index from immutable object events, rereads
state and reconciles abandoned attempts before making cache or budget
decisions. Event sequence allocation and append have a separate advisory
lock and fsync; readers use its shared lock for a complete snapshot. Object
creation writes the full payload event first, then the blob and SQLite index.
Rebuild validates and installs all event-derived rows inside one SQLite
transaction. Separate readers retain the old valid index until commit; a
corrupt rebuild rolls back. The index can be deleted and rebuilt from events
alone. Corrupt event
sequence, object payload, blob or cache envelope fails clearly.

`cancel()` writes a separate fsynced token and event without waiting for the
execution lock. Dispatch, retry, backoff and a cooperative tool context check
observe it. M2 cannot forcibly stop arbitrary in-process Python/C execution;
M4 owns subprocess termination. The UI does not expose a cancellation control
yet.

## Dry runs and compatibility

Expensive dry-run calls emit `planned_call@1` only. The plan names the tool,
effective arguments, cost class and unmet real execution condition. A
planning stub, if registered, is never invoked as scientific work. A plan
cannot satisfy a `relaxed_structure` or `energy_table` input, and dry/real
keys differ. The archived synthetic REU stubs and assertions were removed.
The M4 energy protocols return unavailable/precondition before approval or
expense reservation in real mode, and are hidden from the visible tool list.

M0/M1 `run_started` events lack M2 limits and guard settings. They reopen
under the original project defaults (1800 seconds, 8 expensive calls, 120000
external tokens, USD 2; guards 4/2/6). Their noncached successful physical
durations contribute to historical wall use only when their call ID has no
explicit M2 attempt wall charge. Mixed old/new runs retain historical duration,
new success and failure charges, without counting any call twice. Existing cached success events
are not counted again. An old unclosed attempt is interrupted by a new owner
and uses the conservative remaining run allowance cap. M2 never silently
upgrades an old event into a scientific result.

## Verification boundary

`backend/tests/test_runtime.py` covers validation, recovery ceilings,
prerequisite binding, terminal failures, cache observations, branch guards,
expense, wall accounting, dry plans, tampering, cancellation and real
cross-process ownership. `frontend/tests/event-model.test.cjs` checks
reopened cache observation order and original load → prepare → interaction
lineage. These tests use identified fixtures; the parent agent owns the
live browser cache-read/reopen proof and Astra review. M2 does not claim M3
egress enforcement, M4 hard-worker termination, or M5 reporting.
