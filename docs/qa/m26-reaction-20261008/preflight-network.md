# M26 T1-A 착수 확인 — 실서버 형식·규모·등록 구조 측정 (2026-10-08)

T1의 (a) 실제 응답 모양, (b) 규모, (c) 실제 등록 구조를 공개 서버에 직접 요청해 측정한 기록이다. T2가 `SOURCE_FORMATS`·`ALLOWED_HOSTS`를 못 박는 근거로 쓴다. 아래 숫자는 모두 이 날 받은 응답을 로컬에서 센 값이고, 원본 응답 바이트는 저장소 밖 scratchpad에만 두었다(저장소에는 넣지 않음). 실제 응답 조각은 싣지 않고 필드 이름·형·개수와 최소한의 식별자 예만 적는다.

## 0. 요청 한도와 방법

- 한도(사용자 지정, 2026-10-08): 이 작업의 실서버 요청 100건 이하, GET/HEAD만, 허용 호스트 다섯(`www.ebi.ac.uk`, `rest.uniprot.org`, `ftp.expasy.org`, `www.rhea-db.org`, `api.rhea-db.org`), HTTPS만, 쿠키·인증 헤더·키·사용자 데이터 없음, 리다이렉트를 따르지 않음, 한 번에 150 MB 이하, RCSB mmCIF 내려받기 없음.
- 모든 요청은 scratchpad의 작은 도우미 하나(`m26_t1/net.py`, 저장소 밖)로만 보냈다. 도우미는 (1) 허용 호스트 다섯 밖·포트·사용자 정보·프래그먼트 거부, (2) HTTPS가 아니면 거부, (3) 보내기 전에 지속 카운터를 올리고 100에서 거부(실패도 셈), (4) 돌려주기 전에 `network-ledger.txt`에 한 줄(시각·`T1-A`·방법·URL·상태·응답 바이트·본문 SHA-256, 헤더·키 없음)을 덧붙임, (5) 본문은 scratchpad에만 저장, 리다이렉트 처리기를 끄고 환경 프록시를 쓰지 않음(`ProxyHandler({})`), 고정 `User-Agent: ProtView-M26-T1-preflight/1`와 `Accept-Encoding: identity`만 보냄. 요청 전 거부 경로(http 스킴, `files.rcsb.org`, POST, 포트 8443)는 요청 없이 거부됨을 먼저 확인했다.
- **결과: 요청 46건 / 한도 100건**, 장부 46줄(호스트별 `www.ebi.ac.uk` 16, `rest.uniprot.org` 20, `ftp.expasy.org` 8, `www.rhea-db.org` 2, `api.rhea-db.org` 0). 상태 200이 42건, 400이 3건(필드 이름 탐색 2건, accession 1001개 상한 확인 1건), 404가 1건(없는 accession 확인용). 받은 바이트 합 28,371,129, 가장 큰 응답 5,928,656 바이트(M-CSA `residues` 끝점). 리다이렉트 응답은 한 건도 없었다. 재시도는 하지 않았다.

## (a) 실제 응답 모양

### (a-1) M-CSA API (`https://www.ebi.ac.uk/thornton-srv/m-csa/api/`)

요청: `GET .../api/?format=json`(1건), `GET .../api/entries/?format=json&page=P&page_size=S`(쪽 크기 확인 2건 + 전체 순회 11쪽 + 안정성 재확인 1건), `GET .../api/residues/?format=json&page=1&page_size=1`(1건), `GET .../m-csa/about/`(라이선스 문구 1건).

- 루트는 끝점 셋을 알려 준다: `entries`, `residues`, `fundbe-export`.
- **쪽 나눔**: 응답은 `{count, next, previous, results}`. `count` = **1003**. `page_size`의 최대는 **100**이다 — `page_size=1003`을 보내도 오류 없이 100개만 오고, `next` URL은 요청한 `page_size=1003`을 그대로 되풀이한다(조용한 상한). 전체는 `page_size=100`으로 **11쪽**(마지막 쪽 3개, `next: null`). `mcsa_id`는 1–1005(빈 번호 있음), 쪽 순서대로 오름차순, 중복 없음.
- **안정성**: 같은 1쪽을 두 번 받았을 때 `results`가 완전히 같았고(바이트 차이는 `next` URL의 `page_size` 숫자뿐), 항목 안 잔기 순서도 100개 항목 모두 같았다.
- **항목 최상위 키**(1003개 모두 같은 키 집합): `mcsa_id`(int), `enzyme_name`(str), `is_reference_uniprot_id`(bool, 모두 true), `reference_uniprot_id`(str), `url`(str), `description`(str), `protein`(`{sequences: [{uniprot_id}]}`), `all_ecs`([str]), `residues`([...]), `reaction`(`{ec, compounds, mechanisms, is_polymeric}`).
  - `reference_uniprot_id`: 빈 값 없음. **74개 항목은 accession 여럿을 `", "`로 이은 문자열**이다(예: 값 모양 `"P00396, P68530, Q6JTG5"`). 나누면 모두 UniProt accession 형식에 맞는다.
  - `all_ecs`: 모든 항목에서 원소가 정확히 1개이고 `reaction.ec`와 같다. EC 모양은 `N.N.N.N` 963, `N.N.N.-` 29, `N.N.-.-` 7, `N.-.-.-` 4.
