# Test-only viewer agent fixture

`server.py` mounts the real workspace API on a separate loopback port and
replaces only its viewer egress gate with an in-process `httpx.MockTransport`.
The responses are labeled fixtures. No real model decision or provider socket
is used, and the launcher removes `OPENROUTER_API_KEY` from its child and
Electron environments. Run data lives in the supplied artifacts directory,
outside the repository and the normal user's run root.

After the root QA owner starts a stable production frontend build, use a **new**
artifact directory for each run:

```sh
node backend/tests/offscreen_agent_fixture/qa.cjs \
  --frontend http://127.0.0.1:3000 \
  --fixture-port 8011 \
  --artifacts /tmp/protview-qa/m8-agent-fixture-attempt-1
```

The runner launches actual hidden GPU Electron, proxies only `/api/**` from
that renderer to the isolated fixture API, and sends real UI clicks, drags,
reloads, and uploads. It writes `adversarial.jsonl` plus actual page and
Electron paint images. A case marked `pass` means those exact assertions
passed under a **fault fixture**; it is not evidence of a live Jev response.
The root's separate live A06–A08/A20 proof uses the normal API and provider
budget. A failed case remains failed until rerun against a stable build.

The supplementary run covers A12 history, model, and minimized-source changes
while a fixture model response is held, plus A15 clarification. It copies an
already completed real CPU OpenMM run **into the isolated fixture root**;
copying does not run the engine or edit the accepted original:

```sh
node backend/tests/offscreen_agent_fixture/qa.cjs \
  --supplement \
  --frontend http://127.0.0.1:3000 \
  --fixture-port 8011 \
  --copy-run /tmp/protview-qa/m8-runs/run_31f0ddd9d86347aa89ab8ef227525717 \
  --model-fixture /tmp/protview-qa/m8-inputs/synthetic_multimodel.pdb \
  --artifacts /tmp/protview-qa/m8-agent-supplement-attempt-1
```

The fixture control routes are test-only: `POST /__fixture/scenario`,
`POST /__fixture/release`, and `GET /__fixture/status`. The status exposes
only request path, model, schema, catalog count, and question IDs; it never
records prompt, coordinates, raw catalog, credentials, or headers.
