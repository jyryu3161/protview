"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const root = "/Users/jaeyongryu/Projects/protview";
const { launchOffscreen, capture, status } = require(path.join(root, "frontend/tests/offscreen/driver.cjs"));
const { waitForBoot, waitForViewer, sourceDigest } = require(path.join(root, "frontend/tests/offscreen/normal-flow.cjs"));
const mode = process.argv[2];
assert.ok(["minimized", "busy"].includes(mode), "Usage: node m8-extra-v12-targeted.cjs minimized|busy");
const origin = "http://127.0.0.1:3000";
const fixture = "/tmp/protview-qa/m8-inputs/synthetic_water_hydrogen.pdb";
const artifacts = process.env.PROTVIEW_EXTRA_ARTIFACTS || `/tmp/protview-qa/m8-extra-v12-${mode}-final`;
const completedRun = "run_31f0ddd9d86347aa89ab8ef227525717";
const fingerprint = mode === "busy" ? crypto.createHash("sha256").update(fs.readFileSync(fixture)).digest("hex") : null;
function identity(r) { return [r.model_number,r.chain_auth,r.chain_label,r.seq_auth,r.seq_label,r.icode,r.resname]
  .map(v=>v??"").join("/"); }
function matches(item,native) { return item.model_number===native.model_number &&
  item.chain_auth===native.chain_auth && item.seq_auth===native.seq_auth && item.icode===native.icode &&
  item.resname===native.resname && (item.chain_label==null||item.chain_label===native.chain_label) &&
  (item.seq_label==null||item.seq_label===native.seq_label); }
function label(r) { return `${r.resname} auth ${r.chain_auth}/${r.seq_auth}${r.icode||""}`+
  ` · label ${r.chain_label??"unknown"}/${r.seq_label??"unknown"} · model ${r.model_number??"unknown"}`; }
