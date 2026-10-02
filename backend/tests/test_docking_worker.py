"""M18 T4: the isolated docking worker (``mw/jobs/docking_worker.py``) run in its pinned interpreter.

The worker runs in ``.deps/docking/venv-locked`` exactly as the guardian launches it (``python -I docking_worker.py``
in a private directory with ``input.json`` + ``structure.json``), with the real ``qvina2`` from ``.deps/qvina``. Pure
pieces (hand oracle, fault injection, receptor PDBQT bytes) are exercised by loading the worker module by path in
that same interpreter. The server test process never imports RDKit, Meeko or MDAnalysis. When either pinned
environment is missing these tests fail; they never skip.

Expected values: the hand oracle and the T1 observations in ``fixtures/docking/expected.json`` (the public example is
a public prepared docking example, not experimental validation), and independent re-computation in this file (plain
text parsing of PDB/SDF columns and ``math.dist``). RDKit is used on the test side only to build synthetic inputs and
to compute the reference RMSD of the T1 observation, never through the worker's own functions.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

import pytest

from mw import docking_constants as C

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "backend/mw/jobs/docking_worker.py"
PY = ROOT / ".deps/docking/venv-locked/bin/python"
QVINA = ROOT / ".deps/qvina/env/bin/qvina2"
FIX = Path(__file__).parent / "fixtures/docking"
CHEM = Path(__file__).parent / "fixtures/chemical"
EXPECTED = json.loads((FIX / "expected.json").read_text())
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
REC = (CHEM / "prolif-vina-rec.pdb").read_bytes()
COMPLEX = (FIX / "synthetic-complex-receptor-lig.pdb").read_bytes()
PARENT = (FIX / "public-derived-parent-record0.sdf").read_bytes()
ENUM = json.loads((FIX / "m17-enumerate-result-record0-nmethyl.json").read_text())
CAND = next(c for c in ENUM["candidates"] if c["id"] == EXPECTED["m17_candidate"]["fixed_candidate_id"])
INSTANCE = EXPECTED["receptor_fixtures"]["instance"]
PUBLIC_BOX = EXPECTED["public_example_box"]
MANUAL_BOX = {"source": "manual", "center_A": PUBLIC_BOX["center_A"], "size_A": [22.0, 22.0, 22.0]}
HANDLE = "obj://run_t4/chemical_raw_input/" + "a" * 64
LOAD = ("import importlib.util, json, sys, tempfile, pathlib\n"
        f"spec = importlib.util.spec_from_file_location('dw', {str(WORKER)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n")


def _env_ready() -> None:
    assert PY.is_file(), f"pinned docking interpreter missing at {PY} (no skip)"
    assert QVINA.is_file(), f"pinned qvina2 missing at {QVINA} (no skip)"


def _entry(raw: bytes) -> dict:
    return {"b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _candidate_ligand(parent: bytes = PARENT, *, smiles: str | None = None, retained: list | None = None,
                      parent_sha: str | None = None) -> dict:
    row = {"id": CAND["id"], "smiles": smiles or CAND["smiles"],
           "retained_parent_atoms": CAND["retained_parent_atoms"] if retained is None else retained,
           "stereo_flag": CAND["stereo_flag"]}
    return {"source": "candidate", "parent_sdf": _entry(parent),
            "candidate_set_parent_sha256": parent_sha or _sha(parent), "candidate": row}


def _payload(*, receptor: bytes = REC, instance: dict | None = None, model: int = 1, ligand: dict | None = None,
             mode: str = "free", box: dict | None = None, seed: int = 42, exhaustiveness: int = 1,
             num_modes: int = 9, conformers: int | None = None) -> dict:
    return {"schema": "docking_worker_input@1",
            "receptor": {"handle": HANDLE, "format": "pdb", "bytes": _entry(receptor), "model_number": model,
                         "connectivity": {"kind": "pdb_conect", "sidecar": None}, "instance": instance},
            "ligand": ligand or {"source": "sdf", "sdf": _entry(PARENT)},
            "mode": mode, "box": box or {"source": "ligand_range", "margin_A": 8.0},
            "parameters": {"seed": seed, "exhaustiveness": exhaustiveness, "num_modes": num_modes,
                           "energy_range": 3.0, "conformers": conformers}}


def _call(root: Path, payload: dict, *, control: dict | None = None) -> tuple[int, bytes | None, dict | None]:
    _env_ready()
    root.mkdir(parents=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    (root / "structure.json").write_bytes(raw)
    (root / "input.json").write_text(json.dumps(control or {"adapter": "qvina_dock_v1", "nonce": "0" * 32,
                                                            "job_id": "job_t4", "attempt_id": "att_t4",
                                                            "input_sha256": _sha(raw)}))
    proc = subprocess.run([str(PY), "-I", str(WORKER)], cwd=root, capture_output=True, timeout=600, check=False,
                          env={**ENV, "TMPDIR": str(root)})
    assert len(proc.stderr) < 64_000
    assert not (root / "qvina_work").exists(), "private engine files are removed"
    result = (root / "result.json").read_bytes() if (root / "result.json").exists() else None
    error = json.loads((root / "error.json").read_text()) if (root / "error.json").exists() else None
    return proc.returncode, result, error


def _ok(root: Path, payload: dict) -> tuple[dict, bytes]:
    code, result, error = _call(root, payload)
    assert code == 0 and result is not None and error is None, error
    return json.loads(result), result


def _py(code: str, data: object = None) -> object:
    """Run ``code`` (after loading the worker module as ``m``) in the pinned interpreter; it prints JSON."""
    _env_ready()
    proc = subprocess.run([str(PY), "-I", "-c", LOAD + code], input=json.dumps(data), capture_output=True,
                          text=True, timeout=600, check=False, env=ENV)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _reasons(cases: dict[str, dict]) -> dict[str, list]:
    """Run ``dock`` on each staged payload in one worker interpreter and return [error_class, reason, detail]."""
    code = ("out = {}\n"
            "for name, payload in json.load(sys.stdin).items():\n"
            "    with tempfile.TemporaryDirectory() as tmp:\n"
            "        try:\n"
            "            m.dock(payload, pathlib.Path(tmp)); out[name] = None\n"
            "        except m.DockingWorkerError as exc:\n"
            "            env = exc.envelope(); out[name] = [env['error_class'], env['reason_code'], env['detail']]\n"
            "print(json.dumps(out))\n")
    return _py(code, cases)


def _sdf_atoms(text: str) -> list[tuple[str, tuple[str, str, str]]]:
    """(element, coordinate column strings) per V2000 atom line, read from the text columns."""
    lines = text.splitlines()
    count = int(lines[3][0:3])
    return [(line[31:34].strip(), (line[0:10].strip(), line[10:20].strip(), line[20:30].strip()))
            for line in lines[4:4 + count]]


def _sdf_bonds(text: str) -> set[tuple[int, int]]:
    lines = text.splitlines()
    atoms, bonds = int(lines[3][0:3]), int(lines[3][3:6])
    return {tuple(sorted((int(line[0:3]), int(line[3:6])))) for line in lines[4 + atoms:4 + atoms + bonds]}


def _pdb_sites(raw: bytes) -> list[dict]:
    """Receptor atoms in file order (= gemmi traversal for these single-model, contiguous-chain files)."""
    sites = []
    for line in raw.decode().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            sites.append({"site_index": len(sites), "atom_name": line[12:16].strip(), "element": line[76:78].strip(),
                          "chain": line[21], "seq": int(line[22:26]), "icode": line[26].strip(),
                          "xyz": (float(line[30:38]), float(line[38:46]), float(line[46:54]))})
    return sites


def _kind(a: str, b: str) -> str:
    a, b = a.upper(), b.upper()
    return "polar_contact" if a in "NO" and b in "NO" else "hydrophobic_contact" if a == b == "C" else "contact"


def _independent_contacts(pose_sdf: str, sites: list[dict]) -> list[tuple]:
    rows = []
    for serial, (element, xyz) in enumerate(_sdf_atoms(pose_sdf), start=1):
        if element == "H":
            continue
        point = tuple(float(x) for x in xyz)
        for site in sites:
            if site["element"] != "H" and math.dist(point, site["xyz"]) <= 4.0:
                rows.append((serial, site["site_index"], _kind(element, site["element"])))
    return sorted(rows)


# ------------------------------------------------------------------ handshake and isolation
def test_handshake_reports_pinned_versions_and_engine_hash_without_running_anything():
    _env_ready()
    out = subprocess.run([str(PY), "-I", str(WORKER), "--handshake"], capture_output=True, text=True, timeout=120,
                         check=False, env=ENV)
    assert out.returncode == 0, out.stderr
    shake = json.loads(out.stdout)
    assert shake["schema"] == "docking_worker_handshake@1" and shake["protocols"] == ["qvina_dock_v1"]
    pinned = {"meeko": "0.8.0", "rdkit": "2026.03.6", "MDAnalysis": "2.10.0", "gemmi": "0.7.5"}
    assert shake["versions"] == pinned and shake["versions_expected"] == pinned
    record = json.loads((ROOT / ".deps/qvina/install-record.json").read_text())
    actual = hashlib.sha256(QVINA.read_bytes()).hexdigest()
    assert shake["engine"]["binary_sha256"] == actual == record["executable"]["sha256"]
    assert shake["engine"]["hash_match"] is True and shake["engine"]["present"] is True
    assert shake["engine"]["package"] == "qvina-2.1.0-h4a521e9_8"
    assert shake["worker_sha256"] == hashlib.sha256(WORKER.read_bytes()).hexdigest()


def test_server_modules_never_import_the_worker_or_its_chemistry():
    pattern = re.compile(r"^\s*(from\s+\S*docking_worker\s+import|import\s+\S*docking_worker|"
                         r"from\s+\.+jobs\s+import\s+.*docking_worker|import\s+meeko|from\s+meeko)", re.MULTILINE)
    offenders = [str(path) for path in (ROOT / "backend/mw").rglob("*.py")
                 if path != WORKER and pattern.search(path.read_text())]
    assert offenders == []
    code = ("import sys, mw.docking_inputs, mw.docking_constants\n"
            "print(sorted(m for m in ('rdkit', 'meeko', 'MDAnalysis') if m in sys.modules))")
    out = subprocess.run([str(ROOT / ".venv/bin/python"), "-c", code], capture_output=True, text=True, timeout=120,
                         check=False, cwd=ROOT / "backend", env={**ENV, "PYTHONPATH": str(ROOT / "backend")})
    assert out.returncode == 0 and out.stdout.strip() == "[]", out.stderr


def test_worker_denies_python_network():
    code = ("import socket\n"
            "try:\n    socket.create_connection(('127.0.0.1', 9)); print(json.dumps('connected'))\n"
            "except PermissionError:\n    print(json.dumps('denied'))\n")
    assert _py(code) == "denied"


# ------------------------------------------------------------------ hand oracle (pure pieces)
def test_hand_oracle_contacts_box_and_pose_numbering():
    """``fixtures/docking/expected.json`` contact_oracle: every distance worked out by hand."""
    oracle = EXPECTED["contact_oracle"]
    code = ("d = json.load(sys.stdin)\n"
            "rows = m.receptor_rows(d['rec'].encode(), 'pdb', 'h', 1)\n"
            "heavy = [{'ref': m._public_ref(r), 'xyz': r['coordinate_A']} for r in rows if r['element'] != 'H']\n"
            "mol = m.read_sdf(d['pose'].encode())\n"
            "text, atoms = m.pose_record(mol, 'mode_1')\n"
            "box = m.range_box(m._heavy_points(mol), 8.0)\n"
            "out = {'box': box, 'text': text, 'g': m.geometry(atoms, heavy, box),\n"
            "       'small': m.geometry(atoms, heavy, {'center_A': [0, 0, 0], 'size_A': [2, 2, 2]})}\n"
            "try:\n    m.check_box({'center_A': [100, 100, 100], 'size_A': [8, 8, 8]}, [h['xyz'] for h in heavy])\n"
            "except m.DockingWorkerError as exc:\n    out['far'] = exc.reason_code\n"
            "m.K.MAX_CONTACTS_PER_MODE = 5\n"
            "try:\n    m.geometry(atoms, heavy, box)\n"
            "except m.DockingWorkerError as exc:\n    out['cap'] = [exc.error_class, exc.reason_code]\n"
            "out['stereo'] = [m.unspecified_stereo(m.candidate_heavy(s))\n"
            "                 for s in ('CC(O)CC', 'C[C@H](O)CC', 'CC=CC')]\n"
            "print(json.dumps(out))\n")
    pose = (FIX / "synthetic-contact-oracle-pose.sdf").read_text()
    out = _py(code, {"rec": (FIX / "synthetic-contact-oracle-receptor.pdb").read_text(), "pose": pose})
    by_case = {case["case"]: case for case in oracle["boxes"]}
    ligand_box = by_case["ligand_range margin 8"]
    assert out["box"]["center_A"] == pytest.approx(ligand_box["center_A"], abs=1e-12)
    assert out["box"]["size_A"] == pytest.approx(ligand_box["size_A"], abs=1e-12)
    g = out["g"]
    assert [[c["ligand_serial"], c["receptor_atom"]["site_index"], c["kind"]] for c in g["contacts"]] == \
        oracle["contacts_sorted"]
    hand = {(p["ligand_serial"], p["site_index"]): p["distance_A"] for p in oracle["all_heavy_pairs"]}
    sites = {s["site_index"]: s for s in oracle["receptor_sites"]}
    for row in g["contacts"]:
        assert row["distance_A"] == pytest.approx(hand[(row["ligand_serial"], row["receptor_atom"]["site_index"])],
                                                  abs=oracle["distance_tolerance_A"])
        site = sites[row["receptor_atom"]["site_index"]]
        assert row["receptor_atom"] == {"residue": site["residue"], "atom_name": site["atom_name"], "altloc": "",
                                        "element": site["element"], "site_index": site["site_index"]}
        assert row["ligand_parent_serial"] is None
        assert row["ligand_element"] == {1: "C", 2: "O"}[row["ligand_serial"]]
    assert dict(sorted({k: sum(c["kind"] == k for c in g["contacts"]) for k in C.CONTACT_KINDS}.items())) == \
        dict(sorted(oracle["count_by_kind"].items()))
    assert g["min_heavy_atom_distance_A"] == pytest.approx(oracle["min_heavy_atom_distance_A"]["value"], abs=1e-9)
    assert g["atoms_outside_box"] == ligand_box["atoms_outside_box"] == 0
    assert out["small"]["atoms_outside_box"] == by_case["manual center (0,0,0) size (2,2,2)"]["atoms_outside_box"]
    assert out["far"] == by_case["manual center (100,100,100) size (8,8,8)"]["expected_reason"]
    assert out["cap"] == ["resource_exceeded", "resource_exceeded"], "contacts above the cap fail, never truncated"
    # Pose SDF numbering: atom i of the pose record is atom i of the input record (elements, coordinates, bonds).
    assert _sdf_atoms(out["text"]) == _sdf_atoms(pose) and _sdf_bonds(out["text"]) == _sdf_bonds(pose)
    assert out["text"].splitlines()[0] == "mode_1"
    assert out["stereo"] == [1, 0, 1]


def test_public_example_score_only_is_the_t1_value_and_ignores_the_box():
    """Public prepared docking example (not experimental validation): T1 measured -12.21087 for the reference pose."""
    code = ("d = json.load(sys.stdin)\n"
            "r = m.check_receptor(d['rec'].encode(), 'pdb', 'h', 1, {'kind': 'pdb_conect'}, None, None)\n"
            "tmp = pathlib.Path(tempfile.mkdtemp())\n"
            "(tmp / 'r.pdbqt').write_text(m.receptor_pdbqt(r['kept'], m.receptor_graph(r['kept'], r['kept_bonds'])))\n"
            "text, _map = m.ligand_pdbqt(m.read_sdf(d['lig'].encode()))\n"
            "(tmp / 'l.pdbqt').write_text(text)\n"
            "out = []\n"
            "for box in ([], ['--center_x', '90', '--center_y', '90', '--center_z', '90', '--size_x', '8',\n"
            "                 '--size_y', '8', '--size_z', '8']):\n"
            "    argv = ['--receptor', 'r.pdbqt', '--ligand', 'l.pdbqt', '--score_only', '--cpu', '1', *box]\n"
            "    p = m.run_qvina(argv, tmp)\n"
            "    out.append([p.returncode, m.SCORE_ONLY_RE.findall(p.stdout.decode())])\n"
            "print(json.dumps(out))\n")
    out = _py(code, {"rec": REC.decode(), "lig": PARENT.decode()})
    expected = EXPECTED["public_example_observations"]["score_only_reference_pose_kcal_mol"]
    assert out == [[0, [str(expected)]], [0, [str(expected)]]]


# ------------------------------------------------------------------ free docking, public example
@pytest.fixture(scope="module")
def public_free(tmp_path_factory) -> tuple[dict, bytes]:
    root = tmp_path_factory.mktemp("free") / "attempt"
    return _ok(root, _payload(exhaustiveness=8, seed=42))


def test_public_redock_matches_t1_observation(public_free):
    """Seed 42, exhaustiveness 8, --cpu 1: T1 observed 8 modes and these engine scores (a public prepared example)."""
    out, _raw = public_free
    seen = EXPECTED["public_example_observations"]["free_seed_42"]
    assert out["schema"] == "docking_worker_output@1" and out["method"] == "qvina_free_v1"
    assert out["job_id"] == "job_t4" and out["attempt_id"] == "att_t4"
    assert [m["score_kcal_mol"] for m in out["modes"]] == seen["scores"]
    assert [m["mode"] for m in out["modes"]] == list(range(1, seen["modes_returned"] + 1))
    assert [m["atoms_outside_box"] for m in out["modes"]] == seen["atoms_outside_box"]
    assert out["modes"][0]["engine_rmsd_lb_A"] == 0.0 and out["modes"][0]["engine_rmsd_ub_A"] == 0.0
    assert all(m["conformer_index"] is None and m["core_max_deviation_A"] is None for m in out["modes"])
    assert out["box"] == {"center_A": PUBLIC_BOX["center_A"], "size_A": PUBLIC_BOX["size_A"],
                          "source": "ligand_range", "margin_A": 8.0}
    assert out["parameters"] == {"seed": 42, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0,
                                 "conformers": None, "cpu": 1}
    assert out["engine"] == {"name": "qvina", "version": "2.1.0", "package": "qvina-2.1.0-h4a521e9_8",
                             "binary_sha256": hashlib.sha256(QVINA.read_bytes()).hexdigest()}
    assert out["preparation"] == {"tool": "Meeko", "version": "0.8.0", "rdkit_version": "2026.03.6",
                                  "atom_typing": "ad4", "charges": "gasteiger"}
    assert out["inputs"] == {
        "receptor": {"sha256": _sha(REC), "format": "pdb", "model_number": 1, "atom_count": 4988,
                     "connectivity": {"kind": "pdb_conect", "sidecar_sha256": None}, "removed_instance": None},
        "ligand": {"source": "sdf", "sdf_sha256": _sha(PARENT), "parent_sdf_sha256": None, "candidate_id": None,
                   "generated": {"hydrogens": False, "coordinates": False}, "stereo_flag": None,
                   "unspecified_stereo_centers": None},
        "mode": "free"}
    assert out["limitations"] == list(C.LIMITATIONS[:6])
    assert out["counts"] == {"modes": 8, "contacts_by_mode": [len(m["contacts"]) for m in out["modes"]],
                             "null_result": False, "samples_generated": None, "samples_scored": None}
    assert "affinity" not in json.dumps(out).lower()
    # Heavy-atom RMSD of mode 1 to the reference pose (no alignment, symmetry-aware), computed test-side.
    code = ("from rdkit import Chem\nfrom rdkit.Chem import rdMolAlign\nd = json.load(sys.stdin)\n"
            "ref = Chem.RemoveHs(Chem.MolFromMolBlock(d['ref'], removeHs=False))\n"
            "print(json.dumps([rdMolAlign.CalcRMS(Chem.RemoveHs(Chem.MolFromMolBlock(p, removeHs=False)), ref)\n"
            "                  for p in d['poses']]))\n")
    rmsd = _py(code, {"ref": PARENT.decode(), "poses": [m["pose_sdf"] for m in out["modes"]]})
    assert rmsd[0] == pytest.approx(seen["mode1_heavy_rmsd_to_reference_A"], abs=0.01)
    assert min(rmsd) == pytest.approx(seen["min_heavy_rmsd_any_mode_A"], abs=0.01)


def test_public_pose_sdf_keeps_input_numbering_and_contacts_recompute_independently(public_free):
    out, _raw = public_free
    numbering = EXPECTED["public_example_numbering"]
    parent_atoms = _sdf_atoms(PARENT.decode())
    sites = _pdb_sites(REC)
    for mode in out["modes"]:
        pose = mode["pose_sdf"]
        atoms = _sdf_atoms(pose)
        assert pose.splitlines()[0] == f"mode_{mode['mode']}" and "$$$$" not in pose
        assert len(atoms) == numbering["atoms"]
        assert [a[0] for a in atoms] == [a[0] for a in parent_atoms], "pose atom i = input SDF atom i"
        assert _sdf_bonds(pose) == _sdf_bonds(PARENT.decode())
        assert {a[0] for a in atoms[:43]} == {"C", "N", "O"} and {a[0] for a in atoms[43:]} == {"H"}
        # Restored hydrogens (merged nonpolar ones included) sit on their own parent at an X-H bond length.
        points = [tuple(float(x) for x in a[1]) for a in atoms]
        for first, second in _sdf_bonds(pose):
            if "H" in (atoms[first - 1][0], atoms[second - 1][0]):
                assert 0.9 <= math.dist(points[first - 1], points[second - 1]) <= 1.15
        assert len(set(points)) == len(points)
        rows = [(c["ligand_serial"], c["receptor_atom"]["site_index"], c["kind"]) for c in mode["contacts"]]
        assert rows == _independent_contacts(pose, sites)
        for c in mode["contacts"]:
            site = sites[c["receptor_atom"]["site_index"]]
            assert (c["receptor_atom"]["atom_name"], c["receptor_atom"]["element"],
                    c["receptor_atom"]["residue"]["chain_auth"], c["receptor_atom"]["residue"]["seq_auth"]) == \
                (site["atom_name"], site["element"], site["chain"], site["seq"])
            assert c["ligand_parent_serial"] is None and c["distance_A"] <= 4.0
        heavy = [tuple(float(x) for x in a[1]) for a in atoms if a[0] != "H"]
        minimum = min(math.dist(p, s["xyz"]) for p in heavy for s in sites if s["element"] != "H")
        assert mode["min_heavy_atom_distance_A"] == pytest.approx(minimum, abs=1e-9)


def test_same_seed_gives_identical_bytes_and_another_seed_differs(tmp_path):
    first = _ok(tmp_path / "a", _payload(seed=42))[1]
    second = _ok(tmp_path / "b", _payload(seed=42))[1]
    other = _ok(tmp_path / "c", _payload(seed=7))[1]
    assert first == second
    assert other != first and json.loads(other)["parameters"]["seed"] == 7


# ------------------------------------------------------------------ receptor instance
def test_removing_the_instance_gives_the_receptor_only_pdbqt_bytes():
    code = ("d = json.load(sys.stdin)\nout = []\n"
            "for raw, inst in ((d['complex'], d['inst']), (d['rec'], None)):\n"
            "    r = m.check_receptor(raw.encode(), 'pdb', 'h', 1, {'kind': 'pdb_conect'}, inst, None)\n"
            "    out.append([m.receptor_pdbqt(r['kept'], m.receptor_graph(r['kept'], r['kept_bonds'])),\n"
            "                r['removed_instance']])\n"
            "print(json.dumps(out))\n")
    (with_instance, removed), (plain, none) = _py(code, {"complex": COMPLEX.decode(), "rec": REC.decode(),
                                                         "inst": INSTANCE})
    assert with_instance == plain and none is None
    fixture = EXPECTED["receptor_fixtures"]["synthetic-complex-receptor-lig.pdb"]
    assert removed == {"residue": INSTANCE, "atom_count": fixture["instance_atoms"],
                       "element_counts": fixture["instance_element_counts"]}
    types = EXPECTED["public_example_observations"]["receptor_pdbqt"]
    lines = plain.splitlines()
    assert len(lines) == types["lines"]
    assert dict(sorted((t, sum(line[77:].strip() == t for line in lines)) for t in types["types"])) == \
        dict(sorted(types["types"].items()))


def test_complex_with_instance_docks_with_instance_range_box(tmp_path):
    out, _raw = _ok(tmp_path / "a", _payload(receptor=COMPLEX, instance=INSTANCE,
                                             box={"source": "instance_range", "margin_A": 8.0}, num_modes=2))
    fixture = EXPECTED["receptor_fixtures"]["synthetic-complex-receptor-lig.pdb"]
    assert out["inputs"]["receptor"]["atom_count"] == fixture["total_atoms"]
    assert out["inputs"]["receptor"]["removed_instance"] == {
        "residue": INSTANCE, "atom_count": fixture["instance_atoms"],
        "element_counts": fixture["instance_element_counts"]}
    # The instance is record 0 itself, so its heavy-atom range box is the hand-computed public example box.
    assert out["box"]["center_A"] == PUBLIC_BOX["center_A"] and out["box"]["size_A"] == PUBLIC_BOX["size_A"]
    assert out["box"]["source"] == "instance_range"
    assert out["limitations"] == list(C.LIMITATIONS[:6]) + [C.LIMITATIONS[8]]
    assert 1 <= out["counts"]["modes"] <= 2
    sites = _pdb_sites(COMPLEX)
    assert all(sites[c["receptor_atom"]["site_index"]]["chain"] != "L" for m in out["modes"] for c in m["contacts"])


# ------------------------------------------------------------------ candidates
def test_core_fixed_keeps_core_heavy_atoms_on_parent_coordinates(tmp_path):
    out, _raw = _ok(tmp_path / "a", _payload(ligand=_candidate_ligand(), mode="core_fixed", conformers=5,
                                             num_modes=3))
    assert out["method"] == "qvina_core_fixed_score_only_v1"
    assert out["counts"]["samples_generated"] == 5 and out["counts"]["samples_scored"] == 5
    assert out["counts"]["modes"] == 3 and [m["mode"] for m in out["modes"]] == [1, 2, 3]
    keys = [(m["score_kcal_mol"], m["conformer_index"]) for m in out["modes"]]
    assert keys == sorted(keys) and len({m["conformer_index"] for m in out["modes"]}) == 3
    assert out["inputs"]["ligand"] == {
        "source": "candidate", "sdf_sha256": None, "parent_sdf_sha256": EXPECTED["m17_candidate"]["parent_sha256"],
        "candidate_id": CAND["id"], "generated": {"hydrogens": True, "coordinates": True}, "stereo_flag": "none",
        "unspecified_stereo_centers": 0}
    assert out["limitations"] == list(C.LIMITATIONS[:5]) + [C.LIMITATIONS[6], C.LIMITATIONS[7]]
    parent = _sdf_atoms(PARENT.decode())
    retained = set(CAND["retained_parent_atoms"])
    core = {parent[s - 1][1]: (s, parent[s - 1][0]) for s in retained}
    for mode in out["modes"]:
        assert mode["engine_rmsd_lb_A"] is None and mode["engine_rmsd_ub_A"] is None
        assert mode["core_max_deviation_A"] == 0.0
        atoms = _sdf_atoms(mode["pose_sdf"])
        placed = [(xyz, element) for element, xyz in atoms if xyz in core]
        assert len(placed) == len(retained) == 42, "every core heavy atom sits exactly on its parent coordinate"
        assert all(core[xyz][1] == element for xyz, element in placed)
        assert sum(element != "H" for element, _xyz in atoms) == 44
        for c in mode["contacts"]:
            if c["ligand_parent_serial"] is not None:
                assert atoms[c["ligand_serial"] - 1][1] == parent[c["ligand_parent_serial"] - 1][1]
        assert any(c["ligand_parent_serial"] is not None for c in mode["contacts"])
        assert all(c["ligand_parent_serial"] in retained or c["ligand_parent_serial"] is None
                   for c in mode["contacts"])


def test_core_fixed_far_from_the_receptor_records_empty_contact_lists(tmp_path):
    """Parent moved 60 A away along x: samples keep those core coordinates, so no receptor atom is within 4 A."""
    lines = PARENT.decode().splitlines(keepends=True)
    count = int(lines[3][0:3])
    moved = "".join(f"{float(line[0:10]) + 60:10.4f}{line[10:]}" if 4 <= i < 4 + count else line
                    for i, line in enumerate(lines)).encode()
    out, _raw = _ok(tmp_path / "a", _payload(ligand=_candidate_ligand(moved), mode="core_fixed", conformers=2,
                                             num_modes=2, box=MANUAL_BOX))
    assert out["counts"]["modes"] == 2 and out["counts"]["contacts_by_mode"] == [0, 0]
    assert out["counts"]["null_result"] is False
    for mode in out["modes"]:
        assert mode["contacts"] == [] and mode["min_heavy_atom_distance_A"] > 4.0
        assert mode["atoms_outside_box"] == 44 and mode["core_max_deviation_A"] == 0.0


def test_candidate_free_docking_marks_generated_inputs(tmp_path):
    out, _raw = _ok(tmp_path / "a", _payload(ligand=_candidate_ligand(), num_modes=2))
    assert out["method"] == "qvina_free_v1" and 1 <= out["counts"]["modes"] <= 2
    assert out["inputs"]["ligand"]["generated"] == {"hydrogens": True, "coordinates": True}
    assert out["box"]["center_A"] == PUBLIC_BOX["center_A"], "ligand_range uses the parent SDF coordinates"
    assert out["limitations"] == list(C.LIMITATIONS[:7]) + [C.LIMITATIONS[9]]
    assert all(c["ligand_parent_serial"] is None for m in out["modes"] for c in m["contacts"])


# ------------------------------------------------------------------ refusals (closed reason set)
def _strip_hydrogens(raw: bytes) -> bytes:
    kept, removed, out = set(), set(), []
    for line in raw.decode().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            (removed if line[76:78].strip() == "H" else kept).add(int(line[6:11]))
            if line[76:78].strip() != "H":
                out.append(line)
        elif line.startswith("CONECT"):
            values = [int(line[i:i + 5]) for i in range(6, len(line), 5) if line[i:i + 5].strip()]
            partners = [v for v in values[1:] if v not in removed]
            if values[0] not in removed and partners:
                out.append("CONECT" + "".join(f"{v:5d}" for v in [values[0], *partners]))
        else:
            out.append(line)
    assert removed
    return ("\n".join(out) + "\n").encode()


def _rename_residue(raw: bytes, chain: str, seq: int, old: str, new: str) -> bytes:
    lines = []
    for line in raw.decode().splitlines():
        if line.startswith(("ATOM", "HETATM")) and line[21] == chain and int(line[22:26]) == seq:
            assert line[17:20] == old
            line = line[:17] + new + line[20:]
        lines.append(line)
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture(scope="module")
def synthetic_parents() -> dict:
    """Test-side RDKit 3D parents: ethane, and ethanol with its C-C bond stretched by 3x (about 6 A)."""
    code = ("from rdkit import Chem\nfrom rdkit.Chem import AllChem\n"
            "ethane = Chem.AddHs(Chem.MolFromSmiles('CC')); AllChem.EmbedMolecule(ethane, randomSeed=1)\n"
            "mol = Chem.AddHs(Chem.MolFromSmiles('CCO')); AllChem.EmbedMolecule(mol, randomSeed=1)\n"
            "conf = mol.GetConformer()\n"
            "shift = (conf.GetAtomPosition(0) - conf.GetAtomPosition(1)) * 3.0\n"
            "for i in [0] + [n.GetIdx() for n in mol.GetAtomWithIdx(0).GetNeighbors() if n.GetAtomicNum() == 1]:\n"
            "    conf.SetAtomPosition(i, conf.GetAtomPosition(i) + shift)\n"
            "print(json.dumps({'ethane': Chem.MolToMolBlock(ethane), 'stretched': Chem.MolToMolBlock(mol)}))\n")
    return _py(code)


def test_refusals_use_the_closed_reason_set(synthetic_parents):
    def candidate(smiles: str) -> dict:
        return _payload(ligand=_candidate_ligand(smiles=smiles), box=MANUAL_BOX)

    ethane = synthetic_parents["ethane"].encode()
    stretched = synthetic_parents["stretched"].encode()
    v3000 = PARENT.decode().replace("V2000", "V3000").encode()
    unknown = {**INSTANCE, "seq_auth": 2}
    cases = {
        # receptor (8)
        "receptor_invalid": _payload(model=2),
        "receptor_hydrogens_missing": _payload(receptor=_strip_hydrogens(REC), box=MANUAL_BOX),
        "receptor_unsupported_residue": _payload(receptor=COMPLEX),
        "receptor_unsupported_residue/water_zinc": _payload(receptor=(FIX / "synthetic-receptor-water-zinc.pdb")
                                                            .read_bytes()),
        "receptor_altloc_present": _payload(receptor=(FIX / "synthetic-receptor-altloc.pdb").read_bytes()),
        "receptor_instance_unknown": _payload(receptor=COMPLEX, instance=unknown),
        "receptor_instance_ambiguous": _payload(receptor=(FIX / "synthetic-complex-duplicate-instance.pdb")
                                                .read_bytes(), instance=INSTANCE),
        "receptor_instance_covalent": _payload(receptor=(FIX / "synthetic-complex-covalent-instance.pdb")
                                               .read_bytes(), instance=INSTANCE),
        "receptor_prep_failed": _payload(receptor=_rename_residue(REC, "A", 139, "HSD", "HSE")),
        # ligand (8 here; ligand_prep_failed by fault injection below)
        "ligand_unparseable": _payload(ligand={"source": "sdf", "sdf": _entry(v3000)}),
        "ligand_unparseable/smiles": candidate("C1CC"),
        "ligand_record_count": _payload(ligand={"source": "sdf", "sdf": _entry(PARENT + PARENT)}),
        "ligand_multiple_fragments": candidate("CCO.CC"),
        "ligand_element_not_allowed": candidate("C[Si](C)(C)C"),
        "ligand_too_many_atoms": candidate("C" * 101),
        "ligand_too_many_torsions": candidate("C" * 40),
        "ligand_not_3d": _payload(ligand={"source": "sdf", "sdf": _entry((FIX / "synthetic-ligand-planar-z0.sdf")
                                                                       .read_bytes())}),
        "ligand_hydrogens_missing": _payload(ligand={"source": "sdf", "sdf": _entry(
            (FIX / "synthetic-ligand-implicit-h.sdf").read_bytes())}),
        # candidate and core (candidate_unknown is the server's: the worker only receives the selected row)
        "parent_mismatch": _payload(ligand=_candidate_ligand(parent_sha="0" * 64)),
        "parent_not_3d": _payload(ligand=_candidate_ligand((FIX / "synthetic-ligand-planar-z0.sdf").read_bytes())),
        "core_match_failed": _payload(ligand=_candidate_ligand(smiles="CCO"), mode="core_fixed", conformers=2),
        "core_match_ambiguous": _payload(ligand=_candidate_ligand(ethane, smiles="CCC", retained=[1]),
                                         mode="core_fixed", conformers=2, box=MANUAL_BOX),
        "embed_failed": _payload(ligand=_candidate_ligand(stretched, smiles="CCOC", retained=[1, 2, 3]),
                                 mode="core_fixed", conformers=3, box=MANUAL_BOX),
        # box (3)
        "box_invalid": _payload(box={"source": "instance_range", "margin_A": 8.0}),
        "box_too_large": _payload(box={"source": "ligand_range", "margin_A": 20.0}),
        "box_no_receptor_atoms": _payload(box={"source": "manual", "center_A": [500.0, 500.0, 500.0],
                                               "size_A": [8.0, 8.0, 8.0]}),
    }
    out = _reasons(cases)
    for name, got in out.items():
        assert got is not None, name
        assert got[1] == name.split("/")[0], (name, got)
        assert got[0] == "input_invalid", (name, got)
        assert got[1] in C.REASONS
    items = out["receptor_unsupported_residue/water_zinc"][2]["items"]
    assert [(i["residue"]["resname"], i["residue"]["chain_auth"], i["residue"]["seq_auth"]) for i in items] == \
        [("HOH", "W", 1), ("ZN", "Z", 1)]
    assert out["receptor_unsupported_residue"][2]["items"][0]["residue"] == INSTANCE
    assert out["receptor_altloc_present"][2]["items"] == [{
        "residue": {"model_number": 1, "chain_auth": "A", "chain_label": None, "seq_auth": 38, "seq_label": None,
                    "icode": "", "resname": "TYR"}, "atom_name": "CB", "altloc": "A"}]
    assert out["receptor_instance_ambiguous"][2]["matches"] == 2
    assert out["receptor_prep_failed"][2]["m11_check"] == "histidine_alias_state"
    assert out["box_too_large"][2]["size_A"][0] == pytest.approx(6.321 + 40)
    reasons = {got[1] for got in out.values()} | {"ligand_prep_failed", "candidate_unknown"}
    assert reasons == set(C.RECEPTOR_REASONS + C.LIGAND_REASONS + C.CANDIDATE_REASONS + C.BOX_REASONS)


def test_meeko_failure_is_ligand_prep_failed_and_never_reaches_the_engine():
    code = ("class Broken:\n"
            "    def __init__(self, **kw): pass\n"
            "    def prepare(self, mol): raise RuntimeError('injected')\n"
            "m.MoleculePreparation = Broken\n"
            "try:\n    m.ligand_pdbqt(m.read_sdf(sys.stdin.read().encode()))\n"
            "except m.DockingWorkerError as exc:\n    print(json.dumps([exc.error_class, exc.reason_code]))\n")
    proc = subprocess.run([str(PY), "-I", "-c", LOAD + code], input=PARENT.decode(), capture_output=True, text=True,
                          timeout=120, check=False, env=ENV)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["input_invalid", "ligand_prep_failed"]


def test_refusal_writes_error_json_and_exit_1(tmp_path):
    planar = _payload(ligand={"source": "sdf", "sdf": _entry((FIX / "synthetic-ligand-planar-z0.sdf").read_bytes())})
    code, result, error = _call(tmp_path / "a", planar)
    assert code == 1 and result is None
    assert set(error) == {"schema", "error_class", "reason_code", "message", "detail"}
    assert error["schema"] == "docking_worker_error@1"
    assert [error["error_class"], error["reason_code"]] == ["input_invalid", "ligand_not_3d"]
    broken = copy.deepcopy(planar)
    broken["parameters"]["seed"] = -1
    code, result, error = _call(tmp_path / "b", broken)
    assert code == 1 and result is None and [error["error_class"], error["reason_code"]] == ["fatal", "engine_failed"]
    raw = json.dumps(planar, sort_keys=True, separators=(",", ":")).encode()
    code, result, error = _call(tmp_path / "c", planar, control={"adapter": "qvina_dock_v1", "job_id": "job_t4",
                                                                 "attempt_id": "att_t4", "input_sha256": "0" * 64})
    assert code == 1 and result is None and error["reason_code"] == "engine_failed" and _sha(raw) != "0" * 64


def test_score_only_parser_reads_exponent_notation_and_refuses_nonfinite_or_malformed_values():
    """``--score_only`` stdout parsing alone (no engine run): finite exponent notation passes, nan/inf/garbage do not."""
    lines = {"plain": "Affinity: -7.25 (kcal/mol)", "positive": "Affinity: 3.1 (kcal/mol)",
             "integer": "Affinity: 12 (kcal/mol)", "exp_plus": "Affinity: 1.2e+05 (kcal/mol)",
             "exp_upper": "Affinity: -4.5E-01 (kcal/mol)", "exp_bare": "Affinity: 2e3 (kcal/mol)",
             "nan": "Affinity: nan (kcal/mol)", "inf": "Affinity: inf (kcal/mol)", "neg_inf": "Affinity: -inf (kcal/mol)",
             "overflow": "Affinity: 1e400 (kcal/mol)", "garbage": "Affinity: 1.2.3 (kcal/mol)",
             "hex": "Affinity: 0x1p3 (kcal/mol)", "missing": "Intermolecular contributions only",
             "two": "Affinity: -1.0 (kcal/mol)\nAffinity: -2.0 (kcal/mol)"}
    data = {name: f"Detected 4 CPUs\nReading input ... done.\n{line}\nIntramolecular energy: 0.1\n"
            for name, line in lines.items()}
    code = ("out = {}\n"
            "for name, text in json.load(sys.stdin).items():\n"
            "    try:\n        out[name] = m.parse_score_only(text)\n"
            "    except m.DockingWorkerError as exc:\n        out[name] = [exc.error_class, exc.reason_code]\n"
            "print(json.dumps(out))\n")
    out = _py(code, data)
    assert out["plain"] == -7.25 and out["positive"] == 3.1 and out["integer"] == 12.0
    assert out["exp_plus"] == 1.2e5 and out["exp_upper"] == -0.45 and out["exp_bare"] == 2000.0
    for name in ("nan", "inf", "neg_inf", "overflow", "garbage", "hex", "missing", "two"):
        assert out[name] == ["fatal", "engine_output_invalid"], name
