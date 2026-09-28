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

## M11 chemical interactions (H01–H17)

Every M11 input comes from this repository. Public fixtures: `backend/tests/fixtures/chemical/prolif-vina-rec.pdb` and `prolif-vina-output.sdf` (prepared docking example, not experimental validation). Synthetic derivatives are generated, never committed, and each generator exits non-zero unless the pinned SHA-256 matches:

- `.venv/bin/python scripts/m11_qa_inputs.py --out <dir>`: attach complex PDB, the (+1000,+1000,+1000) Å empty-result SDF, receptor CONECT edges (`backend/tests/fixtures/chemical/SYNTHETIC-PROVENANCE.md`).
- `.venv/bin/python scripts/m11_invalid_inputs.py --out <dir> [--attach-sidecar <run sidecar>]`: labeled H06 invalid derivatives (disconnected atom, altloc, zinc ion, wrong-source/wrong-schema bond sidecars, 2D record) plus `m11-invalid-cases.json`, whose expected offending identities come from the edit the script made. `--attach-sidecar` adds the run-bound covalent-ligand sidecar. `backend/tests/test_m11_invalid_inputs.py` checks the pinned bytes and the product diagnostics.
- `.venv/bin/python scripts/m11_attach_browser_setup.py ...`: run-bound attach sidecar, `map_existing`/`replace_from_sdf` mappings and ligand instance, from the QA run's own source catalog (GET only).

### One-command acceptance sequence

With the frontend already built (`npm --prefix frontend run typecheck` then `npm --prefix frontend run build`, never concurrently) and ports 8000/3000 free:

```bash
.venv/bin/python scripts/m11_offscreen_acceptance.py \
  --root runs/m11-acceptance-<YYYYMMDD> \
  --artifacts frontend/tests/offscreen/artifacts/m11-acceptance/<label>
```

The runner starts and stops its own loopback services (uvicorn `127.0.0.1:8000` with `PYTHONPATH=<repo>/backend` and `MW_RUNS_DIR=<root>/runs`; `next start` on `127.0.0.1:3000`). The root must be fresh (the global job-ledger scan caps at 1,000 runs / 256 MiB, so never reuse a large root) and outside `/tmp`; the artifacts directory must be git-ignored. Phases (`--phases`, default all, in this order):

1. `main` — `capability-ready`, `create`, `empty`, `prepare-only` → `detect-controls`, `job-controls`, `job-controls-failure` (labeled pentavalent-carbon SDF), `running-cancel`, `attach-setup` (labeled loopback API upload/load/import, covers no case), `attach-map` (`map_existing`), `attach-replace` (`replace_from_sdf`, reload with the new preparation queued), `reopen-complete` (second report on the replace result), `restrictions` (saves an ordinary M9 scene through the real control first, annotation on and off, then restores it), `faults` (map vs replace result, two reports), `invalid-inputs`, `invalid-attach` (covalent ligand), `reopen`.
2. `regressions` (H17) — `normal-flow.cjs` with `public_1hsg.cif`; `openmm-flow.cjs --mode full` with `public_1ubq.cif`, then `scenes-flow.cjs --mode core` on that OpenMM run (the original M9 QA order: V05 needs a completed minimization); `comparison-flow.cjs --mode measure` and `--mode alignment`.
3. `replay` (H16) — snapshot with `scripts/m11_replay_probe.py` on the original root, stop the backend, copy only `events.jsonl` of the create/empty/attach runs into `<root>/replay-runs`, rename `<root>/inputs` so the original input paths are absent, start the backend from `<root>/layout-worker-missing` (byte-identical `backend/mw` + `config` copy without `.deps`: worker missing), verify before the browser, run Electron `--mode replay` on each run (reports must download with the original bytes), verify again, then `capability` expecting `worker_missing`.
4. `capability-mismatch` — `<root>/layout-worker-mismatch` whose pinned worker path points at the server interpreter; `capability` expecting `worker_version_invalid`.
5. `ledger` — `node frontend/tests/offscreen/m11-case-ledger.cjs --root <artifacts> --out <artifacts>/case-ledger.json`.

