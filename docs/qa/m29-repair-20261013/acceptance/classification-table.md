# M29 구조 분류 표 (명세 §10.1)

독립 분류 = `scripts/m29_oracle.py`(입력 파일과 설치된 Amber14 템플릿만). 제품 = 사전 검사 읽기. `m21_band`는 T1 측정 표 상수(출처 열)이고 독립 계산이 아니다.

| 구조 | 물 정책 | 문서 | 독립 분류 | 제품 | 보완 뒤 중원자 | m21_band (출처) | 사슬 | 결과 |
|---|---|---|---|---|---|---|---|---|
| 1M17 | strip_all | in_scope | in_scope | in_scope | 2594 | exceeds (측정) | repair→M20→M21 cancelled_queued | pass |
| 1M17 | keep_all | in_scope | in_scope | in_scope | 2594 | exceeds (측정) | repair→M20→M21 cancelled_queued | pass |
| 1FIN | strip_all | out_of_scope(atom_limit_exceeded) | out_of_scope(atom_limit_exceeded) | out_of_scope(atom_limit_exceeded) | 8998 | — (n/a) | 거절 atom_limit_exceeded | pass |
| 1FIN | keep_all | out_of_scope(atom_limit_exceeded) | out_of_scope(atom_limit_exceeded) | out_of_scope(atom_limit_exceeded) | 8998 | — (n/a) | 거절 atom_limit_exceeded | pass |
| 1MQ4 | strip_all | in_scope | in_scope | in_scope | 2160 | near_limit (측정) | repair→M20→M21 cancelled_queued | pass |
| 1MQ4 | keep_all | in_scope | in_scope | in_scope | 2160 | near_limit (측정) | repair→M20→M21 cancelled_queued | pass |
| 1S9I | strip_all | out_of_scope(gap_too_long) | out_of_scope(gap_too_long) | out_of_scope(gap_too_long) | 5205 | — (n/a) | 거절 gap_too_long | pass |
| 1S9I | keep_all | out_of_scope(gap_too_long) | out_of_scope(gap_too_long) | out_of_scope(gap_too_long) | 5205 | — (n/a) | 거절 gap_too_long | pass |
| 1A30 | strip_all | in_scope | in_scope | in_scope | 1542 | completes (측정) | repair→M20→M21 done | pass |
| 1A30 | keep_all | in_scope | in_scope | in_scope | 1542 | completes (측정) | repair→M20→M21 done | pass |
| 1A4I | strip_all | in_scope | in_scope | in_scope | 4476 | exceeds (측정) | repair→M20→M21 cancelled_queued | pass |
| 1A4I | keep_all | in_scope | in_scope | in_scope | 4476 | exceeds (측정) | repair→M20→M21 cancelled_queued | pass |
| 1UBQ | strip_all | out_of_scope(nothing_to_repair) | out_of_scope(nothing_to_repair) | out_of_scope(nothing_to_repair) | 602 | — (n/a) | 거절 nothing_to_repair | pass |
| 1UBQ | keep_all | out_of_scope(nothing_to_repair) | out_of_scope(nothing_to_repair) | out_of_scope(nothing_to_repair) | 602 | — (n/a) | 거절 nothing_to_repair | pass |
| 1HSG | strip_all | in_scope | in_scope | in_scope | 1516 | completes (측정) | repair→M20→M21 done | pass |
| 1HSG | keep_all | in_scope | in_scope | in_scope | 1516 | completes (측정) | repair→M20→M21 done | pass |
| 8VF6 | strip_all | in_scope | in_scope | in_scope | 4538 | exceeds (측정) | repair→M20→M21 cancelled_queued | pass |
| 8VF6 | keep_all | in_scope | in_scope | in_scope | 4538 | exceeds (측정) | repair→M20→M21 cancelled_queued | pass |
| 1RNH | strip_all | in_scope | in_scope | in_scope | 1207 | completes (규칙) | repair→M20→M21 done | pass |
| 1RNH | keep_all | in_scope | in_scope | in_scope | 1207 | completes (규칙) | repair→M20→M21 done | pass |
| 4INS | strip_all | in_scope | in_scope | in_scope | 806 | completes (규칙) | repair→M20→M21 done | pass |
| 4INS | keep_all | in_scope | in_scope | in_scope | 806 | completes (규칙) | repair→M20→M21 done | pass |
| 1AY7 | strip_all | out_of_scope(nothing_to_repair) | out_of_scope(nothing_to_repair) | out_of_scope(nothing_to_repair) | 1466 | — (n/a) | 거절 nothing_to_repair | pass |
| 1AY7 | keep_all | in_scope | in_scope | in_scope | 1466 | completes (규칙) | repair→M20→M21 done | pass |
| 1CLL | strip_all | in_scope | in_scope | in_scope | 1135 | completes (규칙) | repair→M20→M21 done | pass |
| 1CLL | keep_all | in_scope | in_scope | in_scope | 1135 | completes (규칙) | repair→M20→M21 done | pass |
