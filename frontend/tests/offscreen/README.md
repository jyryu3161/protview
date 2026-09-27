# Real Electron offscreen QA

Run the loopback Next.js and FastAPI servers first, then:

```bash
npm --prefix frontend run test:offscreen -- --url http://127.0.0.1:3000
npm --prefix frontend run test:offscreen -- --url http://127.0.0.1:3000 --interactive
```

The first command launches Electron 44.4.5 with a genuinely offscreen, invisible `BrowserWindow`, verifies GPU acceleration is enabled and `webContents.isOffscreen()` is true, waits for an Electron `paint` frame, saves both the paint bitmap and a Playwright page screenshot, writes `artifacts/baseline.json`, and closes its own Electron process. All renderer HTTP/WebSocket requests outside loopback are blocked and recorded. This smoke does not call OpenRouter or create a run.

The interactive command keeps that same Electron process and page open. Send one JSON object per line on stdin. Responses are one JSON object per line on stdout. Product interactions use Playwright locator mouse/keyboard/file chooser input, never DOM `.click()` or application handlers. Example:

```json
{"id":"v01-surface","action":"click","target":{"by":"role","role":"button","name":"surface"},"name":"v01-surface"}
{"id":"viewer-state","action":"status"}
{"id":"final","action":"snapshot","name":"final"}
{"id":"quit","action":"quit"}
```

Supported locator forms are `{ "by":"role", "role":"button", "name":"..." }`, `{ "by":"label", "name":"..." }`, `{ "by":"text", "name":"..." }`, and `{ "by":"css", "selector":"..." }`. Supported actions are `status`, `snapshot`, `click`, `fill`, `press`, `keyboard`, `check`, `uncheck`, `select`, `chooseFile`, `drag`, `wheel`, `download`, `wait`, `text`, `count`, and `quit`. Each input action saves `name.page.png` and `name.paint.png` unless `capture:false`; `interactive.jsonl` records each safe input description and its observed result, including failures and the final close acknowledgment. `download` clicks the real link and waits for Electron's `will-download` and `done: completed` events; the browser-saved file lands under `artifacts/downloads/`. For `chooseFile`, pass `file` and a target locator for the real file input or button that opens the chooser. `--artifacts /absolute/path` changes the evidence directory; its default is ignored by Git. Each artifacts directory has its own ignored `browser-profile/`, so parallel QA Electron instances do not share stored UI state. Reuse an artifacts directory only for an intentional reopen-state check; do not archive the profile as evidence.

A reusable script can import `const { launchOffscreen, command, capture, status } = require('./driver.cjs')`. `launchOffscreen({url, artifacts, interactive:false})` returns `{app, page, artifacts, baseline, close}`. Use `page.getByRole(...).click()`, `page.keyboard`, `page.mouse`, or `command()` for actual inputs. Use read-only page/backend observations for assertions; do not invoke product handlers, set React state, or fake Mol* acknowledgments. Always call `close()` in a `finally` block.

`main.cjs` is an Electron main process host. It keeps `nodeIntegration:false`, `contextIsolation:true`, `sandbox:true`, does not disable hardware acceleration, denies new windows and non-loopback navigation, and writes the first paint frame from Electron's `paint` event. The returned baseline JSON records `offscreen`, `visible`, `painting`, `hardwareAccelerationEnabled`, `paintCount`, bitmap size, Electron/Playwright versions, and blocked request metadata. A frame and a screenshot prove actual offscreen rendering; scenario assertions must still wait for the product's ready state and verify the specific result after clicks.

The download capture follows Electron's [Session `will-download`](https://www.electronjs.org/docs/latest/api/session#event-will-download) and [DownloadItem `setSavePath`/`done`](https://www.electronjs.org/docs/latest/api/download-item) APIs. This is the actual Electron browser download path; Playwright's renderer `download` event did not fire for these offscreen link clicks. Local-only download URLs are enforced before saving.

An offline normal-flow script is also available for an **isolated QA backend** (it creates a run and writes results):