`--only step,step` reruns single steps using `runner-state.json` (run IDs and handles from earlier steps). Every step keeps its artifacts directory, `<step>.log`, `chemical-evidence.json` and `ledger-row.json` (a rerun gets a time-suffixed directory; failures are never deleted). `runner-summary.jsonl` lists outcomes and the final leftover-process/port check.

### Modes and evidence

`node frontend/tests/offscreen/chemical-flow.cjs --mode MODE --artifacts DIR [...]` (see its usage text for arguments). Each run writes `ledger-row.json`: H case ids, mode, evidence type, build id (`frontend/.next/BUILD_ID`), harness SHA-256s, fixture names/SHA-256/provenance labels, labeled renderer-route fixtures, run id, handles, pass/fail, offscreen proof (`isOffscreen`, invisible, painting, GPU, paint count, WebGL renderer) and the non-loopback request count. A row passes only when the harness assertions pass, the offscreen proof is complete and no non-loopback request was attempted.

| Case | Real Electron offscreen modes | Other declared evidence |
| --- | --- | --- |
| H01 | `capability-ready`, `capability-worker_missing`, `capability-worker_version_invalid` (labeled runtime layouts) | `test_m11_job_api.py::test_job_capability_uses_scientific_dependency_validation` |
| H02 | `create` | import-identity tests in `test_chemical_interactions.py`, `test_m11_job_api.py` |
| H03 | `create` (PDB CONECT, terminal add/edit/remove), `attach-map_existing` (sidecar) | cap-declaration tests |
| H04 | `create` | `test_actual_native_create_detect_and_tamper_rejection` |
| H05 | `attach-map_existing`, `attach-replace_from_sdf`, `invalid-attach` | `test_attach_explicit_bijection_and_sidecar`, `test_attach_covalent_ligand_bond_reports_exact_endpoint_atoms` |
| H06 | `invalid-inputs`, `invalid-attach`, `job-controls-failure` (typed native diagnostic) | `test_m11_invalid_inputs.py`, preflight/V2000/native graph diagnostic tests |
| H07 | `create`, `detect-controls`, `job-controls`, `job-controls-failure`, `running-cancel`, `attach-replace_from_sdf` | queue cancel/timeout/retry/busy tests in `test_m11_job_api.py` |
| H08 | `create`, `attach-map_existing` (independent D···A / D–H···A geometry) | analytic explicit-graph numeric tests |
| H09 | `empty` (scientific_null, distinct from error), `job-controls-failure` (error stays error) | translated/bent/distant native tests |
| H10 | `create`, `reopen-complete` | — |
| H11 | `create`, `reopen-complete` (immediate and idle-gated refocus), `restrictions` (return to ordinary) | camera-settle logic in `tests/chemical.test.cjs` |
| H12 | `create`, `restrictions` (annotation on/off, forced clicks create no artifact) | — |
| H13 | `restrictions` | — |
| H14 | `create`, `attach-map_existing`, `reopen-complete`, `reopen`, `replay` | report/events-only tests in `test_m11_job_api.py` |
| H15 | `create`, `job-controls`, `running-cancel`, `faults` | — |
| H16 | `replay` + direct API rows `replay-probe-prebrowser`/`-postbrowser` | events-only recovery tests in `test_m11_job_api.py` |
| H17 | `regression-m8-normal`, `regression-m9-openmm`, `regression-m9-scenes-core`, `regression-m10-measure`, `regression-m10-alignment` | full backend gate |

`m11-case-ledger.cjs` (`CASE_PLAN`) is the authoritative map; a case is `pass` only when every declared mode has a passing row, `fail` when a declared mode has only failing rows, and `missing` otherwise. Backend tests are listed per case; their pass/fail comes from the recorded full backend gate, not from the ledger. Route fixtures (non-approval 409 on Start, held GETs/POSTs, malformed catalog SHA, bounded source-read deadline, WebGL context loss) are renderer-only, labeled in the row and never create a scientific object.
