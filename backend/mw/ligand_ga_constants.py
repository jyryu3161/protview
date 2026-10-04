"""M22 ligand GA design closed sets, parameter ranges, limits, budget constants and fixed wording
(spec .dryforge/spec.md 2, 3, 4, 6, 10).

Dependency-free on purpose (standard library only, no imports at all), like ``docking_batch_constants``, so the
server modules and the isolated GA worker can share one copy by file path. Changing any reason, stop reason, status,
origin, evaluation, state, parameter range or default, limit, budget constant or G sentence needs a user decision
(spec 10; handoff absolute condition 5).
"""
from __future__ import annotations

PROTOCOL = "qvina_ga_dock_v1"
TOOL = "qvina_ga_design"
ENGINE = "qvina"
IMPLEMENTATION = "qvina_ga_dock_v1@1"
SUMMARY_SCHEMA = "ligand_ga_result@1"
OUTPUT_KIND = "ligand_ga_result"
SELECTION_SCHEMA = "ligand_ga_selection@1"
WORKER_INPUT_SCHEMA = "ligand_ga_worker_input@1"
WORKER_OUTPUT_SCHEMA = "ligand_ga_worker_output@1"
INDIVIDUAL_EVENT = "ligand_ga_individual_published"
MODE = "free"                    # fixed: the request has no mode key (spec 2)

# 2 GA parameters ``ga``: every key required, in this order. (min, max, default); ``seed`` has no default.
# ``max_new_dockings`` min is ``population_size`` (cross rule below); ``random_fraction`` is a finite real.
GA_KEYS = ("seed", "population_size", "generations", "elite_count", "tournament_size", "neighbor_count",
           "random_fraction", "patience", "max_new_dockings", "total_s")
GA_RANGES = {
    "seed": (0, 2147483647, None),
    "population_size": (4, 24, 12),
    "generations": (1, 8, 5),
    "elite_count": (0, 4, 2),
    "tournament_size": (2, 4, 2),
    "neighbor_count": (3, 30, 10),
    "random_fraction": (0.0, 0.5, 0.2),
    "patience": (1, 8, 3),
    "max_new_dockings": (4, 100, 60),
    "total_s": (600, 14400, 7200),
}
GA_FLOAT_KEYS = ("random_fraction",)
MIN_NEW_SLOTS = 2                # population_size - elite_count >= 2

# 10 limits.
MAX_POOL = 2000                  # = M17 candidate cap
PER_CANDIDATE_S = 300            # one individual docking (= M19 PER_CANDIDATE_S)
MAX_NEW_DOCKINGS = 100
TOTAL_S_MAX = 14400
FINISH_MARGIN_S = 600            # job timeout_s >= total_s + 600
TIMEOUT_MAX_S = 15000            # = TOTAL_S_MAX + FINISH_MARGIN_S
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_SUMMARY_BYTES = 1024 * 1024
MAX_REUSE_STAGING_BYTES = 128 * 1024 * 1024
# 7 staging bound of ``ligand_ga_worker_input@1`` (queue and worker share it): the M18 staging bound for the receptor,
# parent and pool blocks plus the base64 form of at most MAX_REUSE_STAGING_BYTES of reused result bytes.
STAGED_BASE_BYTES = 48 * 1024 * 1024
MAX_STAGED_BYTES = STAGED_BASE_BYTES + 4 * -(-MAX_REUSE_STAGING_BYTES // 3)

# 6 budget: reserved_units = min(max_new_dockings, P + (G - 1) * (P - E)), reserved once, never refunded;
# needed wall = min(total_s + FINISH_MARGIN_S, reserved_units * PER_CANDIDATE_S + NEED_MARGIN_S). A raise is the M19
# ``limit_increase`` formula with these GA values.
NEED_MARGIN_S = 300
RAISE_MARGIN_S = 60
MAX_RAISE_EXPENSIVE_CALLS = 100
MAX_RAISE_WALL_CLOCK_S = 15000

# 2 admission (before any job, no budget), in this order. Step 2 is every M18/M19 admission reason unchanged.
# 1, 3, 4 are input_invalid (HTTP 422); 5 is resource_exceeded (HTTP 429, nothing charged).
ADMISSION_REASONS = ("ga_pool_too_small", "ga_reuse_too_large", "ga_limit_raise_required")
ADMISSION_ORDER = ("invalid_job_arguments", "m18_admission", "ga_pool_too_small", "ga_reuse_too_large",
                   "ga_limit_raise_required")

# 3 stop reasons (closed) and the status each one gives.
STOP_REASONS = ("generations_complete", "no_change", "pool_exhausted", "docking_limit", "time_exhausted",
                "cancelled", "worker_failed", "resource_exceeded")
STATUSES = ("complete", "partial")
STATUS_BY_STOP_REASON = {
    "generations_complete": "complete", "no_change": "complete", "pool_exhausted": "complete",
    "docking_limit": "partial", "time_exhausted": "partial", "cancelled": "partial", "worker_failed": "partial",
    "resource_exceeded": "partial",
}

# 4 individual closed sets. ``failed`` takes every M18 reason plus FAILED_EXTRA_REASONS; the others take none.
ORIGINS = ("initial", "carried", "similar", "random")
EVALUATIONS = ("reused", "docked")          # carried individuals: null
STATES = ("scored", "null_result", "failed")
FAILED_EXTRA_REASONS = ("candidate_timeout", "worker_failed")

# 3 similarity: Morgan fingerprint Tanimoto (fingerprint arithmetic, not a score or activity), 6 decimals HALF_UP.
FINGERPRINT = {"kind": "morgan", "radius": 2, "n_bits": 2048}
SIMILARITY_DECIMALS = 6

# 4 score target: the first mode of each individual's M18 result (= M19 SCORE_ROW_LABELS["free"]).
SCORE_ROW_LABEL = "모드 1(엔진 출력 순서)"

# 4 fixed sentences, verbatim and in order. G1 always, G2 when partial, G3 when any individual was reused.
STATEMENTS = {
    "G1": "GA는 후보 풀에서 어디를 도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. "
          "부모·유사 후보 연결은 작업 모듈 기록이며 서버가 다시 계산하지 않았다.",
    "G2": "이 실행은 시간·도킹 상한·취소 등으로 일부 세대만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, "
          "한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
    "G3": "재사용한 개체는 같은 수용체·상자·seed·방식·값으로 이전에 저장된 도킹 결과를 가져온 것이며, "
          "저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
}
