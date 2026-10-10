# 0035. M27 kinase 전례 연결은 사용자가 실행하는 네트워크 없는 가져오기 명령 하나가 로컬 `kbase_kinase` 체크아웃의 `dist/` 세 파일과 `ref/pubmed` 최신 서지 스냅샷을 바이트 그대로 별도 참조 가족에 복사하고, 서버는 그 폴더만 읽으며, 값싼 도구가 번호 대응 체인의 표적(UniProt accession)과 같은 표적의 전례만 "미검수 외부 전례"로 연결한다

- 상태: 채택 (사용자 결정 2026-10-10, M27 명세 확정 전 질문에서 모두 추천안을 골랐다(자유 입력·메모 없음). 아래 "조율 세션이 정한 것"은 사용자 선택이 아니며 최종 확인에서 이의를 받는다). 결정 0022("`ref/` 가공 스냅샷뿐, `dist/`의 데이터·결론은 가져오지 않음")를 넓혀 `dist/`의 세 파일과 `ref/pubmed` 서지 스냅샷을 별도 증거 종류 "미검수 외부 전례"로 허용한다(`docs/standards.md` kbase 문장을 고침). 참조 가족을 따로 두는 방식은 결정 0034(M26)를 따른다. 가져오기 명령은 네트워크를 쓰지 않으므로 외부 요청 규칙(결정 0005·0015·0034)은 바뀌지 않는다.

## 배경
로드맵 M27은 kinase 전례·문헌 연결 단계다(선행 M15·M19). `../kbase_kinase`의 커밋된 `dist/`에는 논문 속 화합물 변형 한 건과 그 논문이 보고한 측정 변화·인용문·논문 위치를 담은 Design Move 기록이 있다: `moves.jsonl` 891건, `moves_flagged.jsonl` 885건, 표적 참조 `references.jsonl` 555건(같은 accession에 참조가 여럿일 수 있음). 모든 레코드는 `review_status: "unreviewed"`이고 kbase가 논문에서 기계로 추출한 것이다. `ref/pubmed`의 최신 서지 스냅샷(2026-09-18, 252행)이 전례에 나오는 PMID 167개를 모두 덮는다. 결정 0022는 `dist/`의 데이터·결론 사용을 막아 두었다.

위험은 다섯 가지였다: 전례가 ProtView의 판정·순위·추천이나 효과 주장으로 읽히는 것, 없음·미포함·미해석이 0이나 "없음"으로 보이는 것, 전례가 내 구조·변이·리간드와 맞춰진 것처럼 보이는 것, 실제 kbase 문구(비공개 저장소 자료, 이용 조건 명시 없음)가 커밋 증거로 새는 것, 서버·도구가 kbase 경로나 네트워크를 쓰게 되는 것.

