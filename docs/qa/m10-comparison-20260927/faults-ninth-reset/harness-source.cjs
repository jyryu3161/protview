"use strict";

// M10 real Electron offscreen QA. Product mutations must be visible UI actions.
// Fixture construction/probes are labeled separately from measured product data.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const sharp = require("sharp");
const { launchOffscreen, capture, status, downloadByClick } = require("./driver.cjs");
const { sourceDigest, waitForBoot, waitForViewer } = require("./normal-flow.cjs");

const FIXTURE_DIR = path.join(__dirname, "fixtures");
const MODES = new Set(["measure", "alignment", "identity", "source-matrix", "adapter", "catalog-race", "overlay", "faults", "replay", "regression"]);
const ATOM_FIELDS = ["structure_handle", "residue", "atom_name", "altloc", "element", "site_index"];
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];

function sha(bytes) { return crypto.createHash("sha256").update(bytes).digest("hex"); }
function parse(argv) {
  const input = { url: null, run: null, otherRun: null, artifacts: null, mode: null,
    fixtureDir: FIXTURE_DIR, reference: null, moving: null, figure: null,
    result: null, report: null, otherResult: null, scene: null };
  for (let i = 0; i < argv.length; i += 1) {
    const option = argv[i];
    if (option === "--url") input.url = argv[++i];
    else if (option === "--run") input.run = argv[++i];
    else if (option === "--other-run") input.otherRun = argv[++i];
    else if (option === "--artifacts") input.artifacts = argv[++i];
    else if (option === "--mode") input.mode = argv[++i];
    else if (option === "--fixtures") input.fixtureDir = argv[++i];
    else if (option === "--reference") input.reference = argv[++i];
    else if (option === "--moving") input.moving = argv[++i];
    else if (option === "--figure") input.figure = argv[++i];
    else if (option === "--result") input.result = argv[++i];
    else if (option === "--report") input.report = argv[++i];
    else if (option === "--scene") input.scene = argv[++i];
    else if (option === "--other-result") input.otherResult = argv[++i];
    else throw new Error(`Unknown argument: ${option}`);
  }
  if (!input.url || !input.artifacts || !MODES.has(input.mode))
    throw new Error("Usage: comparison-flow.cjs --url http://127.0.0.1:3000 --artifacts /tmp/... --mode measure|alignment|identity|source-matrix|adapter|catalog-race|faults|replay [--run run_...] [--reference obj://...] [--other-run run_...] [--result obj://...] [--other-result obj://...] [--report obj://...] [--fixtures dir]");
  const url = new URL(input.url);
  if (!["http:", "https:"].includes(url.protocol) ||
      !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname))
    throw new Error("M10 QA URL must use loopback HTTP(S)");
  if (input.run) assert.match(input.run, /^run_[a-f0-9]+$/);
  if (input.otherRun) { assert.match(input.otherRun, /^run_[a-f0-9]+$/);
    assert.notEqual(input.otherRun, input.run); }
  if (input.mode === "source-matrix") assert.ok(input.run && input.otherRun,
    "Source matrix requires real 1HSG and OpenMM run IDs");
  if (input.mode === "catalog-race") assert.ok(input.run,
    "Delayed catalog/native initialization needs an existing real run");
  if (input.mode === "adapter") assert.ok(input.run && input.reference &&
    input.reference.startsWith(`obj://${input.run}/structure/`),
    "PDB adapter roundtrip needs the existing sparse original-PDB run and exact source handle");
  if (input.mode === "replay") assert.ok(input.run && input.result && input.report,
    "Events-only replay requires an existing run, result handle, and report handle");
  if (input.scene) assert.ok(input.mode === "replay" && input.run &&
    input.scene.startsWith(`obj://${input.run}/viewer_scene/`),
  "Optional selected-scene replay must use an existing scene in the same run");
  if (input.mode === "faults") assert.ok(input.run && input.result,
    "Fault QA requires an existing run and immutable comparison result handle");
  input.url = input.run ? new URL(`/?run=${input.run}`, url).toString() : new URL("/", url).toString();
  input.artifacts = path.resolve(input.artifacts);
  input.fixtureDir = path.resolve(input.fixtureDir);
  return input;
}

function vectorSub(a, b) { return a.map((v, i) => v - b[i]); }
function norm(a) { return Math.hypot(...a); }
function dot(a, b) { return a.reduce((sum, value, i) => sum + value * b[i], 0); }
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function normalize(a) { const length = norm(a); assert.ok(length > 1e-12); return a.map(v => v / length); }
function transform(p, rotation, translation) {
  return [0, 1, 2].map(i => rotation.slice(i * 3, i * 3 + 3)
    .reduce((sum, value, j) => sum + value * p[j], translation[i]));
}
function determinant3(m) {
  return m[0] * (m[4] * m[8] - m[5] * m[7]) -
    m[1] * (m[3] * m[8] - m[5] * m[6]) +
    m[2] * (m[3] * m[7] - m[4] * m[6]);
}
function volume(points) {
  const [a, b, c, d] = points;
  const x = vectorSub(b, a), y = vectorSub(c, a), z = vectorSub(d, a);
  return determinant3([...x, ...y, ...z]);
}
function close(actual, expected, tolerance, label) {
  assert.ok(Number.isFinite(actual) && Number.isFinite(expected), `${label} not finite`);
  assert.ok(Math.abs(actual - expected) <= tolerance,
    `${label}: observed ${actual}, expected ${expected}, tolerance ${tolerance}`);
}
function vectorClose(actual, expected, tolerance, label) {
  assert.equal(actual.length, expected.length, `${label} dimension`);
  actual.forEach((v, i) => close(v, expected[i], tolerance, `${label}[${i}]`));
}
function nativeCameraClose(actual, expected, tolerance, label) {
  for (const key of ["mode", "clipFar"]) assert.equal(actual[key], expected[key], `${label}.${key}`);
  for (const key of ["position", "target", "up"])
    vectorClose(actual[key], expected[key], tolerance, `${label}.${key}`);
  for (const key of ["fov", "radius", "radiusMax", "fog", "minNear", "minFar"])
    close(actual[key], expected[key], tolerance, `${label}.${key}`);
}
function projectToCanvas(camera, world, box) {
  assert.equal(camera.mode, "perspective", "Pointer projection helper requires perspective camera");
  const forward = normalize(vectorSub(camera.target, camera.position));
  const right = normalize(cross(forward, camera.up));
  const trueUp = normalize(cross(right, forward));
  const relative = vectorSub(world, camera.position), depth = dot(relative, forward);
  assert.ok(depth > 1e-6, "Target atom is behind native camera");
  const scale = box.height / (2 * Math.tan(camera.fov / 2) * depth);
  const x = box.x + box.width / 2 + dot(relative, right) * scale;
  const y = box.y + box.height / 2 - dot(relative, trueUp) * scale;
  assert.ok(x >= box.x && x <= box.x + box.width && y >= box.y && y <= box.y + box.height,
    `Projected atom lies outside canvas: ${x},${y}`);
  return { x, y, depth, scale };
}

function parsePdb(file) {
  const atoms = [];
  let model = 1;
  let siteIndex = 0;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    if (line.startsWith("MODEL ")) { model = Number(line.slice(10, 14).trim()); siteIndex = 0; continue; }
    if (!line.startsWith("ATOM  ") && !line.startsWith("HETATM")) continue;
    const xyz = [30, 38, 46].map(start => Number(line.slice(start, start + 8)));
    assert.ok(xyz.every(Number.isFinite), `Nonfinite PDB coordinate in ${file}`);
    atoms.push({ site_index: siteIndex++, model_number: model, chain_auth: line.slice(21, 22),
      seq_auth: Number(line.slice(22, 26)), icode: line.slice(26, 27).trim(),
      resname: line.slice(17, 20).trim(), atom_name: line.slice(12, 16).trim(),
      altloc: line.slice(16, 17).trim(), element: line.slice(76, 78).trim(), xyz });
  }
  assert.ok(atoms.length, `No PDB atoms in ${file}`);
  return atoms;
}
function findFixtureAtom(atoms, pair) {
  const found = atoms.filter(atom => atom.model_number === 1 && atom.chain_auth === pair.chain_auth &&
    atom.seq_auth === pair.seq_auth && atom.icode === pair.icode &&
    atom.atom_name === pair.atom_name && atom.altloc === pair.altloc);
  assert.equal(found.length, 1, `Fixture coordinate identity ambiguous: ${JSON.stringify(pair)}`);
  return found[0];
}
function fixtureOracle(directory) {
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, "m10-coordinate-oracle.json"), "utf8"));
  assert.match(manifest.label, /Synthetic M10 coordinate fixtures/);
  for (const [name, expected] of Object.entries(manifest.sha256))
    assert.equal(sha(fs.readFileSync(path.join(directory, name))), expected, `Fixture changed: ${name}`);
  const reference = parsePdb(path.join(directory, manifest.reference));
  const moving = parsePdb(path.join(directory, manifest.moving));
  const reflected = parsePdb(path.join(directory, manifest.reflected));
  const collinear = parsePdb(path.join(directory, manifest.collinear));
  const refPairs = manifest.ca_pairs.map(pair => findFixtureAtom(reference, pair));
  const movPairs = manifest.ca_pairs.map(pair => findFixtureAtom(moving, pair));
  const reflectedPairs = manifest.ca_pairs.map(pair => findFixtureAtom(reflected, pair));
  const collinearPairs = manifest.ca_pairs.map(pair => findFixtureAtom(collinear, pair));
  assert.equal(refPairs.length, 4);
  close(determinant3(manifest.known_rotation_row_major), 1, 1e-12, "Known proper rotation determinant");
  refPairs.forEach((atom, i) => vectorClose(transform(movPairs[i].xyz,
    manifest.known_rotation_row_major, manifest.known_translation_A), atom.xyz, 1e-9,
  `known transformed CA pair ${i}`));
  const unaligned = Math.sqrt(refPairs.reduce((sum, atom, i) =>
    sum + norm(vectorSub(atom.xyz, movPairs[i].xyz)) ** 2, 0) / refPairs.length);
  close(unaligned, manifest.unaligned_rmsd_A, 1e-10, "Known unaligned RMSD");
  const distanceAtoms = manifest.distance_sites.map(pair => findFixtureAtom(reference,
    { chain_auth: "A", icode: "", ...pair }));
  close(norm(vectorSub(distanceAtoms[0].xyz, distanceAtoms[1].xyz)), 5, 1e-12, "3-4-5 fixture distance");
  const coincident = manifest.coincident_sites.map(pair => findFixtureAtom(reference,
    { chain_auth: "A", icode: "", ...pair }));
  assert.notEqual(coincident[0].site_index, coincident[1].site_index);
  close(norm(vectorSub(coincident[0].xyz, coincident[1].xyz)), 0, 1e-12, "distinct coincident sites");
  assert.ok(volume(refPairs.map(atom => atom.xyz)) * volume(reflectedPairs.map(atom => atom.xyz)) < 0,
    "Reflection fixture did not invert handedness");
  close(volume(collinearPairs.map(atom => atom.xyz)), 0, 1e-12, "Collinear fixture volume");
  const identities = parsePdb(path.join(directory, manifest.identities));
  assert.deepEqual([...new Set(identities.map(atom => atom.model_number))], [1, 2]);
  assert.equal(identities.filter(atom => atom.model_number === 2 && atom.seq_auth === 42 &&
    atom.icode === "A" && atom.atom_name === "CA" && atom.altloc === "A").length, 2);
  const distance = parsePdb(path.join(directory, manifest.distance_fixture));
  assert.equal(distance.length, 4);
  close(norm(vectorSub(distance[0].xyz, distance[1].xyz)), 5, 1e-12, "isolated 3-4-5 distance fixture");
  close(norm(vectorSub(distance[2].xyz, distance[3].xyz)), 0, 1e-12, "isolated distinct zero fixture");
  return { manifest, sourceHashes: manifest.sha256, reference, moving, reflected, collinear,
    refPairs, movPairs, reflectedPairs, collinearPairs, identities, distance,
    unalignedRmsdA: unaligned };
}

function assertAtomRef(value, sourceHandle) {
  assert.ok(value && typeof value === "object", "Missing AtomRefV1");
  for (const field of ATOM_FIELDS) assert.ok(Object.hasOwn(value, field), `AtomRef lacks ${field}`);
  if (sourceHandle) assert.equal(value.structure_handle, sourceHandle);
  for (const field of RESIDUE_FIELDS) assert.ok(Object.hasOwn(value.residue, field), `ResidueRef lacks ${field}`);
  assert.ok(Number.isInteger(value.site_index) && value.site_index >= 0);
  assert.ok(typeof value.atom_name === "string" && value.atom_name.length > 0);
  assert.ok(typeof value.altloc === "string");
  return value;
}
function assertDistanceResult(value, sourceHandle) {
  assert.equal(value.schema, "atom_distance@1");
  assert.equal(value.structure_handle, sourceHandle);
  assert.equal(value.unit, "angstrom");
  const atoms = [value.first, value.second];
  assert.equal(atoms.length, 2);
  atoms.forEach(atom => assertAtomRef(atom, sourceHandle));
  const coords = [value.first_coordinate_A, value.second_coordinate_A];
  assert.equal(coords.length, 2);
  const independent = norm(vectorSub(coords[0], coords[1]));
  close(value.distance_A, independent, 1e-10 * Math.max(1, independent), "stored atom distance");
  return { independentDistanceA: independent, atoms };
}
function assertAlignmentResult(value, expected) {
  assert.equal(value.schema, "rigid_alignment@1");
  assert.equal(value.pair_count, expected.refPairs.length);
  assert.equal(value.pairs.length, value.pair_count);
  const rotation = value.rotation.flat(), translation = value.translation_A;
  assert.equal(value.rotation.length, 3);
  value.rotation.forEach(row => assert.equal(row.length, 3));
  assert.equal(rotation.length, 9); assert.equal(translation.length, 3);
  rotation.concat(translation).forEach((number, i) => assert.ok(Number.isFinite(number), `transform[${i}] nonfinite`));
  close(determinant3(rotation), 1, 1e-10, "proper rotation determinant");
  for (let i = 0; i < 3; i += 1) for (let j = 0; j < 3; j += 1)
    close([0, 1, 2].reduce((sum, k) => sum + rotation[k * 3 + i] * rotation[k * 3 + j], 0),
      i === j ? 1 : 0, 1e-10, `rotation orthogonality ${i},${j}`);
  const residuals = expected.refPairs.map((atom, i) => norm(vectorSub(
    transform(expected.movPairs[i].xyz, rotation, translation), atom.xyz)));
  value.pairs.forEach((pair, i) => {
    assertAtomRef(pair.reference, value.reference_handle);
    assertAtomRef(pair.moving, value.moving_handle);
    vectorClose(pair.reference_coordinate_A, expected.refPairs[i].xyz, 1e-6, `reference pair ${i}`);
    vectorClose(pair.moving_coordinate_A, expected.movPairs[i].xyz, 1e-6, `moving pair ${i}`);
    close(pair.after_residual_A, residuals[i], 1e-10, `pair ${i} residual`);
  });
  const rmsd = Math.sqrt(residuals.reduce((sum, value) => sum + value * value, 0) / residuals.length);
  close(value.rmsd_A, rmsd, 1e-10 * Math.max(1, rmsd), "independent aligned RMSD");
  close(value.unaligned_rmsd_A, expected.unalignedRmsdA, 1e-10, "independent unaligned RMSD");
  assert.ok(value.rmsd_A <= 1e-8, "Known rigid fixture did not align");
  return { determinant: determinant3(rotation), independentRmsdA: rmsd,
    unalignedRmsdA: expected.unalignedRmsdA, residuals };
}
function expectedNativeMat4(result, aligned) {
  if (!aligned) return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  const r = result.rotation, t = result.translation_A;
  return [r[0][0], r[1][0], r[2][0], 0,
    r[0][1], r[1][1], r[2][1], 0,
    r[0][2], r[1][2], r[2][2], 0,
    t[0], t[1], t[2], 1];
}
function assertNativeLayers(viewer, result, aligned, visibility) {
  assert.equal(viewer.ready, true);
  assert.ok(Array.isArray(viewer.layers) && viewer.layers.length === 2, "No actual two-layer Mol* observation");
  const [reference, moving] = viewer.layers;
  assert.equal(reference.layer, "reference");
  assert.equal(moving.layer, "moving");
  assert.equal(reference.sourceHandle, result.reference_handle);
  assert.equal(moving.sourceHandle, result.moving_handle);
  assert.ok(reference.nativeAtomCount > 0 && moving.nativeAtomCount > 0,
    "One overlay layer has no native atoms");
  assert.equal(reference.visible, visibility.reference);
  assert.equal(moving.visible, visibility.moving);
  vectorClose(reference.transform, expectedNativeMat4(result, false), 1e-10, "reference native matrix");
  vectorClose(moving.transform, expectedNativeMat4(result, aligned), 1e-9, "moving native matrix");
  return { reference, moving };
}
function assertNativePick(viewer, catalogValue, expectedLayer, result, aligned) {
  const picked = viewer.lastAtomPick;
  assert.ok(picked, "No actual native atom pick observed");
  assert.equal(picked.layer, expectedLayer);
  assertAtomRef(picked.ref, catalogValue.structure_handle);
  const site = catalogValue.rows.find(row => row.ref.site_index === picked.ref.site_index);
  assert.ok(site, "Picked site absent from authoritative catalog");
  assert.deepEqual(picked.ref, site.ref);
  assert.equal(picked.nativeSourceIndex, site.viewer_source_index);
  const sourceCoordinate = site.coordinate_A;
  if (picked.sourceCoordinate_A) vectorClose(picked.sourceCoordinate_A, sourceCoordinate, 1e-5,
    "native pick source coordinate");
  const rotation = result.rotation.flat(), translation = result.translation_A;
  const expectedDisplay = expectedLayer === "moving" && aligned
    ? transform(sourceCoordinate, rotation, translation) : sourceCoordinate;
  vectorClose(picked.worldCoordinate_A, expectedDisplay, 1e-4, "native pick display/world coordinate");
  return { ref: picked.ref, sourceCoordinate_A: sourceCoordinate,
    nativeWorldCoordinate_A: picked.worldCoordinate_A, expectedDisplayCoordinate_A: expectedDisplay };
}