- **`residues[]`**(전체 5,248개, 키 집합 하나): `mcsa_id`(int, 항목과 같음), `roles_summary`(str, 124개 빈 문자열), `function_location_abv`(str, 4,730개 빈 문자열, 값 예 `main-N`·`main-C`·`ptm`·`N-term`), `main_annotation`(str, **entries 끝점에서는 5,248개 모두 빈 문자열**), `ptm`(str, 5,221개 빈 문자열, 값 예 `Llp`·`Pyr`), `roles`([...], 124개 잔기는 빈 목록), `residue_chains`([...]), `residue_sequences`([...]). null 값은 없고 비어 있으면 빈 문자열이다.
  - `roles[]`(26,499개, 키 집합 하나): `group_function`(str, 8,112개 빈 문자열), `function_type`(str, 관찰 값 `interaction`·`spectator`·`reactant`), `function`(str), `emo`(str, `EMO_000nn` 모양).
  - **`residue_chains[]`**(5,201개, 키 집합 하나): `chain_name`(str, 항상 1자), `pdb_id`(str, **항상 소문자 4자**, `[0-9][a-z0-9]{3}`), `assembly_chain_name`(str, 1–2자), `assembly`(**int 4,418개, 빈 문자열 `""` 783개**), `code`(str), `resid`(int, null 없음), `auth_resid`(**int 5,194개, null 7개**), `is_reference`(bool, **5,201개 모두 true**), `domain_name`(str), `domain_cath_id`(str).
    - 잔기 하나의 `residue_chains`는 **0개(47개 잔기) 또는 정확히 1개(5,201개 잔기)**뿐이다. 즉 실제 자료에서는 한 잔기에 PDB 행이 여럿인 경우가 없다(상동 구조 행 없음, 기준 구조 행만).
    - `chain_name`은 **저자 체인 ID**로 판단한다. 근거: 레이블 체인 ID(`label_asym_id`)는 글자만 차례로 붙는데 M-CSA `chain_name`에 숫자 `1`(1TPH), 서브유닛 이름식 `L`·`S`(1CC1), `H`·`L`(2BBK), `L`·`M`(1C17)이 있고, 87개 항목은 `A` 없이 이런 이름만 쓴다. 저장소 안 구조로는 직접 대조할 수 없었다(아래 (c)).
    - `assembly_chain_name`은 4,912행에서 `chain_name`과 같고 289행에서 다르다(같은 글자 둘 `AA` 41, 다른 글자 예 1QUM `A`→`D` 235, 접두 13). 조립체 파일의 체인 이름으로 보이며 명세대로 무시한다.
    - `resid`와 `auth_resid`는 1,612행에서 다르다. 1S9I(M-CSA 282) 행은 `resid` 140·`auth_resid` 194이고 M15 SIFTS 구간(구조 1–346 ↔ UniProt 55–400)과 맞춰 보면 `resid`는 mmCIF `label_seq_id`, `auth_resid`는 저자 번호다(3CMM도 772/781처럼 일정한 차이).
    - **`code` 어휘(전체 순회 기준, 서로 다른 값 22개)**: 표준 20종(`Ala` `Arg` `Asn` `Asp` `Cys` `Gln` `Glu` `Gly` `His` `Ile` `Leu` `Lys` `Met` `Phe` `Pro` `Ser` `Thr` `Trp` `Tyr` `Val`, 모두 첫 글자만 대문자) + **표준 20종 밖 `Sec` 3행·`X` 5행**. 대소문자는 `X`(5행)만 대문자 한 글자이고 나머지는 모두 세 글자 첫 글자 대문자다.
  - **`residue_sequences[]`**(잔기마다 정확히 1개, 5,248개, 키 집합 하나): `uniprot_id`(str, **279행은 빈 문자열**, 54개 항목), `code`(str, 표준 20종 + `Sec` 4행), `is_reference`(bool, 모두 true), **`resid`(int, null 없음)**.
    - **`resid`는 UniProt 서열 위치다.** 이 날 받은 UniProt 서열(아래 (a-2))로 4,932행을 대조하면 4,918행에서 `code`와 그 위치의 아미노산이 같고 14행만 다르다(빈 accession 279행·비활성 accession 37행 제외). 예: M-CSA 175(HIV-1 retropepsin)의 Asp25(구조 저자 번호)는 `residue_sequences.resid` 513(Gag-Pol 다단백 번호).
    - `residue_chains[0].code`와 `residue_sequences[0].code`가 다른 잔기 50개(예: 구조 `X`, 서열 `Ser`).
- **`reaction`**: `ec`(str, 빈 값 없음), `compounds[]`(4,426개, 키 `count`(int)·`type`(str, `reactant` 2,103·`product` 2,322·`cofactor` 1)·`chebi_id`(str)·`name`(str, 2개 빈 문자열)·`mol_file`(str)), `mechanisms[]`(저장 안 함), `is_polymeric`(bool).
  - `chebi_id`는 **`CHEBI:` 접두 없는 숫자 문자열**(예 `15377`)이고, 14개(11개 항목)는 ChEBI가 아닌 `X006nn` 모양이다.
  - 같은 화합물이 한 항목 안에서 두 번 나오는 경우가 있다(순서 유지 대상).
- **`residues` 끝점**(`/api/residues/`): `page`·`page_size`를 무시하고 잔기 5,248개 전체를 목록 하나로 준다(5.9 MB). 내용은 entries 끝점의 잔기와 `main_annotation`만 빼면 다중집합으로 똑같고, **`main_annotation`이 5,167개 잔기에서 채워져 있다**(entries 끝점은 전부 빈 문자열). 항목 안 잔기 순서는 1003개 중 120개 항목에서만 entries 끝점과 같다. `main_annotation`을 뺀 내용은 5,248개 모두 서로 달라 내용 일치로 짝을 지으면 모호함이 없다.
- 라이선스: about 페이지 문구 "It is distributed under a Creative Commons Attribution 4.0 International (CC BY 4.0) License", 링크 `https://creativecommons.org/licenses/by/4.0/`.

### (a-2) UniProt REST (`https://rest.uniprot.org/`)

