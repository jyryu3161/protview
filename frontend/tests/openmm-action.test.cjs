const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const source = fs.readFileSync(path.join(__dirname, "../src/lib/openmm-action.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const { currentOpenmmAction, currentOpenmmBudgetRequest, formatEnergy2,
  openmmContextChange, selectedOpenmmReadError } = moduleObject.exports;

test("late OpenMM action cannot commit after run, input, job, result or newer action changes", () => {
  const request = { epoch: 3, runId: "run-a", input: "prepared-a", jobId: "job-a", result: "result-a", action: 7 };
  assert.equal(currentOpenmmAction(request, { ...request }), true);
  for (const [field, value] of Object.entries({ epoch: 4, runId: "run-b", input: "prepared-b", jobId: "job-b", result: "result-b", action: 8 })) {
    assert.equal(currentOpenmmAction(request, { ...request, [field]: value }), false, field);
  }
});

test("energy display uses checked decimal half-up for positive and negative ties", () => {
  assert.equal(formatEnergy2(1.005), "1.01");
  assert.equal(formatEnergy2(-1.005), "-1.01");
  assert.equal(formatEnergy2(-0.005), "-0.01");
  assert.equal(formatEnergy2(-0.0001), "0.00");
  assert.equal(formatEnergy2(1e-7), "0.00");
  assert.equal(formatEnergy2(Number.POSITIVE_INFINITY), "invalid");
});

test("policy and visible errors reset only when their OpenMM context changes", () => {
  const a = { runId: "run-a", input: "prepared-a", jobId: "job-a" };
  assert.deepEqual({ ...openmmContextChange(null, a) }, { resetPolicy: false, resetErrors: false });
  assert.deepEqual({ ...openmmContextChange(a, a) }, { resetPolicy: false, resetErrors: false });
  assert.deepEqual({ ...openmmContextChange(a, { ...a, jobId: "job-b" }) }, { resetPolicy: false, resetErrors: true });
  assert.deepEqual({ ...openmmContextChange(a, { ...a, input: "prepared-b" }) }, { resetPolicy: true, resetErrors: true });
  assert.deepEqual({ ...openmmContextChange(a, { ...a, runId: "run-b" }) }, { resetPolicy: true, resetErrors: true });
});

test("result and report failures stay independent in either completion order", () => {
  const resultKey = JSON.stringify(["run-a", "result-a"]);
  const reportKey = JSON.stringify([resultKey, "report-a"]);
  let resultError = { key: resultKey, message: "result HTTP 503" };
  let reportError = null;
  assert.equal(selectedOpenmmReadError(resultError, resultKey), "result HTTP 503");
  assert.equal(selectedOpenmmReadError(reportError, reportKey), null);
  reportError = { key: reportKey, message: "report HTTP 503" };
  resultError = null;
  assert.equal(selectedOpenmmReadError(resultError, resultKey), null);
  assert.equal(selectedOpenmmReadError(reportError, reportKey), "report HTTP 503");
  assert.equal(selectedOpenmmReadError(reportError, JSON.stringify([resultKey, "report-b"])), null);
});

test("a delayed budget response cannot replace another run or newer job snapshot", () => {
  const a = { request: 5, epoch: 3, runId: "run-a", jobId: "job-a" };
  assert.equal(currentOpenmmBudgetRequest(a, { ...a }), true);
  for (const changed of [{ request: 6 }, { epoch: 4 }, { runId: "run-b" }, { jobId: "job-b" }])
    assert.equal(currentOpenmmBudgetRequest(a, { ...a, ...changed }), false);
});

test("OpenMM page actions use the live identity guard on success, error and cleanup", () => {
  const page = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf8");
  const actions = ["checkOpenmmInput", "submitOpenmm", "startOpenmm", "approveOpenmm", "cancelOpenmm", "retryOpenmm", "createOpenmmReport"];
  for (const name of actions) {
    const start = page.indexOf(`async function ${name}(`);
    assert.ok(start >= 0, `${name} exists`);
    const end = page.indexOf("\n  async function ", start + 1);
    const body = page.slice(start, end < 0 ? undefined : end);
    assert.match(body, /actionIdentity\(\)/, `${name} captures live identity`);
    assert.match(body, /actionCurrent\(request\)/, `${name} checks identity after awaiting`);
    assert.match(body, /catch \(e\).*actionCurrent\(request\)/s, `${name} guards late errors`);
    if (name === "submitOpenmm" || name === "startOpenmm" || name === "approveOpenmm")
      assert.match(body, /finally \{ if \(actionCurrent\(request\)\) setOpenmmBusy\(false\)/,
        `${name} cannot clear a newer action's busy state`);
  }
  assert.match(page, /if \(actionCurrent\(request\)\) \{ setOpenmmError\(""\); await startOpenmm\(jobId\); \}/,
    "approval follow-up keeps the captured job");
  assert.match(page, /if \(actionCurrent\(request\)\) setSavedReports\(reports\)/,
    "report list refresh checks the current result");
  assert.match(page, /setOpenmmResult\(null\);[\s\S]*api\.openmm\(/,
    "saved result read clears a previous preview");
  assert.match(page, /setOpenmmReport\(null\);[\s\S]*api\.openmmReport\(/,
    "saved report read clears a previous preview");
  const resultEffect = page.slice(page.indexOf('api.openmm(runId, openmmOutput)'), page.indexOf('api.openmmReport(runId, savedOpenmmReport.handle)'));
  const reportEffect = page.slice(page.indexOf('api.openmmReport(runId, savedOpenmmReport.handle)'), page.indexOf('async function checkOpenmmInput'));
  assert.doesNotMatch(resultEffect, /setOpenmmReportError\(/);
  assert.doesNotMatch(reportEffect, /setOpenmmResultError\(/);
  assert.match(page, /setOpenmmViewHandle\(null\); setViewIntent\("latest_pipeline"\)/);
  assert.match(page, /onSelect=\{step => \{ exitSceneOverride\(\); setOpenmmViewHandle\(null\); setViewIntent\("step"\)/);
  assert.match(page, /refreshOpenmmBudget\(runId, openmmJobId, ticket\)/);
  assert.match(page, /currentOpenmmBudgetRequest\(\{ request, epoch: ticket, runId: id, jobId \}/);
});