async function checkPaint(file) {
  const decoded = await sharp(typeof file === "string" ? file : file.path)
    .ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const colors = new Set();
  for (let y = 0; y < decoded.info.height; y += Math.max(1, Math.floor(decoded.info.height / 64)))
    for (let x = 0; x < decoded.info.width; x += Math.max(1, Math.floor(decoded.info.width / 64))) {
      const at = (y * decoded.info.width + x) * 4;
      colors.add([...decoded.data.subarray(at, at + 4)].join(","));
    }
  assert.ok(colors.size >= 12, `Flat/blank offscreen paint: ${colors.size} sampled colors`);
  return { width: decoded.info.width, height: decoded.info.height, sampledColors: colors.size };
}
async function canvasPaint(page, paint) {
  const file = paint.path;
  const metadata = await sharp(file).metadata();
  const box = await page.locator("canvas.mw-molstar-canvas:visible").first().boundingBox();
  assert.ok(box && metadata.width && metadata.height, "Canvas or actual Electron paint missing");
  const viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
  const left = Math.max(0, Math.floor(box.x * metadata.width / viewport.width));
  const top = Math.max(0, Math.floor(box.y * metadata.height / viewport.height));
  const width = Math.min(metadata.width - left,
    Math.max(1, Math.floor(box.width * metadata.width / viewport.width)));
  const height = Math.min(metadata.height - top,
    Math.max(1, Math.floor(box.height * metadata.height / viewport.height)));
  const pixels = await sharp(file).extract({ left, top, width, height }).ensureAlpha().raw()
    .toBuffer({ resolveWithObject: true });
  const colors = new Set();
  for (let y = 0; y < pixels.info.height; y += Math.max(1, Math.floor(pixels.info.height / 70)))
    for (let x = 0; x < pixels.info.width; x += Math.max(1, Math.floor(pixels.info.width / 70))) {
      const at = (y * pixels.info.width + x) * 4;
      colors.add([...pixels.data.subarray(at, at + 4)].join(","));
    }
  assert.ok(colors.size >= 12, `Actual Mol* viewport paint appears flat: ${colors.size} colors`);
  return { sourcePaint: file, crop: { left, top, width, height },
    sampledColors: colors.size, pixelSha256: sha(pixels.data) };
}
async function readJson(url) {
  const response = await fetch(url);
  assert.equal(response.status, 200, `Read-only M10 prerequisite failed: ${url} (${response.status})`);
  return response.json();
}
async function catalog(origin, run, handle) {
  const rows = [];
  let total = null, sha256 = null, modelNumber = null;
  while (total === null || rows.length < total) {
    const url = new URL(`/api/runs/${run}/structures/atoms`, origin);
    url.searchParams.set("handle", handle);
    url.searchParams.set("offset", String(rows.length));
    url.searchParams.set("limit", "500");
    const page = await readJson(url);
    assert.equal(page.schema, "atom_catalog@1");
    assert.equal(page.structure_handle, handle);
    assert.equal(page.offset, rows.length);
    if (total === null) { total = page.total; sha256 = page.viewer_source_sha256;
      modelNumber = page.model_number; }
    else { assert.equal(page.total, total); assert.equal(page.viewer_source_sha256, sha256);
      assert.equal(page.model_number, modelNumber); }
    assert.ok(page.rows.length > 0 || rows.length === total, "Catalog page made no progress");
    rows.push(...page.rows);
  }
  assert.equal(rows.length, total);
  const sites = new Set();
  for (const row of rows) {
    assertAtomRef(row.ref, handle);
    assert.equal(row.ref.residue.model_number, modelNumber);
    assert.equal(row.viewer_source_index, row.ref.site_index);
    assert.ok(row.coordinate_A.length === 3 && row.coordinate_A.every(Number.isFinite));
    assert.equal(sites.has(row.ref.site_index), false, "Catalog duplicated a site index");
    sites.add(row.ref.site_index);
  }
  const bytesUrl = new URL(`/api/runs/${run}/structures/bytes`, origin);
  bytesUrl.searchParams.set("handle", handle);
  const response = await fetch(bytesUrl);
  assert.equal(response.status, 200, `Stored source bytes unavailable: ${handle}`);
  const byteHash = sha(Buffer.from(await response.arrayBuffer()));
  assert.equal(byteHash, sha256, "Catalog served-byte hash differs from immutable source bytes");
  return { schema: "atom_catalog@1", structure_handle: handle, model_number: modelNumber,
    total, viewer_source_sha256: sha256, rows };
}
async function measurement(origin, run, handle) {
  const url = new URL(`/api/runs/${run}/objects/measurement`, origin);
  url.searchParams.set("handle", handle);
  const detail = await readJson(url);
  assert.equal(detail.meta.handle, handle);
  return detail;
}
function sameResidue(actual, expected) {
  return !!actual && !!expected && RESIDUE_FIELDS.every(field => actual[field] === expected[field]);
}
async function completedViewerIntent(origin, run, intentId, timeoutMs = 30000) {
  const url = new URL(`/api/runs/${run}/viewer/intents/${encodeURIComponent(intentId)}`, origin);
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await readJson(url);
    if (["applied", "no_change", "partial", "failed", "cancelled", "detached", "rejected", "unsupported"].includes(last.status))
      return last;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Local viewer intent did not settle: ${JSON.stringify(last)}`);
}
async function nativeSource(page, predicate, timeoutMs = 45000) {
  return waitForViewer(page, value => value.ready && value.sourceHandle && value.nativeCamera &&
    value.sessionId && value.generation !== null && predicate(value), timeoutMs);
}
async function createLocalRun(page) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const previous = new URL(page.url()).searchParams.get("run");
  await page.getByRole("button", { name: "새 run" }).click();
  await page.waitForFunction(old => {
    const current = new URL(location.href).searchParams.get("run");
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    return /^run_[a-f0-9]+$/.test(current ?? "") && current !== old && !!button && !button.disabled;
  }, previous, { timeout: 30000 });
  const runId = new URL(page.url()).searchParams.get("run");
  assert.match(runId, /^run_[a-f0-9]+$/);
  assert.match(await page.locator("body").innerText(), /local_only/);
  return runId;
}
async function uploadAndLoad(page, file, modelIndex = 0) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기" }).waitFor({ timeout: 30000 });
  const selector = page.getByRole("combobox", { name: "model", exact: true });
  if (await selector.count()) await selector.selectOption(String(modelIndex));
  else if (modelIndex !== 0) await page.getByRole("spinbutton", { name: "model index" }).fill(String(modelIndex));
  await page.getByRole("button", { name: "구조 불러오기" }).click();
  const after = await nativeSource(page, value => value.sourceHandle !== before?.sourceHandle, 45000);
  assert.ok(after.sourceHandle.includes("/structure/"), "Upload did not select original immutable structure");
  return { fixture: path.basename(file), sha256: sha(fs.readFileSync(file)), modelIndex,
    sourceHandle: after.sourceHandle, native: after };
}
function observerIdle(value) {
  return value?.ready === true && value.nativeBusy === false &&
    value.nativeUpdating === false && value.nativeAnimating === false &&
    value.cameraTransitioning === false && value.m10QueuePending === 0 &&
    Number.isInteger(value.nativeClickRevision);
}
async function nativeQuietAt(page, row, layer, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    await page.waitForFunction(() => {
      const value = window.__protviewQaSnapshot?.();
      return value?.ready === true && value.nativeBusy === false &&
        value.nativeUpdating === false && value.nativeAnimating === false &&
        value.cameraTransitioning === false && value.m10QueuePending === 0 &&
        Number.isInteger(value.nativeClickRevision);
    }, null, { timeout: Math.max(1000, deadline - Date.now()) });
    const first = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
    await page.evaluate(() => new Promise(resolve =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const second = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
    last = second;
    const atom = value => value?.qaAtoms?.find(item => item.layer === layer &&
      item.ref.structure_handle === row.ref.structure_handle &&
      item.ref.site_index === row.ref.site_index);
    const a = atom(first), b = atom(second);
    if (observerIdle(first) && observerIdle(second) && a && b &&
        norm(vectorSub(a.canvasPixel, b.canvasPixel)) <= 0.25 &&
        norm(vectorSub(first.nativeCamera.position, second.nativeCamera.position)) <= 1e-4 &&
        norm(vectorSub(first.nativeCamera.target, second.nativeCamera.target)) <= 1e-4)
      return { first, second, target: b,
        settle: { nativeBusy: second.nativeBusy, nativeUpdating: second.nativeUpdating,
          nativeAnimating: second.nativeAnimating, cameraTransitioning: second.cameraTransitioning,
          m10QueuePending: second.m10QueuePending,
          nativeClickRevision: second.nativeClickRevision,
          targetCanvasPixel: b.canvasPixel } };
  }
  throw new Error(`Native pointer target did not settle: ${JSON.stringify({
    nativeBusy: last?.nativeBusy, nativeUpdating: last?.nativeUpdating,
    nativeAnimating: last?.nativeAnimating, cameraTransitioning: last?.cameraTransitioning,
    m10QueuePending: last?.m10QueuePending, nativeClickRevision: last?.nativeClickRevision,
    lastNativeClick: last?.lastNativeClick })}`);
}
async function clickCatalogAtom(page, row, layer = "reference", alignment = null, aligned = false) {
  let quiet = await nativeQuietAt(page, row, layer);
  let before = quiet.second;
  assert.equal(before.measureMode, true, "Atom pointer action requires Measure mode");
  assert.ok(Number.isInteger(before.atomPickRevision));
  const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
  const box = await canvas.boundingBox();
  assert.ok(box, "Native Mol* canvas is not visible for pointer pick");
  const world = layer === "moving" && aligned
    ? transform(row.coordinate_A, alignment.rotation.flat(), alignment.translation_A)
    : row.coordinate_A;
  let observed = quiet.target;
  assert.ok(observed, "Target site absent from read-only native Mol* projection observer");
  assert.deepEqual(observed.ref, row.ref);
  vectorClose(observed.worldCoordinate_A, world, 1e-4, "native projected atom world coordinate");
  const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
  assert.ok(size.width > 0 && size.height > 0);
  let point = { x: box.x + observed.canvasPixel[0] * box.width / size.width,
    y: box.y + observed.canvasPixel[1] * box.height / size.height,
    nativeCanvasPixel: observed.canvasPixel };
  assert.ok(point.x >= box.x && point.x <= box.x + box.width &&
    point.y >= box.y && point.y <= box.y + box.height, "Native projection lies outside canvas");
  const attempts = [];
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    if (attempt > 1) await page.mouse.move(point.x + 16, point.y + 16);
    await page.mouse.move(point.x, point.y);
    quiet = await nativeQuietAt(page, row, layer);
    before = quiet.second; observed = quiet.target;
    point = { x: box.x + observed.canvasPixel[0] * box.width / size.width,
      y: box.y + observed.canvasPixel[1] * box.height / size.height,
      nativeCanvasPixel: observed.canvasPixel };
    await page.mouse.click(point.x, point.y);
    let after;
    try {
      after = await waitForViewer(page, value => value.atomPickRevision > before.atomPickRevision &&
        value.lastAtomPick?.layer === layer &&
        value.lastAtomPick.ref.structure_handle === row.ref.structure_handle &&
        value.lastAtomPick.ref.site_index === row.ref.site_index, 1500);
    } catch (error) {
      const raw = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
      const rejected = { attempt, point,
        expectedSite: row.ref.site_index, expectedLayer: layer,
        acceptedBefore: before.atomPickRevision, acceptedAfter: raw?.atomPickRevision,
        nativeClickBefore: before.nativeClickRevision, nativeClickAfter: raw?.nativeClickRevision,
        lastNativeClickBefore: before.lastNativeClick,
        lastNativeClickAfter: raw?.lastNativeClick, nativeBusy: raw?.nativeBusy,
        nativeUpdating: raw?.nativeUpdating, nativeAnimating: raw?.nativeAnimating,
        cameraTransitioning: raw?.cameraTransitioning,
        m10QueuePending: raw?.m10QueuePending, error: String(error).slice(0, 500) };
      attempts.push(rejected);
      if (raw?.atomPickRevision > before.atomPickRevision)
        throw new Error(`Native pointer accepted a different site while targeting exact atom: ${JSON.stringify(attempts)}`);
      if (attempt === 3)
        throw new Error(`Exact native pointer pick failed after three genuine same-site mouse clicks: ${JSON.stringify(attempts)}`);
      continue;
    }
    assert.ok(after.nativeClickRevision > before.nativeClickRevision,
      "Accepted exact atom pick lacks a new raw Mol* click event");
    assert.equal(after.lastNativeClick?.accepted, true);
    assert.equal(after.lastNativeClick?.size, 1,
      "Accepted exact atom pick did not have one atomic locus");
    assert.equal(after.lastNativeClick?.pluginBusy, false);
    return { requested: row.ref, actual: after.lastAtomPick, point, pickRevision: after.atomPickRevision,
      rawNativeClickRevisionBefore: before.nativeClickRevision,
      rawNativeClickRevisionAfter: after.nativeClickRevision,
      rawNativeClickBefore: before.lastNativeClick,
      rawNativeClick: after.lastNativeClick,
      nativeSettle: quiet.settle, camera: before.nativeCamera, canvas: box,
      rejectedSameSiteAttempts: attempts };
  }
  throw new Error("Unreachable exact native pointer retry state");
}
async function clickAnyNativeAtom(page, catalogValue, excludedSites = []) {
  const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
  const box = await canvas.boundingBox(); assert.ok(box);
  const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
  const candidates = (await waitForViewer(page, value => value.measureMode &&
    value.sourceHandle === catalogValue.structure_handle && value.qaAtoms?.length > 0)).qaAtoms
    .filter(atom => atom.layer === "reference" &&
      atom.ref.structure_handle === catalogValue.structure_handle &&
      !excludedSites.includes(atom.ref.site_index) &&
      atom.canvasPixel[0] > 8 && atom.canvasPixel[0] < size.width - 8 &&
      atom.canvasPixel[1] > 8 && atom.canvasPixel[1] < size.height - 8);
  assert.ok(candidates.length > 0, "No projected native atom in real source viewport");
  const attempts = [];
  for (const candidate of candidates.slice(0, 24)) {
    const row = catalogValue.rows.find(item => item.ref.site_index === candidate.ref.site_index);
    assert.ok(row);
    let quiet = await nativeQuietAt(page, row, "reference");
    assert.equal(quiet.second.measureMode, true);
    let point = { x: box.x + quiet.target.canvasPixel[0] * box.width / size.width,
      y: box.y + quiet.target.canvasPixel[1] * box.height / size.height };
    await page.mouse.move(point.x, point.y);
    quiet = await nativeQuietAt(page, row, "reference");
    const before = quiet.second;
    point = { x: box.x + quiet.target.canvasPixel[0] * box.width / size.width,
      y: box.y + quiet.target.canvasPixel[1] * box.height / size.height };
    await page.mouse.click(point.x, point.y);
    let after;
    try {
      after = await waitForViewer(page, value => value.atomPickRevision > before.atomPickRevision &&
        value.lastAtomPick?.layer === "reference" &&
        value.lastAtomPick.ref.structure_handle === catalogValue.structure_handle, 600);
    } catch {
      const raw = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
      attempts.push({ attemptedSite: candidate.ref.site_index,
        nativeClickRevisionBefore: before.nativeClickRevision,
        nativeClickRevisionAfter: raw?.nativeClickRevision,
        lastNativeClick: raw?.lastNativeClick });
      continue; /* projected site may be occluded; try next real pointer target */
    }
    assert.ok(!excludedSites.includes(after.lastAtomPick.ref.site_index),
      "Native occlusion selected the already-pending first site");
    assert.ok(after.nativeClickRevision > before.nativeClickRevision);
    assert.equal(after.lastNativeClick?.accepted, true);
    assert.equal(after.lastNativeClick?.size, 1);
    assert.equal(after.lastNativeClick?.pluginBusy, false);
    const native = assertNativePick(after, catalogValue, "reference",
      { rotation: [[1,0,0],[0,1,0],[0,0,1]], translation_A: [0,0,0] }, false);
    return { attemptedSite: candidate.ref.site_index, pointer: point,
      observedSite: after.lastAtomPick.ref.site_index, native,
      nativeClickRevisionBefore: before.nativeClickRevision,
      nativeClickRevisionAfter: after.nativeClickRevision,
      lastNativeClick: after.lastNativeClick, settle: quiet.settle,
      rejectedAttempts: attempts };
  }
  throw new Error(`No genuine native atom pick succeeded in 24 projected sites for ${catalogValue.structure_handle}: ${JSON.stringify(attempts)}`);
}
async function clickAnyOrdinaryResidue(page, catalogValue) {
  const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
  const box = await canvas.boundingBox(); assert.ok(box);
  const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
  const initial = await waitForViewer(page, value => value.ready && !value.measureMode &&
    value.sourceHandle === catalogValue.structure_handle && value.qaAtoms?.length > 0);
  const initialResidue = initial.selection ?? null;
  const candidates = initial.qaAtoms.filter(atom => atom.layer === "reference" &&
    atom.ref.structure_handle === catalogValue.structure_handle &&
    atom.canvasPixel[0] > 8 && atom.canvasPixel[0] < size.width - 8 &&
    atom.canvasPixel[1] > 8 && atom.canvasPixel[1] < size.height - 8 &&
    RESIDUE_FIELDS.some(field => atom.ref.residue[field] !== initialResidue?.[field]));
  assert.ok(candidates.length > 0, "No different visible native residue for ordinary pointer regression");
  const attempts = [];
  for (const candidate of candidates.slice(0, 24)) {
    const row = catalogValue.rows.find(item => item.ref.site_index === candidate.ref.site_index);
    assert.ok(row);
    let quiet = await nativeQuietAt(page, row, "reference");
    await page.mouse.move(box.x + quiet.target.canvasPixel[0] * box.width / size.width,
      box.y + quiet.target.canvasPixel[1] * box.height / size.height);
    quiet = await nativeQuietAt(page, row, "reference");
    const before = quiet.second;
    const point = { x: box.x + quiet.target.canvasPixel[0] * box.width / size.width,
      y: box.y + quiet.target.canvasPixel[1] * box.height / size.height };
    await page.mouse.click(point.x, point.y);
    let after;
    try {
      after = await waitForViewer(page, value => value.nativeClickRevision > before.nativeClickRevision &&
        value.lastNativeClick?.kind === "element-loci" &&
        value.lastNativeClick.pluginBusy === false && !value.measureMode && value.selection &&
        RESIDUE_FIELDS.some(field => value.selection[field] !== initialResidue?.[field]), 1800);
    } catch {
      const raw = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
      attempts.push({ targetSite: row.ref.site_index, point,
        nativeClickBefore: before.nativeClickRevision, nativeClickAfter: raw?.nativeClickRevision,
        lastNativeClick: raw?.lastNativeClick, selection: raw?.selection ?? null });
      continue;
    }
    const matches = catalogValue.rows.filter(item =>
      RESIDUE_FIELDS.every(field => item.ref.residue[field] === after.selection[field]));
    assert.ok(matches.length > 0,
      `Ordinary native selection lacks authoritative source residue: ${JSON.stringify(after.selection)}`);
    assert.equal(after.selection.model_number, catalogValue.model_number);
    return { targetSite: row.ref.site_index, point, nativeClickBefore: before.nativeClickRevision,
      nativeClickAfter: after.nativeClickRevision, lastNativeClick: after.lastNativeClick,
      selectedResidue: after.selection, matchedCatalogSites: matches.map(item => item.ref.site_index),
      previousResidue: initialResidue, rejectedAttempts: attempts };
  }
  throw new Error(`Real-source ordinary residue selection failed after genuine pointer attempts: ${JSON.stringify(attempts)}`);
}
async function clickAnyExactCa(page, catalogValue, layer, alignment, aligned) {
  const failures = [];
  for (const row of catalogValue.rows.filter(item => item.protein &&
      item.ref.atom_name === "CA").slice(0, 8)) {
    try {
      const clicked = await clickCatalogAtom(page, row, layer, alignment, aligned);
      return { clicked, failures };
    } catch (error) {
      const raw = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
      failures.push({ site: row.ref.site_index, error: String(error).slice(0, 700),
        lastNativeClick: raw?.lastNativeClick,
        nativeClickRevision: raw?.nativeClickRevision });
    }
  }
  throw new Error(`No exact ${layer} CA atom could be pointer-picked: ${JSON.stringify(failures)}`);
}
async function clickWithinWorkflow(page, panel, button) {
  const container = await panel.boundingBox();
  assert.ok(container, "Comparison workflow is not visible");
  const scrolls = [];
  for (let attempt = 0; attempt < 7; attempt += 1) {
    const box = await button.boundingBox();
    assert.ok(box, "Workflow button has no layout box");
    const hitState = await button.evaluate(element => {
      const rect = element.getBoundingClientRect();
      const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
      const hit = document.elementFromPoint(x, y);
      const ancestors = [];
      for (let item = element.parentElement; item; item = item.parentElement) {
        const bounds = item.getBoundingClientRect();
        ancestors.push({ className: item.className, scrollTop: item.scrollTop,
          scrollHeight: item.scrollHeight, clientHeight: item.clientHeight,
          rect: { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height } });
        if (item.classList.contains("mw-workflow")) break;
      }
      return { exposed: hit === element || element.contains(hit),
        hitTag: hit?.tagName ?? null, hitClass: hit?.className ?? null,
        hitText: hit?.textContent?.trim().slice(0, 80) ?? null, ancestors };
    });
    if (hitState.exposed) {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      return { scrolls, pointer: { x: box.x + box.width / 2, y: box.y + box.height / 2 },
        hitTestExposed: true };
    }
    const direction = box.y + box.height / 2 < container.y + 20 ? -450 : 450;
    const pointer = { x: container.x + container.width - 24,
      y: container.y + container.height / 2 };
    await page.mouse.move(pointer.x, pointer.y);
    await page.mouse.wheel(0, direction);
    scrolls.push({ attempt, direction, pointer, targetBoxBefore: box, hitState });
  }
  throw new Error(`Workflow button remained covered after real scrolling: ${JSON.stringify(scrolls)}`);
}
async function clickPairFocusByVisibleScroll(page, panel) {
  return clickWithinWorkflow(page, panel,
    panel.getByRole("region", { name: "명시한 CA 대응" })
      .getByRole("button", { name: "대응 원자 초점" }).first());
}
function itemRows(value) { return Array.isArray(value) ? value : value.rows; }
function catalogPair(catalogValue, identity) {
  const rows = catalogValue.rows.filter(row => row.ref.residue.model_number === 1 &&
    row.ref.residue.chain_auth === identity.chain_auth &&
    row.ref.residue.seq_auth === identity.seq_auth &&
    row.ref.residue.icode === identity.icode && row.ref.atom_name === identity.atom_name &&
    row.ref.altloc === identity.altloc);
  assert.equal(rows.length, 1, `Expected one exact CA catalog site: ${JSON.stringify(identity)}`);
  return rows[0];
}
async function downloadReport(app, page, panel, origin, run, format, expectedHandle) {
  const link = panel.getByRole("link", { name: format === "markdown" ? "Markdown 다운로드" : "정확한 JSON 다운로드" });
  const download = await downloadByClick(app, link);
  const url = new URL(download.url);
  assert.equal(url.origin, origin);
  assert.equal(url.pathname, `/api/runs/${run}/reports/download`);
  assert.equal(url.searchParams.get("handle"), expectedHandle);
  assert.equal(url.searchParams.get("format"), format);
  const response = await fetch(url);
  assert.equal(response.status, 200);
  const actual = fs.readFileSync(download.downloaded), stored = Buffer.from(await response.arrayBuffer());
  assert.ok(actual.equals(stored), `${format} browser download differs from immutable stored bytes`);
  const selectedUrl = new URL(`/api/runs/${run}/reports/selected`, origin);
  selectedUrl.searchParams.set("handle", expectedHandle);
  const selected = await readJson(selectedUrl);
  if (format === "markdown") assert.equal(actual.toString("utf8"), selected.markdown);
  else assert.deepEqual(JSON.parse(actual.toString("utf8")), selected.manifest);
  return { file: download.downloaded, handle: expectedHandle, bytes: actual.length,
    sha256: sha(actual), url: download.url, selectedArtifactMatched: true };
}

async function run(input) {
  const oracle = fixtureOracle(input.fixtureDir);
  const session = await launchOffscreen(input);
  const { app, page, artifacts } = session;
  const harnessBytes = fs.readFileSync(__filename);
  fs.writeFileSync(path.join(artifacts, "harness-source.cjs"), harnessBytes);
  fs.writeFileSync(path.join(artifacts, "harness-source.sha256"), `${sha(harnessBytes)}  harness-source.cjs\n`);
  const evidence = path.join(artifacts, `comparison-${input.mode}.jsonl`);
  const source = { ...sourceDigest(), digestScope: "frontend/app + frontend/src + offscreen tests + backend/mw + frontend/package.json; parent frozen full-runtime manifest is authoritative" };
  const rows = [];
  async function step(caseId, description, action, observe) {
    const before = await status(app, page);
    let result, proof;
    try {
      result = await action();
      const assertion = await observe(result);
      proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0, "Renderer attempted non-loopback request");
      assert.equal(proof.status.offscreen, true);
      assert.equal(proof.status.visible, false);
      assert.equal(proof.status.hardwareAccelerationEnabled, true);
      const row = { caseId, status: "pass", description, source, before, after: proof.status,
        assertion, screenshot: proof.screenshot, paint: proof.paint };
      rows.push(row); fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
      return result;
    } catch (error) {
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* primary failure kept */ }
      const row = { caseId, status: "fail", description, source, before,
        actionResult: result ?? null, after: proof?.status ?? null, error: String(error),
        screenshot: proof?.screenshot, paint: proof?.paint };
      rows.push(row); fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
      throw error;
    }
  }
  try {
    await waitForBoot(page);
    await step("C00", "Observe real GPU-enabled Mol* and fixture provenance", async () => {
      const viewer = input.run ? await waitForViewer(page, value => value.sourceHandle && value.nativeCamera) : null;
      return { viewer, fixtureHashes: oracle.sourceHashes };
    }, async value => ({ sourceHandle: value.viewer?.sourceHandle ?? null, fixtureHashes: value.fixtureHashes }));
    if (input.mode === "adapter") {
      const origin = new URL(page.url()).origin;
      const sourceCatalog = await catalog(origin, input.run, input.reference);
      const targetRow = sourceCatalog.rows.find(row => row.ref.residue.chain_auth === "A" &&
        row.ref.residue.seq_auth === 10 && row.ref.residue.resname === "ALA");
      assert.ok(targetRow, "Sparse original-PDB ALA10 fixture site missing");
      assert.equal(targetRow.ref.residue.chain_label, "Axp");
      assert.equal(targetRow.ref.residue.seq_label, null);
      const selectedSource = await step("C15-pdb-history-source",
        "Click real load_structure history row to return to the exact sparse original PDB",
        async () => {
          await page.getByRole("tab", { name: /^run/i }).click();
          const before = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
          const rows = page.locator(".mw-step").filter({ hasText: "load_structure" });
          const count = await rows.count();
          assert.ok(count > 0, "No actual load_structure history row remains in run");
          let clickedRow = null;
          for (let index = 0; index < count; index += 1) {
            await rows.nth(index).click();
            try {
              const native = await nativeSource(page, value =>
                value.sourceHandle === input.reference && value.catalogReady &&
                value.selectionError == null, 2500);
              clickedRow = index;
              return { before, native, clickedRow, historyRows: count };
            } catch { /* Another genuine history row; continue to the requested source. */ }
          }
          throw new Error(`No visible history row restored exact PDB source ${input.reference}`);
        }, async value => {
          assert.equal(value.native.sourceHandle, input.reference);
          assert.equal(value.native.catalogReady, true);
          assert.equal(value.native.selectionError, null);
          return { historyRowIndex: value.clickedRow, totalRows: value.historyRows,
            sourceHandle: value.native.sourceHandle, catalogSha256: sourceCatalog.viewer_source_sha256,
            nativeAtomCount: value.native.layers?.[0]?.nativeAtomCount };
        });
      const controls = page.locator('section[aria-label="뷰어 요청"]');
      const targetSelector = controls.getByRole("combobox", { name: "뷰어 대상 선택" });
      const target = await step("C15-pdb-local-target",
        "Inspect actual offline target option and its authoritative original-PDB seven-field identity",
        async () => {
          await targetSelector.waitFor({ state: "visible", timeout: 30000 });
          const options = await targetSelector.locator("option").evaluateAll(items =>
            items.map(item => ({ value: item.value, label: item.textContent?.trim() ?? "" })));
          const item = options.find(option => /ALA A\/10(?:\D|$)/.test(option.label));
          assert.ok(item?.value, `No visible ALA A/10 target alias: ${JSON.stringify(options)}`);
          return { alias: item.value, label: item.label, options,
            offlineBadge: await controls.locator(".mw-badge").innerText(),
            native: await nativeSource(page, value => value.sourceHandle === input.reference &&
              value.catalogReady && value.selectionError == null) };
        }, async value => {
          assert.match(value.offlineBadge, /local_only/);
          assert.equal(value.native.sourceHandle, input.reference);
          assert.equal(value.native.selection, null);
          return { alias: value.alias, visibleLabel: value.label,
            offlineMode: value.offlineBadge, authoritativeResidue: targetRow.ref.residue };
        });
      const focus = await step("C15-pdb-local-focus",
        "Choose the visible local target to send supported /focus and apply selection plus camera axes",
        async () => {
          const before = await nativeSource(page, value => value.sourceHandle === input.reference &&
            value.catalogReady && value.sessionId);
          const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
            new URL(response.url()).pathname === `/api/runs/${input.run}/viewer/intents`,
          { timeout: 30000 });
          await targetSelector.selectOption(target.alias);
          const response = await responsePromise;
          assert.equal(response.status(), 201, `Local focus failed: ${await response.text()}`);
          const submitted = await response.json();
          const intent = await completedViewerIntent(origin, input.run, submitted.intent_id);
          const native = await nativeSource(page, value => value.sourceHandle === input.reference &&
            sameResidue(value.selection, targetRow.ref.residue) &&
            norm(vectorSub(value.nativeCamera.target, before.nativeCamera.target)) > 1e-4, 45000);
          const settled = (await nativeQuietAt(page, targetRow, "reference")).second;
          return { before, native, settled, intent,
            submittedPrompt: response.request().postDataJSON().prompt };
        }, async value => {
          assert.equal(value.submittedPrompt, `/focus ${target.alias}`);
          assert.equal(value.intent.source, "local_command");
          assert.equal(value.intent.status, "applied");
          assert.deepEqual(value.intent.commands.map(item => item.axis), ["selection", "camera"]);
          assert.ok(value.intent.acks.every(item => item.status === "applied"));
          assert.ok(sameResidue(value.settled.selection, targetRow.ref.residue));
          assert.equal(value.settled.selectionError, null);
          return { prompt: value.submittedPrompt, intentId: value.intent.intent_id,
            commands: value.intent.commands, acks: value.intent.acks,
            nativeSelection: value.settled.selection,
            beforeCamera: value.before.nativeCamera,
            afterCamera: value.settled.nativeCamera,
            authoritativeAxpNullLabel: true };
        });
      const saved = await step("C15-pdb-save-selected-scene",
        "Click actual M9 Save for a selected original PDB with authoritative Axp identity",
        async () => {
          const name = `M10 Axp original PDB ${Date.now()}`;
          await page.getByRole("textbox", { name: "보기 이름" }).fill(name);
          await page.waitForFunction(() => {
            const button = [...document.querySelectorAll("button")]
              .find(item => item.textContent?.trim() === "현재 보기 저장");
            return !!button && !button.disabled;
          }, null, { timeout: 30000 });
          const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
            new URL(response.url()).pathname === `/api/runs/${input.run}/viewer/scenes`,
          { timeout: 30000 });
          await page.getByRole("button", { name: "현재 보기 저장" }).click();
          const response = await responsePromise;
          assert.equal(response.status(), 201, `Selected PDB scene save failed: ${await response.text()}`);
          const created = await response.json();
          const selectedUrl = new URL(`/api/runs/${input.run}/viewer/scenes/selected`, origin);
          selectedUrl.searchParams.set("handle", created.handle);
          const scene = await readJson(selectedUrl);
          await page.getByText(`보기 저장 완료 · ${name}`, { exact: true }).waitFor({ timeout: 30000 });
          assert.equal(await page.getByRole("combobox", { name: "저장된 보기" }).inputValue(), scene.handle);
          return scene;
        }, async scene => {
          assert.equal(scene.value.structure_handle, input.reference);
          assert.ok(sameResidue(scene.value.selection, targetRow.ref.residue));
          nativeCameraClose(scene.value.camera, focus.settled.nativeCamera, 1e-3,
            "selected PDB scene full camera");
          return { sceneHandle: scene.handle, structureHandle: scene.value.structure_handle,
            selection: scene.value.selection, fullCamera: scene.value.camera };
        });
      fs.writeFileSync(path.join(artifacts, "adapter-selected-scene.json"), JSON.stringify({
        runId: input.run, sourceHandle: input.reference, sceneHandle: saved.handle,
        selection: saved.value.selection, camera: saved.value.camera,
        catalogSha256: sourceCatalog.viewer_source_sha256 }, null, 2) + "\n");
      await step("C15-pdb-local-clear-orbit", "Click supported /clear, then orbit actual native PDB away from saved view", async () => {
        const before = await nativeSource(page, value => sameResidue(value.selection, targetRow.ref.residue));
        const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${input.run}/viewer/intents`,
        { timeout: 30000 });
        await controls.getByRole("button", { name: "선택 해제" }).click();
        const response = await responsePromise;
        assert.equal(response.status(), 201);
        const submitted = await response.json();
        const intent = await completedViewerIntent(origin, input.run, submitted.intent_id);
        const cleared = await nativeSource(page, value => value.sourceHandle === input.reference &&
          value.selection === null && value.selectionError == null &&
          value.lastAck?.status === "applied", 45000);
        const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
        const box = await canvas.boundingBox(); assert.ok(box);
        const x = box.x + box.width * 0.52, y = box.y + box.height * 0.51;
        await page.mouse.move(x, y); await page.mouse.down();
        await page.mouse.move(x + 112, y + 57, { steps: 14 }); await page.mouse.up();
        const orbited = await nativeSource(page, value => value.sourceHandle === input.reference &&
          value.selection === null && norm(vectorSub(value.nativeCamera.position,
            saved.value.camera.position)) > 1e-3, 15000);
        return { before, cleared, orbited, intent,
          submittedPrompt: response.request().postDataJSON().prompt };
      }, async value => {
        assert.equal(value.submittedPrompt, "/clear");
        assert.equal(value.intent.source, "local_command");
        assert.equal(value.intent.status, "applied");
        assert.ok(value.intent.commands.some(item => item.axis === "selection" && item.value === "clear"));
        assert.ok(value.intent.acks.every(item => item.status === "applied"));
        assert.equal(value.cleared.selection, null);
        return { prompt: value.submittedPrompt, commands: value.intent.commands,
          acks: value.intent.acks, nativeCleared: value.cleared.selection,
          orbitCamera: value.orbited.nativeCamera };
      });
      async function restoreSelectedPdb(label) {
        const before = await nativeSource(page, value => value.sourceHandle.includes(input.run));
        await page.getByRole("combobox", { name: "저장된 보기" }).selectOption(saved.handle);
        await page.getByRole("button", { name: "저장된 보기 복원" }).click();
        await page.getByText(`저장된 보기 복원 완료 · ${saved.value.name}`, { exact: true })
          .waitFor({ timeout: 45000 });
        const after = await nativeSource(page, value => value.sourceHandle === input.reference &&
          value.sessionId !== before.sessionId && value.generation !== before.generation &&
          value.catalogReady && value.selectionError == null &&
          sameResidue(value.selection, saved.value.selection), 45000);
        nativeCameraClose(after.nativeCamera, saved.value.camera, 1e-3, label);
        return { before, after };
      }
      await step("C15-pdb-selected-scene-restore", "Restore saved selected PDB scene after clear and manual orbit", async () =>
        restoreSelectedPdb("selected PDB scene restore"), async ({ before, after }) => ({
          sceneHandle: saved.handle, beforeSession: before.sessionId, restoredSession: after.sessionId,
          beforeGeneration: before.generation, restoredGeneration: after.generation,
          nativeSelection: after.selection, fullCamera: after.nativeCamera,
          catalogReady: after.catalogReady, selectionError: after.selectionError }));
      await step("C15-pdb-selected-scene-reopen", "Reload actual Electron page and restore the same immutable selected PDB scene", async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await waitForBoot(page);
        await page.getByRole("combobox", { name: "저장된 보기" })
          .locator(`option[value="${saved.handle}"]`).waitFor({ state: "attached", timeout: 30000 });
        return restoreSelectedPdb("selected PDB scene after page reopen");
      }, async ({ before, after }) => ({ sceneHandle: saved.handle,
        sourceHandle: after.sourceHandle, priorSession: before.sessionId,
        freshSession: after.sessionId, authoritativeSelection: after.selection,
        fullCamera: after.nativeCamera, catalogReady: after.catalogReady,
        selectionError: after.selectionError }));
    } else if (input.mode === "catalog-race") {
      const initial = await nativeSource(page, value => value.sourceHandle.includes(input.run), 45000);
      const origin = new URL(page.url()).origin;
      const source = initial.sourceHandle;
      const immutableCatalog = await catalog(origin, input.run, source);
      let releaseHold, hitHold, intercepted = 0, staleRouteError = null;
      const release = new Promise(resolve => { releaseHold = resolve; });
      const hit = new Promise(resolve => { hitHold = resolve; });
      const holdCatalog = async route => {
        const url = new URL(route.request().url());
        if (route.request().method() !== "GET" ||
            url.pathname !== `/api/runs/${input.run}/structures/atoms` ||
            url.searchParams.get("handle") !== source) {
          await route.continue(); return;
        }
        intercepted += 1;
        if (intercepted === 1) hitHold();
        await release;
        try { await route.continue(); } catch (error) { staleRouteError = String(error); }
      };
      await page.route("**/structures/atoms?*", holdCatalog);
      try {
        await step("C13-catalog-held-until-native-ready",
          "Hold the unchanged real atom-catalog GET until fresh Mol* native structure is ready",
          async () => {
            await page.reload({ waitUntil: "domcontentloaded" });
            await Promise.race([hit, new Promise((_, reject) => setTimeout(() =>
              reject(new Error("Fresh document did not request the source atom catalog")), 15000))]);
            const nativeWithoutCatalog = await waitForViewer(page, value => value.ready &&
              value.sourceHandle === source && value.catalogReady === false &&
              value.layers?.[0]?.sourceHandle === source &&
              value.layers[0].nativeAtomCount > 0, 30000);
            const action = page.locator('[aria-label="원자 거리와 두 구조 비교"]')
              .getByRole("button", { name: "원자 거리 측정", exact: true });
            return { nativeWithoutCatalog, heldCatalogRequests: intercepted,
              measureDisabled: await action.isDisabled(),
              visible: await page.locator("body").innerText() };
          }, async value => {
            assert.ok(value.heldCatalogRequests > 0,
              "No actual catalog response was held during native initialization");
            assert.equal(value.nativeWithoutCatalog.catalogReady, false);
            assert.equal(value.nativeWithoutCatalog.sourceHandle, source);
            assert.ok(value.nativeWithoutCatalog.layers[0].nativeAtomCount > 0,
              "Native structure was not initialized before catalog release");
            assert.equal(value.measureDisabled, true,
              "Atom controls became enabled with no validated source catalog");
            assert.match(value.visible, /원자 목록을 검증하는 중|원자 목록.*읽는 중|원자 목록.*준비/);
            return { fixture: "unchanged real catalog GET held in the renderer route",
              immutableCatalogSha256: immutableCatalog.viewer_source_sha256,
              actualNativeSource: source,
              nativeAtomCount: value.nativeWithoutCatalog.layers[0].nativeAtomCount,
              catalogReadyWhileHeld: false, measureDisabledWhileHeld: true,
              selectionErrorWhileHeld: value.nativeWithoutCatalog.selectionError,
              lateCatalogAfterNativeReadyObserved: true,
              startupEffectInterleavingProven: false };
          });
        releaseHold();
        await step("C13-catalog-after-native-ready",
          "Release unchanged atom catalog and require native bijection/readiness plus usable controls",
          async () => {
            const recovered = await nativeSource(page, value => value.sourceHandle === source &&
              value.catalogReady === true && value.selectionError == null, 45000);
            await page.getByRole("group", { name: "표현 방식" })
              .getByRole("button", { name: "ball-and-stick", exact: true }).click();
            const ready = await waitForViewer(page, value => value.sourceHandle === source &&
              value.catalogReady === true && value.representation === "ball-and-stick", 30000);
            const action = page.locator('[aria-label="원자 거리와 두 구조 비교"]')
              .getByRole("button", { name: "원자 거리 측정", exact: true });
            await action.waitFor({ state: "visible", timeout: 10000 });
            return { recovered, ready, measureDisabled: await action.isDisabled(),
              intercepted, staleRouteError };
          }, async value => {
            assert.equal(value.measureDisabled, false,
              "Validated catalog did not make actual atom controls usable");
            assert.equal(value.ready.sourceHandle, source);
            assert.equal(value.ready.catalogReady, true);
            assert.equal(value.ready.selectionError, null);
            assert.ok(value.ready.qaAtoms?.length > 0);
            return { catalogSha256: immutableCatalog.viewer_source_sha256,
              nativeSource: source, nativeAtomCount: value.ready.qaAtoms.length,
              validatedAfterRelease: true, atomControlEnabled: true,
              heldRequests: value.intercepted, routeError: value.staleRouteError };
          });
      } finally {
        releaseHold();
        await page.unroute("**/structures/atoms?*", holdCatalog);
      }
    } else if (input.mode === "faults") {
      const origin = new URL(page.url()).origin;
      const panel = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
      const selector = panel.getByRole("combobox", { name: "저장된 거리·정렬 결과" });
      const result = (await measurement(origin, input.run, input.result)).result;
      assert.equal(result.schema, "rigid_alignment@1", "Fault lane needs an existing alignment overlay");
      const matchDetail = request => request.method() === "GET" &&
        new URL(request.url()).pathname === `/api/runs/${input.run}/objects/measurement` &&
        new URL(request.url()).searchParams.get("handle") === input.result;
      let injected = 0;
      const failDetail = async route => {
        if (matchDetail(route.request()) && injected++ === 0)
          await route.fulfill({ status: 503, contentType: "application/json",
            body: JSON.stringify({ detail: { error: "qa_fixture_read_unavailable",
              message: "QA fixture: immutable comparison read unavailable" } }) });
        else await route.continue();
      };
      await page.route("**/objects/measurement?*", failDetail);
      await step("C13-detail-read-503", "Inject a labeled single GET 503 while selecting an existing alignment result", async () => {
        await selector.selectOption(input.result);
        const alert = panel.getByRole("alert").filter({ hasText: /QA fixture: immutable comparison read unavailable/ });
        await alert.waitFor({ timeout: 15000 });
        return { error: await alert.innerText(), native: await page.evaluate(() =>
          window.__protviewQaSnapshot?.() ?? null), injected };
      }, async value => {
        assert.equal(value.injected, 1);
        assert.match(value.error, /QA fixture: immutable comparison read unavailable/);
        assert.notEqual(value.native.layers?.length, 2,
          "Failed detail read falsely applied an overlay");
        return { injectedStatus: 503, visibleError: value.error,
          nativeLayerCount: value.native.layers?.length ?? 0,
          fixtureOnly: true };
      });
      await page.unroute("**/objects/measurement?*", failDetail);
      await step("C13-detail-retry", "Retry unchanged saved alignment through visible result selector", async () => {
        await selector.selectOption("");
        await selector.selectOption(input.result);
        return waitForViewer(page, value => value.catalogReady && value.ready &&
          value.layers?.length === 2 && value.layers[0].sourceHandle === result.reference_handle &&
          value.layers[1].sourceHandle === result.moving_handle, 45000);
      }, async native => ({ resultHandle: input.result,
        layers: assertNativeLayers(native, result, true, { reference: true, moving: true }),
        recoveredByImmutableRead: true }));
      await step("C08-focus-then-manual-orbit", "Use pair focus, then orbit with a real mouse drag and check retention", async () => {
        const before = await waitForViewer(page, value => value.layers?.length === 2 && value.nativeCamera);
        const focusedClick = await clickPairFocusByVisibleScroll(page, panel);
        const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
        const box = await canvas.boundingBox(); assert.ok(box);
        const x = box.x + box.width * 0.54, y = box.y + box.height * 0.49;
        await page.mouse.move(x, y); await page.mouse.down();
        await page.mouse.move(x + 125, y + 72, { steps: 14 }); await page.mouse.up();
        const manual = await waitForViewer(page, value => value.nativeCamera &&
          norm(vectorSub(value.nativeCamera.position, before.nativeCamera.position)) > 1e-3, 10000);
        const manualSettled = (await nativeQuietAt(page,
          { ref: result.pairs[0].reference }, "reference")).second;
        // This is a visible focus-then-orbit retention check. It does not
        // establish that focus was still pending when the pointer moved.
        await page.waitForTimeout(700);
        const settled = (await nativeQuietAt(page,
          { ref: result.pairs[0].reference }, "reference")).second;
        return { before, manual, manualSettled, settled, focusedClick };
      }, async ({ before, manual, manualSettled, settled, focusedClick }) => {
        assertNativeLayers(settled, result, true, { reference: true, moving: true });
        const manualDelta = norm(vectorSub(manual.nativeCamera.position,
          before.nativeCamera.position));
        const settledDelta = norm(vectorSub(settled.nativeCamera.position,
          before.nativeCamera.position));
        assert.ok(manualDelta > 1e-3 && settledDelta > 1e-3,
          "Manual orbit was not retained after focus and pointer actions");
        nativeCameraClose(settled.nativeCamera, manualSettled.nativeCamera, 1e-3,
          "manual camera after observation window");
        return { nativeCameraBefore: before.nativeCamera,
          nativeCameraAfterDrag: manual.nativeCamera,
          nativeCameraAfterDragSettled: manualSettled.nativeCamera,
          nativeCameraAfterObservationWindow: settled.nativeCamera,
          focusedClick,
          observationWindowMs: 700,
          overlapOrderingProven: false };
      });
      if (input.otherResult) {
        const bResult = (await measurement(origin, input.run, input.otherResult)).result;
        let releaseHold, hitHold;
        const release = new Promise(resolve => { releaseHold = resolve; });
        const hit = new Promise(resolve => { hitHold = resolve; });
        let settleClientA;
        const clientASettled = new Promise(resolve => { settleClientA = resolve; });
        const onClientASettled = request => { if (matchDetail(request))
          settleClientA({ url: request.url(), failure: request.failure() ?? null }); };
        page.on("requestfinished", onClientASettled);
        page.on("requestfailed", onClientASettled);
        let intercepted = 0, staleRouteError = null;
        const holdDetail = async route => {
          if (!matchDetail(route.request()) || intercepted++ > 0) { await route.continue(); return; }
          hitHold();
          await release;
          try { await route.continue(); } catch (error) { staleRouteError = String(error); }
        };
        await page.route("**/objects/measurement?*", holdDetail);
        try {
          await step("C12-held-A-then-B", "Hold A alignment detail GET, select existing B and release stale A response", async () => {
            await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).click();
            await selector.selectOption("");
            await selector.selectOption(input.result);
            await Promise.race([hit, new Promise((_, reject) =>
              setTimeout(() => reject(new Error("Held A detail GET not issued")), 15000))]);
            await selector.selectOption(input.otherResult);
            const selected = bResult.schema === "rigid_alignment@1"
              ? await waitForViewer(page, value => value.layers?.length === 2 &&
                value.layers[0].sourceHandle === bResult.reference_handle &&
                value.layers[1].sourceHandle === bResult.moving_handle, 45000)
              : await nativeSource(page, value => value.sourceHandle === bResult.structure_handle &&
                value.measureMode, 45000);
            releaseHold();
            const clientSettlement = await Promise.race([clientASettled,
              new Promise((_, reject) => setTimeout(() =>
                reject(new Error("Held A browser request did not settle or fail")), 15000))]);
            await page.evaluate(() => new Promise(resolve =>
              requestAnimationFrame(() => requestAnimationFrame(resolve))));
            const finalNative = bResult.schema === "rigid_alignment@1"
              ? await waitForViewer(page, value => value.layers?.length === 2 &&
                value.layers[0].sourceHandle === bResult.reference_handle &&
                value.layers[1].sourceHandle === bResult.moving_handle, 10000)
              : await nativeSource(page, value => value.sourceHandle === bResult.structure_handle &&
                value.measureMode, 10000);
            return { selected, finalNative, clientSettlement,
              selectorValue: await selector.inputValue(),
              visible: await panel.innerText(), staleRouteError, intercepted };
          }, async value => {
            assert.equal(value.intercepted, 1);
            assert.equal(value.selectorValue, input.otherResult);
            if (bResult.schema === "rigid_alignment@1")
              assertNativeLayers(value.finalNative, bResult, true,
                { reference: true, moving: true });
            else assertDistanceResult(bResult, bResult.structure_handle);
            assert.ok(value.visible.includes(bResult.schema === "rigid_alignment@1" ? "정렬 RMSD" : "원자 거리"));
            assert.ok(!value.visible.includes("저장된 측정 읽는 중"),
              "Stale A kept the comparison busy after its browser request settled");
            return { heldA: input.result, winningB: input.otherResult,
              nativeSource: value.finalNative.sourceHandle,
              clientASettlement: value.clientSettlement,
              staleRouteError: value.staleRouteError ?? null,
              oldDetailDidNotOverwrite: true };
          });
        } finally { releaseHold(); page.off("requestfinished", onClientASettled);
          page.off("requestfailed", onClientASettled);
          await page.unroute("**/objects/measurement?*", holdDetail); }
      }
      if (input.otherRun) {
        let releaseHold, hitHold, settleClientA;
        const release = new Promise(resolve => { releaseHold = resolve; });
        const hit = new Promise(resolve => { hitHold = resolve; });
        const clientASettled = new Promise(resolve => { settleClientA = resolve; });
        const onClientASettled = request => {
          if (matchDetail(request)) settleClientA({ url: request.url(),
            failure: request.failure() ?? null });
        };
        let intercepted = 0, staleRouteError = null;
        const holdDetailForRunSwitch = async route => {
          if (!matchDetail(route.request()) || intercepted++ > 0) {
            await route.continue(); return;
          }
          hitHold();
          await release;
          try { await route.continue(); } catch (error) { staleRouteError = String(error); }
        };
        page.on("requestfinished", onClientASettled);
        page.on("requestfailed", onClientASettled);
        await page.route("**/objects/measurement?*", holdDetailForRunSwitch);
        try {
          await step("C12-held-detail-run-switch", "Hold current-run alignment detail GET while switching to a different real run", async () => {
            if (await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).count())
              await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).click();
            await selector.selectOption("");
            await selector.selectOption(input.result);
            await Promise.race([hit, new Promise((_, reject) => setTimeout(() =>
              reject(new Error("Current-run detail GET was not held")), 15000))]);
            await page.getByRole("tab", { name: /^run/i }).click();
            await page.locator("#run-choice").selectOption(input.otherRun);
            const switched = await nativeSource(page, value =>
              value.sourceHandle.includes(input.otherRun) && value.layers?.length !== 2, 45000);
            releaseHold();
            const clientSettlement = await Promise.race([clientASettled,
              new Promise((_, reject) => setTimeout(() =>
                reject(new Error("Old-run detail request did not settle or fail")), 15000))]);
            await page.evaluate(() => new Promise(resolve =>
              requestAnimationFrame(() => requestAnimationFrame(resolve))));
            const finalNative = await nativeSource(page, value =>
              value.sourceHandle.includes(input.otherRun) && value.layers?.length !== 2, 10000);
            return { switched, finalNative, clientSettlement, staleRouteError,
              intercepted, runChoice: await page.locator("#run-choice").inputValue(),
              resultChoice: await selector.inputValue(), visible: await panel.innerText() };
          }, async value => {
            assert.equal(value.intercepted, 1);
            assert.equal(value.runChoice, input.otherRun);
            assert.equal(value.resultChoice, "", "Old-run comparison result remained selected");
            assert.ok(value.finalNative.sourceHandle.includes(input.otherRun));
            assert.notEqual(value.finalNative.layers?.length, 2);
            assert.ok(!value.visible.includes("저장된 측정 읽는 중"),
              "Old-run response left new run in stale busy state");
            return { heldResult: input.result, winningRun: input.otherRun,
              nativeSource: value.finalNative.sourceHandle,
              clientASettlement: value.clientSettlement,
              oldReadDidNotOverwrite: true };
          });
        } finally {
          releaseHold();
          page.off("requestfinished", onClientASettled);
          page.off("requestfailed", onClientASettled);
          await page.unroute("**/objects/measurement?*", holdDetailForRunSwitch);
        }
        await page.locator("#run-choice").selectOption(input.run);
        await nativeSource(page, value => value.sourceHandle.includes(input.run), 45000);
      }
      await step("C13-native-context-loss", "Trigger actual WEBGL_lose_context on the live Mol* canvas", async () => {
        if (await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).count())
          await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).click();
        await selector.selectOption("");
        await selector.selectOption(input.result);
        const before = await waitForViewer(page, value => value.ready && value.layers?.length === 2 &&
          value.catalogReady, 45000);
        const available = await page.locator("canvas.mw-molstar-canvas:visible").first().evaluate(canvas => {
          const gl = canvas.getContext("webgl2");
          const extension = gl?.getExtension("WEBGL_lose_context");
          if (!extension) return false;
          extension.loseContext();
          return true;
        });
        assert.equal(available, true, "WEBGL_lose_context unavailable in actual Electron renderer");
        await page.getByText("WebGL 연결이 끊어졌습니다. 구조를 다시 불러오세요.")
          .first().waitFor({ timeout: 10000 });
        const after = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
        return { before, after };
      }, async value => {
        assert.equal(value.before.layers.length, 2);
        assert.notEqual(value.after?.ready, true, "Lost WebGL context falsely remained ready");
        return { nativeContextLost: true, readyAfterLoss: value.after?.ready,
          visibleError: "WebGL 연결이 끊어졌습니다. 구조를 다시 불러오세요." };
      });
      await step("C13-context-retry", "Click visible source and atom reread after actual context loss", async () => {
        await panel.getByRole("button", { name: "기준 구조·원자 다시 읽기" }).click();
        return waitForViewer(page, value => value.ready && value.catalogReady &&
          value.layers?.length === 2 && value.layers[0].sourceHandle === result.reference_handle &&
          value.layers[1].sourceHandle === result.moving_handle, 45000);
      }, async native => ({ resultHandle: input.result,
        layers: assertNativeLayers(native, result, true, { reference: true, moving: true }),
        recoveredWithoutRefit: true }));
      await page.reload();
      await waitForBoot(page);
      let movingFaults = 0;
      const failMovingBytes = async route => {
        const url = new URL(route.request().url());
        if (route.request().method() === "GET" &&
            url.pathname === `/api/runs/${input.run}/structures/bytes` &&
            url.searchParams.get("handle") === result.moving_handle && movingFaults++ === 0)
          await route.fulfill({ status: 503, contentType: "application/json",
            body: JSON.stringify({ detail: { error: "qa_fixture_moving_source_unavailable",
              message: "QA fixture: moving source bytes unavailable" } }) });
        else await route.continue();
      };
      await page.route("**/structures/bytes?*", failMovingBytes);
      await step("C13-moving-bytes-503", "Inject labeled moving-source bytes GET 503 during real alignment reopen", async () => {
        if (await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).count())
          await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).click();
        await selector.selectOption("");
        await waitForViewer(page, value => value.ready && value.layers?.length === 1, 15000);
        await selector.selectOption(input.result);
        const alert = panel.getByRole("alert").filter({ hasText: /이동 구조 읽기 실패.*HTTP 503/ });
        await alert.waitFor({ timeout: 15000 });
        return { error: await alert.innerText(), faults: movingFaults,
          native: await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null) };
      }, async value => {
        assert.equal(value.faults, 1);
        assert.notEqual(value.native?.layers?.length, 2,
          "Failed moving-source read falsely applied both native layers");
        return { fixtureOnly: true, status: 503, visibleError: value.error,
          nativeReady: value.native?.ready ?? false,
          nativeLayerCount: value.native?.layers?.length ?? 0 };
      });
      await page.unroute("**/structures/bytes?*", failMovingBytes);
      await step("C13-moving-bytes-retry", "Click visible moving source reread after unchanged 503 fixture", async () => {
        await panel.getByRole("button", { name: "이동 구조·원자 다시 읽기" }).click();
        return waitForViewer(page, value => value.ready && value.catalogReady &&
          value.layers?.length === 2 && value.layers[1].sourceHandle === result.moving_handle, 45000);
      }, async native => ({ layers: assertNativeLayers(native, result, true,
        { reference: true, moving: true }), readRetryWithoutRefit: true }));
      await page.reload();
      await waitForBoot(page);
      let malformedCatalogs = 0;
      const malformedReference = async route => {
        const url = new URL(route.request().url());
        if (route.request().method() === "GET" &&
            url.pathname === `/api/runs/${input.run}/structures/atoms` &&
            url.searchParams.get("handle") === result.reference_handle) {
          const real = await route.fetch();
          assert.equal(real.status(), 200);
          const value = await real.json();
          malformedCatalogs += 1;
          await route.fulfill({ response: real, contentType: "application/json",
            body: JSON.stringify({ ...value, viewer_source_sha256: "0".repeat(64) }) });
        } else await route.continue();
      };
      await page.route("**/structures/atoms?*", malformedReference);
      await step("C13-malformed-catalog-sha", "Inject labeled mismatched reference atom-catalog SHA while reopening alignment", async () => {
        if (await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).count())
          await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).click();
        await selector.selectOption("");
        await waitForViewer(page, value => value.ready && value.layers?.length === 1, 15000);
        await selector.selectOption(input.result);
        await page.getByText(/원자 목록.*일치하지|원자 목록.*SHA|원본.*SHA|source.*hash/i)
          .first().waitFor({ timeout: 15000 });
        return { malformedCatalogs,
          visible: await page.locator("body").innerText(),
          native: await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null) };
      }, async value => {
        assert.ok(value.malformedCatalogs > 0, "No reference catalog response was actually malformed");
        assert.notEqual(value.native?.layers?.length, 2,
          "Mismatched atom catalog falsely applied two native layers");
        return { fixtureOnly: true, injectedSha256: "0".repeat(64),
          malformedResponses: value.malformedCatalogs,
          nativeReady: value.native?.ready ?? false,
          visibleErrorExcerpt: value.visible.match(/.{0,60}(?:SHA|원자 목록|원본).{0,100}/)?.[0] ?? null };
      });
      await page.unroute("**/structures/atoms?*", malformedReference);
      await step("C13-malformed-catalog-retry", "Click visible reference catalog reread after correcting the fixture", async () => {
        await panel.getByRole("button", { name: "기준 구조·원자 다시 읽기" }).click();
        if (await panel.getByRole("button", { name: "대응 원자 목록 다시 읽기" }).count())
          await panel.getByRole("button", { name: "대응 원자 목록 다시 읽기" }).click();
        return waitForViewer(page, value => value.ready && value.catalogReady &&
          value.layers?.length === 2 && value.layers[0].sourceHandle === result.reference_handle &&
          value.layers[1].sourceHandle === result.moving_handle, 45000);
      }, async native => ({ layers: assertNativeLayers(native, result, true,
        { reference: true, moving: true }), readRetryWithoutRefit: true }));
    } else if (input.mode === "replay") {
      const origin = new URL(page.url()).origin;
      const panel = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
      const resultBefore = await measurement(origin, input.run, input.result);
      const reportUrl = new URL(`/api/runs/${input.run}/reports/selected`, origin);
      reportUrl.searchParams.set("handle", input.report);
      const reportBefore = await readJson(reportUrl);
      assert.equal(reportBefore.manifest.result_handle, input.result);
      const sourceHandles = resultBefore.result.schema === "rigid_alignment@1"
        ? [resultBefore.result.reference_handle, resultBefore.result.moving_handle]
        : [resultBefore.result.structure_handle];
      const sourcesBefore = await Promise.all(sourceHandles.map(handle => catalog(origin, input.run, handle)));
      const forbidden = [];
      page.on("request", request => {
        const url = new URL(request.url());
        if (url.origin !== origin || request.method() !== "POST") return;
        if (/\/(commands|method_reports|uploads|viewer\/scenes|viewer\/figures)$/.test(url.pathname))
          forbidden.push({ method: request.method(), url: request.url() });
      });
      await step("C14-select-existing-result", "Select an immutable measured or aligned handle after events-only recovery", async () => {
        await panel.getByRole("combobox", { name: "저장된 거리·정렬 결과" }).selectOption(input.result);
        if (resultBefore.result.schema === "rigid_alignment@1")
          return waitForViewer(page, value => value.ready && value.catalogReady &&
            value.layers?.length === 2 &&
            value.layers[0].sourceHandle === sourceHandles[0] &&
            value.layers[1].sourceHandle === sourceHandles[1] &&
            value.layers[1].visible, 45000);
        return nativeSource(page, value => value.sourceHandle === sourceHandles[0] &&
          value.catalogReady && value.measureMode, 45000);
      }, async native => {
        if (resultBefore.result.schema === "rigid_alignment@1") {
          const result = resultBefore.result;
          assert.ok(result.pairs.length >= 3 && result.pair_count === result.pairs.length);
          const rotation = result.rotation.flat(), residuals = result.pairs.map(pair =>
            norm(vectorSub(transform(pair.moving_coordinate_A, rotation, result.translation_A),
              pair.reference_coordinate_A)));
          const rmsd = Math.sqrt(residuals.reduce((sum, v) => sum + v * v, 0) / residuals.length);
          close(rmsd, result.rmsd_A, 1e-10 * Math.max(1, rmsd), "reopened independent RMSD");
          close(determinant3(rotation), 1, 1e-10, "reopened proper rotation");
          return { resultHandle: input.result, schema: result.schema, independentRmsdA: rmsd,
            layers: assertNativeLayers(native, result, true, { reference: true, moving: true }) };
        }
        return { resultHandle: input.result, schema: resultBefore.result.schema,
          distance: assertDistanceResult(resultBefore.result, sourceHandles[0]),
          sourceHandle: native.sourceHandle, sessionId: native.sessionId };
      });
      await step("C14-existing-report-read", "Click report control and require reuse of existing immutable report", async () => {
        await panel.getByRole("button", { name: "측정 보고서 만들기" }).click();
        await panel.getByLabel("원자 측정 보고서 미리보기").waitFor({ timeout: 30000 });
        const href = await panel.getByRole("link", { name: "Markdown 다운로드" }).getAttribute("href");
        return { handle: new URL(href, page.url()).searchParams.get("handle"),
          markdown: await panel.getByLabel("원자 측정 보고서 미리보기").textContent() };
      }, async value => {
        assert.equal(value.handle, input.report);
        assert.equal(value.markdown, reportBefore.markdown);
        assert.deepEqual(forbidden, [], "Reopen created a scientific or report object");
        return { handle: value.handle, markdownSha256: sha(Buffer.from(value.markdown)),
          reusedStoredReport: true };
      });
      for (const format of ["markdown", "json"]) await step(`C14-download-${format}`,
        `Click existing ${format} browser download after events-only recovery`, async () =>
          downloadReport(app, page, panel, origin, input.run, format, input.report),
        async value => value);
      if (input.scene) {
        const sceneUrl = new URL(`/api/runs/${input.run}/viewer/scenes/selected`, origin);
        sceneUrl.searchParams.set("handle", input.scene);
        const sceneBefore = await readJson(sceneUrl);
        assert.equal(sceneBefore.handle, input.scene);
        assert.ok(sceneBefore.value.selection,
          "Optional events-only scene replay requires a preexisting nonnull selected residue");
        for (const field of RESIDUE_FIELDS)
          assert.ok(Object.hasOwn(sceneBefore.value.selection, field),
            `Preexisting saved-scene selection lacks ${field}`);
        assert.ok(sourceHandles.includes(sceneBefore.value.structure_handle),
          "Saved selected scene does not belong to the requested recovered result source");
        await step("C14-selected-pdb-scene-after-reopen",
          "Restore an existing selected PDB scene through visible controls after events-only recovery",
          async () => {
            const before = await waitForViewer(page, value => value.ready && value.sourceHandle &&
              value.sessionId && value.generation !== null);
            const choice = page.getByRole("combobox", { name: "저장된 보기" });
            await choice.locator(`option[value="${input.scene}"]`)
              .waitFor({ state: "attached", timeout: 30000 });
            await choice.selectOption(input.scene);
            await page.getByRole("button", { name: "저장된 보기 복원" }).click();
            await page.getByText(`저장된 보기 복원 완료 · ${sceneBefore.value.name}`, { exact: true })
              .waitFor({ timeout: 45000 });
            const after = await nativeSource(page, value =>
              value.sourceHandle === sceneBefore.value.structure_handle &&
              value.sessionId !== before.sessionId && value.generation !== before.generation &&
              value.catalogReady && value.selectionError == null &&
              sameResidue(value.selection, sceneBefore.value.selection), 45000);
            return { before, after, sceneAfter: await readJson(sceneUrl),
              selectedOption: await choice.inputValue() };
          }, async value => {
            assert.equal(value.selectedOption, input.scene);
            assert.deepEqual(value.sceneAfter, sceneBefore,
              "Events-only selected scene bytes/identity changed on read");
            assert.deepEqual(value.after.selection, sceneBefore.value.selection);
            assert.equal(value.after.representation,
              sceneBefore.value.representation === "ball_and_stick" ? "ball-and-stick" : sceneBefore.value.representation);
            assert.equal(value.after.theme, sceneBefore.value.theme);
            nativeCameraClose(value.after.nativeCamera, sceneBefore.value.camera, 1e-3,
              "events-only selected PDB scene full camera");
            assert.deepEqual(forbidden, [],
              "Selected-scene replay unexpectedly created a scientific, report, scene or figure object");
            return { sceneHandle: input.scene, sourceHandle: value.after.sourceHandle,
              priorSession: value.before.sessionId, freshSession: value.after.sessionId,
              priorGeneration: value.before.generation, freshGeneration: value.after.generation,
              sevenFieldSelection: value.after.selection, fullCamera: value.after.nativeCamera,
              catalogReady: value.after.catalogReady, selectionError: value.after.selectionError,
              readOnlyRestore: true };
          });
      }
      await step("C14-immutable-after", "Re-read immutable sources, result, report and reject new scientific calls", async () => {
        const sources = await Promise.all(sourceHandles.map(handle => catalog(origin, input.run, handle)));
        return { sources, result: await measurement(origin, input.run, input.result),
          report: await readJson(reportUrl), forbidden };
      }, async value => {
        assert.deepEqual(value.result, resultBefore);
        assert.deepEqual(value.report, reportBefore);
        assert.deepEqual(value.forbidden, []);
        value.sources.forEach((source, i) => {
          assert.equal(source.viewer_source_sha256, sourcesBefore[i].viewer_source_sha256);
          assert.deepEqual(source.rows, sourcesBefore[i].rows);
        });
        return { sourceHashes: value.sources.map(source => source.viewer_source_sha256),
          resultHandle: input.result, reportHandle: input.report, noNewScientificOrReportPosts: true };
      });
    } else if (input.mode === "source-matrix") {
      let activeRun = input.run;
      const panel = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
      async function restoredNativePick(kind, caseSuffix) {
        const origin = new URL(page.url()).origin;
        const url = new URL(`/api/runs/${activeRun}/viewer/scenes`, origin);
        const scenes = itemRows(await readJson(url));
        const summary = scenes.find(scene => scene.value.structure_kind === kind &&
          (kind === "openmm_minimized_structure" || scene.value.selection));
        assert.ok(summary, `Seeded real ${kind} saved scene missing in ${activeRun}`);
        const detailUrl = new URL(`/api/runs/${activeRun}/viewer/scenes/selected`, origin);
        detailUrl.searchParams.set("handle", summary.handle);
        const scene = await readJson(detailUrl);
        const restored = await step(`C04-${caseSuffix}-restore`, `Click saved real ${kind} source scene restore`, async () => {
          await page.getByRole("combobox", { name: "저장된 보기" }).selectOption(scene.handle);
          await page.getByRole("button", { name: "저장된 보기 복원" }).click();
          await page.getByText(`저장된 보기 복원 완료 · ${scene.value.name}`, { exact: true })
            .waitFor({ timeout: 45000 });
          return nativeSource(page, value => value.sourceHandle === scene.value.structure_handle, 45000);
        }, async native => {
          assert.equal(native.sourceHandle, scene.value.structure_handle);
          assert.deepEqual(native.selection ?? null, scene.value.selection ?? null);
          return { runId: activeRun, sceneHandle: scene.handle, sourceHandle: native.sourceHandle,
            sourceKind: kind, selected: native.selection, sessionId: native.sessionId,
            nativeCamera: native.nativeCamera };
        });
        const atoms = await catalog(origin, activeRun, restored.sourceHandle);
        await step(`C04-${caseSuffix}-native-pick`, `Click actual atom on real ${kind} native source`, async () => {
          await page.getByRole("group", { name: "표현 방식" })
            .getByRole("button", { name: "ball-and-stick", exact: true }).click();
          await panel.getByRole("button", { name: "원자 거리 측정", exact: true }).click();
          const picked = await clickAnyNativeAtom(page, atoms);
          await panel.getByRole("button", { name: "원자 거리 측정 끝내기" }).click();
          return picked;
        }, async picked => ({ runId: activeRun, sourceKind: kind,
          catalogSha256: atoms.viewer_source_sha256, atomCount: atoms.total,
          attemptedSite: picked.attemptedSite, observedSite: picked.observedSite,
          pointer: picked.pointer, native: picked.native }));
        if (kind === "structure") await step("C02-real-mmcif-ordinary-after-exit",
          "After Measure exit, click a real 1HSG original mmCIF residue and reconcile all seven authoritative identity fields",
          async () => clickAnyOrdinaryResidue(page, atoms), async picked => {
            assert.ok(picked.nativeClickAfter > picked.nativeClickBefore);
            assert.equal(picked.lastNativeClick.kind, "element-loci");
            assert.equal(picked.lastNativeClick.pluginBusy, false);
            assert.ok(picked.matchedCatalogSites.length > 0);
            return { runId: activeRun, sourceHandle: restored.sourceHandle,
              sourceKind: kind, ...picked, authoritativeSevenFieldIdentity: true };
          });
      }
      await restoredNativePick("structure", "real-mmcif-original");
      await restoredNativePick("prepared_structure", "real-mmcif-prepared");
      await page.getByRole("tab", { name: /^run/i }).click();
      await page.locator("#run-choice").selectOption(input.otherRun);
      activeRun = input.otherRun;
      await waitForViewer(page, value => value.sourceHandle?.includes(activeRun), 45000);
      await restoredNativePick("openmm_minimized_structure", "real-openmm-minimized");
    } else if (input.mode === "identity") {
      const runId = input.run ?? await step("C01-new-run", "Click new local-only run", async () =>
        createLocalRun(page), async id => ({ runId: id, egress: "local_only" }));
      const file = path.join(input.fixtureDir, oracle.manifest.identities);
      const model1 = await step("C04-model-one", "Upload synthetic identity PDB and load explicit model index 0", async () =>
        uploadAndLoad(page, file, 0), async value => ({ runId, handle: value.sourceHandle,
          modelIndex: 0, fixtureSha256: value.sha256 }));
      const firstCatalog = await catalog(new URL(page.url()).origin, runId, model1.sourceHandle);
      assert.equal(firstCatalog.model_number, 1);
      assert.equal(firstCatalog.total, 6);
      const model2 = await step("C04-model-two", "Reupload same bytes and choose explicit nonfirst model index 1", async () =>
        uploadAndLoad(page, file, 1), async value => ({ handle: value.sourceHandle,
          modelIndex: 1, fixtureSha256: value.sha256 }));
      assert.notEqual(model1.sourceHandle, model2.sourceHandle);
      const secondCatalog = await catalog(new URL(page.url()).origin, runId, model2.sourceHandle);
      await step("C04-complete-identities", "Inspect source-bound model/insertion/altloc/duplicate site catalog and native projection", async () => {
        const native = await waitForViewer(page, value => value.sourceHandle === model2.sourceHandle &&
          value.qaAtoms?.length >= 6);
        return native;
      }, async native => {
        assert.equal(secondCatalog.model_number, 2);
        assert.equal(secondCatalog.total, 6);
        const ca = secondCatalog.rows.filter(row => row.ref.atom_name === "CA");
        assert.equal(ca.length, 3);
        assert.deepEqual(ca.map(row => row.ref.altloc), ["A", "B", "A"]);
        assert.equal(new Set(ca.map(row => row.ref.site_index)).size, 3);
        for (const row of secondCatalog.rows) {
          assert.equal(row.ref.residue.model_number, 2);
          assert.equal(row.ref.residue.seq_auth, 42);
          assert.equal(row.ref.residue.icode, "A");
          assert.equal(row.ref.residue.chain_auth, "A");
          const projected = native.qaAtoms.find(atom => atom.ref.structure_handle === model2.sourceHandle &&
            atom.ref.site_index === row.ref.site_index);
          assert.ok(projected, `Native model 2 site ${row.ref.site_index} has no projection`);
          assert.deepEqual(projected.ref, row.ref);
          vectorClose(projected.worldCoordinate_A, row.coordinate_A, 1e-4,
            `native model 2 source site ${row.ref.site_index}`);
        }
        return { originalModelOne: model1.sourceHandle, originalModelTwo: model2.sourceHandle,
          modelOneAtoms: firstCatalog.total, modelTwoAtoms: secondCatalog.total,
          caSiteIndices: ca.map(row => row.ref.site_index), altlocs: ca.map(row => row.ref.altloc),
          authoritativeLabels: ca.map(row => ({ chain_label: row.ref.residue.chain_label,
            seq_label: row.ref.residue.seq_label })) };
      });
      const b = secondCatalog.rows.find(row => row.ref.atom_name === "CA" && row.ref.altloc === "B");
      assert.ok(b);
      const panel = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
      await step("C04-altloc-native-pick", "Enter atom Measure and click real model-2 CA altloc B in Mol*", async () => {
        await page.getByRole("group", { name: "표현 방식" })
          .getByRole("button", { name: "ball-and-stick", exact: true }).click();
        await panel.getByRole("button", { name: "원자 거리 측정", exact: true }).click();
        return clickCatalogAtom(page, b);
      }, async picked => {
        assert.equal(picked.actual.ref.altloc, "B");
        assert.equal(picked.actual.ref.residue.model_number, 2);
        assert.equal(picked.actual.ref.residue.icode, "A");
        return { pointer: picked.point, nativePick: picked.actual,
          duplicateCaAIndices: secondCatalog.rows.filter(row => row.ref.atom_name === "CA" &&
            row.ref.altloc === "A").map(row => row.ref.site_index) };
      });
    } else if (input.mode === "measure") {
      const runId = input.run ?? await step("C01-new-run", "Click new local-only run", async () =>
        createLocalRun(page), async id => ({ runId: id, egress: "local_only" }));
      const loaded = await step("C01-distance-upload", "Choose labeled sparse PDB and load actual atoms", async () =>
        uploadAndLoad(page, path.join(input.fixtureDir, oracle.manifest.distance_fixture)),
      async value => ({ runId, sourceHandle: value.sourceHandle, fixtureSha256: value.sha256 }));
      fs.writeFileSync(path.join(artifacts, "fixture-run.json"), JSON.stringify({ runId,
        structure: loaded.sourceHandle, fixture: oracle.manifest.distance_fixture,
        sha256: oracle.sourceHashes[oracle.manifest.distance_fixture] }, null, 2) + "\n");
      const atoms = await catalog(new URL(page.url()).origin, runId, loaded.sourceHandle);
      assert.equal(atoms.total, 4);
      const first = atoms.rows.find(row => row.ref.residue.seq_auth === 10 && row.ref.atom_name === "N");
      const second = atoms.rows.find(row => row.ref.residue.seq_auth === 11 && row.ref.atom_name === "O");
      const zeroA = atoms.rows.find(row => row.ref.residue.seq_auth === 12 && row.ref.atom_name === "C");
      const zeroB = atoms.rows.find(row => row.ref.residue.seq_auth === 13 && row.ref.atom_name === "N");
      assert.ok(first && second && zeroA && zeroB, "Exact synthetic atom catalog sites missing");
      vectorClose(first.coordinate_A, oracle.distance[0].xyz, 1e-6, "distance source first");
      vectorClose(second.coordinate_A, oracle.distance[1].xyz, 1e-6, "distance source second");
      const panel = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
      await step("C02-enter", "Choose visible ball-and-stick and enter atom Measure mode", async () => {
        await page.getByRole("group", { name: "표현 방식" })
          .getByRole("button", { name: "ball-and-stick", exact: true }).click();
        await panel.getByRole("button", { name: "원자 거리 측정", exact: true }).click();
        return waitForViewer(page, value => value.measureMode === true && value.sourceHandle === loaded.sourceHandle);
      }, async value => ({ measureMode: value.measureMode, sourceHandle: value.sourceHandle,
        representation: value.representation }));
      await step("C02-first-pick", "Click first actual N atom in Mol*", async () => {
        const clicked = await clickCatalogAtom(page, first);
        await panel.getByText(/첫 원자:/).waitFor({ timeout: 10000 });
        return clicked;
      }, async clicked => ({ pointer: clicked.point, native: assertNativePick(
        { lastAtomPick: clicked.actual }, atoms, "reference", { rotation: [[1,0,0],[0,1,0],[0,0,1]],
          translation_A: [0,0,0] }, false),
        rejectedSameSiteAttempts: clicked.rejectedSameSiteAttempts }));
      await step("C02-undo-first", "Click visible first-atom undo control", async () => {
        await panel.getByRole("button", { name: "첫 원자 취소" }).click();
        return panel.getByRole("button", { name: "첫 원자 취소" }).isDisabled();
      }, async disabled => { assert.equal(disabled, true); return { pendingAtomCleared: true }; });
      await step("C02-first-again", "Click first actual N atom after undo", async () =>
        clickCatalogAtom(page, first), async clicked => ({ pointer: clicked.point,
          actual: clicked.actual, rejectedSameSiteAttempts: clicked.rejectedSameSiteAttempts }));
      const distance = await step("C03-two-click-5A", "Click second actual O atom and await guarded distance result", async () => {
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runId}/commands`, { timeout: 30000 })
          .then(response => ({ response }), error => ({ error }));
        const clicked = await clickCatalogAtom(page, second);
        const awaited = await posted;
        if (awaited.error) throw awaited.error;
        const response = awaited.response;
        assert.equal(response.status(), 200);
        const body = await response.json();
        assert.equal(body.ok, true, JSON.stringify(body));
        const handle = body.handle.handle;
        const detail = await measurement(new URL(page.url()).origin, runId, handle);
        await panel.getByText(/원자 거리 5\.000 Å/).waitFor({ timeout: 30000 });
        return { handle, result: detail.result, clicked };
      }, async value => {
        const oracleResult = assertDistanceResult(value.result, loaded.sourceHandle);
        close(value.result.distance_A, 5, 1e-12, "independent 3-4-5 distance");
        assert.equal(value.result.first.site_index, first.ref.site_index);
        assert.equal(value.result.second.site_index, second.ref.site_index);
        return { handle: value.handle, oracleResult, secondPointer: value.clicked.point,
          nativeSecondPick: value.clicked.actual,
          rejectedSameSiteAttempts: value.clicked.rejectedSameSiteAttempts };
      });
      fs.writeFileSync(path.join(artifacts, "distance-result.json"), JSON.stringify({ runId,
        handle: distance.handle, result: distance.result }, null, 2) + "\n");
      const reversed = await step("C02-repeat-reverse", "Repeat genuine two-click measurement in reverse order after native idle", async () => {
        const firstClick = await clickCatalogAtom(page, second);
        await panel.getByText(/첫 원자:/).waitFor({ timeout: 10000 });
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runId}/commands`, { timeout: 30000 })
          .then(response => ({ response }), error => ({ error }));
        const secondClick = await clickCatalogAtom(page, first);
        const awaited = await posted;
        if (awaited.error) throw awaited.error;
        const response = awaited.response;
        assert.equal(response.status(), 200);
        const body = await response.json();
        assert.equal(body.ok, true, JSON.stringify(body));
        return { firstClick, secondClick, detail: await measurement(new URL(page.url()).origin,
          runId, body.handle.handle) };
      }, async value => {
        close(value.detail.result.distance_A, 5, 1e-12, "repeated reversed 3-4-5 distance");
        assert.equal(value.detail.result.first.site_index, second.ref.site_index);
        assert.equal(value.detail.result.second.site_index, first.ref.site_index);
        return { handle: value.detail.meta.handle, firstPointer: value.firstClick.point,
          secondPointer: value.secondClick.point, distance_A: value.detail.result.distance_A,
          firstRejectedSameSiteAttempts: value.firstClick.rejectedSameSiteAttempts,
          secondRejectedSameSiteAttempts: value.secondClick.rejectedSameSiteAttempts };
      });
      const distanceReport = await step("C11-distance-report", "Click create evidence-bound distance report", async () => {
        await panel.getByRole("button", { name: "측정 보고서 만들기" }).click();
        await panel.getByLabel("원자 측정 보고서 미리보기").waitFor({ timeout: 30000 });
        const href = await panel.getByRole("link", { name: "Markdown 다운로드" }).getAttribute("href");
        const handle = new URL(href, page.url()).searchParams.get("handle");
        assert.ok(handle);
        const url = new URL(`/api/runs/${runId}/reports/selected`, page.url());
        url.searchParams.set("handle", handle);
        return { handle, artifact: await readJson(url) };
      }, async value => {
        assert.equal(value.artifact.manifest.analysis_type, "atom_distance");
        assert.equal(value.artifact.manifest.result_handle, reversed.detail.meta.handle,
          "Distance report did not cite the currently selected reversed measurement");
        assert.ok(value.artifact.manifest.claims.every(claim =>
          claim.source_handle === reversed.detail.meta.handle),
        "Distance report contains a claim attributed to a different measurement");
        assert.ok(value.artifact.manifest.claims.some(claim => claim.field_path === "distance_A" &&
          claim.unit === "angstrom" && claim.exact_value === 5));
        assert.equal(await panel.getByLabel("원자 측정 보고서 미리보기").textContent(),
          value.artifact.markdown);
        assert.match(value.artifact.markdown, /angstrom|Å/);
        return { handle: value.handle, markdownSha256: sha(Buffer.from(value.artifact.markdown)),
          resultHandle: value.artifact.manifest.result_handle };
      });
      fs.writeFileSync(path.join(artifacts, "distance-report.json"), JSON.stringify({
        runId, handle: distanceReport.handle, resultHandle: distanceReport.artifact.manifest.result_handle,
        markdownSha256: sha(Buffer.from(distanceReport.artifact.markdown)),
        manifest: distanceReport.artifact.manifest }, null, 2) + "\n");
      for (const format of ["markdown", "json"]) await step(`C11-distance-download-${format}`,
        `Click actual ${format} distance report browser download`, async () =>
          downloadReport(app, page, panel, new URL(page.url()).origin, runId, format, distanceReport.handle),
        async result => result);
      await step("C02-clear", "Click visible measurement clear control", async () => {
        await panel.getByRole("button", { name: "측정 지우기" }).click();
        return { resultMessageCount: await panel.getByText(/원자 거리 5\.000 Å/).count(),
          measureMode: (await waitForViewer(page)).measureMode };
      }, async value => { assert.equal(value.resultMessageCount, 0);
        assert.equal(value.measureMode, true); return value; });
      await step("C02-exit", "Exit atom Measure and restore ordinary residue picking", async () => {
        await panel.getByRole("button", { name: "원자 거리 측정 끝내기" }).click();
        return waitForViewer(page, value => value.measureMode === false);
      }, async value => ({ measureMode: value.measureMode, sourceHandle: value.sourceHandle }));
      await step("C02-residue-after-exit", "Click actual original-PDB atom after Measure exit and require authoritative ordinary residue selection", async () => {
        const before = (await nativeQuietAt(page, first, "reference")).second;
        assert.equal(before.measureMode, false);
        const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
        const box = await canvas.boundingBox();
        assert.ok(box);
        const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
        let point = null;
        const attempts = [];
        for (let attempt = 1; attempt <= 3; attempt += 1) {
          let quiet = await nativeQuietAt(page, first, "reference");
          point = { x: box.x + quiet.target.canvasPixel[0] * box.width / size.width,
            y: box.y + quiet.target.canvasPixel[1] * box.height / size.height,
            nativeCanvasPixel: quiet.target.canvasPixel };
          await page.mouse.move(point.x, point.y);
          quiet = await nativeQuietAt(page, first, "reference");
          point = { x: box.x + quiet.target.canvasPixel[0] * box.width / size.width,
            y: box.y + quiet.target.canvasPixel[1] * box.height / size.height,
            nativeCanvasPixel: quiet.target.canvasPixel };
          await page.mouse.click(point.x, point.y);
          try {
            const after = await waitForViewer(page, value => value.selection?.seq_auth === 10 &&
              value.selection?.chain_auth === "A" && !value.measureMode, 1800);
            return { point, after, attempts: [...attempts, { attempt, selected: true,
              nativeClickBefore: quiet.second.nativeClickRevision,
              nativeClickAfter: after.nativeClickRevision,
              lastNativeClick: after.lastNativeClick }] };
          } catch (error) {
            const raw = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
            attempts.push({ attempt, selected: false,
              observation: raw?.selection ?? null,
              nativeClickBefore: quiet.second.nativeClickRevision,
              nativeClickAfter: raw?.nativeClickRevision,
              lastNativeClick: raw?.lastNativeClick });
            if (attempt === 3) throw new Error(`Ordinary original-PDB residue selection failed after three idle real clicks: ${JSON.stringify(attempts)}; ${error}`);
          }
        }
        throw new Error("Unreachable residue-pick retry state");
      }, async ({ point, after, attempts }) => {
        assert.equal(after.measureMode, false);
        assert.equal(after.selection?.seq_auth, 10);
        assert.equal(after.selection?.chain_auth, "A");
        assert.equal(after.selection?.chain_label, "Axp",
          "Ordinary PDB selection lost the authoritative Gemmi subchain label");
        assert.ok(attempts.every(item => item.nativeClickAfter > item.nativeClickBefore &&
          item.lastNativeClick?.kind === "element-loci" &&
          item.lastNativeClick?.pluginBusy === false),
        "Ordinary source clicks were not actual idle native element clicks");
        return { pointer: point, residue: after.selection, measureMode: after.measureMode,
          attempts, contractC02OrdinarySelectionProven: true };
      });
      await step("C03-zero-distinct-api-fixture", "Labeled exact-site Run.call fixture for visually coincident distinct atoms", async () => {
        const url = new URL(`/api/runs/${runId}/commands`, page.url());
        const response = await fetch(url, { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ tool: "measure_distance", args: { structure: loaded.sourceHandle,
            first: zeroA.ref, second: zeroB.ref }, decided_by: "human", execution_mode: "human" }) });
        assert.equal(response.status, 200);
        const body = await response.json();
        assert.equal(body.ok, true, JSON.stringify(body));
        return measurement(new URL(page.url()).origin, runId, body.handle.handle);
      }, async detail => {
        assert.equal(detail.result.first.site_index, zeroA.ref.site_index);
        assert.equal(detail.result.second.site_index, zeroB.ref.site_index);
        close(detail.result.distance_A, 0, 1e-12, "distinct zero distance");
        return { handle: detail.meta.handle, distance_A: detail.result.distance_A,
          fixture: "explicitly labeled loopback Run.call of two exact coincident catalog sites; not pointer-picked" };
      });
      await step("C03-source-change-clears-first", "Pick a first atom, then load a different source through visible file chooser", async () => {
        await panel.getByRole("button", { name: "원자 거리 측정", exact: true }).click();
        const firstPick = await clickCatalogAtom(page, first);
        await panel.getByText(/첫 원자:/).waitFor({ timeout: 10000 });
        const newSource = await uploadAndLoad(page,
          path.join(input.fixtureDir, oracle.manifest.reference));
        const native = await nativeSource(page, value => value.sourceHandle === newSource.sourceHandle &&
          value.catalogReady, 45000);
        return { firstPick, newSource, native,
          pendingTextCount: await panel.getByText(/첫 원자:/).count(),
          oldResult: await measurement(new URL(page.url()).origin, runId, distance.handle) };
      }, async value => {
        assert.notEqual(value.newSource.sourceHandle, loaded.sourceHandle);
        assert.equal(value.pendingTextCount, 0, "Old-source first atom survived source switch");
        assert.equal(value.oldResult.result.distance_A, 5);
        assert.equal(value.oldResult.result.structure_handle, loaded.sourceHandle);
        return { oldSource: loaded.sourceHandle, newSource: value.native.sourceHandle,
          firstPick: value.firstPick.actual, oldDistanceHandle: distance.handle,
          oldDistanceImmutableA: value.oldResult.result.distance_A, pendingCleared: true };
      });
    } else if (input.mode === "alignment") {
      const runId = input.run ?? await step("C01-new-run", "Click new local-only run", async () =>
        createLocalRun(page), async id => ({ runId: id, egress: "local_only" }));
      const ref = await step("C01-reference-upload", "Choose labeled synthetic reference bytes with real file chooser and load", async () =>
        uploadAndLoad(page, path.join(input.fixtureDir, oracle.manifest.reference)), async value => ({
        runId, sourceHandle: value.sourceHandle, fixtureSha256: value.sha256,
        nativeSource: value.native.sourceHandle }));
      const mov = await step("C01-moving-upload", "Choose labeled known-rigid moving bytes with real file chooser and load", async () =>
        uploadAndLoad(page, path.join(input.fixtureDir, oracle.manifest.moving)), async value => ({
        runId, sourceHandle: value.sourceHandle, fixtureSha256: value.sha256,
        nativeSource: value.native.sourceHandle }));
      assert.notEqual(ref.sourceHandle, mov.sourceHandle);
      fs.writeFileSync(path.join(artifacts, "fixture-run.json"), JSON.stringify({ runId,
        reference: ref.sourceHandle, moving: mov.sourceHandle, fixtureHashes: oracle.sourceHashes }, null, 2) + "\n");
      const refAtoms = await catalog(new URL(page.url()).origin, runId, ref.sourceHandle);
      const movAtoms = await catalog(new URL(page.url()).origin, runId, mov.sourceHandle);
      assert.equal(refAtoms.total, oracle.reference.length);
      assert.equal(movAtoms.total, oracle.moving.length);
      const panel = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
      await step("C05-source-selection", "Select explicit reference and moving immutable source handles", async () => {
        await page.getByRole("group", { name: "표현 방식" })
          .getByRole("button", { name: "ball-and-stick", exact: true }).click();
        await panel.getByRole("combobox", { name: "기준 구조" }).selectOption(ref.sourceHandle);
        await panel.getByRole("combobox", { name: "이동 구조" }).selectOption(mov.sourceHandle);
        await panel.getByRole("combobox", { name: "기준 CA site" }).locator("option").nth(1)
          .waitFor({ state: "attached", timeout: 30000 });
        await panel.getByRole("combobox", { name: "이동 CA site" }).locator("option").nth(1)
          .waitFor({ state: "attached", timeout: 30000 });
        return { reference: await panel.getByRole("combobox", { name: "기준 구조" }).inputValue(),
          moving: await panel.getByRole("combobox", { name: "이동 구조" }).inputValue() };
      }, async selected => { assert.equal(selected.reference, ref.sourceHandle);
        assert.equal(selected.moving, mov.sourceHandle); return selected; });
      const pairRefs = oracle.manifest.ca_pairs.map(identity => ({ reference: catalogPair(refAtoms, identity),
        moving: catalogPair(movAtoms, identity) }));
      for (const [index, pair] of pairRefs.entries()) await step(`C05-add-pair-${index + 1}`,
        "Choose exact CA altloc/site on both sides and click add", async () => {
          await panel.getByRole("combobox", { name: "기준 CA site" })
            .selectOption(String(pair.reference.ref.site_index));
          await panel.getByRole("combobox", { name: "이동 CA site" })
            .selectOption(String(pair.moving.ref.site_index));
          await panel.getByRole("button", { name: "대응 추가" }).click();
          return panel.getByRole("region", { name: "명시한 CA 대응" }).locator("tbody tr").count();
        }, async count => {
          assert.equal(count, index + 1);
          if (index < 2) assert.equal(await panel.getByRole("button", { name: "정렬 계산" }).isDisabled(), true);
          return { pairCount: count, reference: pair.reference.ref, moving: pair.moving.ref };
        });
      await step("C05-remove-readd", "Remove last explicit pair and add its exact CA sites again", async () => {
        await panel.getByRole("region", { name: "명시한 CA 대응" })
          .getByRole("button", { name: "대응 제거" }).last().click();
        const reduced = await panel.getByRole("region", { name: "명시한 CA 대응" }).locator("tbody tr").count();
        const pair = pairRefs.at(-1);
        await panel.getByRole("combobox", { name: "기준 CA site" })
          .selectOption(String(pair.reference.ref.site_index));
        await panel.getByRole("combobox", { name: "이동 CA site" })
          .selectOption(String(pair.moving.ref.site_index));
        await panel.getByRole("button", { name: "대응 추가" }).click();
        return { reduced, restored: await panel.getByRole("region", { name: "명시한 CA 대응" })
          .locator("tbody tr").count() };
      }, async value => { assert.equal(value.reduced, 3); assert.equal(value.restored, 4); return value; });
      await step("C06-duplicate-visible", "Attempt duplicate CA pair through visible selectors", async () => {
        const pair = pairRefs[0];
        await panel.getByRole("combobox", { name: "기준 CA site" })
          .selectOption(String(pair.reference.ref.site_index));
        await panel.getByRole("combobox", { name: "이동 CA site" })
          .selectOption(String(pair.moving.ref.site_index));
        await panel.getByRole("button", { name: "대응 추가" }).click();
        await panel.getByRole("alert").filter({ hasText: /한 번만 대응/ }).waitFor({ timeout: 10000 });
        return { visibleError: await panel.getByRole("alert").innerText(),
          count: await panel.getByRole("region", { name: "명시한 CA 대응" }).locator("tbody tr").count() };
      }, async value => { assert.equal(value.count, 4); return value; });
      const aligned = await step("C07-known-rigid-fit", "Click Compute on four explicit CA correspondences", async () => {
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runId}/commands`, { timeout: 45000 });
        await panel.getByRole("button", { name: "정렬 계산" }).click();
        const response = await posted;
        assert.equal(response.status(), 200, `Alignment command HTTP ${response.status()}`);
        const body = await response.json();
        assert.equal(body.ok, true, JSON.stringify(body));
        const handle = body.handle.handle;
        const detail = await measurement(new URL(page.url()).origin, runId, handle);
        await panel.getByText(/정렬 RMSD/).waitFor({ timeout: 45000 });
        const native = await waitForViewer(page, value => value.layers?.length === 2 &&
          value.layers[0].sourceHandle === ref.sourceHandle &&
          value.layers[1].sourceHandle === mov.sourceHandle, 45000);
        return { handle, result: detail.result, native };
      }, async value => {
        assert.equal(value.result.reference_handle, ref.sourceHandle);
        assert.equal(value.result.moving_handle, mov.sourceHandle);
        const numerical = assertAlignmentResult(value.result, oracle);
        const layers = assertNativeLayers(value.native, value.result, true,
          { reference: true, moving: true });
        return { runId, handle: value.handle, numerical, layers };
      });
      fs.writeFileSync(path.join(artifacts, "alignment-result.json"), JSON.stringify({ runId,
        handle: aligned.handle, result: aligned.result }, null, 2) + "\n");
      let unalignedPaintSha = null;
      await step("C08-unaligned", "Click original coordinates and inspect native untransformed moving layer", async () => {
        await panel.getByRole("radio", { name: "원래 좌표" }).check();
        return waitForViewer(page, value => value.layers?.length === 2 &&
          value.layers[1].transform.every((number, i) =>
            Math.abs(number - expectedNativeMat4(aligned.result, false)[i]) <= 1e-9));
      }, async native => {
        const paint = await canvasPaint(page, (await capture(app, page, artifacts,
          "C08-unaligned-paint")).paint);
        unalignedPaintSha = paint.pixelSha256;
        return { layers: assertNativeLayers(native, aligned.result, false,
          { reference: true, moving: true }), paint };
      });
      await step("C08-full-unaligned-overview", "Zoom out using actual wheel until both complete native structures fit the viewport", async () => {
        const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
        const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
        const box = await canvas.boundingBox(); assert.ok(box);
        const x = box.x + box.width / 2, y = box.y + box.height / 2;
        const observations = [];
        let native = null;
        for (let attempt = 0; attempt < 4; attempt += 1) {
          native = await waitForViewer(page, value => value.layers?.length === 2 &&
            value.qaAtoms?.some(atom => atom.layer === "moving") &&
            value.qaAtoms?.some(atom => atom.layer === "reference"));
          const layerCounts = ["reference", "moving"].map(layer => {
            const atoms = native.qaAtoms.filter(atom => atom.layer === layer);
            return { layer, totalProjected: atoms.length,
              inside: atoms.filter(atom => atom.canvasPixel[0] >= 5 &&
                atom.canvasPixel[0] <= size.width - 5 && atom.canvasPixel[1] >= 5 &&
                atom.canvasPixel[1] <= size.height - 5).length };
          });
          observations.push({ attempt, camera: native.nativeCamera, layerCounts });
          if (layerCounts.every(item => item.totalProjected > 0 &&
            item.inside === item.totalProjected)) break;
          assert.ok(attempt < 3, `Could not fit both native structures with real zoom: ${JSON.stringify(layerCounts)}`);
          const previous = norm(vectorSub(native.nativeCamera.position, native.nativeCamera.target));
          await page.mouse.move(x, y); await page.mouse.wheel(0, 470);
          await waitForViewer(page, value => value.nativeCamera &&
            norm(vectorSub(value.nativeCamera.position, value.nativeCamera.target)) > previous + 1e-3, 10000);
        }
        const proof = await capture(app, page, artifacts, "C08-full-unaligned-overview-paint");
        return { native, observations, paint: await canvasPaint(page, proof.paint) };
      }, async value => ({ layers: assertNativeLayers(value.native, aligned.result, false,
        { reference: true, moving: true }),
        completeProjectedAtomsInsideViewport: value.observations.at(-1).layerCounts,
        realWheelActions: value.observations.length - 1, paint: value.paint }));
      await step("C08-realign", "Click aligned coordinates and inspect native transformed moving layer", async () => {
        await panel.getByRole("radio", { name: "정렬 좌표" }).check();
        return waitForViewer(page, value => value.layers?.length === 2 &&
          value.layers[1].transform.every((number, i) =>
            Math.abs(number - expectedNativeMat4(aligned.result, true)[i]) <= 1e-9));
      }, async native => {
        const paint = await canvasPaint(page, (await capture(app, page, artifacts,
          "C08-aligned-paint")).paint);
        assert.notEqual(paint.pixelSha256, unalignedPaintSha,
          "Aligned and unaligned actual canvas pixels were identical");
        return { layers: assertNativeLayers(native, aligned.result, true,
          { reference: true, moving: true }), paint };
      });
      for (const layer of ["reference", "moving"]) {
        const label = layer === "reference" ? "기준 구조 표시" : "이동 구조 표시";
        await step(`C08-hide-${layer}`, `Uncheck real ${label} control`, async () => {
          await panel.getByRole("checkbox", { name: label }).uncheck();
          return waitForViewer(page, value => value.layers?.length === 2 &&
            value.layers.find(item => item.layer === layer)?.visible === false);
        }, async native => ({ layers: assertNativeLayers(native, aligned.result, true,
          { reference: layer !== "reference", moving: layer !== "moving" }) }));
        await panel.getByRole("checkbox", { name: label }).check();
      }
      await step("C09-same-source-overlay-distance", "After documented bond-hit limitation, pick a distinct native reference atom for source-distance check", async () => {
        await panel.getByRole("checkbox", { name: "이동 구조 표시" }).uncheck();
        const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
        const box = await canvas.boundingBox(); assert.ok(box);
        const x = box.x + box.width * 0.48, y = box.y + box.height * 0.50;
        const beforeOrbit = await waitForViewer(page, value => value.nativeCamera && value.layers?.length === 2);
        await page.mouse.move(x, y); await page.mouse.down();
        await page.mouse.move(x + 88, y + 57, { steps: 12 }); await page.mouse.up();
        const afterOrbit = await waitForViewer(page, value => value.nativeCamera &&
          norm(vectorSub(value.nativeCamera.position, beforeOrbit.nativeCamera.position)) > 1e-3, 10000);
        await panel.getByRole("button", { name: "원자 거리 측정", exact: true }).click();
        await waitForViewer(page, value => value.measureMode && value.layers?.[1]?.visible === false);
        let firstClick = await clickCatalogAtom(page, pairRefs[1].reference);
        await panel.getByText(/첫 원자:/).waitFor({ timeout: 10000 });
        // The third-build exact SER12 CA pixel yielded bond-loci. First
        // retry that same source site after a real camera orbit. A second
        // genuine bond hit is recorded with its visible error; only then use
        // another exact catalog site that the native pointer can atom-pick.
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runId}/commands`, { timeout: 60000 })
          .then(response => ({ response }), error => ({ error }));
        let secondClick, exactFailure = null;
        try {
          const exact = await clickCatalogAtom(page, pairRefs[2].reference);
          secondClick = { native: { ref: exact.actual.ref,
            nativeWorldCoordinate_A: exact.actual.worldCoordinate_A },
          actual: exact.actual, pointer: exact.point, exactSite: true,
          rejectedAttempts: [] };
        } catch (error) {
          const raw = await page.evaluate(() => window.__protviewQaSnapshot?.() ?? null);
          assert.equal(raw?.lastNativeClick?.kind, "bond-loci",
            `Exact-site retry failed for a reason other than bond occlusion: ${error}`);
          assert.equal(raw.lastNativeClick.reason, "locus");
          const toast = await page.locator(".mw-molstar-pick-error[role=alert]").innerText();
          assert.match(toast, /원자 하나를 직접 클릭|결합이나 표면 선택/);
          exactFailure = { expectedSite: pairRefs[2].reference.ref.site_index,
            rawClickRevision: raw.nativeClickRevision, lastNativeClick: raw.lastNativeClick,
            visibleToast: toast, diagnostic: String(error).slice(0, 900) };
          if (await panel.getByText(/첫 원자:/).count() === 0) {
            firstClick = await clickCatalogAtom(page, pairRefs[1].reference);
            await panel.getByText(/첫 원자:/).waitFor({ timeout: 10000 });
          }
          secondClick = await clickAnyNativeAtom(page, refAtoms,
            [firstClick.actual.ref.site_index]);
        }
        const awaited = await posted;
        if (awaited.error) throw awaited.error;
        const response = awaited.response;
        assert.equal(response.status(), 200);
        const body = await response.json();
        assert.equal(body.ok, true, JSON.stringify(body));
        return { firstClick, secondClick, exactFailure, beforeOrbit, afterOrbit,
          detail: await measurement(new URL(page.url()).origin, runId, body.handle.handle) };
      }, async value => {
        const measured = assertDistanceResult(value.detail.result, ref.sourceHandle);
        const firstSourceSite = refAtoms.rows.find(row =>
          row.ref.site_index === value.firstClick.actual.ref.site_index);
        const secondSourceSite = refAtoms.rows.find(row =>
          row.ref.site_index === value.secondClick.native.ref.site_index);
        assert.ok(firstSourceSite && secondSourceSite &&
          firstSourceSite.ref.site_index !== secondSourceSite.ref.site_index);
        const originalDistance = norm(vectorSub(firstSourceSite.coordinate_A,
          secondSourceSite.coordinate_A));
        close(value.detail.result.distance_A, originalDistance, 1e-12,
          "overlay same-source original-coordinate distance");
        assert.equal(value.detail.result.first.site_index, firstSourceSite.ref.site_index);
        assert.equal(value.detail.result.second.site_index, secondSourceSite.ref.site_index);
        return { handle: value.detail.meta.handle, nativeFirst: value.firstClick.actual,
          nativeSecond: value.secondClick.actual ?? value.secondClick.native,
          secondPointer: value.secondClick.pointer,
          rejectedTargetAttempts: value.secondClick.rejectedAttempts,
          originalDistanceA: originalDistance, measured,
          priorExactCaLimitation: "SER12 CA projection hit bond-loci in third-build diagnostic",
          exactSiteAfterOrbit: value.secondClick.exactSite ?? false,
          exactSiteFailureWithVisibleToast: value.exactFailure,
          realOrbitBefore: value.beforeOrbit.nativeCamera,
          realOrbitAfter: value.afterOrbit.nativeCamera };
      });
      await step("C09-cross-layer-rejection", "Click reference first, then moving atom with only its native layer visible", async () => {
        await panel.getByRole("button", { name: "측정 지우기" }).click();
        await waitForViewer(page, value => value.measureMode && value.layers?.length === 2 &&
          value.layers[1].visible === false);
        const firstClick = await clickCatalogAtom(page, pairRefs[1].reference);
        await panel.getByRole("checkbox", { name: "기준 구조 표시" }).uncheck();
        await panel.getByRole("checkbox", { name: "이동 구조 표시" }).check();
        await waitForViewer(page, value => value.layers?.[0]?.visible === false &&
          value.layers?.[1]?.visible === true);
        const secondClick = await clickCatalogAtom(page, pairRefs[3].moving, "moving", aligned.result, true);
        await panel.getByRole("alert").filter({ hasText: /서로 다른 층의 원자/ }).waitFor({ timeout: 10000 });
        return { firstClick, secondClick, visibleError: await panel.getByRole("alert").innerText() };
      }, async value => {
        const pick = assertNativePick({ lastAtomPick: value.secondClick.actual }, movAtoms,
          "moving", aligned.result, true);
        assert.match(value.visibleError, /같은 구조/);
        return { referencePick: value.firstClick.actual, movingPick: pick,
          visibleError: value.visibleError };
      });
      await panel.getByRole("button", { name: "원자 거리 측정 끝내기" }).click();
      await panel.getByRole("checkbox", { name: "기준 구조 표시" }).check();
      await step("C10-single-scene-disabled", "Inspect Save/Export disabled and prompt absent during two-layer comparison", async () => ({
        saveDisabled: await page.getByRole("button", { name: "현재 보기 저장" }).isDisabled(),
        exportDisabled: await page.getByRole("button", { name: "현재 보기 PNG 내보내기" }).isDisabled(),
        saveReason: await page.getByRole("button", { name: "현재 보기 저장" }).getAttribute("title"),
        promptCount: await page.locator("#viewer-prompt").count(),
      }), async value => { assert.equal(value.saveDisabled, true); assert.equal(value.exportDisabled, true);
        assert.match(value.saveReason, /두 구조 비교/); assert.equal(value.promptCount, 0); return value; });
      await step("C10-reopen-alignment-result", "Choose immutable alignment handle in visible saved-result selector", async () => {
        await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).click();
        const single = await waitForViewer(page, value => value.layers?.length === 1 &&
          value.sourceHandle === mov.sourceHandle, 45000);
        assert.equal(single.layers.length, 1, "Comparison did not actually close before reopen");
        await panel.getByRole("combobox", { name: "저장된 거리·정렬 결과" }).selectOption("");
        await panel.getByRole("combobox", { name: "저장된 거리·정렬 결과" }).selectOption(aligned.handle);
        await panel.getByText(/정렬 RMSD/).waitFor({ timeout: 30000 });
        const reopened = await waitForViewer(page, value => value.layers?.length === 2 &&
          value.layers[0].sourceHandle === ref.sourceHandle && value.layers[1].sourceHandle === mov.sourceHandle);
        return { single, reopened };
      }, async ({ single, reopened }) => ({ alignmentHandle: aligned.handle,
        priorSingleSource: single.sourceHandle,
        layers: assertNativeLayers(reopened, aligned.result, true, { reference: true, moving: true }) }));
      await step("C05-reference-screen-pair-pick", "Click reference CA screen-selection control and a genuine reference-layer atom", async () => {
        await panel.getByRole("checkbox", { name: "이동 구조 표시" }).uncheck();
        const control = await clickWithinWorkflow(page, panel,
          panel.getByRole("button", { name: "기준 CA 화면 선택" }));
        await waitForViewer(page, value => value.measureMode && value.layers?.[1]?.visible === false);
        const picked = await clickCatalogAtom(page, pairRefs[1].reference);
        await panel.getByRole("combobox", { name: "기준 CA site" })
          .waitFor({ state: "visible", timeout: 10000 });
        const chosen = await panel.getByRole("combobox", { name: "기준 CA site" }).inputValue();
        return { control, picked, chosen };
      }, async value => {
        assert.equal(value.chosen, String(pairRefs[1].reference.ref.site_index));
        assert.equal(value.picked.actual.layer, "reference");
        return { controlPointer: value.control.pointer,
          selectedSite: value.chosen, nativePick: value.picked.actual,
          exactReferenceBound: true };
      });
      await step("C05-wrong-layer-screen-pick", "With reference CA requested, click moving-layer CA and require visible wrong-layer rejection", async () => {
        await panel.getByRole("checkbox", { name: "기준 구조 표시" }).uncheck();
        await panel.getByRole("checkbox", { name: "이동 구조 표시" }).check();
        await clickWithinWorkflow(page, panel,
          panel.getByRole("button", { name: "기준 CA 화면 선택" }));
        const beforeSite = await panel.getByRole("combobox", { name: "기준 CA site" }).inputValue();
        const picked = await clickAnyExactCa(page, movAtoms, "moving", aligned.result, true);
        const alert = panel.getByRole("alert").filter({ hasText: /선택한 기준 구조의 원자를 클릭하세요/ });
        await alert.waitFor({ timeout: 10000 });
        return { beforeSite, afterSite: await panel.getByRole("combobox", { name: "기준 CA site" }).inputValue(),
          picked, visibleError: await alert.innerText() };
      }, async value => {
        assert.equal(value.afterSite, value.beforeSite,
          "Wrong-layer pick overwrote the requested reference CA selector");
        assert.equal(value.picked.clicked.actual.layer, "moving");
        return { sourceLayer: "moving", requestedLayer: "reference",
          nativePick: value.picked.clicked.actual, visibleError: value.visibleError,
          referenceSelectorUnchanged: true, rejectedCandidates: value.picked.failures };
      });
      await step("C05-moving-screen-pair-pick", "Click moving CA screen-selection control and genuine moving-layer CA", async () => {
        const control = await clickWithinWorkflow(page, panel,
          panel.getByRole("button", { name: "이동 CA 화면 선택" }));
        const picked = await clickAnyExactCa(page, movAtoms, "moving", aligned.result, true);
        const chosen = await panel.getByRole("combobox", { name: "이동 CA site" }).inputValue();
        await panel.getByRole("button", { name: "원자 거리 측정 끝내기" }).click();
        await panel.getByRole("checkbox", { name: "기준 구조 표시" }).check();
        const native = await waitForViewer(page, value => !value.measureMode &&
          value.layers?.length === 2 && value.layers[0].visible && value.layers[1].visible);
        return { control, picked, chosen, native,
          pairCount: await panel.getByRole("region", { name: "명시한 CA 대응" })
            .locator("tbody tr").count() };
      }, async value => {
        assert.equal(value.chosen, String(value.picked.clicked.actual.ref.site_index));
        assert.equal(value.picked.clicked.actual.layer, "moving");
        assert.equal(value.pairCount, 4, "Screen selection changed the saved pair table");
        return { controlPointer: value.control.pointer,
          selectedSite: value.chosen, nativePick: value.picked.clicked.actual,
          rejectedCandidates: value.picked.failures, pairCount: value.pairCount,
          layers: assertNativeLayers(value.native, aligned.result, true,
            { reference: true, moving: true }) };
      });
      await step("C08-pair-row-focus", "Click actual correspondence-row focus on the native two-layer overlay", async () => {
        const before = await waitForViewer(page, value => value.layers?.length === 2 && value.nativeCamera);
        const focusedClick = await clickPairFocusByVisibleScroll(page, panel);
        const after = await waitForViewer(page, value => value.layers?.length === 2 && value.nativeCamera &&
          norm(vectorSub(value.nativeCamera.target, before.nativeCamera.target)) > 1e-4, 15000);
        return { before, after, focusedClick };
      }, async ({ before, after, focusedClick }) => ({ previousTarget: before.nativeCamera.target,
        focusedTarget: after.nativeCamera.target, nativeLayers: assertNativeLayers(after, aligned.result,
          true, { reference: true, moving: true }), focusedClick }));
      await step("C08-manual-camera", "Orbit and wheel the actual overlay with mouse inputs", async () => {
        const before = await waitForViewer(page, value => value.layers?.length === 2 && value.nativeCamera);
        const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
        const box = await canvas.boundingBox(); assert.ok(box);
        const x = box.x + box.width / 2, y = box.y + box.height / 2;
        await page.mouse.move(x, y); await page.mouse.down();
        await page.mouse.move(x + 105, y + 65, { steps: 12 }); await page.mouse.up();
        const orbited = await waitForViewer(page, value => value.nativeCamera &&
          norm(vectorSub(value.nativeCamera.position, before.nativeCamera.position)) > 1e-4);
        await page.mouse.wheel(0, -370);
        const zoomed = await waitForViewer(page, value => value.nativeCamera &&
          norm(vectorSub(value.nativeCamera.position, orbited.nativeCamera.position)) > 1e-4);
        return { before, orbited, zoomed };
      }, async ({ before, orbited, zoomed }) => ({ beforeCamera: before.nativeCamera,
        orbitCamera: orbited.nativeCamera, zoomCamera: zoomed.nativeCamera,
        nativeLayers: assertNativeLayers(zoomed, aligned.result, true,
          { reference: true, moving: true }) }));
      await step("C10-reselect-alignment-after-pair-picks",
        "Reselect the immutable alignment result through visible history after pair-screen Measure exits",
        async () => {
          const selector = panel.getByRole("combobox", { name: "저장된 거리·정렬 결과" });
          await selector.selectOption("");
          await selector.selectOption(aligned.handle);
          const restored = await waitForViewer(page, value => value.ready && value.catalogReady &&
            value.layers?.length === 2 && value.layers[0].sourceHandle === ref.sourceHandle &&
            value.layers[1].sourceHandle === mov.sourceHandle && !value.measureMode, 45000);
          const reportButton = panel.getByRole("button", { name: "측정 보고서 만들기" });
          await reportButton.waitFor({ state: "visible", timeout: 15000 });
          return { restored, selectorValue: await selector.inputValue(),
            reportButtonEnabled: await reportButton.isEnabled() };
        }, async value => {
          assert.equal(value.selectorValue, aligned.handle);
          assert.equal(value.reportButtonEnabled, true);
          return { alignmentHandle: aligned.handle,
            nativeLayers: assertNativeLayers(value.restored, aligned.result, true,
              { reference: true, moving: true }), reportButtonEnabled: true };
        });
      await step("C11-alignment-report", "Click create report for immutable alignment result", async () => {
        await panel.getByRole("button", { name: "측정 보고서 만들기" }).click();
        await panel.getByLabel("원자 측정 보고서 미리보기").waitFor({ timeout: 30000 });
        const link = panel.getByRole("link", { name: "Markdown 다운로드" });
        const url = new URL(await link.getAttribute("href"), page.url());
        const handle = url.searchParams.get("handle");
        assert.ok(handle);
        const reportUrl = new URL(`/api/runs/${runId}/reports/selected`, page.url());
        reportUrl.searchParams.set("handle", handle);
        const report = await readJson(reportUrl);
        return { handle, report };
      }, async value => {
        assert.equal(value.report.manifest.result_handle, aligned.handle);
        for (const [field, unit] of [["rmsd_A", "angstrom"], ["unaligned_rmsd_A", "angstrom"],
          ["pair_count", "count"], ["rotation[0][0]", "dimensionless"],
          ["pairs[0].after_residual_A", "angstrom"]])
          assert.ok(value.report.manifest.claims.some(claim => claim.field_path === field && claim.unit === unit),
            `Alignment report lacks field-bound ${field} ${unit} claim`);
        assert.equal(await panel.getByLabel("원자 측정 보고서 미리보기").textContent(),
          value.report.markdown);
        return { handle: value.handle, resultHandle: aligned.handle,
          markdownSha256: sha(Buffer.from(value.report.markdown)) };
      });
      const reportHandle = new URL(await panel.getByRole("link", { name: "Markdown 다운로드" })
        .getAttribute("href"), page.url()).searchParams.get("handle");
      fs.writeFileSync(path.join(artifacts, "alignment-report.json"), JSON.stringify({
        runId, handle: reportHandle, resultHandle: aligned.handle }, null, 2) + "\n");
      for (const format of ["markdown", "json"]) await step(`C11-download-${format}`,
        `Click actual ${format} report browser download`, async () =>
          downloadReport(app, page, panel, new URL(page.url()).origin, runId, format, reportHandle),
        async result => result);
      await step("C08-immutable-source-bytes", "Read both immutable source bytes after fit, overlay and downloads", async () =>
        Promise.all([catalog(new URL(page.url()).origin, runId, ref.sourceHandle),
          catalog(new URL(page.url()).origin, runId, mov.sourceHandle)]), async ([afterRef, afterMov]) => {
        assert.equal(afterRef.viewer_source_sha256, refAtoms.viewer_source_sha256);
        assert.equal(afterMov.viewer_source_sha256, movAtoms.viewer_source_sha256);
        return { referenceSha256: afterRef.viewer_source_sha256,
          movingSha256: afterMov.viewer_source_sha256,
          sourceCoordinatesUnchanged: true };
      });
      await step("C10-return-single-source", "Click return to one structure and observe one-source controls recover", async () => {
        await panel.getByRole("button", { name: "단일 구조로 돌아가기" }).click();
        const native = await nativeSource(page, value => value.layers?.length === 1, 45000);
        await page.getByRole("textbox", { name: "보기 이름" }).fill("QA returned single source");
        return { native, saveEnabled: await page.getByRole("button", { name: "현재 보기 저장" }).isEnabled(),
          promptCount: await page.locator("#viewer-prompt").count() };
      }, async value => {
        assert.equal(value.saveEnabled, true);
        assert.equal(value.promptCount, 1);
        return { sourceHandle: value.native.sourceHandle, layerCount: value.native.layers.length,
          saveEnabled: value.saveEnabled, promptRestored: true };
      });
    } else {
      // Other product modes are added after initial alignment and native-pick
      // controls have passed on the frozen app build. This explicit failure
      // prevents a scaffold run from being mistaken for completed M10 QA.
      throw new Error(`M10 ${input.mode} product cases are pending; no QA pass may be claimed`);
    }
  } finally { await session.close(); }
}

if (require.main === module) run(parse(process.argv.slice(2))).then(() => {
  process.stdout.write("M10 comparison offscreen QA complete\n");
}).catch(error => { process.stderr.write(`M10 comparison offscreen QA failed: ${error.stack ?? error}\n`); process.exitCode = 1; });

module.exports = { parse, fixtureOracle, assertAtomRef, assertDistanceResult,
  assertAlignmentResult, assertNativeLayers, assertNativePick, catalog, measurement,
  createLocalRun, uploadAndLoad, run };