요청: 여러 accession 한 번에 `GET /uniprotkb/accessions?accessions=<쉼표 목록>&fields=<열>&format=json`(모양 4개 1건, 합집합 1000+630개 2건, 섞은 4개 1건, 표본 326개 1건, 1001개 1건), 하나씩 `GET /uniprotkb/{acc}.json`(비활성 8건, 보조 accession 1건, 없는 것 2건, 전체 항목 1건), 필드 이름 탐색 실패 2건.

- **여러 accession 요청**: `/uniprotkb/accessions`, 한 요청 **최대 1000개**(1001개는 400, 메시지 "Only '1000' accessions are allowed in each request."). 1000개를 보내도 쪽 나눔 없이(`Link` 헤더 없음) 한 응답으로 온다. URL 길이는 accession 1000개에 약 7 KB이며 문제없었다. `X-Total-Results`는 **요청한 개수**(1000)이고 실제 `results`는 활성 항목만(998개) 온다. 결과 순서는 요청 순서와 같다. 응답 헤더 `X-UniProt-Release: 2026_03`, `X-UniProt-Release-Date: 02-September-2026`.
- **비활성·없는 accession**: 여러 개 요청에서는 비활성(삭제·분할)·보조 accession·없는 accession이 **오류 없이 결과에서 빠질 뿐**이다(대표 accession으로 바꿔 주지도 않음). 이유를 알려면 accession마다 `GET /uniprotkb/{acc}.json`이 필요하다.
  - 삭제: 200, `{"entryType":"Inactive","primaryAccession":…,"uniProtkbId":…,"inactiveReason":{"inactiveReasonType":"DELETED","deletedReason":<문자열>},…}`(4건, `deletedReason` 값은 모두 "Not part of a reference proteome").
  - **분할**: 200, `inactiveReason: {"inactiveReasonType":"DEMERGED","mergeDemergeTo":[accession 1–3개]}`(4건 + 보조 accession 시험 1건 — 보조 accession P02023도 `DEMERGED`로 대표 accession 3개를 돌려줌).
  - 없음: **404**, `{"url":…,"messages":["Resource not found"]}`(형식만 맞춘 `Z9ZZZ9ZZZ9`). 형식만 맞춘 `Q0ZZZ9`는 실제로 있었다가 삭제된 accession이라 `DELETED`였다.
  - `MERGED`(합쳐짐, 대표 accession 하나) 응답은 이번 측정에서 **관찰하지 못했다**(보조 accession 열 이름을 찾는 요청 2건은 400이었고 더 찾지 않았다).
- **필드(`fields=`) 이름**(400 없이 받아들여짐): `accession`, `id`, `protein_name`, `organism_name`, `length`, `ec`, `ft_act_site`, `ft_binding`, `ft_site`, `cc_catalytic_activity`, `sequence`. (`sec_acc`는 400.)
- **JSON 모양**(표본 326개 요청 중 활성 325개 + 모양 확인 4개):
  - 최상위: `entryType`(`UniProtKB reviewed (Swiss-Prot)` 312 / `UniProtKB unreviewed (TrEMBL)` 13), `primaryAccession`, `uniProtkbId`(예 `MP2K2_HUMAN`), `organism`(`scientificName`, `taxonId`, `lineage`, 선택 `commonName`·`synonyms`·`evidences`), `proteinDescription`, `sequence`(`fields`에 `sequence`가 없으면 `{length}`만), `features`, `comments`(촉매 활동이 없으면 키 없음, 4/325), `extraAttributes`.
  - 단백질 이름: `proteinDescription.recommendedName.fullName.value`. **TrEMBL 등 10/325는 `recommendedName`이 없고 `submissionNames[0].fullName.value`뿐**이다.
  - **EC 번호 위치가 여러 곳**: `proteinDescription`의 `recommendedName.ecNumbers[]`(311), `alternativeNames[].ecNumbers[]`(29), `includes[].recommendedName.ecNumbers[]`(14), `contains[].recommendedName.ecNumbers[]`(8), `submissionNames[].ecNumbers[]`(3), 원소는 `{value, evidences?}`. 값 모양 `N.N.N.N` 347, `N.N.N.-` 13, `N.N.-.-` 3, `N.-.-.-` 1, `N.N.N.nN`(잠정 번호) 1.
  - **부위**(`features[]`, 요청한 셋만 옴: `Binding site` 1,578, `Active site` 325, `Site` 112): 키 `type`, `location{start{value, modifier}, end{value, modifier}}`, `description`(str, Binding site는 1,526/1,578이 빈 문자열, Active site는 60/325가 빈 문자열), 선택 `evidences`·`featureCrossReferences`·`ligand`·`ligandPart`. 표본 2,015개 모두 `modifier: "EXACT"`이고 `value`는 int였다(`UNKNOWN`·`OUTSIDE`·`UNSURE` 등은 관찰하지 못함). `ligand`는 `{name, id?, label?, note?}`이고 `id`는 **`ChEBI:CHEBI:<n>`** 모양, 160개는 `id` 없이 `name`만(예 `substrate`). `ligandPart` 12개.
  - **촉매 활동**(`comments[]`, `commentType: "CATALYTIC ACTIVITY"`, 644개): `reaction{name, ecNumber?, reactionCrossReferences?, evidences?}`, 선택 `physiologicalReactions[]`(268개, 원소 `{directionType: left-to-right|right-to-left, reactionCrossReference{database:"Rhea", id}, evidences}`), 선택 `molecule`(5개, 동형 단백질 한정 표시). **`ecNumber` 없는 활동 180/644.** `reactionCrossReferences`의 `database`는 `Rhea`·`ChEBI` 둘이고, **Rhea 쪽 ID는 반응 `RHEA:<n>`(592)과 고분자 화합물 `RHEA-COMP:<n>`(527)이 섞여 있다.** ChEBI 쪽은 `CHEBI:<n>`. 반응 하나에 `RHEA:` ID는 0개(52) 또는 1개(592).
  - `reactionCrossReferences`의 `RHEA:` ID 592개는 모두 Rhea **방향 없는(대표) 반응** ID였고, `physiologicalReactions`의 269개는 모두 **방향 있는** 반응 ID였다(아래 (a-3) 파일로 대조).
