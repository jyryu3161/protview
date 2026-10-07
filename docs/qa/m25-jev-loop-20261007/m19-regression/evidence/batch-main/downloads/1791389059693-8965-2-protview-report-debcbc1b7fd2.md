# 리간드 도킹 일괄 보고서 (ligand docking batch)

Status: complete

Batch summary: obj://run\_c81542d0d46349639b7b74837d4f9903/docking\_batch\_result/45c0b800ff595bd5288c7e1a4d35f94c7930d73eb183873386adaaba4f96af70
Batch job: job\_36abc176187c4bf8b3095f8becb3a83f, attempt attempt\_bf983459c8fc4513a22a7b762562a895
Method: qvina\_free\_v1 (자유 도킹)
Engine: qvina 2\.1\.0 (package qvina\-2\.1\.0\-h4a521e9\_8, binary SHA-256 caf5f22a3928be8adf3cb017508eaacbdcecf68ef29c5bca24fceea016c5f79c)
Preparation: Meeko 0\.8\.0, RDKit 2026\.03\.6, atom typing ad4, charges gasteiger

**이 보고서의 수치는 저장된 일괄 요약 객체의 값, 요약 행을 상태 조건으로 센 개수, 점수 행이 가리키는 후보별 도킹 결과 객체의 첫 행 점수다\. 보고서는 도킹을 다시 하지 않았다\.**

- 점수 이름: qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)
- 점수 열: 각 행 후보별 결과의 첫 행, 모드 1(엔진 출력 순서)
- 일괄 상태: complete

## 수용체

- 가져오기: obj://run\_c81542d0d46349639b7b74837d4f9903/chemical\_raw\_input/8a6929ec77067470dd56c91f9a7ec0a28726c5f4ea8ac14e5265e53198e34633
- SHA-256: 745bd4726ba956e27da5cf4da10189f2bbe937db59ff08f302bca9d2cdbc62cc
- 모델 번호: 1
- 연결 정보: pdb\_conect
- 입력 확인 세 항목: keep\_input\_protonation true, rigid\_no\_optimization true, tool\_assigned\_types\_charges true
- 뺀 리간드 인스턴스: 없음

## 후보 집합

- 후보 집합: obj://run\_c81542d0d46349639b7b74837d4f9903/ligand\_candidate\_set/df13801b18b1665ca992727d0a9db4210d83c3f85a34b5ebccc66a0f9c632473
- 부모 SDF 가져오기: obj://run\_c81542d0d46349639b7b74837d4f9903/chemical\_raw\_input/d0b3d601d00033b074659a9aba17d28f27cda5c6378acf3d37af001a2a9c76fd
- 부모 SDF SHA-256: 34a5c499e612156ab2c3ae7abedc95922cc4990363bda5275e7da6acd64c5fd9
- 부모 기준 행: 포함
- 행 수: 4; scored 4, null\_result 0, failed 0, cancelled 0, not\_run 0

## 상자 (Å)

- 출처: ligand\_range, 여백 8.00 Å
- 중심 x, y, z: 3.41, 0.72, 11.31
- 크기 x, y, z: 22.32, 27.51, 27.60
- 좌표계: 리간드 좌표가 수용체와 같은 좌표계라고 가정했다(도구가 검증하지 못한다).

## 값

- seed: 42
- exhaustiveness: 1
- num\_modes: 3
- energy\_range: 3.0 kcal/mol
- cpu: 1

## 행 (일괄 행 순서)

| 행 | 후보 id | 상태 | qvina 점수(kcal/mol) | 점수 대상 | 이유 | 후보별 결과 |
| ---: | --- | --- | ---: | --- | --- | --- |
| 0 | 부모(기준 입력) | scored | -12.9 | 모드 1(엔진 출력 순서) |  | obj://run\_c81542d0d46349639b7b74837d4f9903/docking\_result/e5025fea9dd8fc08113ecf88da2fd65d99491f95f32cebd8f4d6ebd216b1d27e |
| 1 | c\_1afb7cd3e603456c | scored | -9.6 | 모드 1(엔진 출력 순서) |  | obj://run\_c81542d0d46349639b7b74837d4f9903/docking\_result/f1112d3be22fb95e81095a4f8401d47b37889dd3174eaab31c658c0348471c10 |
| 2 | c\_2c7a25e0cc0ad3f2 | scored | -11.8 | 모드 1(엔진 출력 순서) |  | obj://run\_c81542d0d46349639b7b74837d4f9903/docking\_result/0ff940d8e659fd46d270f612f0269a3b45d8250a040e7b642ee97dca1b66d986 |
| 3 | c\_21d6c6f0d07e3759 | scored | -11.6 | 모드 1(엔진 출력 순서) |  | obj://run\_c81542d0d46349639b7b74837d4f9903/docking\_result/f695c19811c202f340fcf091ed72deca2a612a78c38ea2c2f4b237a4df5bd5f9 |

## Limitations

이 일괄의 모든 행은 같은 수용체·상자·seed·방식·값으로 계산되어 점수를 같은 표에서 나란히 볼 수 있으며, 표의 정렬은 표시 순서일 뿐 순위가 아니다.

부모 행은 후보와 같은 설정으로 도킹한 기준 입력이며, 점수 차이를 개선이나 악화로 해석하지 않는다.

점수는 qvina 2.1(Vina 계열 스코어링 함수)이 낸 값(kcal/mol)이며 결합 친화도·결합 자유 에너지가 아니다.

같은 수용체·상자·seed·방식(자유/코어 고정)·값에서 나온 점수끼리만 나란히 볼 수 있다.

수용체는 입력 그대로의 강체이며 수소·양성자화·토토머를 바꾸지 않았고, AutoDock4 원자 유형·부분 전하는 Meeko가 정한 값이다.

리간드 고리 형태는 입력 형태(후보는 RDKit이 만든 형태)로 고정되어 탐색하지 않았다.

접촉은 거리만으로 센 기하 접촉이며 수소결합 등 상호작용 판정이 아니다.

포즈는 엔진이 낸 배치이며 실험으로 확인한 결합 자세가 아니다.

후보의 3D 좌표와 수소는 RDKit이 만든 것이며 입력 구조가 아니다.

자유 도킹은 RDKit 형태 하나를 시작점으로 썼다.

Exact values, units, field paths and row conditions are in the JSON download (38 claims). Per-row results open in the ligand tab docking reads; this report makes no per-row docking report.