## 결정 (사용자, 2026-10-10)
- ① **kbase 접근은 복사본 + 가져오기 명령**이다: 사용자가 실행하는 `scripts/import_precedent_snapshots.py`가 로컬 `kbase_kinase` 체크아웃에서 `dist/moves.jsonl`·`dist/moves_flagged.jsonl`·`dist/references.jsonl`과 `ref/pubmed`의 가장 최근 날짜 서지 스냅샷 하나를 바이트 그대로 로컬 참조 폴더(`.deps/precedent_reference/`, `MW_PRECEDENT_REFERENCE_DIR`, 포인터 `precedent_active@1`)에 복사한다. 명령은 네트워크를 쓰지 않는다(로컬 파일과 읽기 전용 `git -C`만). 서버는 그 폴더만 읽고 kbase 경로를 모른다. M15·M26 가족과 폴더·포인터·모듈·캐시가 모두 따로다.
- ② **연결 기준은 같은 표적만**이다: 번호 대응 체인의 accession과 `target.uniprot`이 같은 전례만 연결한다. 다른 키나아제 전례를 "가설"로 보이는 것(같은 KLIFS 위치·같은 anchor·같은 계열 전이), 구조에서 부위·하위 포켓·DFG 상태 같은 서술자를 계산해 거르는 것은 하지 않는다.
- ③ **인용 검증은 무결성 + kbase 기계 검사 표시**다: "ProtView 무결성 확인"은 가져온 파일 해시, 레코드 해시, 인용 길이(25단어), 논문 쪽 위치 존재뿐이고, "kbase 기계 검사"는 kbase가 만들 때 한 결과를 그대로 보인 것이다. 논문 원문과 대조하지 않으며 화면에 "원문 대조 안 함"(UP1)이 있다.
- ④ **문헌 색인을 만들지 않는다**(전례 텍스트 BM25·공개 논문 코퍼스 색인 없음).
- ⑤ **논문 서지(`ref/pubmed`)도 가져온다**(초록 없음, 라이선스 `public-domain-ncbi`).
- ⑥ **`moves_flagged`는 가져오되 기본 숨김**이다: 호출 인자 `include_flagged`(필수, 화면 기본 꺼짐)로 포함을 고른다.
- ⑦ **보고서는 요약 + 출처 목록**이다: 인용문과 보고된 측정 변화(effects) 값은 보고서에 담지 않고 화면에서만 본다.
- ⑧ **실데이터 QA용 RCSB 공개 구조 2개**(`1M17` EGFR, `1FIN` CDK2, CC0, `https://files.rcsb.org/download/<ID>.cif` HTTPS GET, 구조 수만큼)를 개발·검증 중에 받는다.
- ⑨ **범위 밖**: Mol* 뷰어 표시·저장된 보기 변경, M24·M25 JEV 전송에 전례 자료를 보내는 것, M13 분석 흐름 연동, 번호 대응 없이 accession만으로 조회, 다른 키나아제 전이 가설, M17 리간드 후보·M19 일괄 도킹 행과의 자동 연결·이동 링크(전례 891건 모두 SMILES가 없다), 새 한도 증액 경로, 비싼 계산 단위·승인.
- ⑩ **결과 저장은 표시 필드 사본 + 원본 해시**다: 레코드에서 정확히 두 경로(`source.parser` 파서 옵션, `checks.cross_parser_numbers.measurements` 숫자 교차검증 측정 목록)만 뺀 사본을 저장하고(`record_format` `kbase_record_minus_2_paths@1`), `content_hash`는 원본 전체 레코드의 해시 그대로 둔다(사본에서 다시 계산하지 않음).
- ⑪ **표적 미해석 전례**(`target.uniprot` null)는 어떤 체인에도 연결하지 않고 알린다: 세트 전체 개수(UP5), 이름별 개수 표(`unresolved_names`, 최대 100), 전례마다 해석 근거(`resolution_basis`) 표시. 이름·별칭으로 자동 연결하지 않고, 추정 근거(`name_token`·`pubmed_title`·`alias`·`notation`)로 해석된 전례도 같은 accession이면 연결하되 근거를 그대로 보인다.
- ⑫ **체인 자격은 accession 하나 + mapped 잔기 1개 이상**이다: 번호 대응에서 그 체인의 `mapped` 행 accession이 정확히 하나일 때만 `linked`이고, 없으면 `not_linked` `no_mapped_residues`, 둘 이상(융합)이면 `not_linked` `multiple_accessions`로 나열한다(mapped 비율 기준 없음).
- ⑬ **표시 충실도**: 화면 상세는 kbase 필드를 전부 보이고(처음에 보인 필드 밖의 값은 "그 밖의 kbase 필드" 접힘 블록), 방향·크기에는 산출 근거("kbase 규칙 v1 산출", `direction_basis`)를 붙이며, 파일 이름 `moves`·`moves_flagged`를 이름 그대로 부른다("통과/실패"라 부르지 않음).
- ⑭ **PDB 언급 일치 표시 없음**: `structure_ref`·`structure_links`는 kbase 기록(근거 수준 포함)으로만 보이고 이 구조와의 일치 배지를 만들지 않는다(UP4).
- ⑮ **이용 조건 문구를 보이고 커밋 증거에는 해시만** 둔다: 화면·보고서에 KT1, 실제 kbase 자료로 만든 QA 결과는 해시·ID·개수만 커밋하고 문구는 Git 제외 폴더에 둔다.
- ⑯ **kbase 버전 세 값 엄격 고정**: dist 매니페스트 `meta`의 `schema_version` `"1"`·`effect_rules_version` `"1"`·`vocab_version`(`contact_class@1+goal@1+interaction@1+site@2+tactic@1+target_aliases@2:024a47d5…cc11e`)이 상수 `KBASE_PINS`와 정확히 같을 때만 가져온다. `kb_version`은 기록만 한다.
- ⑰ **개수는 기록된 변이 표기별로 나누고 미포함을 안내**한다: 표적마다 `target.variant` 원문별 개수, 포함하지 않은 `moves_flagged` 수는 별도 정수 `excluded_flagged`와 UP2이며 포함 수 칸은 null이다(0이 아님).

