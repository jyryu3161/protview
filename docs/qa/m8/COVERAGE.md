# M8 실제 클릭 검증 목록

계획 86개 항목 · 통과 86 · 미완료 0.

정상 제품 클릭, 실제 모델 호출, loopback 장애 주입, provider fixture는 각 항목의 실행 방식으로 구분한다. 세부 하위 동작과 모든 증거 위치는 [coverage.json](coverage.json), 원본 SHA-256은 [archive.json](archive.json)을 따른다. 원본 실패를 통과 기록으로 바꾸지 않는다.

## Workspace

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| W01 | Initial load, empty run, no structure | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) · [inputs-fixed.jsonl](raw/inputs-fixed.jsonl) |
| W02 | New run button | PASS | [normal.jsonl](raw/normal.jsonl) |
| W03 | Saved-run selector | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) · [default-service.json](raw/default-service.json) |
| W04 | RUN and MODELS tabs | PASS | [normal.jsonl](raw/normal.jsonl) |
| W05 | Theme button both directions | PASS | [normal.jsonl](raw/normal.jsonl) |
| W06 | Keyboard navigation/Enter and scrolling | PASS | [extra.json](raw/extra.json) · [default-service.json](raw/default-service.json) · 전체 참조는 JSON |

## Inputs

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| I01 | File input PDB and mmCIF | PASS | [normal.jsonl](raw/normal.jsonl) · [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| I02 | File input malformed/empty/oversize | PASS | [inputs-fixed.jsonl](raw/inputs-fixed.jsonl) |
| I03 | Model selector each fixture model then load | PASS | [normal.jsonl](raw/normal.jsonl) · [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| I04 | Load repeatedly/same-name changed bytes | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| I05 | Altloc highest_occupancy and first | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| I06 | Water strip_all and keep_all | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| I07 | Hydrogen strip and keep | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| I08 | Prepare button/repeated prepare | PASS | [normal.jsonl](raw/normal.jsonl) · [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| I09 | Reopen pending upload, numeric model-index fallback | PASS | [model-index-reopen.jsonl](raw/model-index-reopen.jsonl) |

## Viewer

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| V01 | Cartoon, ball-and-stick, surface buttons | PASS | [normal.jsonl](raw/normal.jsonl) |
| V02 | Canvas drag/orbit and wheel | PASS | [normal.jsonl](raw/normal.jsonl) |
| V03 | New zoom-in/zoom-out/reset controls | PASS | [normal.jsonl](raw/normal.jsonl) |
| V04 | Ligand instance buttons in MODELS | PASS | [normal.jsonl](raw/normal.jsonl) |
| V05 | Contact-row click and keyboard activation | PASS | [normal.jsonl](raw/normal.jsonl) · [read-recovery.jsonl](raw/read-recovery.jsonl) |
| V06 | Clear-selection control | PASS | [normal.jsonl](raw/normal.jsonl) |
| V07 | History step click, including cache observation | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| V08 | Return to latest structure | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| V09 | Structure-read503, then retry | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| V10 | Rapid delayed A→B source switch | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| V11 | Model5/insertion/label fixture focus | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| V12 | Direct residue pick on the Mol* canvas | PASS | [canvas-pick-final.jsonl](raw/canvas-pick-final.jsonl) · [canvas-minimized-final.jsonl](raw/canvas-minimized-final.jsonl) · 전체 참조는 JSON |

## Contacts

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| C01 | Ligand dropdown each distinct instance | PASS | [normal.jsonl](raw/normal.jsonl) · [inputs-fixed.jsonl](raw/inputs-fixed.jsonl) |
| C02 | Cutoff input2.5,4,6 and invalid bounds/NaN | PASS | [normal.jsonl](raw/normal.jsonl) · [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) · 전체 참조는 JSON |
| C03 | Compute contacts | PASS | [normal.jsonl](raw/normal.jsonl) |
| C04 | Next/previous page buttons | PASS | [normal.jsonl](raw/normal.jsonl) |
| C05 | Horizontal table scroll | PASS | [normal.jsonl](raw/normal.jsonl) |
| C06 | Zero-contact result | PASS | [inputs-fixed.jsonl](raw/inputs-fixed.jsonl) |
| C07 | Row-read503 and retry | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| C08 | No ligand and missing preparation | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |

## SASA

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| S01 | Latest selected-ligand SASA button | PASS | [normal.jsonl](raw/normal.jsonl) |
| S02 | “This input's SASA” from historical contact | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| S03 | Prepared-history ligand focus then SASA | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| S04 | SASA residue row button | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) · [extra.json](raw/extra.json) |
| S05 | Zero-burial synthetic case | PASS | [inputs-fixed.jsonl](raw/inputs-fixed.jsonl) |
| S06 | SASA-result503 and retry | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |

## Reports

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| R01 | Geometry report create | PASS | [normal.jsonl](raw/normal.jsonl) |
| R02 | Geometry Markdown/JSON downloads | PASS | [normal.jsonl](raw/normal.jsonl) |
| R03 | SASA report create and both downloads | PASS | [normal.jsonl](raw/normal.jsonl) |
| R04 | Report reload/reopen | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) · [default-service.json](raw/default-service.json) |
| R05 | Geometry/SASA report failures and retries | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| R06 | Held B report response after selecting A | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |

## OpenMM

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| O01 | OpenMM preflight on1HSG | PASS | [extra.json](raw/extra.json) |
| O02 | OpenMM1UBQ exclusions disclosure | PASS | [openmm-full.jsonl](raw/openmm-full.jsonl) · [openmm-queued-cancel.jsonl](raw/openmm-queued-cancel.jsonl) · 전체 참조는 JSON |
| O03 | Each policy checkbox + submit disabled states | PASS | [openmm-full.jsonl](raw/openmm-full.jsonl) · [openmm-queued-cancel.jsonl](raw/openmm-queued-cancel.jsonl) · 전체 참조는 JSON |
| O04 | Submit and start without prior approval | PASS | [openmm-full.jsonl](raw/openmm-full.jsonl) · [openmm-queued-cancel.jsonl](raw/openmm-queued-cancel.jsonl) · 전체 참조는 JSON |
| O05 | Explicit high-cost approval then start | PASS | [openmm-full.jsonl](raw/openmm-full.jsonl) · [openmm-running-cancel.jsonl](raw/openmm-running-cancel.jsonl) |
| O06 | Actual normal completion | PASS | [openmm-full.jsonl](raw/openmm-full.jsonl) |
| O07 | Minimized coordinates / original return | PASS | [openmm-full.jsonl](raw/openmm-full.jsonl) |
| O08 | OpenMM report create and both downloads | PASS | [openmm-full.jsonl](raw/openmm-full.jsonl) |
| O09 | Job selection/reopen | PASS | [openmm-persistence.jsonl](raw/openmm-persistence.jsonl) |
| O10 | Queued cancellation | PASS | [openmm-queued-cancel.jsonl](raw/openmm-queued-cancel.jsonl) |
| O11 | Running cancellation after worker_started | PASS | [openmm-running-cancel.jsonl](raw/openmm-running-cancel.jsonl) |
| O12 | Retry a genuine failed/cancelled attempt | PASS | [openmm-retry.jsonl](raw/openmm-retry.jsonl) |
| O13 | Result503 and report503 separately, retries | PASS | [openmm-read-retry.jsonl](raw/openmm-read-retry.jsonl) |
| O14 | Late submit/start/approve/create across run switch | PASS | [openmm-late-result.jsonl](raw/openmm-late-result.jsonl) · [openmm-late-report.jsonl](raw/openmm-late-report.jsonl) · 전체 참조는 JSON |

## Budget / capability / dry-run

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| B01 | Budget topbar and detailed meter | PASS | [openmm-persistence.jsonl](raw/openmm-persistence.jsonl) |
| B02 | Capability unavailable entries | PASS | [read-recovery.jsonl](raw/read-recovery.jsonl) |
| B03 | Dry-run/offline recorded run reopen | PASS | [dry-run-feedback.jsonl](raw/dry-run-feedback.jsonl) |
| B04 | Busy/history/minimized disabled controls | PASS | [extra.json](raw/extra.json) |
| B05 | Gallery route, if retained | PASS | [gallery.json](raw/gallery.json) |

## Agent

| ID | 검증한 동작 | 판정 | 근거 |
| --- | --- | --- | --- |
| A01 | Prompt composer empty/oversize, submit button, Enter shortcut | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) · [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A02 | Local command examples across all six action kinds | PASS | [live-v2.json](raw/live-v2.json) · [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A03 | Natural-language send while local_only | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) |
| A04 | Payload preview/target catalog/scope selection | PASS | [inputs-earlier.jsonl](raw/inputs-earlier.jsonl) · [live-v1.jsonl](raw/live-v1.jsonl) · 전체 참조는 JSON |
| A05 | Explicit online enable/disable and cap display | PASS | [live-v1.jsonl](raw/live-v1.jsonl) |
| A06 | Actual live compound representation+residue prompt | PASS | [live-v1.jsonl](raw/live-v1.jsonl) |
| A07 | Actual live ligand+camera prompt | PASS | [live-v1.jsonl](raw/live-v1.jsonl) |
| A08 | Actual live clear/reset/representation prompt | PASS | [live-v2.json](raw/live-v2.json) · [live-summary.json](raw/live-summary.json) |
| A09 | Double click/same request retry | PASS | [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A10 | Stop before dispatch / during response / during application | PASS | [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A11 | Disable online during pending request | PASS | [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A12 | Switch run/model/history/minimized source before response | PASS | [agent-source-transitions.jsonl](raw/agent-source-transitions.jsonl) · [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A13 | Manual viewer action while model pending | PASS | [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A14 | Unavailable key/provider, timeout, invalid model/choice | PASS | [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A15 | Ambiguous/unlisted target, malformed plan, injection text | PASS | [agent-source-transitions.jsonl](raw/agent-source-transitions.jsonl) · [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A16 | Request cap/budget exhausted; toggle off/on | PASS | [live-v2.json](raw/live-v2.json) · [live-summary.json](raw/live-summary.json) · 전체 참조는 JSON |
| A17 | WebGL not-ready/failure or lost command ack | PASS | [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A18 | Reload intent history and stale browser session | PASS | [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A19 | Multiple browser clients/same run | PASS | [agent-adversarial-final.jsonl](raw/agent-adversarial-final.jsonl) |
| A20 | Final end-to-end user prompt demonstration | PASS | [live-summary.json](raw/live-summary.json) |
