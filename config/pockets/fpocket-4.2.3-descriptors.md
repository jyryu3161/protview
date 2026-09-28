# fpocket 4.2.3 기술자 계산 근거

출처: fpocket 4.2.3 태그 공개 소스 `https://github.com/Discngine/fpocket/archive/4.2.3.tar.gz`
(SHA-256 `62b3da6490eeab0db488f0182150d340de2be0be23f4fd1def9d5846ce724ede`, conda-forge `fpocket-4.2.3-hb88c64c_2`
recipe의 source sha256과 같음). recipe patch `fpocket.patch`는 `src/fparams.c`의 `-P` 인자 처리 포인터 버그만 고치며
아래 계산 코드는 건드리지 않는다. 줄 번호는 태그 tarball 기준이다.

## 출력 위치

`protein_info.txt`의 포켓별 항목은 `write_out_fpocket_info_file`(`src/fpout.c:150-213`)이 쓴다.

| native 이름 | 출력 줄 | 원천 필드 | 형식 |
|---|---|---|---|
| `Score` | `src/fpout.c:184` | `pocket->score` | `%.3f` |
| `Druggability Score` | `src/fpout.c:185` | `pdesc->drug_score` | `%.3f` |
| `Number of Alpha Spheres` | `src/fpout.c:186` | `pocket->size` | `%d` |
| `Total SASA` | `src/fpout.c:187` | `pdesc->surf_vdw14` | `%.3f` |
| `Volume` | `src/fpout.c:190` | `pdesc->volume` | `%.3f` |

계산 순서(`src/fpocket.c:158-214`): 알파 구 군집 → 포켓 배정 → `set_pockets_descriptors`(기술자·정규화·점수) →
`dropSmallNpolarPockets`(`src/refine.c:114-144`) → 점수 내림차순 정렬(`src/fpocket.c:206`, `src/psorting.c:228-232`)
→ 번호 재부여. 따라서 fpocket 번호(rank)는 `Score` 내림차순이다.

좌표는 입력 PDB의 Å 좌표이고, 원자 반지름은 원소별 van der Waals 반지름 표(`src/pertable.c:120-`, 예: C 1.7)에서
Å 단위로 온다(`src/rpdb.c:1161` 등 `pte_get_vdw_ray`). 알파 구 반지름은 Voronoi 꼭짓점과 접촉 원자 중심 사이 거리(Å)이며
`-m`/`-M` 범위로 거른다(`src/voronoi.c:1010-1016`).

## Score — 무차원

- `src/pocket.c:633` `cur->pocket->score = score_pocket(cur->pocket->pdesc)`.
- `src/pscoring.c:241-247`에서 실제로 쓰이는 식(그 위의 식들은 주석 처리됨):
  `score = -0.03783394 + 0.48461469·nas_norm + 0.09093926·as_density + 0.0004155899·convex_hull_volume
  − 0.003995233·surf_pol_vdw14 − 0.004072336·surf_apol_vdw14`.
- `nas_norm`은 같은 실행의 모든 포켓(필터 전)에 대한 알파 구 개수 min-max 정규화다(`src/pocket.c:664-780`,
  특히 `:757`). 따라서 `Score`는 같은 실행 안의 다른 포켓에 따라 달라지는 상대 점수다.
- 계수가 단위를 흡수한 회귀식의 결과이므로 물리 단위가 없다. 결합 부위·친화도 증거가 아니다.
- `convex_hull_volume`은 qhull `qconvex`를 TMPDIR 파일로 실행해 구한다(`src/descriptors.c:247`, `src/voronoi.c:1235-1267`).

## Druggability Score — 무차원, 0–1

- `src/pocket.c:634` `drug_score = drug_score_pocket(pdesc)`.
- `src/pscoring.c:325-329`: 로지스틱 함수
  `1 / (1 + exp(−(−9.5698768 + 7.479844·mean_loc_hyd_dens_norm + 0.3696134·as_max_dst − 0.04671833·surf_pol_vdw22)))`.