```bash
npm --prefix frontend run test:offscreen:normal -- --url http://127.0.0.1:3000 --fixture ../backend/tests/fixtures/public_1hsg.cif --artifacts /tmp/protview-qa/normal-1hsg
```

It clicks the actual upload, load, prepare, ligand, contact, representation, report, SASA, and download controls. It requires the read-only `window.__protviewQaSnapshot()` observation from the actual Mol* instance to pass viewer cases; an absent bridge fails the run. Each passing case waits for its product result before saving page and Electron-paint screenshots. Report downloads are byte-compared with read-only saved report responses and their Markdown preview or JSON manifest. `normal-flow.jsonl` records the source/fixture fingerprints, input, before/after observations, paths, and assertions. The script does not invoke a provider or OpenMM.

The separate 1UBQ OpenMM scenario exercises real local CPU work through visible controls on a fresh isolated QA run:

```bash
npm --prefix frontend run test:offscreen:openmm -- --url http://127.0.0.1:3000 --fixture ../backend/tests/fixtures/public_1ubq.cif --artifacts /tmp/protview-qa/openmm-full --mode full
```

It keeps 1UBQ's waters for the exclusion preflight, checks both policy checkboxes, submits, attempts an unapproved start, then clicks explicit approval/start. It waits for the real job and native finite result, switches minimized/original coordinate views, creates the method report, and compares both downloaded files to saved bytes. `--mode queued-cancel` stops after a real queued cancellation; `--mode running-cancel` requires an observed running worker and clicks its cancel control. Use a separate artifacts directory and isolated QA run root for each mode. An unobserved running state fails that case. These scripts never call OpenRouter.

The read-only history keyboard check opens an existing run and sends real Tab, Enter, and Space keys in offscreen Electron:

```bash
npm --prefix frontend run test:offscreen:keyboard -- --url 'http://127.0.0.1:3000/?run=<existing-run-id>' --artifacts /tmp/protview-qa/history-keyboard
```

It requires two history steps, confirms both key selections in the UI, and saves `history-keyboard.json` plus page/paint screenshots. The pre-fix M7 build had two `.mw-step` rows with `tabIndex:-1`, no role, and no focused row after 100 actual Tab inputs. On 2026-09-25, the fixed source was served from an isolated `/tmp/protview-qa/m8-keyboard-build` Next dev copy on port 3001 (only `node_modules` linked to this repo); the command above with port 3001 passed with Enter selecting row 0 and Space selecting row 1. Evidence: `/tmp/protview-qa/m8-history-keyboard-before/` and `/tmp/protview-qa/m8-keyboard-reusable/history-keyboard.json`. That temporary server was stopped after the check, and it did not write to this repo's `.next` build.

For a read-fault retry, use the interactive driver on an **existing isolated QA run** while a separately documented loopback fault fixture returns 503 for the selected read. First observe the visible error and retry button with `status` and `snapshot`. After the fixture is switched off, send the actual `click` input for `저장된 OpenMM 결과 다시 읽기` or `저장된 OpenMM 보고서 다시 읽기` with `capture:false`, then a `wait` for `시작 전위` or `저장된 OpenMM 보고서 미리보기`, and finally `snapshot`. Keep the fault setup/teardown and each clicked result as distinct evidence rows; the driver never creates a success response. The same sequence applies to the contact-row and SASA read retry controls with their own visible result labels.

For repeatable OpenMM GET fault/race cases on a real completed QA run, use `test:offscreen:faults` with `--target-run <done-run> --other-run <run-without-OpenMM> --artifacts /tmp/...` and one of `--mode read-retry|late-result|late-report`. `read-retry` returns a labeled 503 only for the target run's result/report GETs until both visible retry controls appear, removes the fault, then clicks each real retry control. The late modes hold an unchanged real backend GET response with Playwright's `route.fetch()`, switch runs through the saved-run selector, then release it and check that the old result/report never appears in the other run. The route affects only this QA renderer, not the backend or any other browser. These modes do not prepare a failed OpenMM job or claim to cover job submission/start races.

