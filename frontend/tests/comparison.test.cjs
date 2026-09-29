const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/comparison.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require, setTimeout, clearTimeout, Promise });
const { alignmentMat4, transformPoint, atomLabel, sameAtomRef, sameComparisonAction,
  catalogAttemptKey, catalogForAttempt, catalogResponseCurrent, retainCatalogState,
  comparisonViewChangeRevokes, comparisonViewIntentKey,
  nativeIntentCurrent, ordinaryFocusCurrent, nativeDeadline, atomPickFailure, singleSourceSceneCompatible,
  sameResidueRef, residueFromNativeSites, rowsForAuthoritativeResidue,
  validateReadyCatalog, catalogSelectionReadback } = moduleObject.exports;

test("held latest-result B survives old physical source arrival while stale A and explicit changes are rejected", async () => {
  const desired = { runId: "run/a", view: "latest_result", stepNumber: null,
    latestHandle: "structure/latest", pipelineHandle: "structure/pipeline",
    inspectionRevision: 3, sceneToken: null, openmmHandle: null,
    distanceHandle: null, comparisonHandle: null };
  const scope = comparisonViewIntentKey(desired);
  let current = { action: 1, epoch: 4, runId: "run/a", scope };
  let releaseA, releaseB;
  const a = new Promise(resolve => { releaseA = resolve; }).then(() =>
    sameComparisonAction(current, { action: 1, epoch: 4, runId: "run/a", scope }));
  current = { ...current, action: 2 };
  const b = new Promise(resolve => { releaseB = resolve; }).then(() =>
    sameComparisonAction(current, { action: 2, epoch: 4, runId: "run/a", scope }));
  // The prior Return Single source and step metadata can arrive while B is
  // held. Neither physical readiness nor asynchronously resolved targetHandle
  // changes the desired latest-result intent key.
  const physicalSourceBefore = null, physicalSourceAfter = "structure/prior";
  assert.notEqual(physicalSourceBefore, physicalSourceAfter);
  assert.equal(comparisonViewIntentKey({ ...desired }), scope);
  assert.equal(comparisonViewChangeRevokes(scope, scope), false,
    "a delayed effect for B's own view cannot abort B after admission");
  assert.equal(comparisonViewChangeRevokes(scope, "prior-view"), true,
    "an old action is revoked when the desired view changes");
  releaseB(); assert.equal(await b, true, "B still owns the enabled navigation");
  releaseA(); assert.equal(await a, false, "older A cannot install after B");
  for (const change of [
    { view: "step", stepNumber: 7 }, { latestHandle: "structure/new-latest" },
    { inspectionRevision: 4 }, { distanceHandle: "structure/explicit" },
    { comparisonHandle: "alignment/explicit" }, { runId: "run/b" },
    { pocketHandle: "prepared_structure/pocket-source" },
  ]) {
    const changedScope = comparisonViewIntentKey({ ...desired, ...change });
    assert.notEqual(changedScope, scope, JSON.stringify(change));
    assert.equal(sameComparisonAction({ ...current, scope: changedScope,
      runId: change.runId ?? current.runId }, { action: 2, epoch: 4, runId: "run/a", scope }), false);
  }
  assert.equal(sameComparisonAction({ ...current, action: 3 },
    { action: 2, epoch: 4, runId: "run/a", scope }), false, "explicit clear revokes");
  assert.equal(sameComparisonAction({ ...current, epoch: 5 },
    { action: 2, epoch: 4, runId: "run/a", scope }), false, "run epoch revokes");
  const selectedStep = { ...desired, view: "step", stepNumber: 7, latestHandle: null };
  assert.equal(comparisonViewIntentKey(selectedStep),
    comparisonViewIntentKey({ ...selectedStep, pipelineHandle: "structure/metadata-late" }));
});