async function preview(page) { return JSON.parse(await page.getByLabel("전송 상태 미리보기").textContent()); }
async function agentStatus(page) {
  const value = await page.locator(".mw-agent-status").innerText();
  assert.doesNotMatch(value,/viewer action revision must increase|장면 동기화 실패|HTTP 409/);
  return value;
}
async function main() {
  const session = await launchOffscreen({ url: mode === "minimized" ? `${origin}/?run=${completedRun}` : origin, artifacts });
  const { app, page } = session;
  const source = sourceDigest();
  const evidence = path.join(artifacts, `V12-${mode}.jsonl`);
  let runId = mode === "minimized" ? completedRun : null;
  let release = () => {};
  let heldRoute;
  async function row(caseId, action, observe) {
    const before = await status(app,page);
    try {
      await action();
      const assertion = await observe();
      const proof = await capture(app,page,artifacts,caseId);
      assert.equal(proof.status.offscreen,true);
      assert.equal(proof.status.visible,false);
      assert.deepEqual(proof.status.blockedRequests,[]);
      const data={caseId,status:"pass",source,runId,fixtureSha256:fingerprint,before,after:proof.status,
        assertion,screenshot:proof.screenshot,paint:proof.paint};
      fs.appendFileSync(evidence,JSON.stringify(data)+"\n");
      return data;
    } catch(error) {
      let proof=null; try{proof=await capture(app,page,artifacts,`${caseId}-failure`);}catch{}
      fs.appendFileSync(evidence,JSON.stringify({caseId,status:"fail",source,runId,fixtureSha256:fingerprint,
        before,after:proof?.status,screenshot:proof?.screenshot,paint:proof?.paint,error:String(error)})+"\n");
      throw error;
    }
  }
  async function assertSelected(selected,viewer) {
    const response=await fetch(`${origin}/api/runs/${runId}/structures/residues?handle=${encodeURIComponent(viewer.sourceHandle)}`);
    assert.equal(response.status,200);
    const data=await response.json();
    const found=data.residues.filter(item=>matches(item,selected));
    assert.equal(found.length,1,"Native selection must uniquely match displayed source");
    const legend=await page.locator("main.mw-canvas").innerText();
    assert.ok(legend.includes(`선택: ${label(found[0])}`));
    await page.waitForFunction(()=>{
      try{return !!JSON.parse(document.querySelector('pre[aria-label="전송 상태 미리보기"]')?.textContent||"{}").selected_target;}
      catch{return false;}
    },null,{timeout:10000});
    const projected=await preview(page);
    assert.match(projected.selected_target,/^t\d{4}$/);
    return {selected,backendResidue:found[0],legend,preview:projected,
      agentStatus:await agentStatus(page)};
  }
  async function pickAny(box) {
    const targets=[];
    for(const x of [.50,.42,.58,.35,.65]) for(const y of [.50,.42,.58,.35,.65])
      targets.push({x:Math.round(box.x+box.width*x),y:Math.round(box.y+box.height*y)});
    const attempts=[];
    for(const point of targets) {
      await page.mouse.click(point.x,point.y);
      await page.waitForTimeout(120);
      const value=(await status(app,page)).viewer.selection;
      attempts.push({point,selection:value});
      if(value) return {value,attempts};
    }
    throw new Error(`No native residue selected by bounded real canvas clicks: ${JSON.stringify(attempts)}`);
  }
  try {
    await waitForBoot(page);
    if(mode==="minimized") {
      await row("V12-minimized-setup",async()=>{
        const first=await waitForViewer(page);
        await page.getByRole("button",{name:"최소화 단백질 좌표 보기"}).click();
        await waitForViewer(page,v=>v.sourceHandle!==first.sourceHandle,60000);
        await page.getByRole("button",{name:"ball-and-stick"}).click();
        await page.waitForFunction(()=>window.__protviewQaSnapshot?.().molstarRepresentation?.toLowerCase().includes("ball"));
      },async()=>({viewer:(await status(app,page)).viewer}));
    } else {
      await row("V12-busy-setup",async()=>{
        const previous=new URL(page.url()).searchParams.get("run");
        await page.getByRole("button",{name:"새 run"}).click();
        await page.waitForFunction(old=>{const next=new URL(location.href).searchParams.get("run");
          const button=[...document.querySelectorAll("button")].find(item=>item.textContent?.trim()==="새 run");
          return !!next&&next!==old&&!!button&&!button.disabled;},previous);
        runId=new URL(page.url()).searchParams.get("run");
        const chooser=page.waitForEvent("filechooser");
        await page.locator('input[type="file"]').click();
        await (await chooser).setFiles(fixture);
        await page.getByRole("button",{name:"구조 불러오기"}).click();
        await waitForViewer(page);
        await page.getByRole("button",{name:"전처리",exact:true}).click();
        await waitForViewer(page,v=>v.sourceHandle.includes("/prepared_structure/"));
        await page.getByRole("button",{name:"ball-and-stick"}).click();
        await page.waitForFunction(()=>window.__protviewQaSnapshot?.().molstarRepresentation?.toLowerCase().includes("ball"));
        await page.getByRole("combobox",{name:/^리간드/}).selectOption({index:1});
      },async()=>({viewer:(await status(app,page)).viewer}));
      let resolveHeld;
      const held=new Promise(resolve=>{resolveHeld=resolve;});
      const gate=new Promise(resolve=>{release=resolve;});
      const pattern=`**/api/runs/${runId}/commands`;
      heldRoute=async route=>{
        const body=route.request().postDataJSON();
        if(route.request().method()!=="POST"||body?.tool!=="compute_interactions") {
          await route.continue();return;
        }
        const response=await route.fetch();
        resolveHeld({status:response.status(),url:route.request().url()});
        await gate;
        try{await route.fulfill({response});}catch{}
      };
      await page.route(pattern,heldRoute);
      await row("V12-busy-held-real-command",async()=>{
        await page.getByRole("button",{name:"기하 접촉 계산"}).click();
        const observed=await Promise.race([held,new Promise((_,reject)=>setTimeout(()=>reject(new Error("real POST hold timeout")),30000))]);
        assert.equal(observed.status,200);
        await page.getByText(/compute_interactions 실행 중/).waitFor({timeout:10000});
      },async()=>({busyVisible:true,viewer:(await status(app,page)).viewer}));
    }
    const box=await page.locator("canvas.mw-molstar-canvas").boundingBox();
    assert.ok(box);
    let chosen;
    await row(`V12-${mode}-native-pick`,async()=>{chosen=await pickAny(box);},async()=>{
      const state=await status(app,page);
      assert.ok(state.viewer.ready);
      assert.equal(identity(state.viewer.selection),identity(chosen.value));
      return {attempts:chosen.attempts,...await assertSelected(chosen.value,state.viewer)};
    });
    await row(`V12-${mode}-blank-clear`,async()=>{
      const blank = mode === "minimized"
        ? { x: Math.round(box.x + box.width * .03), y: Math.round(box.y + box.height * .18) }
        : { x: Math.round(box.x + box.width * .94), y: Math.round(box.y + box.height * .74) };
      await page.mouse.click(blank.x,blank.y);
      await page.waitForFunction(()=>window.__protviewQaSnapshot?.().selection===null,null,{timeout:10000});
      await page.waitForFunction(()=>{try{return JSON.parse(document.querySelector('pre[aria-label="전송 상태 미리보기"]')?.textContent||"{}").selected_target==null;}catch{return false;}},null,{timeout:10000});
    },async()=>{
      const state=await status(app,page);
      assert.equal(state.viewer.selection,null);
      const legend=await page.locator("main.mw-canvas").innerText();
      assert.ok(!legend.includes("선택:"));
      return {nativeSelection:null,legend,preview:await preview(page),
        agentStatus:await agentStatus(page)};
    });
    if(mode==="busy") {
      release();
      await page.unroute(`**/api/runs/${runId}/commands`,heldRoute);
      heldRoute=null;
    }
    process.stdout.write(JSON.stringify({ok:true,mode,runId,evidence})+"\n");
  } finally {
    release();
    if(heldRoute) await page.unroute(`**/api/runs/${runId}/commands`,heldRoute);
    await session.close();
  }
}
main().catch(error=>{process.stderr.write(`V12 ${mode} failed: ${error.stack||error}\n`);process.exitCode=1;});