- 라이선스: UniProt 라이선스 페이지(`www.uniprot.org/help/license`)는 허용 호스트 밖이라 요청하지 않았다(측정하지 않음, CC BY 4.0은 인계 문서의 기존 확인 값).

### (a-3) Rhea (`www.rhea-db.org`, `ftp.expasy.org`)

요청: `ftp.expasy.org/databases/rhea/` 목록·`LICENSE.txt`·`rhea-release.properties`·`tsv/` 목록·`tsv/README.txt`·`txt/` 목록·`txt/README.txt`·`txt/rhea-reactions.txt.gz`(8건), `www.rhea-db.org/rhea?...&format=tsv`(2건). `api.rhea-db.org`는 필요 없어 요청하지 않았다.

- 배포판: `rhea-release.properties` = 릴리스 **142**, 날짜 **2026-09-02**.
- **경로 1 — Rhea REST(권장, 요청 1건)**: `GET https://www.rhea-db.org/rhea?query=&columns=rhea-id,equation,chebi,chebi-id,ec&format=tsv&limit=20000` → 200, `text/plain; charset=UTF-8`, 5,104,978 바이트, 리다이렉트 없음, 쪽 나눔 없음, 전체 개수 헤더 없음.
  - 머리줄 열 이름(정확히): `Reaction identifier`, `Equation`, `ChEBI name`, `ChEBI identifier`, `EC number`. 행 **18,611개**, 모든 행이 5열, ID는 `RHEA:<n>`이고 정수 오름차순·중복 없음.
  - `ChEBI identifier`와 `ChEBI name`은 `;`로 이은 목록이고 모든 행에서 개수가 같다(위치로 짝지음), 한 행 안 ChEBI ID 중복 없음, 빈 ChEBI 목록 없음. `ChEBI name`은 반응식 속 표기가 아니라 ChEBI 이름이다(예: 반응식 `H2O`, 이름 `water`).
  - `EC number`는 `EC:` 접두 + `;` 구분, **10,965행은 빈 칸**, 값 모양 `EC:N.N.N.N` 7,901·`EC:N.N.N.nN` 40.
  - 쿼리가 비면 방향 없는(대표) 반응만 온다. `limit`를 실제 개수보다 작게 주면 조용히 잘릴 수 있으므로 가져오기는 "받은 행 수 < limit"를 검사해야 한다(전체 개수 헤더가 없음).
- **경로 2 — FTP(`ftp.expasy.org/databases/rhea/`)**: 최상위 `biopax/ ctfiles/ eb-eye/ kegg/ nlp/ old_releases/ rdf/ tsv/ txt/ LICENSE.txt rhea-release.properties rhea_news.html`.
  - `tsv/`(README 기준): `rhea2<db>.tsv`(열 `RHEA_ID`, `DIRECTION`(UN·LR·RL·BI), `MASTER_ID`, `ID`), `rhea2xrefs.tsv`(+`DB`), `chebiId_name.tsv`(576K), `rhea-directions.tsv`(436K), `rhea-ec-iubmb.tsv`, `rhea2ec.tsv`(190K), `rhea-obsoletes.tsv`, `rhea-relationships.tsv`, SMILES 두 파일(실험적), `rhea2uniprot*.tsv`, `rhea-tsv.tar.gz`(4.1M, trembl 제외 묶음). **반응식 텍스트를 담은 TSV는 없다.**
  - `txt/rhea-reactions.txt.gz`(1,556,033 바이트, 풀면 16.5 MB, KEGG REACTION 형식): 레코드 74,444개(`ENTRY RHEA:<n>`, `DEFINITION` 이름 반응식, `EQUATION` ChEBI 반응식(계수 `2 CHEBI:…`, 고분자 `CHEBI:a,CHEBI:b`), `ENZYME` EC(공백 구분, 여러 줄 가능, 대표 반응 7,646개에만)). 대표(`=`) 18,611 + 방향 있는(`=>` 37,222, `<=>` 18,611). README는 이 형식을 "only provided for backwards-compatibility … We strongly recommend to use one of the other data formats"라고 적는다. 참여자 이름은 `tsv/chebiId_name.tsv`가 따로 필요하다.
  - **두 경로 대조**: REST의 18,611개 ID = FTP 대표 반응 18,611개, `Equation` = `DEFINITION`(18,611/18,611), EC 집합 = `ENZYME`(18,611/18,611), ChEBI 집합 = `EQUATION`의 ChEBI 집합(18,611/18,611).
- 라이선스(`LICENSE.txt`): CC BY 4.0(`https://creativecommons.org/licenses/by/4.0/`)을 Rhea의 저작권 대상 전체에 적용하며 FTP 파일은 저작권 문구를 함께 둘 때 자유롭게 재배포 가능, 정확성 보증 없음·의료 용도 아님(DISCLAIMER).

## (b) 규모