test("rejected catalog cannot enter a new source read attempt before fresh GET finishes", async () => {
  const run = "run/a", handle = "structure/ref";
  const oldKey = catalogAttemptKey(run, handle, 2, 0);
  const retryKey = catalogAttemptKey(run, handle, 3, 1);
  const bad = { structure_handle: handle, viewer_source_sha256: "0".repeat(64) };
  const good = { structure_handle: handle, viewer_source_sha256: "a".repeat(64) };
  let state = { key: oldKey, catalog: bad }, requestedKey = oldKey;
  assert.equal(catalogForAttempt(state, requestedKey), bad);
  // The source reload is pending: the old bad catalog loses eligibility in
  // the render that changes the read attempt, before effect cleanup or GET.
  requestedKey = null;
  assert.equal(catalogForAttempt(state, requestedKey), null);
  requestedKey = retryKey; // source returns before the fresh catalog GET
  assert.equal(catalogForAttempt(state, requestedKey), null);
  let releaseOld, releaseFresh;
  const oldResponse = new Promise(resolve => { releaseOld = resolve; }).then(() => {
    if (catalogResponseCurrent(oldKey, requestedKey, handle, handle)) state = { key: oldKey, catalog: bad };
  });
  const freshResponse = new Promise(resolve => { releaseFresh = resolve; }).then(() => {
    if (catalogResponseCurrent(retryKey, requestedKey, handle, handle)) state = { key: retryKey, catalog: good };
  });
  releaseOld(); await oldResponse;
  assert.equal(catalogForAttempt(state, requestedKey), null, "late rejected attempt cannot poison retry");
  releaseFresh(); await freshResponse;
  assert.equal(catalogForAttempt(state, requestedKey), good);
  assert.equal(catalogForAttempt(state, catalogAttemptKey("run/b", handle, 3, 1)), null);
  assert.equal(catalogForAttempt(state, catalogAttemptKey(run, "structure/other", 3, 1)), null);
  assert.equal(catalogForAttempt(state, catalogAttemptKey(run, handle, 4, 1)), null);
});

test("moving and draft retries require current attempt and exact returned handle", () => {
  const moving = "structure/moving";
  const prior = catalogAttemptKey("run/a", moving, "alignment/one", 0);
  const retry = catalogAttemptKey("run/a", moving, "alignment/one", 1);
  const otherResult = catalogAttemptKey("run/a", moving, "alignment/two", 1);
  const oldSource = { key: prior, source: { handle: moving } };
  const oldCatalog = { key: prior, catalog: { structure_handle: moving } };
  assert.equal(catalogForAttempt(oldCatalog, retry), null);
  assert.equal(oldSource.key === retry ? oldSource.source : null, null);
  assert.equal(catalogResponseCurrent(prior, retry, moving, moving), false);
  assert.equal(catalogResponseCurrent(retry, retry, moving, moving), true);
  assert.equal(catalogResponseCurrent(retry, retry, "structure/wrong", moving), false);
  assert.equal(catalogResponseCurrent(retry, otherResult, moving, moving), false);
  const draftPrior = catalogAttemptKey("run/a", moving, 0);
  const draftRetry = catalogAttemptKey("run/a", moving, 1);
  assert.equal(catalogForAttempt({ key: draftPrior, catalog: { structure_handle: moving } }, draftRetry), null);
});

const fit = { rotation: [[0, -1, 0], [1, 0, 0], [0, 0, 1]], translation_A: [10, -7, 2] };
const ref = { structure_handle: "structure/ref", residue: { model_number: 2, chain_auth: "A",
  chain_label: null, seq_auth: 42, seq_label: null, icode: "B", resname: "GLY" },
  atom_name: "CA", altloc: "A", element: "C", site_index: 17 };

test("row-major backend fit becomes column-major native matrix without changing coordinates", () => {
  const input = [2, 3, 4];
  const transformed = transformPoint(fit, input);
  assert.deepEqual(Array.from(transformed), [7, -5, 6]);
  const matrix = alignmentMat4(fit, true);
  const native = [0, 1, 2].map(i => matrix[i] * input[0] + matrix[4 + i] * input[1] +
    matrix[8 + i] * input[2] + matrix[12 + i]);
  assert.deepEqual(native, Array.from(transformed));
  assert.deepEqual(Array.from(input), [2, 3, 4]);
  const identity = alignmentMat4(fit, false);
  assert.deepEqual([0, 1, 2].map(i => identity[i] * input[0] + identity[4 + i] * input[1] +
    identity[8 + i] * input[2] + identity[12 + i]), input);
});