## 조율 세션이 정한 것 (사용자 선택이 아님, 최종 확인에서 이의를 받는다)
- **명세 작성 때**: 같은 accession의 체인이 여럿이면 표적은 한 번만 만들고 체인 행은 각자 둔다. 측정 변화 안의 다른 표적(`target_ref`, 이름으로 적힌 off-target)은 매칭하지 않고 전례의 대표 표적만 본다. 변이 표기는 원문 그대로 보이고 구조 서열과 대조하지 않는다(UP3). 전례 정렬 키에서 측정 변화(effects)·방향·크기를 뺐다(`move_id`·`pmid`·`year`·`variant`·`file`만). 서지가 없는 PMID는 오류가 아니라 "서지 없음"이다. `quotes_within_limit`이 거짓이어도 전례를 제외하지 않고 값을 보인다(`locations_have_page`는 가져오기가 쪽 없는 위치를 거절하므로 늘 참이고 확인했다는 사실만 보인다). 호출 때 레코드 해시 불일치는 그 호출을 412 `snapshot_invalid`로 거절한다. 필터 선택지는 결과의 `facets`(그 표적에 실제 나온 용어)에서 만들고 어휘 상수는 가져오기·검증에만 쓴다. `kbase.dirty`는 기록만 한다. 결과가 정규 JSON 1 MiB를 넘으면 자르지 않고 호출 단위로 거절하며 어느 체인을 빼거나 `include_flagged`를 끄면 되는지 알려 준다.
- **착수 확인 뒤(T1, 2026-10-10)**: 회귀 동안 `.deps/precedent_reference`와 `.deps/reaction_reference`를 없는 채로 두고 옛 실행기의 환경변수는 고치지 않는다(M26과 같은 절차). 1FIN의 B·D(cyclin A)는 M15가 쓸 방법이 없어 넣으면 번호 대응 호출 전체가 422 `no_usable_method`로 실패하므로 번호 대응 체인은 A·C만 넣는다. `not_in_kbase_references`·`no_mapped_residues`·`multiple_accessions`와 실데이터에 없는 닫힌 값은 합성 fixture로만 시험한다.
- **구현 중**: 형식 검사를 명세보다 엄격하게 했다(`target.variant`는 문자열, `name_as_written`은 문자열|null, JSONL은 중복 키·BOM·빈 줄·비UTF-8을 거절, 매니페스트 `kbase_sha256` = `"sha256:" + sha256`, `verification` 개수 = 파일 행 수, `move_id` 숫자 부분이 정수로 읽히지 않으면 거절). 서지 행은 다섯 필드(`title`·`journal`·`year`·`doi`·`pmc`)가 문자열|null일 때만 서지로 쓰고 아니면 "서지 없음"이다(가져오기가 거절하지 않음). 가져오기 명령의 git 호출은 `GIT_*` 환경을 지우고 `GIT_CEILING_DIRECTORIES`·`-c core.fsmonitor=false -c protocol.allow=never`·`--untracked-files=normal`을 쓰며, 그래서 `--from`은 kbase 저장소 루트여야 한다. 보고서는 무결성 확인 값과 kbase 검사의 `pass` 개수를 ProtView가 만든 값이라 `computed`로 분류하고(명세 §7은 참조값 목록 안에 적었으나 §2의 두 채널 분리를 따름) `pass`가 아닌 검사의 이름=상태만 `reference_value`로 둔다. Stop 훅에 이름 있는 pytest 그룹 둘을 더했다(M27 백엔드 일곱 파일, `test_analysis_workflows.py` + `test_jev_loop_reports.py`).

