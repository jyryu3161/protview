const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/event-model.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const { latestHandles, resultEvents, resultId } = moduleObject.exports;

function handle(kind, name) {
  return { handle: `obj://r/${kind}/${name}`, kind, schema: `${kind}@1`,
    summary: {}, preview: [], null_result: false };
}
function called(seq, call_id, tool, args) {
  return { seq, ts: seq, type: "tool_called", call_id, tool, args, key: call_id,
    decided_by: "human", attempt: 1, version: "1" };
}
function succeeded(seq, call_id, tool, output, cached = false) {
  return { seq, ts: seq, type: "tool_succeeded", call_id, tool, key: call_id,
    output, null_result: false, cached };
}
function cache(seq, observation_id, source_call_id, tool, args, output) {
  return { seq, ts: seq, type: "cache_hit", observation_id, proposal_id: observation_id,
    source_call_id, tool, key: source_call_id, args, output };
}
function cacheResults(events) {
  return resultEvents(events).filter(event => event.type === "cache_hit");
}

test("reopened cache reads move the latest pipeline through physical lineage", () => {
  const l1 = handle("structure", "l1");
  const p1 = handle("prepared_structure", "p1");
  const i1 = handle("interaction_set", "i1");
  const l2 = handle("structure", "l2");
  const p2 = handle("prepared_structure", "p2");
  const i2 = handle("interaction_set", "i2");
  const events = [
    called(1, "c1", "load_structure", { source: "u1", model_index: 0 }),
    succeeded(2, "c1", "load_structure", l1),
    called(3, "c2", "prepare_structure", { structure: l1.handle }),
    succeeded(4, "c2", "prepare_structure", p1),
    called(5, "c3", "compute_interactions", { structure: p1.handle }),
    succeeded(6, "c3", "compute_interactions", i1),
    called(7, "c4", "load_structure", { source: "u2", model_index: 0 }),
    succeeded(8, "c4", "load_structure", l2),
    called(9, "c5", "prepare_structure", { structure: l2.handle }),
    succeeded(10, "c5", "prepare_structure", p2),
    called(11, "c6", "compute_interactions", { structure: p2.handle }),
    succeeded(12, "c6", "compute_interactions", i2),
    cache(13, "read1", "c1", "load_structure", { source: "u1", model_index: 0 }, l1),
    cache(14, "read2", "c2", "prepare_structure", { structure: l1.handle }, p1),
    cache(15, "read3", "c3", "compute_interactions", { structure: p1.handle }, i1),
  ];
  assert.deepEqual(JSON.parse(JSON.stringify(latestHandles(events))), {
    loaded: l1, prepared: p1, interactions: i1,
  });
  const latest = resultEvents(events).at(-1);
  assert.equal(resultId(latest), "read3");
  assert.equal(latest.source_call_id, "c3");
  assert.equal(latest.duration_s, undefined);
  assert.equal(resultEvents(events).filter(e => e.type === "cache_hit").length, 3);
  const forged = cache(16, "forged", "c3", "compute_interactions", { structure: p2.handle }, i1);
  assert.equal(resultEvents([...events, forged]).at(-1).observation_id, "read3");
  assert.equal(resultId({ ...succeeded(17, "c3", "compute_interactions", i1, true) }),
    "legacy_cache_17");
});

test("cache reads require the physical call key and source success in sequence", () => {
  const output = handle("structure", "source");
  const call = called(1, "c1", "load_structure", { source: "u1", model_index: 0 });
  const success = succeeded(2, "c1", "load_structure", output);
  const read = cache(3, "read1", "c1", "load_structure", call.args, output);
  assert.equal(cacheResults([call, success, read]).length, 1);
  assert.equal(cacheResults([{ ...call, key: "wrong" }, success, read]).length, 0);
  assert.equal(cacheResults([call, { ...success, key: "wrong" }, read]).length, 0);
  assert.equal(cacheResults([call, success, { ...read, key: "wrong" }]).length, 0);
  assert.equal(cacheResults([{ ...call, seq: 2 }, { ...success, seq: 1 }, read]).length, 0);
  assert.equal(cacheResults([call, { ...success, seq: 3 }, { ...read, seq: 3 }]).length, 0);
  assert.equal(cacheResults([call, { ...success, cached: true }, read]).length, 0);
  assert.equal(cacheResults([call, { ...success, tool: "prepare_structure" }, read]).length, 0);
  assert.equal(cacheResults([call, success, { ...read, tool: "prepare_structure" }]).length, 0);
});