- **M-CSA**(전체 쪽 순회 1회, 11쪽 = 11요청 + 쪽 크기 탐색): 항목 **1,003**, 잔기 5,248, `residue_chains` 행 5,201, 서로 다른 PDB **1,002**(항목당 PDB 0개 5·1개 988·2개 10, 한 PDB가 여러 항목에 나오는 것 5개: 3CMM·2ZR8·1QI9(3개 항목)·1A4I·3WQL).
- **accession 수**(명세 §4.2의 합집합):
  - 원문 문자열 그대로면 `reference_uniprot_id` 996종 ∪ `residue_sequences.uniprot_id` 989종 = 1,111종인데, 그중 쉼표로 이은 문자열 74개와 빈 문자열 1종은 accession이 아니다.
  - `", "`로 나누고 빈 문자열을 빼면 `reference_uniprot_id` 1,084 ∪ `residue_sequences` 988 = **1,094**(서열 쪽에만 있는 것 10, 기준 쪽에만 있는 것 106). 모두 UniProt accession 형식에 맞는다(6자 1,089·10자 5).
  - M15 활성 세트(`.deps/reference/active.json` → `sets/aa21ead9…3317/files/uniprot/2026-09-15/entries.jsonl`, 542행, 로컬 읽기만): `status: "ok"` **541**(`lookup_failed` 1개 제외). M-CSA와 겹침 5개(P06213·P35557·P36507·P41743·P78356).
  - **합집합 1,630** — `MAX_ACCESSIONS` 20,000 안이다.
  - 이 날 UniProt에서 활성인 것 1,622, **받지 못하는 것 8개**(모두 M-CSA에서 나온 파생 accession, kinase 쪽은 0): 삭제(`DELETED`) 4, 분할(`DEMERGED`) 4. `MAX_SKIPPED` 50 안이다.
- **실제 가져오기 예상 요청 수**(전체 1회): M-CSA 11(`page_size=100`) [+ `residues` 끝점 1, `main_annotation`을 채우기로 정하면] + UniProt 2(1000개씩) + 빠진 accession 분류 8(하나씩) + Rhea 1(REST) = **22건**(또는 23건). FTP 경로를 쓰면 Rhea는 2건(`rhea-reactions.txt.gz` + `chebiId_name.tsv`). 받는 원본은 합쳐 약 24 MB(M-CSA 11.2 MB + UniProt 부위·촉매 활동 열 약 7.4 MB(표본 326개 1.48 MB에서 외삽) + Rhea 5.1 MB, `residues` 끝점을 더하면 +5.9 MB)이고 한 응답은 최대 약 1.7 MB(M-CSA 한 쪽)·5.1 MB(Rhea)다.
- **가공 파일 크기 추정**(명세 §3.3 허용 필드만, 정규 JSON 한 줄씩, scratchpad에서 실제 응답으로 만들어 셈, 저장소에 두지 않음): `mcsa/entries.jsonl` 1,003행 약 **5.4 MB**(5,419,317 B), `uniprot_function/entries.jsonl` 약 1,622행 약 **2.3 MB**(표본 325행 평균 1,420 B로 외삽), `rhea/reactions.jsonl` 18,611행 약 **8.3 MB**(8,297,875 B). 합 약 16 MB.
- 측정 중 요청은 46건으로 한도 안에서 끝났고, 외삽한 것은 UniProt 가공 크기(표본 1/5)뿐이다.

## (c) 실제 등록 구조

- **저장소 안 구조의 PDB ID**(파일 머리 로컬 확인): `public_1hsg.cif` = `_entry.id 1HSG`(사슬 잔기 A 99·B 99), `public_1mq4.cif` = `1MQ4`(A 261), `public_1ubq.cif` = `1UBQ`(A 76), `derived_1hsg_first10_fixture.cif` = 데이터 블록 `1HSG_DERIVED_FIRST10`, **`_entry.id` 없음**(A 1–10만).
- **M-CSA `residue_chains`에 있는가**: 1HSG **없음**, 1MQ4 **없음**, 1UBQ **없음**, 파생 1HSG도 없음(PDB ID 자체가 파일에 없음). → 저장소 안 구조는 모두 `pdb_not_in_snapshot`이 된다. **저장소 안에는 실제 `matched` 사례를 만드는 구조가 없다.**
  - 참고(정보용, 명세상 연결하지 않음): HIV-1 프로테아제 M-CSA 항목은 175(PDB **1A30**, UniProt P04585)이고 행은 A/B 체인의 Asp25·Thr26·Gly27 여섯 개다. gemmi로 1HSG의 같은 저자 체인·저자 번호를 보면 여섯 모두 같은 잔기 이름(ASP·THR·GLY, 삽입 코드 없음, `label_seq`도 같은 번호)이 있다. 그러나 명세 범위 밖(서열로 다른 PDB에 잇기)이므로 1HSG는 `pdb_not_in_snapshot`이다. 파생 1HSG(1–10)에는 이 번호가 없다.
  - 1MQ4(Aurora A, O14965)는 M-CSA에 없지만 UniProt 부위는 있다: Active site 256 "Proton acceptor", Binding site 143·162 등(ATP). gemmi로 1MQ4 A의 저자 번호 256 = ASP(`label_seq` 137), 143 = LYS, 162 = LYS. M15 SIFTS 구간(구조 6–272 ↔ O14965 125–391)과도 맞는다. → **1MQ4 + M15 번호 대응으로 UniProt 부위 연결(`linked_via: numbering_map`)을 저장소 안 구조로 실제 시험할 수 있다**(M-CSA 절은 `pdb_not_in_snapshot`).
  - 1UBQ는 M-CSA에 없다(유비퀴틴 관련 M-CSA 항목은 3CMM·1C4Z·1UCH·1NBF·2BX4 등 다른 PDB). 빈 결과·`pdb_not_in_snapshot` 사례로 쓸 수 있다.
