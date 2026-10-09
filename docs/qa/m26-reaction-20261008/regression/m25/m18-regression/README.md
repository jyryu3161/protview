# M18 단일 리간드 도킹(qvina) 오프스크린 수락 QA 증거

- 생성: 2026-10-09T10:28:52.488363+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "Dikedmz3G0FMeEOWwIdzo", "gitHead": "dac2755a00e0139b0ce25085a82a1ed08caf3e71", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "4c7db47848caae952fc83dc3b03001d06f0c2563e9cfc4137656949eaebf54de", "dirtyFiles": ["?? docs/qa/m26-reaction-20261008/acceptance/", "?? docs/qa/m26-reaction-20261008/regression/"], "recordedAt": "2026-10-09T10:27:36.124359+00:00", "codeRoot": "<repo>", "harnessSha256": {"docking-flow.cjs": "93ab8a165cdd0c0e82d53a5897085ba9ca8a1bfb5ebbda9d9a7af61085218473", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "a6b4a447d0898cf01009a28fbf1675bd6d68c1e2ba75f5aeba7ca452752576ba"}
- 작업 환경: docking venv-locked 있음 · qvina2 있음 · M17 venv-locked 있음 · 주 backend 도킹 capability 사용 가능 · 환경 없는 layout backend `worker_missing`
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| D-run-create | structure tab: 새 run + public_1mq4.cif; the ligand tab's docking area uses the global run (no run choice there), capability line, empty result list, start disabled | pass | docking-main:pass |
| D-imports | prolif-vina-rec.pdb and the public-derived 3D SDF chosen through the file chooser, 가져오기 → chemical_raw_input handles listed by the docking prerequisites; nothing chosen automatically | pass | docking-main:pass |
| D-ack-missing | two of three acknowledgements: 도킹 작업 시작 disabled with acknowledgement_missing | pass | docking-main:pass |
| D-mode-compat | core-fixed disabled for the SDF source (mode_source_mismatch); instance range disabled without an instance | pass | docking-main:pass |
| D-free-job | 도킹 작업 시작 → 비싼 계산 승인 → 작업 시작 → real qvina_dock_v1 done, one expensive unit, result not opened automatically | pass | docking-main:pass |
| D-free-result | summary (full score name, engine, seed 42, values, box = hand oracle, receptor/ligand SHA-256), mode table = stored rows (모드 n(엔진 출력 순서), ROUND_HALF_UP), limitations = spec §5.4 selection | pass | docking-main:pass |
| D-contacts | 접촉 보기 모드 1: contact page = stored rows (pose SDF serial, receptor seven fields, site_index, distance, geometric kind), cutoff 4.0 Å, element-pair kinds, order | pass | docking-main:pass |
| D-downloads | 모드 1 and 전체 pose SDF downloads = stored pose_sdf (events.jsonl payload) = backend bytes; mode_<n> titles, $$$$ separators | pass | docking-main:pass |
| D-report | 보고서 만들기 → 리간드 도킹 보고서 in the knowledge-tab list; Markdown/JSON downloads equal the backend | pass | docking-main:pass |
| D-instance | synthetic complex receptor: instance list (seven fields, 79 atoms, elements), instance range enabled only after choosing it; result records the removed instance, the box equals the hand oracle and the poses equal the plain-receptor poses byte for byte | pass | docking-main:pass |
| D-m17-candidates | real M17 inspection + enumeration from the candidate area (site 22, fixed replacement) → the fixture candidate ids, no second approval | pass | docking-main:pass |
| D-core-fixed | 입력 목록 다시 읽기 → M17 candidate + parent SDF, 코어 고정, conformers 5 → 샘플 n(점수 오름차순 나열) rows, core deviation, generated H/coordinates, parent serials, limitations 1–5, 7, 8 | pass | docking-main:pass |
| D-structure-kept | structure tab stays mounted (hidden) while the ligand tab is shown; same Mol* session, source and generation on return; global budget equals the backend | pass | docking-main:pass |
| D-run-switch-late | run B shows only its own list; a held run A docking-results response released after the switch is not applied | pass | docking-main:pass |
| D-reject-planar | planar SDF → job failed ligand_not_3d, 실패 with the closed reason, no result stored | pass | docking-main:pass |
| D-reject-implicit-h | implicit-H SDF → job failed ligand_hydrogens_missing, no result stored | pass | docking-main:pass |
| D-reject-box | manual side 41 Å → start disabled (box_too_large, no job request); ligand range + margin 20 → worker box_too_large, no result stored | pass | docking-main:pass |
| D-reject-receptor | receptor with water + zinc left (instance 없음) → submission refused receptor_unsupported_residue; receptor with an altloc atom → receptor_altloc_present; the on-screen refusal list shows each item's seven residue fields (nulls kept) and atom names (altloc) equal to the fixture oracle; no job, no budget, no result | pass | docking-main:pass |
| D-cancel | exhaustiveness 32 job running with a qvina2 process → 작업 취소 → cancelled, no worker/guardian/qvina2 process left, no result stored | pass | docking-main:pass |
| D-wording | no rank/best/optimum/improvement/binding-strength/affinity word on screen outside the fixed limitation sentences and the score names | pass | docking-main:pass |
| D-no-run | no run: the docking area shows only the no-run reason (no numbers, no controls) | pass | docking-unavailable:pass |
| D-unavailable | backend without the locked environments: 사용할 수 없음 with the capability reason (worker_missing), no numbers, no controls, no docking requests | pass | docking-unavailable:pass |
| D-reproducible | same receptor, ligand, box, values and seed docked again in two fresh runs: scores and all-modes pose SDF bytes equal the flow's stored free-docking result (cpu 1, seed fixed) | pass | runner:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 관찰하지 않은 사례

- D-zero-modes: qvina returns modes for every valid input used here; no input is forged to produce a zero-mode result. Covered by frontend/tests/docking.test.cjs (dockingPanelState) and the backend docking tests.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| docking-main | pass |  |
| docking-unavailable | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m18_offscreen_acceptance.py --root runs/m18-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m18-acceptance/<label> \
    --out docs/qa/m18-docking-<YYYYMMDD>/acceptance
```