test("atom label preserves model, insertion, altloc and exact site identity", () => {
  assert.match(atomLabel(ref, "moving"), /GLY A\/42B · CA alt A · model 2 · site 17/);
  assert.equal(sameAtomRef(ref, { residue: { ...ref.residue }, site_index: 17, element: "C",
    altloc: "A", atom_name: "CA", structure_handle: "structure/ref" }), true);
  for (const changed of [{ site_index: 18 }, { altloc: "B" }, { structure_handle: "structure/other" },
    { residue: { ...ref.residue, model_number: 1 } }, { residue: { ...ref.residue, icode: "" } }])
    assert.equal(sameAtomRef(ref, { ...ref, ...changed }), false);
});

test("same-run older distance, read, or report response cannot own newer comparison intent", () => {
  const expected = { action: 8, epoch: 4, runId: "run-one", scope: "ref-a/mov-b/pairs-3" };
  assert.equal(sameComparisonAction(expected, { ...expected }), true);
  for (const changed of [{ action: 9 }, { epoch: 5 }, { runId: "run-two" },
    { scope: "ref-a/mov-c/pairs-3" }, { scope: "ref-a/mov-b/pairs-4" }])
    assert.equal(sameComparisonAction({ ...expected, ...changed }, expected), false);
});

test("queued native pair focus is revoked by pointer/orbit, source operation or newer pair", () => {
  const expected = { token: 8, revision: 4, intent: 2 };
  assert.equal(nativeIntentCurrent(expected, { ...expected }), true);
  for (const changed of [{ token: 9 }, { revision: 5 }, { intent: 3 }])
    assert.equal(nativeIntentCurrent(expected, { ...expected, ...changed }), false);
});

test("queued ordinary residue focus is revoked by manual action, source or catalog change", () => {
  const catalog = {}, expected = { token: 5, revision: 8, sourceHandle: "source/a", catalog };
  assert.equal(ordinaryFocusCurrent(expected, { ...expected }), true);
  for (const changed of [{ token: 6 }, { revision: 9 }, { sourceHandle: "source/b" },
    { catalog: {} }, { catalog: null }])
    assert.equal(ordinaryFocusCurrent(expected, { ...expected, ...changed }), false);
});

test("held ordinary focus is skipped after an orbit or newer focus intent", async () => {
  const catalog = {}, expected = { token: 5, revision: 8, sourceHandle: "source/a", catalog };
  for (const newer of [{ revision: 9 }, { token: 6 }, { sourceHandle: "source/b" }]) {
    let current = { ...expected }, release, applied = 0;
    const held = new Promise(resolve => { release = resolve; }).then(() => {
      if (ordinaryFocusCurrent(expected, current)) applied += 1;
    });
    current = { ...current, ...newer };
    release(); await held;
    assert.equal(applied, 0, JSON.stringify(newer));
  }
});

test("native operation deadline is bounded and fires its failure callback once", async () => {
  let timeoutCount = 0;
  await assert.rejects(nativeDeadline(new Promise(() => {}), 8, () => timeoutCount++), /timed out/);
  assert.equal(timeoutCount, 1);
  assert.equal(await nativeDeadline(Promise.resolve("done"), 100, () => timeoutCount++), "done");
  assert.equal(timeoutCount, 1);
});

test("Measure accepts one atomic element only in ball-and-stick", () => {
  assert.equal(atomPickFailure("ball-and-stick", true, 1, true), null);
  assert.equal(atomPickFailure("cartoon", true, 1, true), "representation");
  assert.equal(atomPickFailure("surface", true, 1, true), "representation");
  assert.equal(atomPickFailure("ball-and-stick", false, 0, false), "locus");
  assert.equal(atomPickFailure("ball-and-stick", true, 2, true), "multi");
  assert.equal(atomPickFailure("ball-and-stick", true, 1, false), "non_atomic");
});

