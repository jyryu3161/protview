# 0006. PyRosetta는 사용할 수 없음으로 두고, FreeSASA·OpenMM을 별도 이름으로 추가

- 상태: 채택 (MVP 2026-09-24, M6–M7 확장 2026-09-24)

## 배경
참고 구현의 Rosetta 작업 프로세스는 TODO뿐이었고, 확인한 환경에는 PyRosetta가 설치되어 있지 않았다(라이선스 필요). 사용자는 PyRosetta 대신 쓸 만한 대체 방법을 요청했다.

## 결정
- Rosetta 프로토콜 4종(relax, Cartesian ddG, interface, residue energies)은 이유를 담은 unavailable로 두고, 숫자를 만들지 않는다.
- M6: FreeSASA 단백질–리간드 노출·매몰 면적(Å²). M7: OpenMM 단백질 전용 Amber14/GBn2 전위·최소화(kJ/mol). 둘 다 별도 능력 이름, 결과 종류, 보고서를 가진다.

## 검토한 대안
- import 성공을 근거로 Rosetta 기능 표시: 실제 구현과 검증이 없다.
- 대체 방법 값을 Rosetta, ΔΔG, 친화도 이름으로 표시: 과학적으로 다른 양을 같은 것처럼 주장하게 된다.

## 결과
- 돌연변이 설계와 안정성 순위는 제공하지 않는다. 실제 지원·검증된 엔진이 생기기 전까지 계속 그렇다.
- OpenMM은 리간드가 없는 단백질만 계산한다. 복합체나 리간드 매개변수화는 별도 과학 프로젝트다.
