# 변이 후보 보고서 (mutation candidates)

Status: complete

Result: obj://run\_m23\_golden\_keys/mutation\_candidate\_set/84f197b36aa8b4f70e4393f978bb153c6de35819634208d52732291d0502ecb3
Structure: obj://run\_m23\_golden\_keys/prepared\_structure/5cdc93bbe8c2682757eb2773d292b85e25edd3e9b3d395b78a43f0c86aa3d9e4 (prepared\_structure, model 1)
Method: mw\.mutation\_candidates/v1

**ProtView counted the stored position and candidate rows, took the minimum of the stored ligand distances, and copied the protection check states\. UniProt accessions and KLIFS site labels are reference snapshot values \(참조 스냅샷 값, 계산 아님\) copied into the set, not ProtView calculations\. No structure was modelled and no candidate was regenerated\.**

## 요청 (입력 값, 계산 아님)

- 포켓 출처: 주지 않음
- 리간드 껍질 출처: 주지 않음
- 리간드: 주지 않음
- 허용 잔기: AW
- 금속 근접 기준: 3\.0 Å
- 이황화 Cys SG–SG 기준: 2\.5 Å
- 번호 대응: 주지 않음
- 주석: 주지 않음

## 위치와 후보 수 (ProtView 계산: 저장된 행의 개수)

- 위치 (positions): 4
- 후보 위치 (candidate): 3
- 제외 위치 (excluded): 1
- 보호 해제된 위치 (released): 0
- 후보 (candidates): 6

## 제외 사유별 위치 수

- 비표준 잔기 (non\_standard\_residue): 0
- 사용자 보호 (user\_protected): 1
- KLIFS 주요 부위 (klifs\_key\_site): 0
- 금속 근접 (metal\_contact): 0
- 이황화 Cys (disulfide\_cys): 0
- 허용 목록에 바꿀 잔기 없음 (no\_allowed\_alternative): 0

## 출처별 위치 수

- 포켓 (pocket): 0
- 리간드 껍질 (ligand\_shell): 0
- 직접 선택 (user): 4

## 리간드까지 최소 거리

- 계산하지 않음: 리간드를 주지 않아 위치별 거리가 없다.

## 보호 검사

| 검사 | 상태 | 세부 |
| --- | --- | --- |
| 사용자 보호·해제 목록 (user\_list) | 검사함 \(checked\) | 보호 목록 1, 해제 목록 0 |
| KLIFS 주요 부위 (klifs\_key\_sites) | 검사하지 않음 \(not\_checked\) | 이유: 주석을 주지 않음 (annotation\_not\_given). 보호 여부를 판정하지 않았다. |
| 금속 근접 (metal\_contact) | 검사함 \(checked\) | 기준 3\.0 Å, 금속 잔기 0 (none) |
| 이황화 Cys SG–SG (disulfide) | 검사함 \(checked\) | 기준 2\.5 Å, SG–SG 쌍 0 |
| 촉매 잔기 데이터베이스 (catalytic\_residue\_database) | 사용할 수 없음 \(not\_available\) | 이유: 구현하지 않음 (not\_implemented). 촉매 잔기를 판정하지 않았다. |

## 번호 대응 (참조 스냅샷 값, 계산 아님)

- 번호 대응: 주지 않음. 위치별 UniProt·KLIFS 번호가 없다.

## Limitations

후보는 위치와 바꿀 잔기의 조합 목록이며 구조 모델링·에너지·점수를 계산하지 않았다.

이 목록은 변이의 효과(안정성·결합·활성)를 뜻하지 않으며 순위나 추천이 아니다.

보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 기준으로만 판정했고 촉매 잔기 데이터베이스는 사용하지 않았다(없음).

거리는 준비된 구조의 저장 좌표에서 계산한 중원자 사이 최소 거리(Å)이며 결합이나 상호작용을 뜻하지 않는다.

바꿀 히스티딘의 양성자 상태와 변이 구조의 형태는 정하지 않았다.

Exact values, evidence kinds and field paths are in the JSON download (23 claims). Position and candidate rows are in the stored result.
