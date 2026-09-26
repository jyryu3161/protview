"use strict";

// Read-only existing-run check: only keyboard UI selection is changed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { options, launchOffscreen, capture } = require("./driver.cjs");

async function runKeyboard(input) {
  if (!new URL(input.url).searchParams.get("run")) {
    throw new Error("--url must include an existing ?run= ID; this check never creates a run");
  }
  const session = await launchOffscreen(input);
  try {
    const { app, page, artifacts } = session;
    await page.locator(".mw-step").first().waitFor({ timeout: 20000 });
    const initial = await page.locator(".mw-step").evaluateAll(rows => rows.map(row => ({
      tabIndex: row.tabIndex, role: row.getAttribute("role"), selected: row.getAttribute("aria-selected"),
    })));
    assert.ok(initial.length >= 2, "Need at least two existing history steps for Enter/Space check");

    let enterIndex = -1;
    for (let i = 0; i < 100; i += 1) {
      await page.keyboard.press("Tab");
      const index = await page.evaluate(() => [...document.querySelectorAll(".mw-step")].indexOf(document.activeElement));
      if (index >= 0 && initial[index].selected !== "true") { enterIndex = index; break; }
    }
    assert.ok(enterIndex >= 0, "Actual Tab input never focused an unselected history step");
    await page.keyboard.press("Enter");
    await page.waitForFunction(index => document.querySelectorAll(".mw-step")[index]?.getAttribute("aria-selected") === "true", enterIndex);

    const spaceIndex = enterIndex === 0 ? 1 : 0;
    let focusedIndex = -1;
    for (let i = 0; i < 100; i += 1) {
      await page.keyboard.press("Tab");
      focusedIndex = await page.evaluate(() => [...document.querySelectorAll(".mw-step")].indexOf(document.activeElement));
      if (focusedIndex === spaceIndex) break;
    }
    assert.equal(focusedIndex, spaceIndex, "Actual Tab input never focused the other history step");
    await page.keyboard.press("Space");
    await page.waitForFunction(index => document.querySelectorAll(".mw-step")[index]?.getAttribute("aria-selected") === "true", spaceIndex);

    const final = await page.locator(".mw-step").evaluateAll(rows => rows.map(row => ({
      selected: row.getAttribute("aria-selected"), pressed: row.getAttribute("aria-pressed"),
    })));
    const proof = await capture(app, page, artifacts, "history-keyboard");
    assert.equal(proof.status.offscreen, true);
    assert.equal(final[spaceIndex].pressed, "true");
    const evidence = { url: input.url, initial, enterIndex, spaceIndex, final,
      screenshot: proof.screenshot, paint: proof.paint, offscreen: proof.status.offscreen,
      versions: proof.status.versions, blockedRequests: proof.status.blockedRequests };
    fs.writeFileSync(path.join(artifacts, "history-keyboard.json"), JSON.stringify(evidence, null, 2) + "\n");
    return evidence;
  } finally {
    await session.close();
  }
}

if (require.main === module) {
  runKeyboard(options(process.argv.slice(2))).then(result => process.stdout.write(JSON.stringify({
    ok: true, enterIndex: result.enterIndex, spaceIndex: result.spaceIndex,
    screenshot: result.screenshot,
  }) + "\n")).catch(error => {
    process.stderr.write(`History keyboard QA failed: ${error.stack || error}\n`);
    process.exitCode = 1;
  });
}

module.exports = { runKeyboard };
