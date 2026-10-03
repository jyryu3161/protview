"""M19 batch docking closed sets, limits and fixed wording (spec .dryforge/spec.md 4.2-4.4, 5.4, 5.5, 6.3).

Dependency-free on purpose (standard library only, no imports at all), like ``docking_constants``, so the server
modules and the isolated batch worker can share one copy by file path. Changing any limit, state, reason, status or
batch sentence needs a user decision (spec 4.2, 5.4; handoff absolute condition 8).
"""
from __future__ import annotations

PROTOCOL = "qvina_batch_dock_v1"
TOOL = "qvina_dock_batch"
ENGINE = "qvina"
SUMMARY_SCHEMA = "docking_batch_result@1"
OUTPUT_KIND = "docking_batch_result"
SELECTION_SCHEMA = "docking_batch_selection@1"

# 4.2 limits. Rows = candidates (<= 50) + the optional parent row.
MAX_CANDIDATES = 50
PER_CANDIDATE_S = 300            # one row: ligand preparation, conformers, qvina and contacts
TOTAL_S = 7200                   # whole batch inside the job, receptor preparation and parent row included
TIMEOUT_MAX_S = 7800             # job time limit for this protocol only (in-job clock 7200 s + finishing margin)
MAX_OUTPUT_BYTES = 128 * 1024 * 1024   # sum of per-row result files (tunable default, spec 4.4)
MAX_SUMMARY_BYTES = 1024 * 1024        # docking_batch_result@1 object (spec 5.2)
LIMITS = {"max_candidates": MAX_CANDIDATES, "per_candidate_s": PER_CANDIDATE_S, "total_s": TOTAL_S}

# 6.3 budget need and limit raise: needed wall = min(TIMEOUT_MAX_S, N * PER_CANDIDATE_S + FINISH_MARGIN_S), or
# EMPTY_BATCH_WALL_S when N = 0. A raise adds RAISE_MARGIN_S to a wall shortfall (runtime overhead charged right after
# the raise must not make the batch short again); the increment never exceeds one full batch's need.
FINISH_MARGIN_S = 300
EMPTY_BATCH_WALL_S = 60
RAISE_MARGIN_S = 60
MAX_RAISE_EXPENSIVE_CALLS = MAX_CANDIDATES + 1
MAX_RAISE_WALL_CLOCK_S = TIMEOUT_MAX_S

# 4.3 / 4.4 closed sets.
ROW_KINDS = ("parent", "candidate")
ROW_STATES = ("scored", "null_result", "failed", "cancelled", "not_run")
BATCH_STATUSES = ("complete", "partial")
STOP_REASONS = ("cancelled", "time_exhausted", "worker_failed", "resource_exceeded")

# 5.5 reasons added by M19. Admission: before any job (batch_limit_raise_required is 429, no budget). Row level:
# every M18 reason plus these (resource_exceeded is already an M18 reason).
ADMISSION_REASONS = ("batch_empty", "batch_too_large", "batch_parent_not_allowed", "batch_limit_raise_required")
ROW_ONLY_REASONS = ("candidate_timeout", "time_exhausted", "cancelled", "worker_failed")
# Reason codes by row state (failed also takes every M18 reason; scored/null_result take none).
FAILED_EXTRA_REASONS = ("candidate_timeout", "worker_failed")
CANCELLED_REASONS = ("cancelled", "time_exhausted")
NOT_RUN_REASONS = STOP_REASONS

# 5.2 score column target: the first row of each per-row result, never called "best".
SCORE_ROW_LABELS = {"free": "모드 1(엔진 출력 순서)", "core_fixed": "샘플 1(점수 오름차순 나열)"}

# 5.4 batch sentences, verbatim and in order. B1 always, B2 when partial, B3 when the parent row is included.
BATCH_STATEMENTS = {
    "B1": "이 일괄의 모든 행은 같은 수용체·상자·seed·방식·값으로 계산되어 점수를 같은 표에서 나란히 볼 수 있으며, "
          "표의 정렬은 표시 순서일 뿐 순위가 아니다.",
    "B2": "이 일괄은 일부만 계산되었다. 계산하지 않은 행은 점수가 없으며 0이 아니다.",
    "B3": "부모 행은 후보와 같은 설정으로 도킹한 기준 입력이며, 점수 차이를 개선이나 악화로 해석하지 않는다.",
}