- **M15 SIFTS ∩ M-CSA**: M15 SIFTS 세그먼트의 PDB 537개(`segments.jsonl`, 상태 ok 511) 중 M-CSA PDB와 겹치는 것은 **1S9I 하나**다(M-CSA 282, 효소 이름 "mitogen-activated protein kinase kinase", UniProt P36507, EC 2.7.12.2, 체인 A의 Asp194(`resid` 140)·Asp221(`resid` 167)). M15 SIFTS: 1S9I A ok, P36507 55–400 ↔ 구조 1–346. M15 UniProt 가공본에 P36507이 있다(kinase 세트). UniProt P36507 부위: Active site 194 "Proton acceptor", Binding site 78–86·101(ATP), Site 1개. → **1S9I 하나로 M-CSA `matched`(예상) + M15 번호 대응을 통한 UniProt 부위 연결 + 반응 절(UniProt 촉매 활동의 Rhea ID)을 함께 시험할 수 있다.** `../kbase_kinase`는 읽지 않았다(M15 세트에 SIFTS가 있었음).
  - 그 밖에 M-CSA accession이 M15 kinase 세트에 있는 항목(번호 대응을 서열 정렬로 만들 수 있는 후보): 1IR3(P06213), 3IDH(P35557), 1BO1(P78356), 1ZRZ(P41743). 이들은 M15 SIFTS에는 없다.
- **수락 QA 구조 제안**(내려받지 않음, 허용된 RCSB mmCIF 최대 3개 안에서, 우선순위 순):
  1. **1S9I**(MEK2) — 필수 후보. M-CSA 등록(체인 A 두 행) + M15 SIFTS·UniProt 세트에 있음 → `matched` 행·역할 원문·반응 절과 UniProt Active site 194의 번호 대응 연결을 한 구조로 보인다.
  2. **1A30**(HIV-1 프로테아제, M-CSA 175) — 두 체인 A·B 모두 `covered`인 사례(이량체가 공유하는 촉매 부위, 6행). 저장소의 1HSG와 같은 단백질이라 "PDB가 다르면 잇지 않음"(1HSG `pdb_not_in_snapshot`)과 나란히 보일 수 있다. UniProt P04585 Active site 513은 번호 대응이 없으므로 `linked_via: null`·`numbering_map_not_given` 사례가 된다.
  3. **1A4I**(MTHFD1 탈수소효소/고리화효소, P11586, M-CSA 389·458) — 한 체인(A)에 M-CSA 항목 둘이 함께 나오는 사례("하나를 고르지 않고 모두 보임"). 대안은 2ZR8(세린 라세미화효소, 항목 330·956).
  - 충돌·대응 없음 행은 계획대로 합성 파생 구조(한 잔기 이름 바꿈)로 만든다. 실제 자료에서 `non_standard_code`(`X`·`Sec`, 예 1PYA·1CC1)와 `no_author_number`(7행, 예 1JDI)가 있으나 구조를 더 받지 않는 한 합성으로 시험한다.

## SOURCE_FORMATS / ALLOWED_HOSTS 제안 (명세 §3.3·§4.3, 사용자 결정 필요 항목은 "결정 필요")

### ALLOWED_HOSTS

`("www.ebi.ac.uk", "rest.uniprot.org", "www.rhea-db.org")` — 세 개. Rhea는 REST 한 요청으로 반응식·ChEBI 참여자·이름·EC가 모두 오고 FTP 대표 반응과 내용이 같다. `ftp.expasy.org`는 REST가 막힐 때의 대안(이 경우 `www.rhea-db.org` 대신 `ftp.expasy.org`, 파일 둘)이며, `api.rhea-db.org`는 필요 없다. 허용 목록 밖 호스트는 필요 없다.

### 요청 URL (가져오기 명령)

- M-CSA: `https://www.ebi.ac.uk/thornton-srv/m-csa/api/entries/?format=json&page={1..N}&page_size=100` — `next`를 따르지 말고 `count`로 쪽 수를 계산해 순회, 모든 쪽의 `count`가 같고 받은 항목 수 = `count`·`mcsa_id` 중복 없음을 검사. (`main_annotation`을 채우기로 정하면 `https://www.ebi.ac.uk/thornton-srv/m-csa/api/residues/?format=json` 1건 추가 — 결정 필요 2.)
- UniProt: `https://rest.uniprot.org/uniprotkb/accessions?accessions=<≤1000개>&fields=accession,id,protein_name,organism_name,length,ec,ft_act_site,ft_binding,ft_site,cc_catalytic_activity&format=json`, 결과에 없는 accession마다 `https://rest.uniprot.org/uniprotkb/{acc}.json?fields=accession`(200 `entryType: "Inactive"` → `inactiveReason`로 분류, 404 → 없음).
- Rhea: `https://www.rhea-db.org/rhea?query=&columns=rhea-id,equation,chebi,chebi-id,ec&format=tsv&limit=<L>`(받은 행 수 < L 검사, 머리줄 다섯 열 정확 일치 검사).

### `mcsa/entries.jsonl` (항목 하나당 한 행, `mcsa_id` 오름차순)

`{mcsa_id: int, enzyme_name: str, reference_uniprot_id: str(원문, ", "로 이은 여러 accession 가능), all_ecs: [str], reaction: {ec: str, compounds: [{type: str, chebi_id: str(숫자 문자열 또는 비ChEBI 원문), name: str}]}, residues: [{roles_summary: str, function_location_abv: str, main_annotation: str, ptm: str, roles: [{group_function: str, function_type: str, function: str, emo: str}], residue_chains: [{pdb_id: str(소문자 4자), chain_name: str(저자 체인), assembly_chain_name: str, assembly: int|"", code: str, resid: int|null, auth_resid: int|null, is_reference: bool}], residue_sequences: [{uniprot_id: str(빈 문자열 가능), code: str, is_reference: bool}]}]}`

