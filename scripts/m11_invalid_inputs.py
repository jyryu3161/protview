#!/usr/bin/env python3
"""Deterministically build labeled M11 H06 invalid-input QA derivatives from the public ProLIF fixtures.

Every output is a synthetic invalid derivative of the licensed public tutorial receptor/SDF
(backend/tests/fixtures/chemical/), made only to exercise a specific preparation prerequisite
rejection. None is an observed structure or experimental evidence. Each static output must match
its pinned SHA-256 or the script exits non-zero before writing anything. The manifest records, per
case, the independently known offending identities (from the edit this script made), which the
offscreen harness compares with the visible product diagnostics.

- m11-invalid-disconnected-atom.pdb: every PDB CONECT pair touching serial 20 (TYR A 38 OH) removed,
  which also isolates its only neighbor HH (serial 21).
- m11-invalid-altloc.pdb: altloc column (17) of serial 20 (TYR A 38 OH) set to "A".
- m11-invalid-metal.pdb: one HETATM zinc ion (ZN chain Z 901, serial 4989) inserted before CONECT.
- m11-invalid-wrong-source-bonds.json: a receptor_bonds@1 sidecar bound to a nonexistent source handle.
- m11-invalid-wrong-schema-bonds.json: a JSON file whose schema is not receptor_bonds@1.
- m11-invalid-2d-record.sdf: public SDF with record 0's header dimension code changed from 3D to 2D.
- With --attach-sidecar RUN_SIDECAR (a run-bound receptor_bonds@1 from m11_attach_browser_setup.py):
  m11-invalid-covalent-ligand-bonds-run.json adds one bond between the first receptor atom of the
  first sidecar bond and ligand atom X1 (a synthetic covalent-ligand graph; run-bound, not pinned).

Usage: .venv/bin/python scripts/m11_invalid_inputs.py --out DIR [--attach-sidecar FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from m11_qa_inputs import LIGAND_SDF, RECEPTOR, verify

LABEL = "Synthetic invalid derivative of the public ProLIF tutorial fixture; not experimental evidence"
EXPECTED = {
    "m11-invalid-disconnected-atom.pdb": "211e16361f2c01d07a302b0bec925b78173e37a1d7e5c5f5b8dc12ae3c737a02",
    "m11-invalid-altloc.pdb": "9eeb88502458c182858bfc46c1678e989ec8a3fa906ed9c8e488781d77905872",
    "m11-invalid-metal.pdb": "bcf0df223943e28a3a3be02f2ec561c906346ef5bdb79d4f6422b73e103f9739",
    "m11-invalid-wrong-source-bonds.json": "e2e466f6dd849a110e2bd788af45c965ad11c7cb6c165fc15b57815d6c4a92da",
    "m11-invalid-wrong-schema-bonds.json": "28ef868bd6fb59e1fbe6a0d5123aa65ca810df6c39f50f992ff1cf0c04241035",
    "m11-invalid-2d-record.sdf": "4d366fe193cac0c476c757ce4901549b37318e144a5283ba77541d1cee614032",
}
TYR38 = {"model_number": 1, "chain_auth": "A", "chain_label": None, "seq_auth": 38, "seq_label": None,
         "icode": "", "resname": "TYR"}
ZN = {"model_number": 1, "chain_auth": "Z", "chain_label": None, "seq_auth": 901, "seq_label": None,
      "icode": "", "resname": "ZN"}


def _atom(residue: dict, name: str, element: str, altloc: str = "") -> dict:
    return {"residue": residue, "atom_name": name, "altloc": altloc, "element": element}


def disconnected_atom(receptor: str, serial: int = 20) -> bytes:
    lines = []
    for line in receptor.splitlines():
        if line.startswith("CONECT"):
            values = [int(line[i:i + 5]) for i in range(6, len(line), 5) if line[i:i + 5].strip()]
            if values[0] == serial:
                continue
            kept = [value for value in values[1:] if value != serial]
            if not kept:
                continue
            line = "CONECT" + "".join(f"{value:5d}" for value in [values[0], *kept])
        lines.append(line)
    return ("\n".join(lines) + "\n").encode()


def altloc_atom(receptor: str, serial: int = 20) -> bytes:
    lines = []
    for line in receptor.splitlines():
        if line.startswith("ATOM  ") and int(line[6:11]) == serial:
            assert line[16] == " "
            line = line[:16] + "A" + line[17:]
        lines.append(line)
    return ("\n".join(lines) + "\n").encode()


def metal_ion(receptor: str) -> bytes:
    head, tail = receptor.split("CONECT", 1)
    ion = (f"HETATM{4989:5d} {'ZN':<4s} ZN  Z 901    {0.0:8.3f}{0.0:8.3f}{0.0:8.3f}"
           f"{1.00:6.2f}{0.00:6.2f}          ZN  ")
    return (head + ion + "\nCONECT" + tail).encode()


def two_d_record(sdf: str) -> bytes:
    lines = sdf.split("\n")
    assert lines[1][20:22] == "3D"
    lines[1] = lines[1][:20] + "2D" + lines[1][22:]
    return "\n".join(lines).encode()


def build_static() -> tuple[dict[str, bytes], list[dict]]:
    receptor = verify("prolif-vina-rec.pdb", RECEPTOR.read_bytes()).decode()
    sdf = verify("prolif-vina-output.sdf", LIGAND_SDF.read_bytes()).decode()
    wrong_source = {"schema": "receptor_bonds@1", "complete": True, "bonds": [],
                    "source_handle": "obj://run_00000000000000000000000000000000/chemical_raw_input/" + "0" * 64}
    files = {
        "m11-invalid-disconnected-atom.pdb": disconnected_atom(receptor),
        "m11-invalid-altloc.pdb": altloc_atom(receptor),
        "m11-invalid-metal.pdb": metal_ion(receptor),
        "m11-invalid-wrong-source-bonds.json": (json.dumps(wrong_source, sort_keys=True) + "\n").encode(),
        "m11-invalid-wrong-schema-bonds.json": b'{"schema": "not_receptor_bonds@0", "bonds": []}\n',
        "m11-invalid-2d-record.sdf": two_d_record(sdf),
    }
    public_receptor, public_sdf = RECEPTOR.name, LIGAND_SDF.name
    cases = [
        {"case": "missing_graph", "category": "missing graph", "receptor": public_receptor, "sdf": public_sdf,
         "connectivity": "sidecar", "sidecar": None,
         "expected": {"kind": "client_error", "text": "완전한 수용체 결합 sidecar를 업로드하세요."}},
        {"case": "wrong_schema_graph", "category": "wrong graph", "receptor": public_receptor, "sdf": public_sdf,
         "connectivity": "sidecar", "sidecar": "m11-invalid-wrong-schema-bonds.json",
         "expected": {"kind": "upload_error", "text": "malformed chemical input"}},
        {"case": "wrong_source_graph", "category": "wrong graph", "receptor": public_receptor, "sdf": public_sdf,
         "connectivity": "sidecar", "sidecar": "m11-invalid-wrong-source-bonds.json",
         "expected": {"kind": "preview_error", "text": "incomplete or source-mismatched bond sidecar"}},
        {"case": "unacknowledged_graph_h", "category": "incomplete connectivity/H declaration",
         "receptor": public_receptor, "sdf": public_sdf, "connectivity": "pdb_conect", "acknowledge": False,
         "expected": {"kind": "blockers", "codes": ["supplied_graph_complete", "supplied_hydrogens_complete",
                                                     "use_supplied_protonation_tautomer",
                                                     "infer_receptor_orders_charges"], "atoms": {}}},
        {"case": "disconnected_atom", "category": "incomplete connectivity",
         "receptor": "m11-invalid-disconnected-atom.pdb", "sdf": public_sdf, "connectivity": "pdb_conect",
         "expected": {"kind": "blockers", "codes": ["disconnected_receptor_atom"],
                      "atoms": {"disconnected_receptor_atom": [_atom(TYR38, "OH", "O"),
                                                               _atom(TYR38, "HH", "H")]}}},
        {"case": "altloc", "category": "altloc", "receptor": "m11-invalid-altloc.pdb", "sdf": public_sdf,
         "connectivity": "pdb_conect",
         "expected": {"kind": "blockers", "codes": ["alternate_location"],
                      "atoms": {"alternate_location": [_atom(TYR38, "OH", "O", "A")]}}},
        {"case": "metal", "category": "unsupported element/residue/metal", "receptor": "m11-invalid-metal.pdb",
         "sdf": public_sdf, "connectivity": "pdb_conect",
         "expected": {"kind": "blockers", "codes": ["unsupported_receptor_chemistry", "disconnected_receptor_atom"],
                      "atoms": {"unsupported_receptor_chemistry": [_atom(ZN, "ZN", "Zn")],
                                "disconnected_receptor_atom": [_atom(ZN, "ZN", "Zn")]}}},
        {"case": "record_without_3d", "category": "wrong record", "receptor": public_receptor,
         "sdf": "m11-invalid-2d-record.sdf", "connectivity": "pdb_conect",
         "expected": {"kind": "preview_error", "text": "selected SDF record declares no 3D coordinates"}},
        {"case": "ligand_identity_collision", "category": "collision", "receptor": public_receptor,
         "sdf": public_sdf, "connectivity": "pdb_conect", "ligand_instance": TYR38,
         "expected": {"kind": "preview_error", "text": "new ligand instance model or identity collides"}},
    ]
    return files, cases


def covalent_sidecar(sidecar: dict) -> tuple[bytes, dict]:
    if sidecar.get("schema") != "receptor_bonds@1" or not sidecar.get("bonds"):
        raise SystemExit("--attach-sidecar is not a run-bound receptor_bonds@1 sidecar")
    receptor_atom = sidecar["bonds"][0]["first"]
    ligand_residue = {"model_number": 1, "chain_auth": "L", "chain_label": None, "seq_auth": 1,
                      "seq_label": None, "icode": "", "resname": "LIG"}
    ligand_atom = {**receptor_atom, "residue": ligand_residue, "atom_name": "X1", "altloc": "", "element": "C",
                   "site_index": 4988}
    data = {**sidecar, "bonds": [*sidecar["bonds"], {"first": receptor_atom, "second": ligand_atom}]}
    case = {"case": "covalent_ligand", "category": "covalent ligand", "mode": "attach_existing",
            "sidecar": "m11-invalid-covalent-ligand-bonds-run.json",
            "expected": {"kind": "blockers", "codes": ["cross_excluded_bond"],
                         "atoms": {"cross_excluded_bond": [
                             {k: receptor_atom[k] for k in ("residue", "atom_name", "altloc", "element")},
                             {k: ligand_atom[k] for k in ("residue", "atom_name", "altloc", "element")}]}}}
    return (json.dumps(data, separators=(",", ":")) + "\n").encode(), case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="output directory (git-ignored, not /tmp)")
    parser.add_argument("--attach-sidecar", help="run-bound m11-attach-bonds-run.json to derive the covalent case")
    parser.add_argument("--print-hashes", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    files, cases = build_static()
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    if args.print_hashes:
        print(json.dumps(digests, indent=2))
        return
    mismatched = {name: digest for name, digest in digests.items() if EXPECTED[name] != digest}
    if mismatched:
        raise SystemExit(f"SHA-256 mismatch for {sorted(mismatched)}: {mismatched}")
    if args.attach_sidecar:
        raw, case = covalent_sidecar(json.loads(Path(args.attach_sidecar).read_text()))
        files[case["sidecar"]] = raw
        cases.append(case)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    manifest = {"schema": "m11_invalid_inputs@1", "label": LABEL,
                "public_receptor": {"path": str(RECEPTOR), "sha256": hashlib.sha256(RECEPTOR.read_bytes()).hexdigest()},
                "public_ligand_sdf": {"path": str(LIGAND_SDF),
                                      "sha256": hashlib.sha256(LIGAND_SDF.read_bytes()).hexdigest()},
                "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                                 "pinned": name in EXPECTED} for name, data in files.items()},
                "cases": cases}
    (out / "m11-invalid-cases.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"out": str(out), "cases": [case["case"] for case in cases],
                      "files": manifest["files"]}, indent=2))


if __name__ == "__main__":
    main()