## 이유
- 가져오기를 로컬 복사 명령 하나에 가두면 서버·도구·보고서·화면은 계속 네트워크 없이 동작하고, kbase 코드·경로는 제품에 들어오지 않는다. 바이트 그대로 복사하고 kbase 매니페스트의 SHA-256·바이트·행 수와 모든 레코드의 `content_hash`를 다시 계산해 맞을 때만 설치하므로 무엇을 가져왔는지가 해시로 고정된다.
- 같은 accession만 잇고 미해석 전례를 연결하지 않으면, 연결 판정에 ProtView의 추정이 끼지 않는다. 체인 자격을 accession 하나 + mapped ≥ 1로 두면 번호 대응이 근거 없는 체인이나 융합 체인에 전례를 붙이지 않는다.
- 포함 수와 미포함 수를 다른 필드로 두고 한쪽이 정수면 다른 쪽이 null이게 하면 "포함하지 않음"이 0으로 읽히지 않는다.
- 사본 + 원본 해시로 결과가 이벤트만으로 다시 열리고(참조 폴더 없이), 원본과의 관계를 해시로 밝힌다. 뺀 두 경로(파서 옵션, 숫자 교차검증 측정 목록)는 화면에 쓰지 않는 추출 과정 기록이며 BTK 레코드에서 정규 JSON 크기의 약 14%다(착수 확인 (b)).
- 참조 가족을 M15·M26과 나누면 두 가족의 폴더·형식·세트 해시·코드를 건드리지 않는다.

## 검토한 대안 (기각, 되돌리지 말 것)
서버가 kbase 경로를 직접 읽기, kbase MCP 서버 호출, 다른 키나아제 전이 가설, 구조에서 자동 서술자 계산, 논문 텍스트·PDF 대조, 전례 텍스트 BM25 색인과 공개 논문 코퍼스 색인, 서지 없이 PMID만 표시, `moves_flagged` 항상 함께 표시/가져오지 않음, 보고서에 인용문·측정 변화 전부 또는 화면에서 고른 것만, 이름·별칭으로 미해석 표적 자동 연결, 추정 근거 전례 제외, accession만 확인하는 체인 자격(M26 규칙)과 mapped 비율 기준, 요약 필드만 표시, PDB 일치 배지, 이용 조건 문구 생략, kbase 버전 값 느슨한 허용, 하나의 총수, 원본 레코드 전체 사본·해시만 저장, 리간드 탭 진입 링크·JEV 전송 포함.

## 외부 요청
- 가져오기 명령·서버·도구·읽기·보고서·화면·테스트·오프스크린 QA의 외부 요청은 0건이다. 가져오기 명령은 네트워크 모듈(`urllib`·`http`·`socket`·`ssl`)을 import하지 않고 호스트·URL을 받는 옵션·환경변수가 없다(소켓을 막은 자식 프로세스에서 도는지 시험이 확인).
- 개발·검증 중 예외는 ⑧의 RCSB 구조 2건뿐이었다: `1M17` 307,709 B, `1FIN` 999,052 B(2026-10-10, 각 한 번, 둘 다 200, 키·헤더 없음). 장부 `docs/qa/m27-precedents-20261010/network-ledger.txt`, 출처 기록 `backend/tests/fixtures/public_1m17.provenance.json`·`public_1fin.provenance.json`. 실제 JEV·OpenRouter 호출은 하지 않았다.

## 수용한 대가
- 호출 키 해시 파일은 하나도 바뀌지 않았다(`docking_worker.py`·`docking_constants.py`·`openmm_mutation_worker.py`·`mutation_model_constants.py`·`mutation_model_math.py`·`mutation_candidates.py`·`ligand_ga_*`·`sequence_ga_*`·`docking_batch_*`). 그래서 기존 결과의 자동 재사용은 그대로이고 골든 셋(`golden_science_m24.json`·`golden_egress_events.json`·`golden_call_keys.json`)을 다시 기록하지 않았다.
- kbase를 갱신해 dist 매니페스트의 세 버전 값이 `KBASE_PINS`와 달라지면 가져오기가 거절되고, 고치려면 사용자 결정으로 상수를 바꿔야 한다(이전 세트·결과는 그대로).
- 결과 객체는 실제 인용문을 run 이벤트에 저장하므로 사용자 run 폴더는 공유하지 않는 자료다(KT1).
- 서로 다른 accession 두 체인(예: EGFR + BTK)에 `moves_flagged`를 포함하면 1 MiB를 넘어 거절된다(합성 변형 실측 1,605,026 B, 끄면 737,133 B). 체인을 나눠 요청하거나 `include_flagged`를 끈다.

