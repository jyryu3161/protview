const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const source = fs.readFileSync(path.join(__dirname, "../src/lib/viewer-scene.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require, TextEncoder });
const { withViewerSceneUpdate, commandTargetsCurrentScene, advanceSceneGeneration, cameraChanged,
  viewerPromptAllowed } = moduleObject.exports;
const bindingSource = fs.readFileSync(path.join(__dirname, "../src/lib/saved-scene.ts"), "utf8");
const bindingCompiled = ts.transpileModule(bindingSource, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;
const bindingModule = { exports: {} };
vm.runInNewContext(bindingCompiled, { module: bindingModule, exports: bindingModule.exports, require });
const { nativeTokenAfterBinding } = bindingModule.exports;

const session = {
  viewer_session_id: "session-a", client_instance_id: "client-a", scene_generation: 3,
  structure_handle: "structure-a", catalog_hash: "catalog-a", action_revision: 5,
  representation: "cartoon", selected_alias: null,
  projection: { schema: "viewer_intent@1", representation: "cartoon", selected_target: null,
    scope_complete: false, catalog: [{ alias: "t0001", category: "polymer", chain_auth: "A", seq_auth: 25 }] },
};
const command = {
  schema: "viewer_plan@1", viewer_session_id: "session-a", client_instance_id: "client-a",
  scene_generation: 3, structure_handle: "structure-a", catalog_hash: "catalog-a",
  action_revision: 5, command_id: "command-a", intent_id: "intent-a", axis: "camera", value: "reset",
};
const observed = { ready: true, sourceHandle: "structure-a", sessionId: "session-a", generation: 3 };

test("manual scene change immediately updates the visible outbound projection", () => {
  const next = withViewerSceneUpdate(session, {
    representation: "surface", selected_alias: "t0001", action_revision: 6,
  });
  assert.equal(next.projection.representation, "surface");
  assert.equal(next.projection.selected_target, "t0001");
  assert.deepEqual(next.projection.catalog, session.projection.catalog);
  assert.equal(session.projection.representation, "cartoon", "prior durable view stays immutable");
  assert.equal(next.action_revision, 6);
});

test("ordinary focus keeps confirmed selection through matching acknowledgement and publishes success afterward", async () => {
  const selected = { ...session, selected_alias: "t0001", action_revision: 9 };
  const next = withViewerSceneUpdate(selected, { representation: selected.representation,
    selected_alias: selected.selected_alias, action_revision: selected.action_revision + 1 });
  assert.equal(next.selected_alias, "t0001");
  assert.equal(next.projection.selected_target, "t0001");
  assert.equal(next.action_revision, 10);
  const binding = value => ({ sessionId: value.viewer_session_id, clientId: value.client_instance_id,
    generation: value.scene_generation, sourceHandle: value.structure_handle,
    catalogHash: value.catalog_hash, actionRevision: value.action_revision });
  let token = nativeTokenAfterBinding(4, binding(selected), binding(next));
  assert.equal(token, 5);
  let release;
  let applied = 0;
  const focus = new Promise(resolve => { release = resolve; }).then(() => {
    if (token === 5) applied += 1;
  });
  // The old native residue is still selected while focus is pending, so page
  // props and the optimistic session agree without a second revision.
  const selectedPropAlias = "t0001";
  assert.equal(next.selected_alias, selectedPropAlias);
  const acknowledged = { ...next, projection: { ...next.projection } };
  token = nativeTokenAfterBinding(token, binding(next), binding(acknowledged));
  assert.equal(token, 5);
  release(); await focus;
  assert.equal(applied, 1);
  const focused = withViewerSceneUpdate(next, { representation: next.representation,
    selected_alias: "t0002", action_revision: 11 });
  assert.equal(focused.selected_alias, "t0002");
  const representationChange = withViewerSceneUpdate(next, { representation: "surface",
    selected_alias: "t0001", action_revision: 11 });
  assert.equal(nativeTokenAfterBinding(token, binding(next), binding(representationChange)), 6);
});

test("a genuinely newer manual action selecting the same old alias still revokes held focus", async () => {
  const selected = { ...session, selected_alias: "t0001", action_revision: 9 };
  const pending = withViewerSceneUpdate(selected, { representation: selected.representation,
    selected_alias: "t0001", action_revision: 10 });
  const bind = value => ({ sessionId: value.viewer_session_id, clientId: value.client_instance_id,
    generation: value.scene_generation, sourceHandle: value.structure_handle,
    catalogHash: value.catalog_hash, actionRevision: value.action_revision });
  let token = nativeTokenAfterBinding(4, bind(selected), bind(pending));
  let release, applied = 0;
  const held = new Promise(resolve => { release = resolve; }).then(() => {
    if (token === 5) applied += 1;
  });
  const newer = withViewerSceneUpdate(pending, { representation: pending.representation,
    selected_alias: "t0001", action_revision: 11 });
  assert.equal(newer.selected_alias, "t0001");
  token = nativeTokenAfterBinding(token, bind(pending), bind(newer));
  release(); await held;
  assert.equal(token, 6);
  assert.equal(applied, 0);
});

test("late plan is rejected after manual revision, source or scene changes", () => {
  assert.equal(commandTargetsCurrentScene(command, session, observed), true);
  assert.equal(commandTargetsCurrentScene(command, { ...session, action_revision: 6 }, observed), false);
  assert.equal(commandTargetsCurrentScene(command, session, { ...observed, ready: false }), false);
  assert.equal(commandTargetsCurrentScene(command, session, { ...observed, sourceHandle: "structure-b" }), false);
  assert.equal(commandTargetsCurrentScene(command, session, { ...observed, generation: 4 }), false);
  assert.equal(commandTargetsCurrentScene({ ...command, catalog_hash: "other-catalog" }, session, observed), false);
  assert.equal(commandTargetsCurrentScene({ ...command, client_instance_id: "other-browser" }, session, observed), false);
});

test("catalog scope and displayed source each advance the same client generation", () => {
  const initial = { key: null, generation: 0 };
  const sourceA = advanceSceneGeneration(initial, "source-a/all");
  assert.equal(sourceA.generation, 1);
  assert.equal(advanceSceneGeneration(sourceA, "source-a/all"), sourceA);
  const narrowed = advanceSceneGeneration(sourceA, "source-a/chain-B");
  assert.equal(narrowed.generation, 2);
  const sourceB = advanceSceneGeneration(narrowed, "source-b/all");
  assert.equal(sourceB.generation, 3);
});

test("orbit-only camera reset counts as an observed change", () => {
  const before = { position: [0, 0, 20], target: [0, 0, 0], radius: 10, distance: 20 };
  assert.equal(cameraChanged(before, { ...before, position: [20, 0, 0] }), true);
  assert.equal(cameraChanged(before, { ...before, position: [0, 0, 20] }), false);
  assert.equal(cameraChanged(before, { ...before, distance: 16 }), true);
});

test("Enter and button share offline, dry-run and prompt validation", () => {
  assert.equal(viewerPromptAllowed("Show surface", false, false), false);
  assert.equal(viewerPromptAllowed("Show surface", true, false), true);
  assert.equal(viewerPromptAllowed("Show surface", true, true), false);
  assert.equal(viewerPromptAllowed("/zoom in", false, false), true);
  assert.equal(viewerPromptAllowed("/zoom in", false, true), true);
  for (const value of ["", "  ", "x".repeat(513), "bad\0prompt", "bad\u0081prompt"])
    assert.equal(viewerPromptAllowed(value, true, false), false, value.slice(0, 20));
});