- 명세와 같은 키 집합이다. 바뀐 것은 값 형(`assembly`가 int 또는 `""`, `uniprot_id`가 빈 문자열 가능, `reference_uniprot_id`가 여러 accession을 담을 수 있음)뿐이다. 역할 문구는 null이 아니라 빈 문자열로 온다(원문 그대로 빈 문자열 보존 권장).
- 버리는 필드: `is_reference_uniprot_id`, `url`, `description`, `protein`, `reaction.mechanisms`, `reaction.is_polymeric`, `compounds[].count`·`mol_file`, `residues[].mcsa_id`, `residue_chains[].domain_name`·`domain_cath_id`, `residue_sequences[].resid`(결정 필요 1).
- accession 합집합(§4.2)과 `accession_differs_from_mcsa`(§5.4)는 `reference_uniprot_id`를 `","`로 나눠 앞뒤 공백을 지운 accession들과 비지 않은 `residue_sequences[].uniprot_id`로 계산해야 한다(결정 필요 3).

### `uniprot_function/entries.jsonl` (accession 하나당 한 행, accession 오름차순)

`{accession: str, entry_name: str, protein_name: str|null, organism: str, sequence_length: int, ec_numbers: [str], catalytic_activities: [{reaction_name: str, ec_number: str|null, rhea_ids: [str], chebi_ids: [str]}], features: [{type: "Active site"|"Binding site"|"Site", start: int, end: int, description: str, ligand_name: str|null, ligand_id: str|null}]}`

- 대응: `accession` ← `primaryAccession`, `entry_name` ← `uniProtkbId`, `protein_name` ← `proteinDescription.recommendedName.fullName.value`, 없으면 `submissionNames[0].fullName.value`(결정 필요 5), `organism` ← `organism.scientificName`, `sequence_length` ← `sequence.length`, `ec_numbers` ← `proteinDescription` 안 모든 `ecNumbers[].value`(recommendedName·alternativeNames·includes·contains·submissionNames, 결정 필요 5), `reaction_name` ← `reaction.name`, `ec_number` ← `reaction.ecNumber`(없으면 null), `rhea_ids` ← `reactionCrossReferences` 중 `database == "Rhea"`이고 `^RHEA:[0-9]+$`인 ID만(`RHEA-COMP:`는 버림, `physiologicalReactions`의 방향 ID는 넣지 않음), `chebi_ids` ← `database == "ChEBI"` ID(`CHEBI:<n>`), 부위 `start`/`end` ← `location.start.value`/`location.end.value`, `ligand_name`/`ligand_id` ← `ligand.name`/`ligand.id`(`ChEBI:CHEBI:<n>` 원문).
- 형식 검사: `location.*.modifier`가 `EXACT`가 아니거나 `value`가 int가 아닌 부위는 이번 측정에서 없었다. 나타나면 어떻게 할지(가져오기 중단 / 그 accession 건너뜀)는 결정 필요 6.
- 버리는 필드: `entryType`, `extraAttributes`, `organism`의 나머지, `evidences`, `featureCrossReferences`, `ligand.label`·`note`, `ligandPart`, `physiologicalReactions`, `molecule`.

### `rhea/reactions.jsonl` (반응 하나당 한 행, `rhea_id` 정수 부분 오름차순)

`{rhea_id: str("RHEA:<n>"), equation: str, ec_numbers: [str]("EC:" 접두를 뗀 값), participants: [{chebi_id: str("CHEBI:<n>"), name: str}]}`

- REST TSV 열 대응: `rhea_id` ← `Reaction identifier`, `equation` ← `Equation`, `ec_numbers` ← `EC number`를 `;`로 나눠 `EC:` 접두 제거(빈 칸이면 `[]`), `participants` ← `ChEBI identifier`와 `ChEBI name`을 `;`로 나눠 위치로 짝(개수가 다르면 형식 오류). `name`은 ChEBI 이름이다.
- 범위: 방향 없는 대표 반응 18,611개(결정 필요 7). UniProt 촉매 활동이 가리키는 Rhea ID는 모두 대표 반응이었다.

## 명세와 다른 점

명세 §3.3·§4.2–§4.4·§5.3·§5.4·§11.2와 인계 문서의 가정에 비해 실제 자료가 다른 곳이다. "결정 필요"는 닫힌 집합·필드 목록이 바뀌므로 사용자 결정이 있어야 한다.