test("conflicting cache observation identities cannot select another output", () => {
  const a = handle("structure", "a");
  const b = handle("structure", "b");
  const events = [
    called(1, "c1", "load_structure", { source: "u1" }),
    succeeded(2, "c1", "load_structure", a),
    cache(3, "read1", "c1", "load_structure", { source: "u1" }, a),
    called(4, "c2", "load_structure", { source: "u2" }),
    succeeded(5, "c2", "load_structure", b),
    cache(6, "read1", "c2", "load_structure", { source: "u2" }, b),
  ];
  assert.equal(cacheResults(events).length, 0);
  assert.equal([...resultEvents(events)].reverse().find(event => resultId(event) === "read1"), undefined);
  assert.equal(latestHandles(events).loaded.handle, b.handle);
  assert.equal(cacheResults([...events.slice(0, 5), { ...events[5], key: "wrong" }]).length, 0);
  assert.equal(cacheResults([events[0], events[1], { ...events[2], observation_id: "c1" }]).length, 0);
  const legacy = succeeded(3, "c1", "load_structure", a, true);
  assert.equal(cacheResults([events[0], events[1], legacy,
    cache(4, "legacy_cache_3", "c1", "load_structure", { source: "u1" }, a)]).length, 0);
});

test("canonical JSON args accept reordered objects and preserve array order", () => {
  const output = handle("structure", "canonical");
  const call = called(1, "c1", "load_structure", {
    source: "u1", options: { model_index: 0, settings: { waters: "strip", altloc: "first" } },
    selection: [{ chain: "A", seq: 1 }, { chain: "B", seq: 2 }],
  });
  const success = succeeded(2, "c1", "load_structure", output);
  const args = {
    selection: [{ seq: 1, chain: "A" }, { seq: 2, chain: "B" }],
    options: { settings: { altloc: "first", waters: "strip" }, model_index: 0 }, source: "u1",
  };
  const read = cache(3, "read1", "c1", "load_structure", args, output);
  assert.equal(cacheResults([call, success, read]).length, 1);
  assert.equal(cacheResults([call, success, { ...read, args: { ...args, selection: [...args.selection].reverse() } }]).length, 0);
  assert.equal(cacheResults([call, success, { ...read, args: { ...args, source: "u2" } }]).length, 0);
});

test("cache reads need their original input and exact output reference", () => {
  const output = handle("prepared_structure", "prepared");
  const call = called(1, "c1", "prepare_structure", { structure: "obj://r/structure/input" });
  const success = succeeded(2, "c1", "prepare_structure", output);
  const read = cache(3, "read1", "c1", "prepare_structure", call.args, output);
  assert.equal(cacheResults([call, success, read]).length, 1);
  const uuidRead = { ...read, observation_id: "7b34136b-58fd-4fcb-9fe4-397467d82666",
    proposal_id: "7b34136b-58fd-4fcb-9fe4-397467d82666" };
  assert.equal(resultId(cacheResults([call, success, uuidRead])[0]), uuidRead.observation_id);
  assert.equal(cacheResults([success, read]).length, 0);
  assert.equal(cacheResults([call, read]).length, 0);
  assert.equal(cacheResults([call, success, { ...read, source_call_id: "missing" }]).length, 0);
  assert.equal(cacheResults([call, success, { ...read, args: { structure: "obj://r/structure/other" } }]).length, 0);
  assert.equal(cacheResults([call, success, { ...read, output: { ...output, kind: "structure" } }]).length, 0);
  assert.equal(cacheResults([call, success, { ...read, output: handle("prepared_structure", "other") }]).length, 0);
  const legacy = succeeded(4, "c1", "prepare_structure", output, true);
  assert.equal(resultEvents([call, success, read, legacy]).length, 3);
  assert.equal(resultId(legacy), "legacy_cache_4");
});
