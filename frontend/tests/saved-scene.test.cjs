const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/saved-scene.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const { bindingMatches, nativeOperationBound, nativeRepresentationIntentCurrent, nativeTokenAfterBinding,
  cameraMatches, desiredSceneSelection, exactResidue, restoreCatalogScope,
  mergeSavedRows, sameResidue, sceneMatches } = moduleObject.exports;

const camera = { mode: "perspective", fov: 0.8, position: [1, 2, 40], up: [0, 1, 0],
  target: [0, 0, 0], radius: 10, radiusMax: 20, fog: 50, clipFar: true, minNear: 0, minFar: 0 };
const residue = { model_number: 2, chain_auth: "A", chain_label: null, seq_auth: 42,
  seq_label: null, icode: "A", resname: "GLY" };

test("full native camera accepts readback roundoff but preserves all eleven fields", () => {
  const close = { ...camera, position: [1.00005, 2, 40], fov: 0.8000005,
    up: [0, 1.0000005, 0], radius: 10.00005 };
  assert.equal(cameraMatches(close, camera), true);
  for (const changed of [
    { fov: 0.80001 }, { fog: 50.00001 }, { up: [0.00001, 1, 0] },
    { position: [1.01, 2, 40] }, { mode: "orthographic" }, { clipFar: false },
    { radiusMax: 21 }, { minNear: 0.01 }, { minFar: 0.01 },
  ]) assert.equal(cameraMatches({ ...camera, ...changed }, camera), false, JSON.stringify(changed));
});

test("selection retains model, insertion and nullable label identity", () => {
  const projected = exactResidue({ ...residue, atom_count: 45, category: "nonpolymer" });
  assert.deepEqual({ ...projected }, residue);
  assert.equal(Object.hasOwn(projected, "atom_count"), false);
  assert.throws(() => exactResidue({ ...residue, model_number: undefined }), /model number/);
  assert.equal(sameResidue(residue, { ...residue }), true);
  assert.equal(sameResidue(null, null), true);
  assert.equal(sameResidue(null, residue), false);
  for (const changed of [{ model_number: 1 }, { icode: "" }, { seq_label: 42 },
    { chain_label: "A" }, { chain_auth: "B" }, { seq_auth: 43 }, { resname: "ALA" }])
    assert.equal(sameResidue(residue, { ...residue, ...changed }), false, JSON.stringify(changed));
  const scene = { structure_handle: "source-a", selection: residue, representation: "surface", camera, theme: "dark" };
  assert.equal(sceneMatches({ ...scene, camera: { ...camera, position: [1.00005, 2, 40] } }, scene), true);
  assert.equal(sceneMatches({ ...scene, selection: { ...residue, icode: "" } }, scene), false);
  assert.equal(sceneMatches({ ...scene, structure_handle: "source-b" }, scene), false);
  assert.equal(sceneMatches({ ...scene, representation: "cartoon" }, scene), false);
  assert.equal(sceneMatches({ ...scene, theme: "light" }, scene), false);
});

test("cloned bridge binding matches values; every stale field is rejected", () => {
  const binding = { sessionId: "session-a", clientId: "client-a", generation: 5,
    sourceHandle: "source-a", catalogHash: "catalog-a", actionRevision: 7 };
  assert.equal(bindingMatches({ ...binding }, binding), true);
  assert.equal(bindingMatches(null, binding), false);
  for (const changed of [{ sessionId: "session-b" }, { clientId: "client-b" }, { generation: 6 },
    { sourceHandle: "source-b" }, { catalogHash: "catalog-b" }, { actionRevision: 8 }])
    assert.equal(bindingMatches({ ...binding, ...changed }, binding), false, JSON.stringify(changed));
});

test("identical acknowledgement preserves held native focus; every changed binding revokes it", async () => {
  const binding = { sessionId: "session-a", clientId: "client-a", generation: 5,
    sourceHandle: "source-a", catalogHash: "catalog-a", actionRevision: 7 };
  let token = nativeTokenAfterBinding(0, null, binding);
  const expected = token;
  let release;
  let applied = 0;
  const held = new Promise(resolve => { release = resolve; }).then(() => {
    if (token === expected) applied += 1;
  });
  token = nativeTokenAfterBinding(token, binding, { ...binding });
  assert.equal(token, expected, "byte-for-byte matching server ack cannot cancel held focus");
  release(); await held;
  assert.equal(applied, 1);
  for (const changed of [null, { actionRevision: 8 }, { sourceHandle: "source-b" },
    { sessionId: "session-b" }, { clientId: "client-b" }, { generation: 6 },
    { catalogHash: "catalog-b" }]) {
    const next = changed === null ? null : { ...binding, ...changed };
    let cancelledFocusApplied = 0;
    let unblock;
    const pending = new Promise(resolve => { unblock = resolve; }).then(() => {
      if (token === expected) cancelledFocusApplied += 1;
    });
    token = nativeTokenAfterBinding(expected, binding, next);
    assert.equal(token, expected + 1, `changed binding must revoke: ${JSON.stringify(changed)}`);
    unblock(); await pending;
    assert.equal(cancelledFocusApplied, 0);
  }
});

