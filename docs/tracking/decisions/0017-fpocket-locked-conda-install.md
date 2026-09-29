# 0017. fpocket을 해시 잠금 conda 환경으로 격리 설치한다

- 상태: 채택 (사용자 결정 2026-09-28)

## 배경
M12 포켓 검출은 fpocket 4.2.3 실행 파일이 필요하다. 시험 실행에서 conda-forge `osx-arm64/fpocket-4.2.3-hb88c64c_2`가 동작했고, 35개 패키지의 explicit 목록과 해시가 남아 있었다. 실행 파일 자체는 시스템 라이브러리만 링크한다.

## 결정
- `config/pockets/`에 explicit 목록과 35개 패키지 해시를 둔다. `scripts/setup_fpocket.py`가 conda·플랫폼(macOS ≥ 14.5 arm64)을 확인하고, 사용자가 지정한 로컬 archive 폴더의 해시를 모두 맞춘 뒤 `conda create --offline`으로 `.deps/fpocket/env`에 설치한다. 실행 파일 SHA-256을 고정값과 대조하고 설치 기록을 남긴다.
- 런타임은 설치·다운로드하지 않는다. 서버는 `.deps/fpocket/env/bin/fpocket` 한 경로만 쓰고, 작업 프로세스는 해시를 확인한 복사본을 실행한다.

## 검토한 대안
- 소스(태그 4.2.3)에서 직접 빌드: 컴파일러·링크 기록이 추가로 필요하고 설계에서 예비 경로였다.
- conda 없이 archive 직접 풀기: conda 형식 처리 코드를 새로 짜고 검증해야 한다.

## 결과
- conda가 없는 컴퓨터에서는 포켓 검출이 `not_installed`로 표시되고 나머지 기능은 동작한다.
- conda 23.3.1은 새 환경을 `~/.conda/environments.txt`에 등록한다(끌 설정 없음). base 환경과 패키지 캐시는 바뀌지 않는다.
- 다른 플랫폼 빌드는 별도 잠금·검증이 필요하다.
