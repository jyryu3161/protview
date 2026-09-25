# Step0 / M8 — real prompt agent, acknowledged viewer, actual offscreen QA

Design/review: GPT-6 Astra. Implementation: GPT-6 Sol. Baseline e0abffc; actual branch phase/m8-agent-viewer. No prefilled completion/review status. User authorized implementation and real offscreen testing; do not ask again for planning approval.

## Read first

AGENTS.md, docs/M8_AGENT_VIEWER_CONTRACT.md, docs/M8_OFFSCREEN_QA_PLAN.md, docs/EGRESS_CONTRACT.md, docs/RUNTIME_CONTRACT.md, docs/M7_PROCESS_IDENTITY.md, existing M7 review and actual current API/gate/MolstarViewer sources.

## Selected implementation

Implement actual bounded natural-language interpretation through the existing pinned Jev Decisions gate, separate strict viewer projection/questions, explicit persisted online mode and viewer-only consent, real request/usage limits, exact scene target aliases, typed compiler, scoped cancellation, durable idempotent intent/ack history and actual Mol* representation/selection/camera execution. Keep local commands/manual controls functional offline and label their source honestly. Do not auto-run scientific tools/jobs or broaden provider/file/JS execution. Preserve old immutable reports, scientific methods and process identity/cleanup/accounting contracts. Correct the minimized-coordinate caption and all functional issues reproduced by the comprehensive click inventory.

Add a separate real Electron offscreen QA harness with GPU/WebGL retained. It must record webContents.isOffscreen true and drive the actual app renderer; CDP/Playwright may be the driver, not a substitute renderer. Provide observable actual readiness/command acknowledgment and a repeatable local harness entry point. The QA harness is development tooling, not a production remote-control endpoint. Pins and ownership/cleanup must be explicit.

Create docs/M8_AGENT_VIEWER.md describing actual implemented routes, safe data flow, offline/local distinction, live model identity/usage, limits, command acknowledgments and known unavailable cases. Maintain a completed per-control QA matrix with original failure and corrected evidence. No mocked/stubbed model result may count as actual integration.

## Acceptance commands

The Sol-created phase index stores these exact argv arrays; initial status is pending and no success evidence is prefilled:

```text
.venv/bin/python -m pytest backend/tests/test_agent_viewer.py backend/tests/test_llm_egress.py backend/tests/test_runtime.py -q
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks
.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py -q
npm --prefix frontend run test:events
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Add meaningful new frontend tests under the existing test:events glob. The backend test file must cover the new service/projection/compiler/API and shared gate invariants. Do not add a fake always-passing browser command to the phase index. Actual offscreen per-control execution and bounded live model evidence are mandatory review inputs in addition to these commands; parent can run the honest harness on stable servers/builds. Document its exact executable command and dependency installation in the implementation guide.

## Required gate evidence

1. Real offscreen Electron mode, nonvisible window, WebGL/paint output and exact version/source/build identity, with actual mouse/key/file controls and completed screenshots/downloads. Inventory all mounted product controls, individually exercise supported and disabled/error/retry states, preserve failures and retest fixes. No normal hidden tab/headless-Chromium substitution.
2. Actual user prompt through public production route/gate/pinned model, within at most4 physical live requests and selected cap; valid served snapshot, normalized usage, typed compiled commands and actual Mol* applied acknowledgments. No secrets/raw coordinates/sequence/files in egress or capture. No regex-only demonstration passed as model integration.
3. Focus full model/auth/label/icode identity on real and synthetic ambiguous scenes; representation/zoom/reset/clear semantics, history/minimized input separation, current-scene/manual-intent guards, cancellation and no false applied status. Model/transport failures retain honest accounting and leave a usable local UI.
4. Persisted mode/scoped consent, same-request idempotence, cumulative cap, unknown delivery/usage recovery and old scientific report/engine-free replay. Online viewer consent never grants scientific-job approval. All current M7/M6/MVP shared regressions remain covered, including actual host process tests with no skip counted as acceptance.
5. Final Astra report and exact reviewed-file hashes, explicit current extension supersession of historical e0abffc coverage, actual parent record-review/--verify and real commit. Do not rewrite old MVP/M6/M7 history or claim their old hashes freshly verified.