test("held M8 native apply accepts cloned acknowledgement but rejects changed, null, and explicit cancellation", async () => {
  const binding = { sessionId: "session-a", clientId: "client-a", generation: 5,
    sourceHandle: "source-a", catalogHash: "catalog-a", actionRevision: 7 };
  async function heldApply(nextBinding, cancel = false) {
    const captured = { ...binding };
    const token = 12;
    let currentToken = token, currentBinding = captured, release;
    const pending = new Promise(resolve => { release = resolve; }).then(() =>
      nativeOperationBound(token, currentToken, currentBinding, captured));
    currentToken = nativeTokenAfterBinding(currentToken, currentBinding, nextBinding);
    currentBinding = nextBinding;
    if (cancel) currentToken += 1; // explicit bridge.cancelNative()/invalidate()
    release();
    return pending;
  }
  assert.equal(await heldApply({ ...binding }), true, "identical server acknowledgement survives an await");
  for (const change of [{ actionRevision: 8 }, { sourceHandle: "source-b" },
    { sessionId: "session-b" }, { clientId: "client-b" }, { generation: 6 },
    { catalogHash: "catalog-b" }])
    assert.equal(await heldApply({ ...binding, ...change }), false, JSON.stringify(change));
  assert.equal(await heldApply(null), false, "bind(null) revokes");
  assert.equal(await heldApply({ ...binding }, true), false, "explicit native cancellation revokes despite equal binding");
});

test("queued M8 command retains admission token through an older native operation", async () => {
  const binding = { sessionId: "session-a", clientId: "client-a", generation: 5,
    sourceHandle: "source-a", catalogHash: "catalog-a", actionRevision: 7 };
  let currentBinding = binding, currentToken = 2, manualRevision = 4, release;
  const admitted = { binding: currentBinding, token: currentToken, manualRevision };
  const older = new Promise(resolve => { release = resolve; });
  const queued = older.then(() => nativeOperationBound(admitted.token, currentToken,
    currentBinding, admitted.binding) && admitted.manualRevision === manualRevision);
  // The older operation is still running. A genuine manual cancellation must
  // not be adopted as the queued command's new baseline, even if the binding
  // is republished with exactly the same values.
  currentToken += 1; manualRevision += 1;
  currentBinding = { ...binding };
  release();
  assert.equal(await queued, false);
});

test("representation stages stop after cancellation and a newer effect intent can reconcile", async () => {
  const binding = { sessionId: "session-a", clientId: "client-a", generation: 5,
    sourceHandle: "source-a", catalogHash: "catalog-a", actionRevision: 7 };
  for (const heldStage of ["delete-main", "add-main", "delete-ligand", "add-ligand"]) {
    const stages = ["delete-main", "add-main", "delete-ligand", "add-ligand"];
    const performed = [];
    let token = 1, currentBinding = binding, unblock;
    const current = () => nativeOperationBound(1, token, currentBinding, binding);
    const stage = async name => {
      performed.push(name);
      if (name === heldStage) await new Promise(resolve => { unblock = resolve; });
      return current();
    };
    const work = (async () => {
      for (const name of stages) if (!await stage(name)) return false;
      return true;
    })();
    while (!unblock) await Promise.resolve();
    token += 1; currentBinding = { ...binding };
    unblock();
    assert.equal(await work, false);
    assert.deepEqual(performed, stages.slice(0, stages.indexOf(heldStage) + 1), heldStage);
  }
  const source = {};
  const captured = { revision: 3, source, representation: "surface" };
  assert.equal(nativeRepresentationIntentCurrent(captured,
    { revision: 3, source, representation: "surface", comparison: false }), true);
  assert.equal(nativeRepresentationIntentCurrent(captured,
    { revision: 3, source, representation: "cartoon", comparison: false }), false);
  assert.equal(nativeRepresentationIntentCurrent(captured,
    { revision: 3, source: {}, representation: "surface", comparison: false }), false);
  assert.equal(nativeRepresentationIntentCurrent(captured,
    { revision: 4, source, representation: "surface", comparison: false }), false);
  assert.equal(nativeRepresentationIntentCurrent(captured,
    { revision: 3, source, representation: "surface", comparison: true }), false);
  const newer = { revision: 4, source, representation: "cartoon" };
  assert.equal(nativeRepresentationIntentCurrent(newer,
    { revision: 4, source, representation: "cartoon", comparison: false }), true);
});

