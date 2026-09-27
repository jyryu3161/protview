# M9 — saved local scenes and traceable figure export

GPT-6 Astra design/review; GPT-6 Sol implementation. 2026-09-27. Accepted predecessor `6894ab4`; actual work branch `phase/m9-scenes-export`. The user authorized implementation of the planned features while testing. This contract specifies M9 first; M10–M13 remain subsequent authorized increments, not completed or cancelled by M9. No new provider request is required or authorized by this phase. New capabilities remain pending until real gate evidence.

## Product behavior

Save the actual current viewer as a named immutable scene. Reopen the run, choose that scene and restore its exact original, prepared/historical or validated OpenMM-minimized source, model, residue selection, representation, camera and theme. Export genuine Mol* pixels as a locally saved PNG and a JSON provenance sidecar. Provide visible loading, ready, error and disabled states, retry reads without rerunning scientific/model work, and a clear return-to-current-structure action.

A scene is a local viewing artifact, not a scientific measurement, model answer or executable command. Restore/export cannot run tools/jobs, grant approval, enable online mode, reuse an old session/intent acknowledgment or fetch structures. Old scientific reports retain exact bytes. The existing local_only and immutable/recovery boundaries remain authoritative.

## Current implementation anchors and inspected native API

`frontend/app/page.tsx` currently derives `targetHandle` from history/measurement/OpenMM state; introduce an explicit saved-scene source override with priority over those derivations. Its identity must participate in `viewerContextKey` and scene generation even when restoring the same source again. `ViewerAgentPanel.tsx` currently owns session creation and binding; coordinate restore with that single owner or extract a shared controller, never create competing independent sessions. Native operations belong in the existing serialized `MolstarViewer` bridge.

The pinned installed Mol* is5.11.0. Directly inspected local declarations/implementation: `mol-canvas3d/camera.d.ts`, `camera.js`, `passes/image.d.ts`, `passes/image.js`, `canvas3d.d.ts`, and `mol-plugin/util/viewport-screenshot.js`. Camera supports `getSnapshot()` and `setState(snapshot, 0)`. Its full Snapshot fields are mode, fov, position, up, target, radius, radiusMax, fog, clipFar, minNear and minFar. The current reduced QA camera omits required orientation/projection fields and is insufficient for saved scenes. `canvas3d.getImagePass(props).getImageData(runtime, width, height)` yields actual ImageData. Follow the native screenshot implementation's owned animation-loop stop/resume in try/finally, `updateBackground()`, ImageData copy into a2D encoding canvas and PNG blob encoding. Do not use an arbitrary blank canvas, DOM mock image, external renderer or main canvas readback without an actual completed render. Keep GPU enabled. Reuse/manage the image pass within viewer lifetime and release references on disposal.

## Immutable schemas

Strict objects reject unknown keys, booleans where numbers are expected, nonfinite values and unsupported versions. Persist canonical values without timestamps/session/request IDs in content hashes. Timestamps, request UUIDs and execution attribution belong to events.

`viewer_scene@1`, kind `viewer_scene`:

```text
schema: "viewer_scene@1"
name: trimmed nonempty Unicode text, <=80 characters and <=320 UTF-8 bytes
structure_handle: exact same-run accepted immutable structure handle
structure_kind: structure | prepared_structure | openmm_minimized_structure
structure_schema: exact source schema validated by server
model_number: actual selected model number (server-derived)
selection: null | complete authoritative ResidueRef
representation: cartoon | ball_and_stick | surface
camera: CameraStateV1 below
theme: dark | light
renderer: { name: "molstar", version: "5.11.0", scene_schema: "protview_scene@1" }
```

Names are display text only: reject NUL/control characters, render escaped, never use them as filesystem paths, download names, HTML or egress context. Duplicate names are permitted and distinguished by handle; re-saving identical canonical content yields the same handle. No rename/delete workflow is required; editing means saving a new immutable scene.

Source validation reuses the same allowed kind/schema pairs and validated minimized-source path as `create_session` in `backend/mw/viewer_intents.py`. Resolve actual local bytes and `structure_residues`; reject inconsistent kind/model or a selected residue that does not match exactly one full authoritative identity. Preserve null label IDs, insertion codes and model number; do not persist Mol*'s inferred label IDs where source labels are unknown. Never accept a catalog alias as durable residue identity. Selected source is the displayed handle, never automatically the latest pipeline handle.