To verify the failed-job retry control, run `npm --prefix frontend run test:offscreen:retry -- --url http://127.0.0.1:3000 --fixture ../backend/tests/fixtures/public_1ubq.cif --artifacts /tmp/protview-qa/openmm-retry` against an **isolated QA backend**. Its clearly labeled loopback API setup creates a new 1UBQ run and triggers a genuine physical worker timeout at 0.001 s; the actual Electron UI then clicks `실패한 작업 재시도` and checks that the same job is queued without starting or charging a second attempt. The fixture must fail from the real supervisor or the scenario fails. A cancelled job is not retry eligible in the current API.

For O14 POST response races, run `npm --prefix frontend run test:offscreen:post-races -- --url http://127.0.0.1:3000 --fixture ../backend/tests/fixtures/public_1ubq.cif --other-run <run-without-OpenMM> --artifacts /tmp/protview-qa/post-submit --mode submit`, then repeat with distinct artifact paths and `start`, `approve`, and `create`. Each mode prepares an isolated old run through the loopback API. Playwright lets the real POST commit on the backend, holds its actual response, switches to the other run through the visible selector, then releases it. Assertions check the displayed Mol* source and both runs' saved jobs/reports. `create` performs a real local OpenMM job first; `approve` must not chain-start a worker after the run switch. No provider call is made.

For B03, run `npm --prefix frontend run test:offscreen:dry-run -- --url http://127.0.0.1:3000 --fixture ../backend/tests/fixtures/public_1ubq.cif --artifacts /tmp/protview-qa/dry-run`. The loopback API creates only the initial `dry_run: true` record. The Electron UI performs upload, load, prepare, preflight, policy checks, submit, and reopen. It verifies a plan-only response, no durable job or physical attempt, zero expensive/token/USD charges, and the persisted dry-run badge.

For O09/B01, run `npm --prefix frontend run test:offscreen:persistence -- --url http://127.0.0.1:3000 --fixture ../backend/tests/fixtures/public_1ubq.cif --full-run <completed-run> --queued-cancel-run <queued-cancel-run> --running-cancel-run <running-cancel-run> --artifacts /tmp/protview-qa/openmm-persistence`. A labeled loopback setup creates two distinct queued jobs in one new run. The Electron UI selects both job IDs, opens completed and cancelled runs, compares its topbar/detail expensive count with the backend's reservation ledger, then reopens the two-job run and selects an older job again.

For M11 chemical interactions (`test:offscreen:chemical`), every input comes from this repository. `create`, `prepare-only`, `job-controls`, and `running-cancel` use the public fixtures `--receptor ../backend/tests/fixtures/chemical/prolif-vina-rec.pdb --sdf ../backend/tests/fixtures/chemical/prolif-vina-output.sdf`. Synthetic derivatives (attach complex PDB, the (+1000,+1000,+1000) Å empty-result SDF, and the receptor CONECT edge list) are not committed; rebuild them with `.venv/bin/python scripts/m11_qa_inputs.py --out <git-ignored dir, e.g. frontend/tests/offscreen/artifacts/m11-inputs>`, which fails unless every SHA-256 matches `backend/tests/fixtures/chemical/SYNTHETIC-PROVENANCE.md`. They are synthetic, not experimental evidence. For `attach`, load the generated `m11-attach-complex.pdb` into the QA run and import the public SDF, then run `.venv/bin/python scripts/m11_attach_browser_setup.py --api-base http://127.0.0.1:8000 --run-id <run> --complex-handle <obj://...> --ligand-import-handle <obj://...> --out <dir>`. It reads that run's actual source catalog (GET only) and writes the sidecar, request, `map_existing`/`replace_from_sdf` mapping files, and ligand instance for `--sidecar`, `--mapping`, and `--ligand`; no nearest-coordinate or guessed mapping is used. The GET-only events-only replay helper is `scripts/m11_replay_probe.py` (copied from the M10 helper in `docs/qa/m10-comparison-20260927/commands/`).