test("held UI representation reconciles after own same-scene session revision acknowledgement", async () => {
  const source = {};
  const desired = { revision: 8, source, representation: "surface" };
  let actionToken = 4, currentBinding = { sessionId: "s", clientId: "c", generation: 1,
    sourceHandle: "h", catalogHash: "sha", actionRevision: 11 };
  let release;
  const older = new Promise(resolve => { release = resolve; });
  const queued = older.then(() => nativeRepresentationIntentCurrent(desired,
    { revision: 8, source, representation: "surface", comparison: false }));
  const acknowledged = { ...currentBinding, actionRevision: 12 };
  actionToken = nativeTokenAfterBinding(actionToken, currentBinding, acknowledged);
  currentBinding = acknowledged;
  assert.equal(actionToken, 5, "M8 command authorization still revokes on changed revision");
  release();
  assert.equal(await queued, true, "the displayed surface remains the user's desired representation");
  assert.equal(nativeRepresentationIntentCurrent(desired,
    { revision: 9, source, representation: "cartoon", comparison: false }), false);
  assert.equal(nativeRepresentationIntentCurrent(desired,
    { revision: 9, source: {}, representation: "surface", comparison: false }), false);
});

test("catalog observation leaves held selected and empty restores intact; real clear and orbit revoke", async () => {
  const binding = { sessionId: "session-a", clientId: "client-a", generation: 5,
    sourceHandle: "source-a", catalogHash: "catalog-a", actionRevision: 7 };
  for (const saved of [residue, null]) {
    const token = nativeTokenAfterBinding(0, null, binding);
    const expectedManual = 3;
    let currentToken = token, currentManual = expectedManual, manualCallbackCount = 0, release;
    const held = new Promise(resolve => { release = resolve; }).then(() =>
      currentToken === token && currentManual === expectedManual &&
      bindingMatches(binding, binding) && desiredSceneSelection(true, saved, null) === saved);
    // Catalog readback changes neither native token nor the manual callback.
    assert.equal(manualCallbackCount, 0);
    release(); assert.equal(await held, true);
    for (const manualKind of ["empty-canvas clear", "orbit"]) {
      let unblock, completed = false;
      const pending = new Promise(resolve => { unblock = resolve; }).then(() => {
        if (currentToken === token && currentManual === expectedManual) completed = true;
      });
      currentManual += 1; manualCallbackCount += 1;
      currentToken = nativeTokenAfterBinding(token, binding, { ...binding, actionRevision: 8 });
      unblock(); await pending;
      assert.equal(completed, false, manualKind);
      assert.equal(currentToken, token + 1, manualKind);
      assert.equal(manualCallbackCount > 0, true, manualKind);
      currentToken = token; currentManual = expectedManual;
    }
  }
});

test("delayed list read preserves local immutable saves and selected handle", () => {
  const old = { handle: "old", value: { name: "Old" } };
  const savedWhileReading = { handle: "new", value: { name: "New" } };
  const result = mergeSavedRows([savedWhileReading], [old]);
  assert.deepEqual(Array.from(result, row => row.handle), ["new", "old"]);
  assert.deepEqual(Array.from(mergeSavedRows(result, [savedWhileReading, old]), row => row.handle), ["new", "old"]);
  assert.equal(result.find(row => row.handle === "new"), savedWhileReading);
});

test("saved selection seeds only pending restore; manual clear wins afterward", () => {
  assert.equal(desiredSceneSelection(true, residue, null), residue);
  assert.equal(desiredSceneSelection(false, residue, null), null);
  const later = { ...residue, seq_auth: 43 };
  assert.equal(desiredSceneSelection(false, residue, later), later);
});

test("restore scopes only catalogs above 256 and names the exact authoritative target", () => {
  const rows = Array.from({ length: 257 }, (_, index) => ({ ...residue, seq_auth: index + 1,
    icode: index === 256 ? "A" : "" }));
  const selected = rows[256];
  assert.deepEqual({ ...restoreCatalogScope(rows.slice(0, 256), rows[255]) }, { kind: "full", index: "" });
  assert.deepEqual({ ...restoreCatalogScope(rows, selected) }, { kind: "exact", index: "257" });
  assert.deepEqual({ ...restoreCatalogScope(rows, { ...selected, icode: "" }) }, { kind: "missing", index: "" });
  assert.deepEqual({ ...restoreCatalogScope(rows, null) }, { kind: "full", index: "" });
});