test("M9 single-source scene cannot encode active M10 measurement or overlay visuals", () => {
  assert.equal(singleSourceSceneCompatible(false, false, false, false), true);
  for (const active of [[true, false, false, false], [false, true, false, false],
    [false, false, true, false], [false, false, false, true]])
    assert.equal(singleSourceSceneCompatible(...active), false);
});

test("native PDB source indices preserve authoritative Axp and null labels, including all alt sites", () => {
  const residue = { model_number: 2, chain_auth: "A", chain_label: "Axp", seq_auth: 42,
    seq_label: null, icode: "A", resname: "GLY" };
  const rows = ["N", "CA", "CA", "CA", "C", "O"].map((atom_name, i) => ({
    ref: { structure_handle: "structure/pdb", residue, atom_name, altloc: i === 1 || i === 3 ? "A" : i === 2 ? "B" : "",
      element: atom_name === "N" ? "N" : atom_name === "O" ? "O" : "C", site_index: i },
    coordinate_A: [20 + i, 0, 0], protein: true, viewer_source_index: i,
  }));
  const catalog = { schema: "atom_catalog@1", structure_handle: "structure/pdb", model_number: 2,
    viewer_source_sha256: "sha", total: rows.length, offset: 0, limit: rows.length, rows };
  assert.deepEqual(residueFromNativeSites(catalog, [1, 2, 3]), residue);
  assert.deepEqual(rowsForAuthoritativeResidue(catalog, residue).map(row => row.ref.site_index), [0, 1, 2, 3, 4, 5]);
  assert.equal(rowsForAuthoritativeResidue(catalog, { ...residue, chain_label: "A" }).length, 0);
  assert.equal(rowsForAuthoritativeResidue(catalog, { ...residue, seq_label: 42 }).length, 0);
  assert.equal(rowsForAuthoritativeResidue(catalog, { ...residue, model_number: 1 }).length, 0);
  assert.equal(rowsForAuthoritativeResidue(catalog, { ...residue, icode: "" }).length, 0);
  assert.throws(() => residueFromNativeSites(catalog, [99]), /Unknown/);
  assert.throws(() => residueFromNativeSites({ ...catalog, rows: rows.slice(1) }, [1]), /Incomplete/);
  assert.throws(() => residueFromNativeSites({ ...catalog, rows: [rows[0], { ...rows[1], viewer_source_index: 0 }, ...rows.slice(2)] }, [0]), /Ambiguous/);
  assert.throws(() => residueFromNativeSites({ ...catalog, rows: [{ ...rows[0], ref: { ...rows[0].ref, structure_handle: "other" } }, ...rows.slice(1)] }, [0]), /Ambiguous/);
  assert.throws(() => residueFromNativeSites({ ...catalog, rows: [{ ...rows[0], ref: { ...rows[0].ref, residue: { ...residue, model_number: 1 } } }, ...rows.slice(1)] }, [0]), /Ambiguous/);
});

test("source row projection rejects mixed residues and retains exact mmCIF auth/label identities", () => {
  const a = { model_number: 1, chain_auth: "AUTH|X", chain_label: "L|1", seq_auth: 7,
    seq_label: 2, icode: "", resname: "ALA" };
  const b = { ...a, chain_auth: "AUTH", chain_label: "X|L|1" };
  assert.equal(sameResidueRef(a, b), false);
  const rows = [a, a, b].map((residue, i) => ({ ref: { structure_handle: "structure/cif", residue,
    atom_name: i === 0 ? "N" : "CA", altloc: "", element: i === 0 ? "N" : "C", site_index: i },
    coordinate_A: [i, 0, 0], protein: true, viewer_source_index: i }));
  const catalog = { schema: "atom_catalog@1", structure_handle: "structure/cif", model_number: 1,
    viewer_source_sha256: "sha", total: 3, offset: 0, limit: 3, rows };
  assert.deepEqual(residueFromNativeSites(catalog, [0, 1]), a);
  assert.throws(() => residueFromNativeSites(catalog, [0, 2]), /Mixed/);
  assert.deepEqual(rowsForAuthoritativeResidue(catalog, b).map(row => row.ref.site_index), [2]);
});

