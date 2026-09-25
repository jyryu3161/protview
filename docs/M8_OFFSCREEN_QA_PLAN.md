# M8 actual offscreen full-product click plan

GPT-6 Astra design, 2026-09-25. Baseline e0abffc. **Planned coverage, no completed test claims.** Root executes, records and reviews actual evidence; Sol owns implementation/fixes and QA harness code. See `M8_AGENT_VIEWER_CONTRACT.md` for command, egress and scientific boundaries.

## Offscreen host and reproducibility

Use a separate pinned official Electron QA harness (`frontend/tests/offscreen/`), with an actual `BrowserWindow({show:false, webPreferences:{offscreen:true}})`. Verify `webContents.isOffscreen()===true`, no visible QA window, exact Electron/Chromium versions, WebGL initialization and bitmap paint frames. Retain GPU acceleration; do not call app.disableHardwareAcceleration. Actual offscreen is different from an ordinary hidden browser tab or unrelated headless Chromium. Parent found that the Orca CLI exposes background/hidden tabs but no verifiable offscreen flag, so they are not claimed as the requested mode. [Official Electron guidance](https://www.electronjs.org/docs/latest/tutorial/offscreen-rendering).

Playwright/CDP can attach to this Electron renderer for genuine DOM-targeted mouse/keyboard/file-input interactions and frame capture. Do not run a separate Chromium browser as the accepted renderer, invoke application handlers directly, set React state, fake Mol* acknowledgment, or replace normal backend responses with success fixtures. Use loopback-bound QA servers with recorded source/build hashes. Harness process handles are owned and cleaned on exit; never broad-kill the user's browser. Use an isolated QA run root and preserve the user's default demo and reports. Downloads go to a named QA artifacts directory. A failed WebGL context is a failed setup to fix, not a reason to substitute screenshots.

The selected harness command is `npm --prefix frontend run test:offscreen -- --url http://127.0.0.1:3000`. Sol owns this script and exact QA dependency pins; the intended verified install is Electron44.4.5 and Playwright1.63.0. Record actual installed versions rather than claiming these planned pins are already tested.

Record one JSON row per control/case: case_id, source/build SHA, actual input/run/handle, offscreen window+renderer identity, before state, click/key/file action, awaited observable result, assertion, screenshot/download/event references, network/error observations, pass/fail/blocked, and whether a fault fixture was injected. Data attributes/test-observation bridge must reflect actual Mol* readiness, source/session, selection and command acknowledgment. DOM text alone does not prove a molecular camera/representation change. A screenshot is inspected after rendering completes, not immediately after clicking. Capture failures before fixes and rerun their exact cases on stable corrected sources. This inventory supplements executable tests; no future clicks are prefilled as passed.

Ordinary offline runs must make zero nonloopback requests. Online live tests permit only the server's fixed OpenRouter request; the Electron page still makes only loopback/local asset requests. Do not capture credentials, Authorization headers or raw provider errors. Intent audit IDs/body hashes and bounded normalized usage are enough.

## Inputs and evidence baselines

Use exact existing public1HSG and1UBQ fixtures and preserve their SHA bytes, including source whitespace. Actual1HSG contacts at4Å are97 atom pairs/26 residues/minimum2.6264474104767457Å; these are prior independently measured reference values, not UI fixtures. Real SASA uses fixed Lee–Richards100 settings and full1559 atom/198 residue results. OpenMM1UBQ requires real CPU execution; do not hardcode its energies. 1HSG's absent terminal OXT remains a typed unsupported result.

Use clearly labeled synthetic fixtures for two structures sharing author IDs but differing coordinates; authX100A/labelL97/model5 versus model1; duplicate ligand names; actual multiple models; alternate occupancies; no-ligand and far-separated/zero-contact/zero-burial cases. They test identity and UI lifecycle, not scientific accuracy. Fault fixtures may delay or return503 for chosen loopback reads; they are removed for real happy-path acceptance and never shim a mismatched API query into working behavior.

## Click inventory

Each identifier below needs its own evidence row. Where options are enumerated, record a subrow for each option. Discover the final mounted production controls again after implementation and add any missing control; this table is not permission to ignore a new button.

| ID | Actual interaction | Required observation |
| --- | --- | --- |
| W01 | Initial load, empty run, no structure | Explicit empty state; no fabricated canvas/result; offline badge |
| W02 | New run button | New durable run, default local_only, no copied approvals/model dispatch |
| W03 | Saved-run selector | Exact selected history/source; old reports unchanged |
| W04 | RUN and MODELS tabs | Correct content/count/selection; no dead placeholder |
| W05 | Theme button both directions | Canvas/background and panels update; molecule remains rendered |
| W06 | Keyboard navigation/Enter and scrolling | Usable actual focus; controls and right inspector accessible; no clipped essential actions |
| I01 | File input PDB and mmCIF | Real upload feedback; correct model choices and source hash |
| I02 | File input malformed/empty/oversize | Explicit bounded error; no success/scientific_null/canvas substitution |
| I03 | Model selector each fixture model then load | Correct original model numbers; exact displayed bytes/identities |
| I04 | Load repeatedly/same-name changed bytes | Correct idempotence/source identity; changed bytes do not reuse stale structure |
| I05 | Altloc highest_occupancy and first | Actual selected coordinates/policy manifest differ as expected |
| I06 | Water strip_all and keep_all | Counts/components/exclusions and source preservation match policies |
| I07 | Hydrogen strip and keep | Actual policy/counts; no invented coordinates |
| I08 | Prepare button/repeated prepare | Linked to current loaded input; exact result handle/cache observation |
| I09 | Reopen pending upload, numeric model-index fallback | Actual numeric input selects the requested zero-based model and original model identity; invalid negative/fractional indices cannot submit, unavailable index produces an honest error |
| V01 | Cartoon, ball-and-stick, surface buttons | Actual committed Mol* representation and completed frame for each |
| V02 | Canvas drag/orbit and wheel | Actual camera changes; structure identity retained |
| V03 | New zoom-in/zoom-out/reset controls | Correct observed camera direction/reset or honest limit no_change |
| V04 | Ligand instance buttons in MODELS | Exact full ligand identity, nonempty loci, visible selection/focus |
| V05 | Contact-row click and keyboard activation | Exact residue/camera acknowledgment, never wrong model/structure |
| V06 | Clear-selection control | Mol* selection, local highlight and legend all cleared |
| V07 | History step click, including cache observation | Correct exact source; no latest/history mixed table or camera |
| V08 | Return to latest structure | Latest correctly linked pipeline, highlights/overrides cleared; mutations enabled only appropriately |
| V09 | Structure-read503, then retry | Error not empty molecule; old focus cannot apply; real retry restores matching source |
| V10 | Rapid delayed A→B source switch | Late A bytes/ack cannot replace B or mark B as A-ready |
| V11 | Model5/insertion/label fixture focus | Complete identity matches actual loci; no auth-only collision |
| V12 | Direct residue pick on the Mol* canvas | Actual canvas pointer click resolves a nonempty residue in the displayed structure; observed selection and local identity/legend agree, without invoking a focus handler directly |
| C01 | Ligand dropdown each distinct instance | Same-name ligands distinguish exact model/chain/icode/label |
| C02 | Cutoff input2.5,4,6 and invalid bounds/NaN | Valid calls use entered range; invalid button/HTTP path fails honestly |
| C03 | Compute contacts | Actual1HSG97 rows/units/provenance; no scientific claims beyond geometry |
| C04 | Next/previous page buttons | All97 rows reachable, page boundaries correct, no duplicate/lost rows |
| C05 | Horizontal table scroll | Distances/identities remain reachable and match selected row |
| C06 | Zero-contact result | Valid scientific_null distinguished from failed row load |
| C07 | Row-read503 and retry | Error without false scientific_null; exact rows restored |
| C08 | No ligand and missing preparation | Clear disabled reason; no accidental first ligand or stale prepared input |
| S01 | Latest selected-ligand SASA button | Real engine result with exact selected input/ligand, method and Å² |
| S02 | “This input's SASA” from historical contact | Binds that contact's prepared input/ligand, not latest |
| S03 | Prepared-history ligand focus then SASA | Requires actual confirmed ligand focus, correct full identity |
| S04 | SASA residue row button | Exact residue focus on its input; does not focus latest foreign structure |
| S05 | Zero-burial synthetic case | Legitimate0.00Å², separate nonempty atoms/rows/provenance |
| S06 | SASA-result503 and retry | Independent error/recovery without stale totals |
| R01 | Geometry report create | Exact selected measurement; all rows/units/evidence |
| R02 | Geometry Markdown/JSON downloads | Bytes equal saved preview/manifest, no new calculation |
| R03 | SASA report create and both downloads | Full atom/residue data, method/area claims, exact selected result |
| R04 | Report reload/reopen | Existing exact bytes; no POST/model/tool rerun solely to read |
| R05 | Geometry/SASA report failures and retries | Explicit error/no false preview; other measured result remains |
| R06 | Held B report response after selecting A | A preview/download cannot be overwritten by B |
| O01 | OpenMM preflight on1HSG | Actual missing-OXT typed message, no reservation/energy |
| O02 | OpenMM1UBQ exclusions disclosure | Protein-only/58waters/complete input and H policy visible |
| O03 | Each policy checkbox + submit disabled states | Both explicit policies required; input/run change resets them |
| O04 | Submit and start without prior approval | Queued/approval required; no premature expense/engine launch |
| O05 | Explicit high-cost approval then start | Actual worker, one reservation, live state/budget refresh |
| O06 | Actual normal completion | Native finite potentials kJ/mol, counts, no convergence/affinity claims |
| O07 | Minimized coordinates / original return | Actual separate source and truthful minimized legend; original contacts not applied |
| O08 | OpenMM report create and both downloads | Exact native values/rounding/System/mapping links |
| O09 | Job selection/reopen | Correct job/input/result; immutable report and preparation survive |
| O10 | Queued cancellation | No launched attempt/expensive charge |
| O11 | Running cancellation after worker_started | Actual cleanup, charged once, no energy; preparation only if actually completed |
| O12 | Retry a genuine failed/cancelled attempt | Explicit bounded new attempt, correct job/input/settings/charge; no bypass of approval/cleanup |
| O13 | Result503 and report503 separately, retries | One successful parallel read cannot erase the other's error |
| O14 | Late submit/start/approve/create across run switch | No stale UI mutation or unintended second start |
| B01 | Budget topbar and detailed meter | Actual recorded expense/wall/token/USD, including failures/cancel |
| B02 | Capability unavailable entries | PyRosetta methods honestly unavailable; no fake score or enabled dead action |
| B03 | Dry-run/offline recorded run reopen | Accurate badge and blocked physical/model behavior |
| B04 | Busy/history/minimized disabled controls | Reason explained; no hidden action despite disabled UI |
| B05 | Gallery route, if retained | Explicit design examples; unimplemented demo controls cannot masquerade as production capabilities |

Job retry preconditions that cannot be created by a visible normal control may be prepared by a documented local API/fixture setup, then the **actual retry button** is clicked. Record this distinction; do not call the setup itself a clicked product flow. Do not add a new timeout editor or unsupported protocol solely to make QA easier.

## New prompt/agent controls and adversarial cases

| ID | Interaction | Required observation |
| --- | --- | --- |
| A01 | Prompt composer empty/oversize, submit button, Enter shortcut | Validation and accessible busy state; exactly one intent per submit |
| A02 | Local command examples across all six action kinds | Actual representation/selection/camera ack; source=local_command; zero transport |
| A03 | Natural-language send while local_only | Honest offline guidance; no fake model result or hidden transmission |
| A04 | Payload preview/target catalog/scope selection | Exact source/session and safe identifiers, no coordinates/sequence/source path/key |
| A05 | Explicit online enable/disable and cap display | Persisted truthful mode/scoped consent; no automatic OpenMM approval |
| A06 | Actual live compound representation+residue prompt | Real served pin+usage, typed plan, nonempty exact loci and final rendered change |
| A07 | Actual live ligand+camera prompt | Correct distinct ligand alias/model; real zoom/focus acknowledgment |
| A08 | Actual live clear/reset/representation prompt | Actual state cleared/reset and changed representation, not only transcript text |
| A09 | Double click/same request retry | One physical outbound request; duplicate plan cannot apply twice |
| A10 | Stop before dispatch / during response / during application | Visible cancelled/partial status; no late unacknowledged command; honest charges/delivery |
| A11 | Disable online during pending request | New dispatch denied and old plan invalidated; no claims of unsending a delivered request |
| A12 | Switch run/model/history/minimized source before response | No cross-scene command or stale applied acknowledgment |
| A13 | Manual viewer action while model pending | Newer user intent preserved; old plan stale/rejected |
| A14 | Unavailable key/provider, timeout, invalid model/choice | Visible failure; no fallback disguised as model; usage still settled when known |
| A15 | Ambiguous/unlisted target, malformed plan, injection text | No arbitrary code/files/tools; exact aliases only; no unintended first target |
| A16 | Request cap/budget exhausted; toggle off/on | No transport; consent counter cannot reset silently |
| A17 | WebGL not-ready/failure or lost command ack | No applied claim; safe manual/retry path without duplicate model call |
| A18 | Reload intent history and stale browser session | No automatic resend or command replay; prior browser ack remains attributed |
| A19 | Multiple browser clients/same run | Session/generation separation; one client cannot acknowledge another's plan |
| A20 | Final end-to-end user prompt demonstration | Actual user text→production gate→pinned served response→typed commands→Mol* applied ack with source-bound evidence |

Live A06–A08 may cover multiple viewer actions per call. At most4 physical live model requests total under the dedicated consent cap; use deterministic injected transports for A09–A19 error/race cases and label them. No server credential is printed or included in screenshots. A model's unsupported/ambiguous answer is not edited into a successful fixture answer.

## Completion and review

After Sol terminal, record full backend/harness/Ruff, frontend tests/typecheck/build and actual offscreen evidence on stable source hashes. Preserve old M5/M6/M7 report bytes; independently replay saved scientific/agent records without model/engine/process launches. A browser acknowledgment is evidence of UI state, not scientific validation; retain independent physical calculations. Every inventory row must be passed, explicitly unsupported/disabled with verified reason, or an unresolved failure. No unresolved functional blocker may be hidden in “tested all”. Document narrow nonblocking limits with evidence.

Astra reviews the final implementation, actual provider/usage evidence, offscreen identity, clicked state transitions, screenshot completion and downloads, then writes current M8/shared-source review. Parent records the new phase and actual --verify/commit only afterward. Earlier M7 tests/headless-browser evidence remain historical and do not prove the new user-requested offscreen test run.
