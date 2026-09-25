"use strict";

// Real UI path on an isolated QA backend. Never run against the accepted default run root.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { launchOffscreen, capture, status, downloadByClick } = require("./driver.cjs");
const { sha256, sourceDigest, waitForViewer, waitForBoot,
  assertViewer, validateReportDownload } = require("./normal-flow.cjs");

function parse(argv) {
  const input = { url: null, fixture: null, artifacts: null, mode: "full" };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--url") input.url = argv[++i];
    else if (argv[i] === "--fixture") input.fixture = argv[++i];
    else if (argv[i] === "--artifacts") input.artifacts = argv[++i];
    else if (argv[i] === "--mode") input.mode = argv[++i];
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  if (!input.url || !input.fixture || !input.artifacts || !["full", "queued-cancel", "running-cancel"].includes(input.mode))
    throw new Error("Usage: openmm-flow.cjs --url LOOPBACK --fixture public_1ubq.cif --artifacts PATH [--mode full|queued-cancel|running-cancel]");
  const url = new URL(input.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("QA URL must be loopback HTTP(S)");
  input.fixture = path.resolve(input.fixture);
  input.artifacts = path.resolve(input.artifacts);
  if (!fs.statSync(input.fixture).isFile()) throw new Error("Fixture is not a file");
  return input;
}

async function readJson(url) {
  const response = await fetch(url);
  assert.equal(response.status, 200, `Read-only QA request failed: ${url}`);
  return response.json();
}

async function runOpenmm(input) {
  const session = await launchOffscreen(input);
  const { app, page, artifacts } = session;
  const evidence = path.join(artifacts, `openmm-${input.mode}.jsonl`);
  const source = sourceDigest();
  const fixtureSha256 = sha256(input.fixture);
  const rows = [];
  let runId;
  let preparedHandle;
  let jobId;

  async function step(caseId, description, action, observe) {
    const before = await status(app, page);
    const started = Date.now();
    let row;
    try {
      await action();
      const assertion = await observe(await status(app, page));
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.offscreen, true);
      assert.equal(proof.status.visible, false);
      assert.equal(proof.status.blockedRequests.length, 0);
      row = { caseId, status: "pass", source, fixtureSha256, description, before,
        after: proof.status, assertion, screenshot: proof.screenshot, paint: proof.paint,
        durationMs: Date.now() - started };
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* preserve first failure */ }
      row = { caseId, status: "fail", source, fixtureSha256, description, before,
        after: proof?.status, screenshot: proof?.screenshot, paint: proof?.paint,
        error: String(error), durationMs: Date.now() - started };
      fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
      rows.push(row);
      throw error;
    }
    fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
    rows.push(row);
    return row;
  }

  try {
    await step("O-setup-run", "Click 새 run for isolated 1UBQ OpenMM QA", async () => {
      await waitForBoot(page);
      const previous = new URL(page.url()).searchParams.get("run");
      await page.getByRole("button", { name: "새 run" }).click();
      await page.waitForFunction(old => {
        const next = new URL(location.href).searchParams.get("run");
        const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
        return !!next && next !== old && !!button && !button.disabled;
      }, previous);
      runId = new URL(page.url()).searchParams.get("run");
    }, async () => {
      assert.match(runId, /^run_/);
      assert.match(await page.locator("body").innerText(), /local_only/);
      return { runId };
    });

    await step("O-setup-upload", "Choose public 1UBQ mmCIF through native file input", async () => {
      const chooser = page.waitForEvent("filechooser");
      await page.locator('input[type="file"]').click();
      await (await chooser).setFiles(input.fixture);
      await page.getByRole("button", { name: "구조 불러오기" }).waitFor({ timeout: 20000 });
    }, async () => ({ fixtureSha256, filename: path.basename(input.fixture) }));

    await step("O-setup-load", "Click 1UBQ model load", async () => {
      await page.getByRole("button", { name: "구조 불러오기" }).click();
      await page.getByRole("button", { name: "전처리", exact: true }).waitFor({ timeout: 20000 });
      await waitForViewer(page);
    }, async after => ({ viewer: assertViewer(after) }));

    await step("O-setup-policy", "Select keep_all water policy so exclusions remain inspectable", async () => {
      await page.getByRole("combobox", { name: /^물/ }).selectOption("keep_all");
    }, async () => {
      assert.equal(await page.getByRole("combobox", { name: /^물/ }).inputValue(), "keep_all");
      return { waterPolicy: "keep_all" };
    });

    await step("O-setup-prepare", "Click prepare with keep_all water policy", async () => {
      const before = await waitForViewer(page);
      await page.getByRole("button", { name: "전처리", exact: true }).click();
      await page.getByRole("button", { name: "단백질 입력·제외 항목 확인" }).waitFor({ timeout: 20000 });
      await waitForViewer(page, viewer => viewer.sourceHandle !== before.sourceHandle);
    }, async after => {
      preparedHandle = assertViewer(after).sourceHandle;
      return { preparedHandle };
    });

    const openmmSection = page.getByText("OpenMM 단백질 전용 최소화 · kJ/mol").locator("..");
    await step("O02", "Click protein input/exclusions preflight", async () => {
      await openmmSection.getByRole("button", { name: "단백질 입력·제외 항목 확인" }).click();
      await openmmSection.getByRole("region", { name: "OpenMM 제외 성분" }).waitFor({ timeout: 30000 });
    }, async () => {
      const exclusions = await openmmSection.getByRole("region", { name: "OpenMM 제외 성분" }).locator("p").count();
      assert.equal(exclusions, 58, "1UBQ keep_all preflight should disclose 58 waters");
      const text = await openmmSection.innerText();
      assert.match(text, /단백질 중원자/);
      return { exclusions, preparedHandle };
    });

    const proteinOnly = openmmSection.getByLabel(/protein_only 선택과 제외 항목/);
    const hydrogen = openmmSection.getByLabel(/기존 수소 제거 후 pH 7.0/);
    const submit = openmmSection.getByRole("button", { name: "OpenMM 작업 제출" });
    await step("O03-protein", "Check protein-only exclusions policy", async () => {
      await proteinOnly.check();
    }, async () => {
      assert.equal(await submit.isDisabled(), true);
      return { proteinOnly: await proteinOnly.isChecked(), hydrogen: await hydrogen.isChecked(), submitDisabled: true };
    });
    await step("O03-hydrogen", "Check hydrogen rebuilding policy", async () => {
      await hydrogen.check();
    }, async () => {
      assert.equal(await submit.isEnabled(), true);
      return { proteinOnly: await proteinOnly.isChecked(), hydrogen: await hydrogen.isChecked(), submitEnabled: true };
    });

    await step("O04-queued", "Click OpenMM job submit", async () => {
      await submit.click();
      await openmmSection.getByText(/상태 queued/).waitFor({ timeout: 30000 });
      jobId = await openmmSection.getByLabel("작업").inputValue();
    }, async () => {
      assert.ok(jobId);
      const job = await readJson(new URL(`/api/runs/${encodeURIComponent(runId)}/jobs/${encodeURIComponent(jobId)}`, page.url()));
      assert.equal(job.status, "queued");
      assert.equal(job.attempt_ordinal, 0);
      return { jobId, status: job.status, attemptOrdinal: job.attempt_ordinal };
    });

    if (input.mode === "queued-cancel") {
      await step("O10", "Click queued job cancel without starting worker", async () => {
        await openmmSection.getByRole("button", { name: "작업 취소" }).click();
        await openmmSection.getByText(/상태 cancelled/).waitFor({ timeout: 30000 });
      }, async () => {
        const job = await readJson(new URL(`/api/runs/${encodeURIComponent(runId)}/jobs/${encodeURIComponent(jobId)}`, page.url()));
        assert.equal(job.status, "cancelled");
        assert.equal(job.attempt_ordinal, 0);
        assert.equal(job.output_handles.length, 0);
        return { jobId, status: job.status, attemptOrdinal: job.attempt_ordinal, outputHandles: [] };
      });
      return { runId, jobId, rows, artifacts };
    }

    await step("O04-unapproved-start", "Click start before high-cost approval", async () => {
      await openmmSection.getByRole("button", { name: "작업 시작" }).click();
      await openmmSection.getByRole("button", { name: "고비용 계산 승인 후 시작" }).waitFor({ timeout: 30000 });
    }, async () => {
      const job = await readJson(new URL(`/api/runs/${encodeURIComponent(runId)}/jobs/${encodeURIComponent(jobId)}`, page.url()));
      assert.equal(job.status, "claimed", "Unapproved start must stop at the claimed gate");
      assert.equal(job.blocked_reason, "approval_or_cancel");
      assert.equal(job.attempt_ordinal, 0);
      return { jobId, status: job.status, blockedReason: job.blocked_reason,
        attemptOrdinal: job.attempt_ordinal };
    });

    await step("O05", "Click explicit high-cost approval and start", async () => {
      await openmmSection.getByRole("button", { name: "고비용 계산 승인 후 시작" }).click();
      await openmmSection.getByText(/상태 (running|done)/).waitFor({ timeout: 60000 });
    }, async () => {
      const job = await readJson(new URL(`/api/runs/${encodeURIComponent(runId)}/jobs/${encodeURIComponent(jobId)}`, page.url()));
      assert.ok(["claimed", "running", "done"].includes(job.status));
      assert.equal(job.attempt_ordinal, 1);
      return { jobId, status: job.status, attemptOrdinal: job.attempt_ordinal };
    });

    if (input.mode === "running-cancel") {
      await step("O11", "Click cancel while real worker is running", async () => {
        await openmmSection.getByText(/상태 running/).waitFor({ timeout: 30000 });
        await openmmSection.getByRole("button", { name: "작업 취소" }).click();
        await openmmSection.getByText(/상태 (cancelled|interrupted)/).waitFor({ timeout: 60000 });
      }, async () => {
        const job = await readJson(new URL(`/api/runs/${encodeURIComponent(runId)}/jobs/${encodeURIComponent(jobId)}`, page.url()));
        assert.ok(["cancelled", "interrupted"].includes(job.status));
        assert.equal(job.output_handles.length, 0);
        return { jobId, status: job.status, attemptOrdinal: job.attempt_ordinal, outputHandles: [] };
      });
      return { runId, jobId, rows, artifacts };
    }

    let result;
    await step("O06", "Wait for native OpenMM result from real job", async () => {
      await openmmSection.getByText(/상태 done/).waitFor({ timeout: 180000 });
      await openmmSection.getByText("시작 전위").waitFor({ timeout: 30000 });
    }, async () => {
      const job = await readJson(new URL(`/api/runs/${encodeURIComponent(runId)}/jobs/${encodeURIComponent(jobId)}`, page.url()));
      assert.equal(job.status, "done");
      assert.equal(job.output_handles.length, 1);
      const payload = await readJson(new URL(`/api/runs/${encodeURIComponent(runId)}/openmm_minimization?handle=${encodeURIComponent(job.output_handles[0])}`, page.url()));
      result = payload.result;
      assert.equal(result.schema, "openmm_protein_minimization@1");
      assert.equal(result.job_id, jobId);
      assert.equal(result.structure, preparedHandle);
      for (const key of ["before_kJ_mol", "after_kJ_mol", "potential_change_kJ_mol"])
        assert.ok(Number.isFinite(result[key]), `${key} must be a native finite result`);
      return { jobId, resultHandle: job.output_handles[0], result };
    });

    await step("O07-minimized", "Click minimized protein coordinates", async () => {
      await openmmSection.getByRole("button", { name: "최소화 단백질 좌표 보기" }).click();
      await waitForViewer(page, viewer => viewer.sourceHandle === result.minimized_structure, 60000);
    }, async after => ({ minimizedHandle: assertViewer(after).sourceHandle, camera: after.viewer.camera }));
    await step("O07-original", "Click original structure return", async () => {
      await openmmSection.getByRole("button", { name: "원래 구조로 돌아가기" }).click();
      await waitForViewer(page, viewer => viewer.sourceHandle === preparedHandle, 60000);
    }, async after => ({ restoredHandle: assertViewer(after).sourceHandle }));

    await step("O08-create", "Click OpenMM native method report create", async () => {
      await openmmSection.getByRole("button", { name: "OpenMM 방법 보고서 만들기" }).click();
      await openmmSection.getByLabel("저장된 OpenMM 보고서 미리보기").waitFor({ timeout: 30000 });
    }, async () => ({ previewBytes: Buffer.byteLength(await openmmSection.getByLabel("저장된 OpenMM 보고서 미리보기").textContent()) }));
    for (const [suffix, name] of [["md", "Markdown 다운로드"], ["json", "정확한 JSON 다운로드"]]) {
      let downloaded;
      await step(`O08-${suffix}`, `Click OpenMM ${name}`, async () => {
        downloaded = await downloadByClick(app, openmmSection.getByRole("link", { name }));
      }, async () => ({ ...await validateReportDownload(page, openmmSection, runId,
        downloaded.downloaded, suffix), electronDownload: downloaded }));
    }

    return { runId, jobId, rows, artifacts };
  } finally {
    await session.close();
  }
}

if (require.main === module) {
  runOpenmm(parse(process.argv.slice(2))).then(result => process.stdout.write(JSON.stringify({
    ok: true, runId: result.runId, jobId: result.jobId, cases: result.rows.length,
    evidence: path.join(result.artifacts, `openmm-${process.argv.includes("--mode")
      ? process.argv[process.argv.indexOf("--mode") + 1] : "full"}.jsonl`),
  }) + "\n")).catch(error => {
    process.stderr.write(`OpenMM click QA failed: ${error.stack || error}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parse, runOpenmm };
