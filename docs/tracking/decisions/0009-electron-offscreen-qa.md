# 0009. UI 수락 검증은 실제 Electron 오프스크린 렌더러로

- 상태: 채택 (M8, 2026-09-25)

## 배경
사용자는 모든 제품 컨트롤을 실제 오프스크린 환경에서 클릭 검증하길 원했다. 쓸 수 있던 숨김 탭 제어로는 실제 오프스크린 모드인지 확인할 수 없었다. Mol*는 WebGL이 필요하다.

## 결정
Electron `BrowserWindow`를 `show:false`, `webPreferences.offscreen:true`로 띄우고, `webContents.isOffscreen()===true`, GPU·WebGL 켜짐, 실제 paint 프레임을 기록한다. Playwright는 CDP로 이 렌더러를 조작만 하고, 자체 headless Chromium으로 바꿔 치지 않는다.

## 검토한 대안
- 일반 Playwright headless Chromium: 오프스크린 여부를 확인할 수 없고, GPU 조건이 다르다.
- GPU를 끄고 비트맵 캡처: Mol* WebGL 검증이 무의미해진다.

## 결과
- Electron 44.4.5가 개발 의존성에 들어간다. QA는 loopback이 아닌 요청을 차단하고 기록한다.
- 헤드리스 CI 서버에서는 GPU가 없으면 이 검증을 할 수 없다.