## 결과
- 착수 확인(`docs/qa/m27-precedents-20261010/preflight.md`, 기준 main `6ac3a59`): 실제 `dist/`(HEAD `77354f9`, dist 커밋 `43a935e` 2026-09-21T00:05:28+09:00, `kb_version` `kbv1:ae11f41d19e5bef9`)가 핀 세 값·파일 대조·21개 최상위 키·닫힌 값·어휘(20·12·18)·레코드 해시 재계산(891·885·555)을 모두 통과했다. 캐시 없이 해석·색인하면 약 0.32초·+105 MB라 세트 단위 색인 캐시(세트 하나, 성공만)를 두었다. 단일 표적 결과는 최악(BTK `moves_flagged` 포함)도 855,798 B로 1 MiB 안이다.
- 소스 고정 `b414728`: Stop 훅 pytest 18개 그룹 합계 6,037 passed, ruff·`test:events` 534/534·typecheck → build·`node --check` 하네스 31개·골든 셋 exit 0, 호출 키 해시 파일 변경 없음(`gate.txt`). M27 수락 `scripts/m27_offscreen_acceptance.py --stages fixture,real` 46/46, `acceptance: true`, 브라우저 비-loopback 요청 0, 가져오기 네트워크 시도 0, 두 번 설치의 파일 SHA-256 같음(`acceptance/`). 회귀: M26 fixture 단계 39/39, M25 실행기 `--regressions` 사슬 M24–M13 전부 통과(`regression-chain.txt`). 세부는 `docs/tracking/m27-acceptance.md`.
- 변경하지 않은 것: 호출 키 해시 파일 전부, M13 흐름, M15 `reference_snapshots.py`·`residue_numbering.py`·`sifts_mapping.py`·`klifs_numbering.py`와 `residue_numbering_map@1`, M16·M17·M20·M24·M25·M26 코드·형식, `viewer_scene@2`·`viewer_figure@2`, `request_science`·`request_jev`·`request_viewer`·뷰어 동의, `Run.raise_limits` 호출자(M19·M22·M23 셋).
- 규칙 전체: `docs/business-rules.md` "키나아제 전례 (M27, `link_kinase_precedents`)". API: `docs/contracts.md`. 보안: `docs/security.md`. 완료 기록: `docs/tracking/m27-acceptance.md`.

## 한계
- 전례는 kbase_kinase가 논문에서 기계로 추출한 미검수 기록이며 ProtView는 원문과 대조하지 않았다. 방향·크기는 kbase 규칙 v1의 산출값이고 논문의 결론도 ProtView의 판정도 아니다.
- `not_in_kbase_references`는 원리상 실데이터로도 도달한다: M15에는 SIFTS만으로 행을 `mapped`로 만드는 체인이 있고(`7Z87` A → `P78527`, `8H7G` A → `Q15393`) 그 accession은 kbase 참조에 없다(M15 UniProt `ok` kinase 541개는 모두 kbase 참조에 있다). 이 구조들은 저장소에 없고 요청 한도 밖이라 이번 단계에서는 합성으로만 시험했다. `no_mapped_residues`·`multiple_accessions`와 실데이터에 없는 닫힌 값(25단어 초과 인용, `direction_basis` `none`, 위치 `figure`, `structure_links.basis` `sole_candidate`, `resolution_basis` `klifs_gene_name`)도 합성으로만 시험했다.
- 그 밖의 남은 조언은 `docs/tracking/findings.md`.

## 변경하려면 사용자 결정이 필요한 것
가져오는 파일 셋(`dist/` 세 파일 + `ref/pubmed` 최신 하나), `KBASE_PINS` 세 값, 어휘 용어 목록(`SITE_TERMS` 20·`GOAL_TERMS` 12·`TACTIC_TERMS` 18), 레코드 형식 규칙과 그 닫힌 값 집합, 세트 불가 이유 둘, 파일 원천 둘, 체인 상태 둘·이유 둘, 표적 상태 셋, 입장 이유 다섯과 순서, 결과 거절 이유 둘, 필터 키 여섯·정렬 키 다섯, 사본 형식 `kbase_record_minus_2_paths@1`과 빼는 두 경로, 고정 문장 KP1–KP6·KT1·UP1–UP5, 상한(결과 1 MiB, `unresolved_names` 100, 검색어 100자, 읽기 쪽 크기 1–100, 보고서 표적당 300줄, 파일 64 MiB·100,000줄, dist 매니페스트 1 MiB, `ref/manifest.json` 64 MiB), 체인 자격 규칙, 연결 기준(같은 accession만). 읽기 쪽 크기 기본값(전례 25·결과 목록 50), 폴링 간격, git 하위 프로세스 제한 시간(60초), 세트 캐시 방식, 화면 접힘 기본은 조정 가능한 기본값이다.