`CameraStateV1` is the exact11-field native allowlist above. mode is perspective/orthographic; clipFar is strict boolean. position,target,up are arrays of exactly3 finite numbers. Coordinate magnitudes <=1e7 Å; position-to-target distance in[1e-4,1e7] Å. up norm in[0.5,2], nonparallel to view direction (normalized cross-product norm >=1e-4). fov in[0.01,3.13] radians; radius in[1e-4,1e7] Å; radiusMax in[1e-4,1e7] Å and >=radius; fog in[0,100]; minNear,minFar in[0,1e7] Å. Validate captured actual supported state; reject out-of-contract state explicitly rather than silently clamp/change saved values. Viewport size is export metadata, not an identity-changing camera field.

`viewer_png@1`, kind `viewer_png`, fmt `png`: raw captured PNG bytes. Max8MiB; dimensions integer64–2048 per axis and <=4,000,000 pixels. Server validates signature/IHDR, supported PNG encoding and bounded well-formed content; reject malformed/truncated/oversized input before durable write. If a decoder is used, enforce decompressed size bounds and pin its dependency. User cannot provide filesystem paths or destinations. Filename is server-generated from handle prefix.

Additionally cap aggregate distinct persisted PNG raw bytes at64MiB per run, checked under the admission transition before writing a new PNG. Reusing an already stored identical PNG or idempotently repeating a request consumes no additional byte allocation. Reconstruct usage from durable PNG objects/events after restart; never reset the allocation on reopening. With base64 event payloads this bounds PNG event data to approximately86MiB plus metadata, avoiding an unbounded image archive in the existing whole-log reader. Keep the separate100-figure cap; on either limit return explicit resource_exceeded with the applicable limit and do not append new image bytes. Test exact-boundary, rejection, duplicate reuse and restart accounting. This selected bounded storage does not change the completed MVP event design.

`viewer_figure@1`, kind `viewer_figure`, JSON sidecar:

```text
schema: "viewer_figure@1"
scene_handle, structure_handle, model_number
png_handle, png_sha256 (SHA-256 of raw PNG bytes)
width, height, media_type: "image/png"
renderer: same pinned renderer record
capture_method: "molstar_image_pass"
provenance: "client_rendered_local_view"
limitations: fixed text that this is a rendering, not new scientific evidence
```

Server constructs authoritative source fields from the saved scene and computes image hash/dimensions from received bytes. The PNG and figure object are durable using `ObjectStore.put`; existing object_created events include enough bytes for events-only reconstruction. Browser-rendered provenance is explicitly client-reported; server image validation cannot independently prove which molecule was rendered. QA supplies that independent renderer observation. Sidecar download is the exact stored manifest (a handle envelope may be returned separately by API), not a subsequently reformatted report. Export image pixels may differ across GPU/software versions; never require future rerendered PNG byte identity. Restored stored PNG downloads must remain byte-identical.

## API and lifecycle

Suggested strict routes under `/runs/{rid}/viewer` (consistent alternatives allowed): POST/GET `/scenes`, GET `/scenes/selected?handle=...`, POST `/figures`, GET `/figures/selected?handle=...`, GET `/figures/download?handle=...&format=png|json`. Lists bounded/paginated; default50 maximum100. Detail/download verifies expected object kind/schema and same-run ownership. Scene save request includes UUID plus current session/client/generation/action_revision and captured state; server compares current scene binding and constructs validated object. Content hash does not include request UUID. Identical UUID+payload is idempotent, conflicting reuse409; deduplicate concurrent admission under short `run._transition()` as existing viewer lifecycle does. Do not hold the long scientific owner to read/download saved artifacts. Limit per-run scene/figure admissions (default100 each), and return explicit resource_exceeded on new admission beyond the cap; duplicate reads/saves remain safe.

Figure creation includes exact saved scene, current binding and bounded PNG, with the same idempotency discipline. Choose bounded multipart or strict base64 JSON (decoded8MiB plus bounded encoded body); no arbitrary metadata. Validate representation/selection and native camera/theme against saved scene before capture and immediately afterward. POST stale binding rejects; UI never labels a different current view as that saved scene. An immutable successfully persisted capture may remain listed after a later navigation, but stale completion must not change the new run/scene UI or start automatic downloads there. List persisted figures with explicit PNG/JSON download links, allowing blocked downloads to be retried locally.

Export UX is one capture followed by two explicit download links from that immutable figure handle, PNG and JSON. Both links refer to the same pair; no second capture when JSON is requested. No ZIP dependency is needed. Use fixed handle-derived filenames such as `protview-figure-<hash-prefix>.png/.json`; scene name never enters the filename. The UI states that PNG contains the molecular viewport, not the entire app, and that a saved scene must be restored/current before exporting it. Persisted PNG bytes and sidecar both replay; no image rerender is required to redownload them.

