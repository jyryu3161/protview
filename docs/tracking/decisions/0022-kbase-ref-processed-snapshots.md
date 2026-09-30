# 0022. `kbase_kinase/ref`의 가공 스냅샷은 가져오기 명령으로 복사해 읽는다

- 상태: 채택 (사용자 결정 2026-09-30, M15 명세 확정 때). `docs/standards.md` 의존성 절의 kbase 문장을 좁힌다.

## 배경
M15(참조 스냅샷과 잔기 번호 대응)에는 UniProt 서열, SIFTS 잔기 대응, KLIFS 포켓 서열이 필요하다. `docs/standards.md`는 "`../kbase_kinase`의 과학 코드·데이터·결론을 가져오지 않는다"고 정해 두었다. 한편 `../kbase_kinase/ref/`에는 매니페스트에 SHA-256·바이트 수로 고정된 날짜별 스냅샷(UniProt 2026-09-15, SIFTS 2026-09-20, KLIFS 2026-09-19)이 이미 있어, 네트워크나 새 외부 목적지 없이 쓸 수 있다.

이 파일들은 원출처 원본 바이트가 아니라 kbase가 가공한 JSONL이다(원본은 kbase 매니페스트의 `raw_sha256` 해시로만 남아 있다). 범위도 kinase로 한정된다(SIFTS 약 658체인, 사람 kinase UniProt 542개). 목록에 없는 PDB는 SIFTS가 없다. 사용자는 이 한계를 들은 뒤 그대로 쓰기로 했다.

## 결정
- `../kbase_kinase/ref/`의 가공 스냅샷(UniProt `entries.jsonl`, SIFTS `residues.jsonl`·`segments.jsonl`, KLIFS `kinases.jsonl`, 대조용 `match_residues.jsonl`)은 사용자가 실행하는 가져오기 명령 `scripts/import_reference_snapshots.py`로만 로컬 참조 폴더(기본 `.deps/reference/`, Git 제외)에 복사한다. 복사 전에 kbase 매니페스트의 SHA-256·바이트·행 수와 대조하고, 하나라도 다르면 아무것도 바꾸지 않는다.
- 서버는 로컬 참조 폴더만 읽는다(`MW_REFERENCE_DIR`로 위치 변경 가능). 서버는 `../kbase_kinase`를 읽지 않는다.
- 여전히 금지: kbase 코드의 import·복사, kbase `dist/`(문헌·전례·결론) 사용, `ref/`의 다른 파일 사용. 형식을 이해하려고 kbase 소스(예: `src/domains/kinase/sources/sifts.py`)를 읽는 것은 된다. 해석 코드는 ProtView가 따로 쓴다(`backend/mw/sifts_mapping.py` 등).
- 화면·보고서·결정 기록은 이 데이터를 "kbase_kinase 가공본"(`origin: "kbase_kinase processed snapshot"`)으로 표시하고, 출처·스냅샷 ID·날짜·버전·라이선스(UniProt `CC-BY-4.0`, SIFTS `EMBL-EBI-terms`, KLIFS `none-stated`)를 그대로 보여 준다. kinase 한정 범위를 숨기지 않는다.
- `match_residues.jsonl`은 테스트·측정 대조용(`use: comparison_only`)이다. 제품 계산은 이 파일을 읽지 않는다(`PinnedSet`이 명시적 opt-in 없이는 거부).

## 검토한 대안
- 원출처(UniProt·PDBe·KLIFS)에서 직접 받기: 원본 바이트를 얻지만, 가져오기에 네트워크와 새 외부 목적지가 필요해 보안 정책을 바꿔야 한다.
- 사용자가 파일을 직접 넣기: 형식 검증기 부담이 크고, 출처·버전 기록이 사용자에게 달린다.

## 결과
- `docs/standards.md`의 kbase 문장이 "범용 실행기·훅 인프라, 그리고 이 결정의 `ref/` 가공 스냅샷(가져오기 명령으로만)"으로 좁혀졌다.
- 스냅샷 세트는 가져올 때마다 새 세트 해시를 받는다(매니페스트에 `imported_at`이 들어가므로, 같은 파일을 다시 가져와도 해시가 다르다). 이전 세트 폴더는 지우지 않는다.
- 로드맵 M27(kinase 전례·문헌, `dist/`)의 사용 범위는 이 결정으로 열리지 않는다. 그때 따로 정한다.
- 규칙 세부: `docs/business-rules.md` "잔기 번호 대응 (M15)", `docs/security.md` "참조 스냅샷", 결정 0023.