test("catalog arriving during native initialization validates only after ready and cannot commit a stale read", async () => {
  const catalog = { structure_handle: "structure/pdb", viewer_source_sha256: "sha" };
  const events = [];
  let current = true;
  let release;
  const verify = async () => { events.push("verify"); await new Promise(resolve => { release = resolve; }); };
  const commit = value => events.push(`commit:${value.structure_handle}`);
  // The HTTP catalog resolves after the loading render, before the native
  // instance exists. No validation is discarded or acknowledged in that gap.
  assert.equal(await validateReadyCatalog("loading", catalog.structure_handle, null, catalog,
    null, verify, () => current, commit), "waiting");
  assert.equal(await validateReadyCatalog("loading", catalog.structure_handle, catalog.structure_handle,
    catalog, null, verify, () => current, commit), "waiting");
  assert.deepEqual(events, []);
  const pending = validateReadyCatalog("ready", catalog.structure_handle, catalog.structure_handle,
    catalog, null, verify, () => current, commit);
  assert.deepEqual(events, ["verify"]);
  current = false; release();
  assert.equal(await pending, "stale");
  assert.deepEqual(events, ["verify"]);
  current = true;
  assert.equal(await validateReadyCatalog("ready", catalog.structure_handle, catalog.structure_handle,
    catalog, null, async () => { events.push("reverify"); }, () => current, commit), "validated");
  assert.deepEqual(events, ["verify", "reverify", "commit:structure/pdb"]);
  assert.equal(await validateReadyCatalog("ready", catalog.structure_handle, catalog.structure_handle,
    catalog, catalog, async () => { throw new Error("must not revalidate"); }, () => current, commit), "already_valid");
});

test("catalog readiness observes pending selected and empty scenes without emitting manual selection", async () => {
  let manualCallbackCount = 0;
  const selected = { model_number: 2, chain_auth: "A", chain_label: "Axp",
    seq_auth: 42, seq_label: null, icode: "A", resname: "GLY" };
  let observed = null;
  for (const pending of [selected, null]) {
    const catalog = { structure_handle: "source/a" };
    const result = await validateReadyCatalog("ready", "source/a", "source/a", catalog, null,
      async () => {}, () => true, () => { observed = catalogSelectionReadback(() => pending); });
    assert.equal(result, "validated");
    assert.equal(observed.selection, pending);
    assert.equal(observed.error, null);
    assert.equal(manualCallbackCount, 0);
  }
  // Genuine native user events are the separate caller of the manual callback.
  const genuineNativeClear = () => { manualCallbackCount += 1; };
  genuineNativeClear();
  assert.equal(manualCallbackCount, 1);
  const invalid = catalogSelectionReadback(() => { throw new Error("unknown site"); });
  assert.equal(invalid.selection, null);
  assert.match(invalid.error, /unknown site/);
});

test("a re-read of the same catalog attempt keeps the validated catalog object", () => {
  // A saved-scene restore briefly clears the display source, so the same read attempt is fetched
  // again. Mol* validation is bound to the catalog object; swapping in an equal copy mid-restore
  // made the running restore read an unvalidated catalog.
  const run = "run/a", handle = "structure/ref";
  const key = catalogAttemptKey(run, handle, 2, 0);
  const first = { structure_handle: handle, viewer_source_sha256: "a".repeat(64) };
  const state = { key, catalog: first };
  const copy = { ...first };
  assert.equal(retainCatalogState(state, key, copy), state);
  const retryKey = catalogAttemptKey(run, handle, 2, 1);
  const fresh = (next, expectedKey, expectedCatalog) => {
    assert.notEqual(next, state); assert.equal(next.key, expectedKey); assert.equal(next.catalog, expectedCatalog);
  };
  fresh(retainCatalogState(state, retryKey, copy), retryKey, copy);
  const changed = { structure_handle: handle, viewer_source_sha256: "b".repeat(64) };
  fresh(retainCatalogState(state, key, changed), key, changed);
  const other = { structure_handle: "structure/other", viewer_source_sha256: "a".repeat(64) };
  fresh(retainCatalogState(state, key, other), key, other);
  fresh(retainCatalogState(null, key, copy), key, copy);
});