Capture is one consistent native snapshot transaction. Flush the existing same-session state mutation queue, wait for a settled frame and capture current binding/revision, source, authoritative selection, representation, camera and actual rendered theme together. Do not save a React camera guess or race a pending drag/revision POST. While capture/encode is in progress, either prevent manual canvas/theme/representation changes visibly or treat any new manual revision as invalidation and discard the pair. Recheck full native state and binding after encoding; drift means retry, never save mixed-time state. Flushing a pending valid manual action must not itself mark a valid save stale. Theme background must be committed before pixel capture and verified with the scene theme; merely setting a DOM attribute is not proof of rendered background. Theme changes are manual viewer mutations and invalidate pending M8 commands as well as in-progress restores/captures.

Restore is a fresh explicit browser action, not automatic on run reopen and not server execution. Load/validate scene, immediately invalidate pending viewer commands and current bridge binding, increment generation/restore token, set explicit source override and request actual source bytes. Wait for ready Mol*, then establish one fresh viewer session for that source. If selection is outside the current model-facing256-item catalog, create exact local target scope or maintain separate local scene selection; do not export a silently incomplete catalog or lose the saved selection. Restore does not require online consent.

Serialize native restoration in this order: representation, exact selection/clear without camera focus, theme/background commit, full camera with duration0, completed frame, readback. Existing highlight effects auto-focus and React representation effects must not overwrite the restored camera after acknowledgment. Suppress/coordinate them and synchronize authoritative page/legend/preview state only after guarded native work. Source/session/generation/action revision/restore token checks before and after every await; new run/source/restore/manual action invalidates previous work. Rapid A→B restoration must leave B authoritative. A same-source restore still uses a fresh session and generation. Do not revive cancelled/unacknowledged intents.

Bridge operations expose narrow `captureScene`, `restoreScene`, `captureFigure` behavior (names adaptable) and actual read-only QA observations. They serialize with existing native work, reject lost/not-ready WebGL, and have bounded deadlines (default15s restore/capture,30s source read). Late continuations cannot apply after timeout/invalidation. Partial native work is visibly partial/failed and reconciled to real state; do not claim rollback or applied success. Restore has no scientific budget charge; no scientific expensive approval is needed.

Successful restore means representation/theme exact, authoritative selected residue exact or genuinely empty, and native camera readback within: vectors/scalars in coordinate units max(1e-4 Å,1e-6×absolute expected component), fov/up/fog within1e-6, booleans/mode exact. Poll bounded native settled frames, not only React state. Resizing may change aspect ratio without changing the saved camera; this does not guarantee identical pixels. Save/export during pending restoration, source loading or another native capture is disabled with reason. Errors retain a manual retry path without model/scientific replay.

## Mandatory evidence

Backend: strict schema and source/selection/camera validation; foreign/wrong-kind/corrupt/missing objects; name escaping/path attacks; caps, idempotent/conflicting/concurrent requests; bounded image validation; source-linked sidecar and exact downloads; restart/event-only reconstruction including saved PNG/scene without input paths or engines/model calls; no scientific report mutation or budget/egress changes.

Frontend: actual full camera round-trip including roll/up and projection; normalized source identity; restore invalidation/manual precedence; same-source generation; no auto-focus overwrite; context loss/read error/timeouts; image encoding failure; export binding rejection; late run navigation; final toolbar/native/legend/catalog coherence. Meaningful pure frontend tests complement actual rendering, never replace it.

Actual Electron offscreen per-control QA: empty/invalid names, save/list/reopen/restore, duplicate names/identical save, original and prepared-history and real OpenMM-minimized scenes, each representation and both themes, selected/cleared and insertion/model/null-label cases, camera orbit/zoom restore, repeat/rapid restore, return-to-current, disabled busy/not-ready, fixture read failure/retry, context loss, genuine exported PNG+JSON downloads and decoded dimensions/nonblank content/hash/provenance, stored artifact redownload after replay. Preserve original failed captures/repairs. Record isOffscreen true/nonvisible/GPU/WebGL/paint/build/source hashes; directly inspect representative restored scenes and exported PNGs. All runtime requests loopback; no fresh provider call. Saved reports before/after must preserve bytes.

M9 review lists changed shared-source coverage explicitly and supersedes only those earlier review hashes, retaining all old review/report artifacts. Full shared regressions and fresh original/history/minimized workflows are required before completion. Parent owns phase recording, actual verify and Git transitions.
