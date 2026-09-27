const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parsePDB } = require('molstar/lib/commonjs/mol-io/reader/pdb/parser.js');
const { trajectoryFromPDB } = require('molstar/lib/commonjs/mol-model-formats/structure/pdb.js');
const { Structure, StructureElement, StructureProperties } = require('molstar/lib/commonjs/mol-model/structure.js');

async function nativeRows(file, frameIndex) {
  const pdb = (await parsePDB(fs.readFileSync(path.join(__dirname, 'offscreen/fixtures', file), 'utf8')).run()).result;
  const trajectory = await trajectoryFromPDB(pdb).run();
  const model = await trajectory.getFrameAtIndex(frameIndex);
  const structure = Structure.ofModel(model);
  const rows = [];
  for (const unit of structure.units) for (const element of unit.elements) {
    const loc = StructureElement.Location.create(structure, unit, element);
    rows.push({ model: unit.model.modelNum, sourceIndex: StructureProperties.atom.sourceIndex(loc),
      chainAuth: StructureProperties.chain.auth_asym_id(loc),
      chainLabel: StructureProperties.chain.label_asym_id(loc),
      seqAuth: StructureProperties.residue.auth_seq_id(loc),
      seqLabel: StructureProperties.residue.label_seq_id(loc),
      icode: StructureProperties.residue.pdbx_PDB_ins_code(loc),
      atom: StructureProperties.atom.auth_atom_id(loc),
      altloc: StructureProperties.atom.label_alt_id(loc) });
  }
  return { frameCount: trajectory.frameCount, rows };
}

test('installed Mol* PDB parser generates display labels distinct from authoritative Gemmi PDB labels', async () => {
  const native = await nativeRows('m10-distance.pdb', 0);
  assert.equal(native.frameCount, 1);
  assert.deepEqual(native.rows.map(row => row.sourceIndex), [0, 1, 2, 3]);
  assert.deepEqual(native.rows.map(row => [row.chainAuth, row.chainLabel, row.seqAuth, row.seqLabel]),
    [['A', 'A', 10, 10], ['A', 'A', 11, 11], ['A', 'A', 12, 12], ['A', 'A', 13, 13]]);
  // The paired Gemmi fixture probe records chain_label=Axp and seq_label=null.
  // Native generated labels must not replace the authoritative catalog identity.
});

test('installed Mol* keeps exact input site indices for nonfirst model, insertion and duplicate alt sites', async () => {
  const native = await nativeRows('m10-identities.pdb', 1);
  assert.equal(native.frameCount, 2);
  assert.deepEqual(native.rows.map(row => row.sourceIndex), [0, 1, 2, 3, 4, 5]);
  assert.ok(native.rows.every(row => row.model === 2 && row.seqAuth === 42 && row.icode === 'A'));
  assert.deepEqual(native.rows.slice(1, 4).map(row => [row.atom, row.altloc]),
    [['CA', 'A'], ['CA', 'B'], ['CA', 'A']]);
});