- `mean_loc_hyd_dens_norm`은 같은 실행 포켓들에 대한 min-max 정규화(`src/pocket.c:753-754`), `as_max_dst`는 알파 구 중심 간
  최대 거리(Å, `src/descriptors.c:213,226,252`), `surf_pol_vdw22`는 탐침 2.2 Å 극성 SASA(`src/asa.c:361-398`).
- fpocket 고유의 회귀 점수이며 약물성 증거가 아니다(`detector_specific_note`로 항상 함께 표시).

## Number of Alpha Spheres — 개수

- `pocket->size = pocket->v_lst->n_vertices`(`src/pocket.c:133`, 병합 시 `src/pocket.c:1080-1081`).
- 포켓에 속한 알파 구(Voronoi 꼭짓점) 개수. `-i 15` 미만이면 제거된다(`src/refine.c:129`).

## Total SASA — Å²

- `set_ASA`(`src/asa.c:240-338`), `src/descriptors.c:245`에서 호출.
- 포켓 알파 구에 접촉한 고유 원자마다 반지름 `r_vdW + 1.4 Å`(`M_PROBE_SIZE`, `headers/asa.h:43`) 구 위에 100개
  나선 점(`M_NSPIRAL`, `headers/asa.h:41`)을 놓는다. 점이 그 원자에 접촉한 알파 구 안에 있지 않고(`:305-312`),
  주변 다른 원자의 `r_vdW + 1.4` 구에도 묻히지 않으면(`:313-325`) 노출 점으로 센다.
- 원자 면적 = `4π(r_vdW + 1.4)² / 100 × 노출 점 수`(`src/asa.c:330`), 포켓 합계 `surf_vdw14`(`src/asa.c:336`).
- 거리 단위가 Å이므로 Å²다. 포켓에 접한 원자들의, 포켓 알파 구에 가리지 않은 용매 접근 표면을 점 표본으로 추정한 값이며
  단백질 전체 SASA나 프로젝트의 SASA 도구 결과와 같은 양이 아니다.

## Volume — Å³ (Monte Carlo 추정치)

- `src/descriptors.c:246` `desc->volume = get_verts_volume_ptr(tvert, nvert, niter, -1.6)`; `niter`는 `-v 300`
  (`src/pocket.c:579`).
- `get_verts_volume_ptr`(`src/voronoi.c:1150-1233`): 각 알파 구 반지름을 1.6 Å 줄인 구(`r − 1.6`)들의 합집합에 대해,
  경계 상자(`:1166-1200`, 상자 좌표에도 −1.6이 더해짐)에서 균일 난수 점 `niter`개를 뽑아 합집합 안에 든 비율 × 상자 부피를
  구하고(`:1205-1227`), 이를 100번(`nreps`, `:1161`) 반복해 평균한다(`:1232`).
- 좌표·반지름이 Å이므로 Å³다. fpocket의 확률적 추정치이며 알파 구 합집합의 해석적 부피가 아니다.
- 난수: `rand_uniform`(`src/utils.c:113-128`)은 `rand()`를 쓰고, 시드는 `srand((int)time(NULL))`(`src/utils.c:90`)과
  `srand(time(NULL))`(`src/voronoi.c:87`)에서 현재 시각으로 정한다. 시드 옵션이 없으므로 같은 입력이라도 새로 실행할 때마다
  `Volume`이 달라질 수 있다(`seed_control: "unsupported"`).
- 참고: `basic_volume_div`(−1)와 `set_pocket_volume`/`set_pocket_mtvolume`(`src/pocket.c:314,405`)은 4.2.3 fpocket
  경로에서 호출되지 않는다.

## 필터에 관한 주의 (값 해석용)

`src/refine.c:129-130`의 제거 조건은 소스에 쓰인 그대로
`n_vertices < min_pock_nb_asph || pasph < (refine_min_apolar_asphere_prop || as_density < min_as_density)`다. 괄호 안은
C 논리합(0 또는 1)이다. `as_density`는 이름과 달리 알파 구 중심 간 평균 거리(Å, `src/descriptors.c:257`)다. 이 동작을
바꾸거나 다시 해석하지 않고 기록만 한다.
