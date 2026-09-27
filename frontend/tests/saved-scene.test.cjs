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
const { bindingMatches, cameraMatches, desiredSceneSelection, exactResidue, restoreCatalogScope,
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
