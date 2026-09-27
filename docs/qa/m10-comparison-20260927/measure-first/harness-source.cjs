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
const MODES = new Set(["measure", "alignment", "identity", "source-matrix", "overlay", "faults", "replay", "regression"]);
const ATOM_FIELDS = ["structure_handle", "residue", "atom_name", "altloc", "element", "site_index"];
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];

function sha(bytes) { return crypto.createHash("sha256").update(bytes).digest("hex"); }
function parse(argv) {
  const input = { url: null, run: null, otherRun: null, artifacts: null, mode: null,
    fixtureDir: FIXTURE_DIR, reference: null, moving: null, figure: null };
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
    else throw new Error(`Unknown argument: ${option}`);
  }
  if (!input.url || !input.artifacts || !MODES.has(input.mode))
    throw new Error("Usage: comparison-flow.cjs --url http://127.0.0.1:3000 --artifacts /tmp/... --mode measure|alignment|identity|source-matrix|overlay|faults|replay|regression [--run run_...] [--other-run run_...] [--fixtures dir]");
  const url = new URL(input.url);
  if (!["http:", "https:"].includes(url.protocol) ||
      !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname))
    throw new Error("M10 QA URL must use loopback HTTP(S)");
  if (input.run) assert.match(input.run, /^run_[a-f0-9]+$/);
  if (input.otherRun) { assert.match(input.otherRun, /^run_[a-f0-9]+$/);
    assert.notEqual(input.otherRun, input.run); }
  if (input.mode === "source-matrix") assert.ok(input.run && input.otherRun,
    "Source matrix requires real 1HSG and OpenMM run IDs");
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
async function clickCatalogAtom(page, row, layer = "reference", alignment = null, aligned = false) {
  const before = await waitForViewer(page, value => value.ready && value.nativeCamera &&
    value.measureMode && Array.isArray(value.qaAtoms) && Number.isInteger(value.atomPickRevision));
  const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
  const box = await canvas.boundingBox();
  assert.ok(box, "Native Mol* canvas is not visible for pointer pick");
  const world = layer === "moving" && aligned
    ? transform(row.coordinate_A, alignment.rotation.flat(), alignment.translation_A)
    : row.coordinate_A;
  const observed = before.qaAtoms.find(atom => atom.layer === layer &&
    atom.ref.structure_handle === row.ref.structure_handle && atom.ref.site_index === row.ref.site_index);
  assert.ok(observed, "Target site absent from read-only native Mol* projection observer");
  assert.deepEqual(observed.ref, row.ref);
  vectorClose(observed.worldCoordinate_A, world, 1e-4, "native projected atom world coordinate");
  const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
  assert.ok(size.width > 0 && size.height > 0);
  const point = { x: box.x + observed.canvasPixel[0] * box.width / size.width,
    y: box.y + observed.canvasPixel[1] * box.height / size.height,
    nativeCanvasPixel: observed.canvasPixel };
  assert.ok(point.x >= box.x && point.x <= box.x + box.width &&
    point.y >= box.y && point.y <= box.y + box.height, "Native projection lies outside canvas");
  await page.mouse.click(point.x, point.y);
  const after = await waitForViewer(page, value => value.atomPickRevision > before.atomPickRevision &&
    value.lastAtomPick?.layer === layer &&
    value.lastAtomPick.ref.structure_handle === row.ref.structure_handle &&
    value.lastAtomPick.ref.site_index === row.ref.site_index, 7000);
  return { requested: row.ref, actual: after.lastAtomPick, point, pickRevision: after.atomPickRevision,
    camera: before.nativeCamera, canvas: box };
}
async function clickAnyNativeAtom(page, catalogValue) {
  const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
  const box = await canvas.boundingBox(); assert.ok(box);
  const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
  const candidates = (await waitForViewer(page, value => value.measureMode &&
    value.sourceHandle === catalogValue.structure_handle && value.qaAtoms?.length > 0)).qaAtoms
    .filter(atom => atom.layer === "reference" &&
      atom.ref.structure_handle === catalogValue.structure_handle &&
      atom.canvasPixel[0] > 8 && atom.canvasPixel[0] < size.width - 8 &&
      atom.canvasPixel[1] > 8 && atom.canvasPixel[1] < size.height - 8);
  assert.ok(candidates.length > 0, "No projected native atom in real source viewport");
  for (const candidate of candidates.slice(0, 24)) {
    const before = await waitForViewer(page, value => value.measureMode &&
      value.sourceHandle === catalogValue.structure_handle);
    const point = { x: box.x + candidate.canvasPixel[0] * box.width / size.width,
      y: box.y + candidate.canvasPixel[1] * box.height / size.height };
    await page.mouse.click(point.x, point.y);
    let after;
    try {
      after = await waitForViewer(page, value => value.atomPickRevision > before.atomPickRevision &&
        value.lastAtomPick?.layer === "reference" &&
        value.lastAtomPick.ref.structure_handle === catalogValue.structure_handle, 600);
    } catch { continue; /* projected site may be occluded; try next real pointer target */ }
    const native = assertNativePick(after, catalogValue, "reference",
      { rotation: [[1,0,0],[0,1,0],[0,0,1]], translation_A: [0,0,0] }, false);
    return { attemptedSite: candidate.ref.site_index, pointer: point,
      observedSite: after.lastAtomPick.ref.site_index, native };
  }
  throw new Error(`No genuine native atom pick succeeded in 24 projected sites for ${catalogValue.structure_handle}`);
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
    if (input.mode === "source-matrix") {
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
          translation_A: [0,0,0] }, false) }));
      await step("C02-undo-first", "Click visible first-atom undo control", async () => {
        await panel.getByRole("button", { name: "첫 원자 취소" }).click();
        return panel.getByRole("button", { name: "첫 원자 취소" }).isDisabled();
      }, async disabled => { assert.equal(disabled, true); return { pendingAtomCleared: true }; });
      await step("C02-first-again", "Click first actual N atom after undo", async () =>
        clickCatalogAtom(page, first), async clicked => ({ pointer: clicked.point,
          actual: clicked.actual }));
      const distance = await step("C03-two-click-5A", "Click second actual O atom and await guarded distance result", async () => {
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runId}/commands`, { timeout: 30000 });
        const clicked = await clickCatalogAtom(page, second);
        const response = await posted;
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
          nativeSecondPick: value.clicked.actual };
      });
      fs.writeFileSync(path.join(artifacts, "distance-result.json"), JSON.stringify({ runId,
        handle: distance.handle, result: distance.result }, null, 2) + "\n");
      await step("C02-repeat-reverse", "Repeat real two-click measurement with reverse endpoint order", async () => {
        const firstClick = await clickCatalogAtom(page, second);
        await panel.getByText(/첫 원자:/).waitFor({ timeout: 10000 });
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runId}/commands`, { timeout: 30000 });
        const secondClick = await clickCatalogAtom(page, first);
        const response = await posted;
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
          secondPointer: value.secondClick.point, distance_A: value.detail.result.distance_A };
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
        assert.ok(value.artifact.manifest.claims.some(claim => claim.field_path === "distance_A" &&
          claim.unit === "angstrom" && claim.exact_value === 5));
        assert.equal(await panel.getByLabel("원자 측정 보고서 미리보기").textContent(),
          value.artifact.markdown);
        assert.match(value.artifact.markdown, /angstrom|Å/);
        return { handle: value.handle, markdownSha256: sha(Buffer.from(value.artifact.markdown)),
          resultHandle: value.artifact.manifest.result_handle };
      });
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
      await step("C02-residue-after-exit", "Click actual N atom after exit and observe ordinary residue selection", async () => {
        const before = await waitForViewer(page, value => !value.measureMode && value.nativeCamera &&
          value.qaAtoms?.some(atom => atom.ref.site_index === first.ref.site_index));
        const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
        const box = await canvas.boundingBox();
        assert.ok(box);
        const atom = before.qaAtoms.find(value => value.layer === "reference" &&
          value.ref.site_index === first.ref.site_index);
        assert.ok(atom);
        const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
        const point = { x: box.x + atom.canvasPixel[0] * box.width / size.width,
          y: box.y + atom.canvasPixel[1] * box.height / size.height,
          nativeCanvasPixel: atom.canvasPixel };
        await page.mouse.click(point.x, point.y);
        const after = await waitForViewer(page, value => value.selection?.seq_auth === 10 &&
          value.selection?.chain_auth === "A", 7000);
        return { point, after };
      }, async ({ point, after }) => ({ pointer: point, residue: after.selection,
        measureMode: after.measureMode }));
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
      await step("C09-same-source-overlay-distance", "Hide moving layer; enter Measure; click two real reference CA atoms", async () => {
        await panel.getByRole("checkbox", { name: "이동 구조 표시" }).uncheck();
        await panel.getByRole("button", { name: "원자 거리 측정", exact: true }).click();
        await waitForViewer(page, value => value.measureMode && value.layers?.[1]?.visible === false);
        const firstClick = await clickCatalogAtom(page, pairRefs[1].reference);
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runId}/commands`, { timeout: 30000 });
        const secondClick = await clickCatalogAtom(page, pairRefs[2].reference);
        const response = await posted;
        assert.equal(response.status(), 200);
        const body = await response.json();
        assert.equal(body.ok, true, JSON.stringify(body));
        return { firstClick, secondClick, detail: await measurement(new URL(page.url()).origin,
          runId, body.handle.handle) };
      }, async value => {
        const measured = assertDistanceResult(value.detail.result, ref.sourceHandle);
        close(value.detail.result.distance_A, 5, 1e-12, "overlay same-source original 5 Å distance");
        return { handle: value.detail.meta.handle, nativeFirst: value.firstClick.actual,
          nativeSecond: value.secondClick.actual, measured };
      });
      await step("C09-cross-layer-rejection", "Click reference first, then moving atom with only its native layer visible", async () => {
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
        await panel.getByRole("combobox", { name: "저장된 거리·정렬 결과" }).selectOption(aligned.handle);
        await panel.getByText(/정렬 RMSD/).waitFor({ timeout: 30000 });
        return waitForViewer(page, value => value.layers?.length === 2 &&
          value.layers[0].sourceHandle === ref.sourceHandle && value.layers[1].sourceHandle === mov.sourceHandle);
      }, async native => ({ alignmentHandle: aligned.handle,
        layers: assertNativeLayers(native, aligned.result, true, { reference: true, moving: true }) }));
      await step("C08-pair-row-focus", "Click actual correspondence-row focus on the native two-layer overlay", async () => {
        const before = await waitForViewer(page, value => value.layers?.length === 2 && value.nativeCamera);
        await panel.getByRole("region", { name: "명시한 CA 대응" })
          .getByRole("button", { name: "대응 원자 초점" }).first().click();
        const after = await waitForViewer(page, value => value.layers?.length === 2 && value.nativeCamera &&
          norm(vectorSub(value.nativeCamera.target, before.nativeCamera.target)) > 1e-4, 15000);
        return { before, after };
      }, async ({ before, after }) => ({ previousTarget: before.nativeCamera.target,
        focusedTarget: after.nativeCamera.target, nativeLayers: assertNativeLayers(after, aligned.result,
          true, { reference: true, moving: true }) }));
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