1. **`residue_sequences[].resid`가 있다(결정 필요 1).** 인계 문서는 "UniProt 위치 필드 없음"이라 했으나 실제로 int `resid`가 있고 UniProt 서열 위치다(4,918/4,932 일치). 명세 §3.3 허용 필드에는 없다. 그대로 버릴지, 참조값으로 저장할지(저장해도 구조 연결에는 쓰지 않음) 정해야 한다.
2. **entries 끝점의 `main_annotation`은 항상 빈 문자열이다(결정 필요 2).** 같은 문구는 `residues` 끝점에만 있다(5,167/5,248). 명세대로 entries만 받으면 이 칸은 늘 빈 문자열이다. `residues` 끝점을 1건 더 받아 내용 일치로 채우는 방안(현재 자료에서 짝 모호성 없음)이 있으나 잔기 순서는 entries 끝점을 따라야 하고(`residue_index`), 요청·검사 규칙이 늘어난다.
3. **`reference_uniprot_id`가 여러 accession을 `", "`로 이은 문자열일 수 있다(74개 항목, 결정 필요 3).** 명세는 단일 accession으로 가정한다. accession 합집합·`accession_differs_from_mcsa`·`GET /reaction_reference/pdb/{pdb_id}`의 `reference_uniprot_id`(화면 제안용)에서 나누는 규칙이 필요하다.
4. **`residue_sequences[].uniprot_id`가 빈 문자열인 행이 279개다(54개 항목).** 합집합에서 빼야 한다(규칙만 추가, 닫힌 집합 변화 없음).
5. **`assembly`가 int 또는 빈 문자열 `""`이다(783행, 결정 필요 4).** 명세 §5.3의 `assemblies`(오름차순 목록)는 형이 섞여 그대로 정렬할 수 없다. `""`를 원문 그대로 둘지(정렬 규칙 정의), null로 바꿀지 정해야 한다. 실제 자료에서는 그룹이 늘 원소 하나라 목록도 늘 원소 하나다.
6. **UniProt 비활성 이유에 `DEMERGED`(분할)가 있다(결정 필요 8, 닫힌 집합).** 명세의 건너뜀 이유는 `obsolete`·`merged`·`not_found`·`fetch_failed` 넷이고 `primary_accession`은 문자열 하나|null이다. 실제로 받지 못한 8개 중 4개가 `DEMERGED`이고 대상 accession이 1–3개다(보조 accession P02023도 `DEMERGED`로 3개). `MERGED`는 관찰하지 못했다. 또 UniProt 이름은 `DELETED`인데 명세는 `obsolete`다(대응 규칙만 정하면 됨). `demerged` 이유와 대상 목록 필드를 더할지, `merged`에 목록을 둘지 정해야 한다. 분류에는 accession마다 요청 1건이 든다(여러 개 요청은 이유 없이 빠뜨림).
7. **M-CSA `page_size` 상한 100이 조용히 적용되고 `next`가 요청 값을 되풀이한다.** 명세는 쪽 크기를 정하지 않았으므로 충돌은 아니나, 가져오기는 `page_size=100` 고정과 `count` 대조가 필요하다.
8. **UniProt 촉매 활동의 Rhea 교차참조에 `RHEA-COMP:<n>`이 섞여 있다.** `rhea_ids`는 `^RHEA:[0-9]+$`만 남겨야 한다. `physiologicalReactions`의 방향 있는 Rhea ID(269개)는 명세 필드가 없어 버려진다.
9. **UniProt EC 번호 위치가 여러 곳이고, TrEMBL 항목은 `recommendedName` 대신 `submissionNames`를 쓴다(결정 필요 5).** 명세는 `ec_numbers`·`protein_name`의 출처를 정하지 않았다.
10. **UniProt 부위 위치 모양**: 측정 표본은 모두 `EXACT` int였지만 UniProt 형식상 모르는 위치가 있을 수 있다(결정 필요 6). `ligand_id`는 `ChEBI:CHEBI:<n>` 모양, 160/1,578은 없음(null 허용과 일치). 촉매 활동 180/644는 EC 없음(null 허용과 일치). 동형 단백질 한정(`molecule`) 표시는 버려진다.
11. **Rhea "모든 반응"의 범위(결정 필요 7)**: 대표 반응 18,611개인지 방향 있는 반응까지 74,444개인지. REST는 대표 반응만, FTP txt는 전부. UniProt 연결 ID는 모두 대표 반응이므로 대표 반응만 권장. Rhea 참여자 이름은 ChEBI 이름이라 반응식 표기와 다를 수 있다.
12. **M-CSA 화합물 `chebi_id`는 `CHEBI:` 접두가 없고, 14개는 ChEBI가 아닌 `X006nn` 값이다.** UniProt·Rhea의 `CHEBI:<n>`과 형이 다르다. 명세는 M-CSA 화합물과 Rhea를 잇지 않으므로 원문 그대로 저장·표시하면 된다(규칙 변화 없음, 표시 주의).
13. **`is_reference`가 모든 행에서 true이고, 잔기마다 `residue_chains`가 0개 또는 1개뿐이다.** entries API에는 상동 구조 행이 없다. 명세 규칙(그룹 합침·`mcsa_rows_disagree`·`is_reference` 하나라도 참)은 틀리지 않지만 실제 자료에서는 발생하지 않으므로 합성 fixture로만 시험된다. 같은 항목 안 다른 잔기(다른 `residue_index`)가 같은 PDB·체인·`auth_resid`를 가리키는 조합은 85개 있다(각각 별도 행이 되고 M20에서는 한 위치에 `catalytic` 원소가 여럿 붙는다).
14. **`code` 어휘**: 표준 20종 밖은 `Sec`(3행)·`X`(5행)뿐이고 표기는 첫 글자 대문자(`X`만 한 글자). 명세 규칙(대문자로 바꿔 표준 20종 비교 → 밖이면 `non_standard_code`)과 맞는다. `auth_resid` null 7행(`no_author_number`)도 명세와 맞는다. `resid` null은 없다(명세는 null 허용, 문제없음).
15. **체인 의미**: `chain_name`은 저자 체인(근거 위 (a-1)), `pdb_id`는 늘 소문자 — 명세 가정과 같다. `assembly_chain_name`은 289행에서 다르다(명세대로 무시).
16. **accession 상한**: 합집합 1,630 ≪ `MAX_ACCESSIONS` 20,000, 받지 못함 8 ≤ `MAX_SKIPPED` 50 — 명세와 충돌 없음. UniProt 한 요청 1000개 상한.
17. **실제 등록 구조**: 저장소 안 구조(1HSG·1MQ4·1UBQ·파생 1HSG)는 M-CSA에 하나도 없다(계획의 "실제 M-CSA 등록 구조가 없음"에 해당하나, 허용된 RCSB 구조 3개 안에서 1S9I 등으로 확보 가능). M15 SIFTS ∩ M-CSA = {1S9I}.

## 남긴 파일·재현

- 저장소에 남긴 것: 이 문서, `network-ledger.txt`(46줄). 원본 응답·분석 스크립트(`net.py`, `analyze_mcsa.py`, `analyze_uni.py`, `size_estimate.py`)는 scratchpad(`/private/tmp/claude-501/.../scratchpad/m26_t1/`)에만 있고 저장소에 넣지 않았다.
- 같은 측정을 다시 하면 요청이 다시 든다. 이후 형식 시험은 이 문서의 모양을 본뜬 합성 fixture로 한다(실제 응답 조각 커밋 없음).
