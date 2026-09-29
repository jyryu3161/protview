# 0020. 커밋하는 QA 증거는 작은 텍스트로 제한하고 큰 증거는 해시와 함께 Git 제외 폴더로 옮긴다

- 상태: 채택 (사용자 결정 2026-09-29, M13 수락 QA 뒤)

## 배경
M13 수락 실행기는 M11·M12 수락 실행기 전체를 하위 단계로 돌린다. 내보낸 텍스트 증거는 실행마다 256 KiB를 넘는 파일이 50개, 합계 약 331 MB였다(M11 하위 실행기의 `chemical-evidence.json`은 하나가 최대 약 62 MB).

## 결정
- 256 KiB를 넘는 텍스트 증거는 Git에 넣지 않고 그 실행의 Git 제외 artifacts 폴더 `export-full/`로 옮긴다(폴더 기준 상대 경로 유지, 삭제하지 않음).
- 대장(`case-ledger*.json`, `ledger-row.json`)은 크기와 관계없이 커밋한다.
- 옮긴 파일의 SHA-256은 `ARCHIVED-EVIDENCE.sha256`에 모으고, `SHA256SUMS`의 원래 줄도 남긴다. README 끝 절에 목록·크기·해시와 확인 명령을 적는다.

## 검토한 대안
- 전부 커밋: 저장소가 실행마다 수백 MB 늘어난다.

## 결과
- 옮긴 파일의 내용은 그 컴퓨터의 artifacts 폴더에만 있다. 커밋한 해시로 동일성은 확인할 수 있지만, 폴더를 잃으면 내용은 복구할 수 없다.
- M13에서는 `docs/qa/m13-workflows-20260929/`와 `-run1/` 두 폴더에 적용했다(`frontend/tests/offscreen/artifacts/m13-acceptance/20260929b/export-full/`, `.../20260929/export-full/`).
