"""M17 T2 pure server modules: site pre-check graph and stored-value filter evaluation (spec 4.1, 5)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from mw import ligand_constants as C
from mw.core.errors import FailureClass, ToolFailure
from mw.ligand_filters import evaluate_row, normalize_filter_spec, query_candidates
from mw.ligand_site import check_site

FIX = Path(__file__).parent / "fixtures" / "ligand"
EXPECTED = json.loads((FIX / "expected.json").read_text())
MW = Path(__file__).resolve().parents[1] / "mw"


def _sdf_atoms_bonds(name: str) -> tuple[list[str], list[tuple[int, int, int]]]:
    """Read a V2000 block by column position (independent of the module under test)."""
    lines = (FIX / name).read_text().splitlines()
    na, nb = int(lines[3][0:3]), int(lines[3][3:6])
    elements = [line[31:34].strip() for line in lines[4:4 + na]]
    bonds = [(int(line[0:3]), int(line[3:6]), int(line[6:9])) for line in lines[4 + na:4 + na + nb]]
    return elements, bonds


def _inspection(variant: str) -> dict:
    """Build the inspection-graph input (T3 schema) from the hand oracle and the SDF H lines."""
    parent = EXPECTED["parents"][variant]
    bonds = [{"a": a, "b": b, "order": order} for a, b, order in parent["bonds_heavy"]]
    neighbors: dict[int, list[int]] = {atom["serial"]: [] for atom in parent["heavy_atoms"]}
    for bond in bonds:
        neighbors[bond["a"]].append(bond["b"])
        neighbors[bond["b"]].append(bond["a"])
    elements, sdf_bonds = _sdf_atoms_bonds(parent["file"])
    hydrogens = []
    for a, b, _ in sdf_bonds:
        for h, heavy in ((a, b), (b, a)):
            if elements[h - 1] == "H":
                hydrogens.append({"serial": h, "attached_to": heavy})
    return {"atoms": [{"serial": atom["serial"], "element": atom["element"], "formal_charge": 0,
                       "neighbors": sorted(neighbors[atom["serial"]])} for atom in parent["heavy_atoms"]],
            "bonds": bonds, "hydrogens": sorted(hydrogens, key=lambda row: row["serial"])}


# ---------------------------------------------------------------- site


def test_site_valid_without_hydrogens_matches_hand_oracle():
    parent = EXPECTED["parents"]["no_h"]
    result = check_site(_inspection("no_h"), [12, 11])
    assert result["valid"] is True and result["reason"] is None
    assert result["site_atoms"] == parent["site_methoxy"]
    assert result["core_atoms"] == parent["core_retained_parent_atoms"]
    a, b, order = parent["crossing_bond"]
    assert result["crossing_bonds"] == [{"core_atom": a, "site_atom": b, "order": order}]
    assert result["site_hydrogens"] == []
    assert result["retained_parent_atoms"] == parent["core_retained_parent_atoms"]


def test_site_valid_with_explicit_hydrogens_keeps_sdf_serials_with_gaps():
    parent = EXPECTED["parents"]["explicit_h"]
    result = check_site(_inspection("explicit_h"), parent["site_methoxy"])
    assert result["valid"] is True
    # Heavy-atom core uses SDF serials with H positions skipped.
    assert result["core_atoms"] == parent["core_retained_parent_atoms"] == [1, 5, 6, 7, 9, 10, 12, 14, 15, 17]
    a, b, order = parent["crossing_bond"]
    assert result["crossing_bonds"] == [{"core_atom": a, "site_atom": b, "order": order}]
    # H on the site leave with the site; H on the core stay with the core (spec 4.1, 4.4).
    assert result["site_hydrogens"] == parent["site_hydrogens_removed_with_site"] == [21, 22, 23]
    core_h = sorted(set(parent["hydrogen_serials"]) - {21, 22, 23})
    assert result["retained_parent_atoms"] == sorted(parent["core_retained_parent_atoms"] + core_h)
    assert result["retained_parent_atoms"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18]


def test_site_empty():
    result = check_site(_inspection("no_h"), [])
    assert result["valid"] is False and result["reason"] == "site_empty"
    assert result["crossing_bonds"] is None and result["retained_parent_atoms"] is None


def test_site_atom_unknown_includes_hydrogen_serials_and_out_of_range():
    for site in ([13], [11, 99], [0]):
        result = check_site(_inspection("no_h"), site)
        assert result["reason"] == "site_atom_unknown"
    # H serials are not site atoms: the atom table is heavy atoms only.
    result = check_site(_inspection("explicit_h"), [19, 20, 21])
    assert result["valid"] is False and result["reason"] == "site_atom_unknown"
    assert result["unknown_atoms"] == [21]
    # The gap serial 2 (an H line) on the explicit-H parent is also unknown.
    assert check_site(_inspection("explicit_h"), [2])["reason"] == "site_atom_unknown"


def test_site_core_empty():
    result = check_site(_inspection("no_h"), list(range(1, 13)))
    assert result["valid"] is False and result["reason"] == "core_empty"
    assert result["crossing_bonds"] is None


def test_site_crossing_bond_count_two_and_zero_cases():
    # Ring atom 6 alone is bonded to 5 and 7: two crossing bonds.
    result = check_site(_inspection("no_h"), [6])
    assert result["reason"] == "crossing_bond_count"
    assert [(x["core_atom"], x["site_atom"]) for x in result["crossing_bonds"]] == [(5, 6), (7, 6)]
    # Methoxy O + ring C8: crossing 7-8, 9-8 (aromatic, count failure takes precedence).
    assert check_site(_inspection("no_h"), [8, 11, 12])["reason"] == "crossing_bond_count"
    # Zero crossing bonds needs a disconnected stored graph; the check still reports it by count.
    graph = _inspection("no_h")
    graph["bonds"] = [b for b in graph["bonds"] if (b["a"], b["b"]) != (8, 11)]
    for atom in graph["atoms"]:
        atom["neighbors"] = [n for n in atom["neighbors"] if {atom["serial"], n} != {8, 11}]
    result = check_site(graph, [11, 12])
    assert result["reason"] == "crossing_bond_count" and result["crossing_bonds"] == []


def test_site_crossing_bond_not_single_for_double_and_aromatic():
    # Carbonyl O3 attaches by a double bond.
    result = check_site(_inspection("no_h"), [3])
    assert result["reason"] == "crossing_bond_not_single"
    assert result["crossing_bonds"] == [{"core_atom": 2, "site_atom": 3, "order": "double"}]
    assert result["retained_parent_atoms"] is None
    # Whole ring + methoxy on one side vs acetamide: crossing N4-C5 is single -> valid.
    assert check_site(_inspection("no_h"), [5, 6, 7, 8, 9, 10, 11, 12])["valid"] is True
    # Synthetic aromatic crossing bond.
    graph = _inspection("no_h")
    for bond in graph["bonds"]:
        if (bond["a"], bond["b"]) == (8, 11):
            bond["order"] = "aromatic"
    assert check_site(graph, [11, 12])["reason"] == "crossing_bond_not_single"


def test_site_reasons_are_the_closed_set():
    assert set(C.SITE_REASONS) == {"site_empty", "core_empty", "crossing_bond_count",
                                   "crossing_bond_not_single", "site_atom_unknown"}


@pytest.mark.parametrize("site", [[11, 11], [True], ["11"], [11.0], "11", None])
def test_site_rejects_malformed_request_as_typed_input_error(site):
    with pytest.raises(ToolFailure) as caught:
        check_site(_inspection("no_h"), site)
    assert caught.value.cls is FailureClass.input_invalid


@pytest.mark.parametrize("mutate", [
    lambda g: g["bonds"].append({"a": 1, "b": 99, "order": "single"}),
    lambda g: g["bonds"].append({"a": 1, "b": 2, "order": "single"}),
    lambda g: g["bonds"].__setitem__(0, {"a": 1, "b": 2, "order": "quadruple"}),
    lambda g: g["atoms"].append(dict(g["atoms"][0])),
    lambda g: g["hydrogens"].append({"serial": 1, "attached_to": 2}),
    lambda g: g["hydrogens"].append({"serial": 40, "attached_to": 99}),
    lambda g: g.pop("hydrogens"),
    lambda g: g["atoms"][0].__setitem__("neighbors", [2, 3]),
])
def test_site_rejects_malformed_inspection_graph(mutate):
    graph = _inspection("no_h")
    mutate(graph)
    with pytest.raises(ToolFailure) as caught:
        check_site(graph, [11, 12])
    assert caught.value.cls is FailureClass.input_invalid


# ---------------------------------------------------------------- filters


def _props(**over):
    base = {"mol_weight": 165.192, "crippen_logp": 1.6536, "hbd": 1, "hba": 3, "tpsa": 38.33,
            "rotatable_bonds": 2, "heavy_atoms": 12, "formal_charge": 0}
    return {**base, **over}


def _row(i, pains=(), **over):
    return {"id": f"c_{i:016x}", "smiles": f"C{i}", "origins": [{"rule_id": "fixed", "block_name": f"b{i}"}],
            "retained_parent_atoms": [1], "stereo_flag": "none", "properties": _props(**over),
            "pains": {"matches": [{"catalog": "PAINS_A", "name": n} for n in pains]}}


def test_filter_bounds_are_inclusive_at_min_and_max():
    spec = normalize_filter_spec({"ranges": {"mol_weight": {"min": 165.192, "max": 165.192}}})
    assert evaluate_row(_row(0), spec) == {"filters": {"mol_weight": True}, "passes_all": True}
    assert evaluate_row(_row(0, mol_weight=165.1919), spec)["filters"] == {"mol_weight": False}
    assert evaluate_row(_row(0, mol_weight=165.1921), spec)["passes_all"] is False
    only_min = normalize_filter_spec({"ranges": {"hbd": {"min": 1}}})
    assert evaluate_row(_row(0, hbd=1), only_min)["passes_all"] is True
    assert evaluate_row(_row(0, hbd=0), only_min)["passes_all"] is False
    only_max = normalize_filter_spec({"ranges": {"formal_charge": {"max": 0}}})
    assert evaluate_row(_row(0, formal_charge=0), only_max)["passes_all"] is True
    assert evaluate_row(_row(0, formal_charge=1), only_max)["passes_all"] is False


def test_no_active_filter_gives_null_passes_all():
    for spec in ({}, {"ranges": {}}, {"ranges": {}, "pains_exclude": False},
                 {"ranges": {"tpsa": {"min": None, "max": None}}}):
        assert evaluate_row(_row(0), normalize_filter_spec(spec)) == {"filters": {}, "passes_all": None}


def test_pains_exclude_and_combined_filters():
    spec = normalize_filter_spec({"ranges": {"tpsa": {"max": 50}}, "pains_exclude": True})
    assert evaluate_row(_row(0), spec) == {"filters": {"tpsa": True, "pains_exclude": True}, "passes_all": True}
    flagged = evaluate_row(_row(0, pains=["anil_di_alk_A(478)"]), spec)
    assert flagged == {"filters": {"tpsa": True, "pains_exclude": False}, "passes_all": False}
    assert evaluate_row(_row(0, tpsa=50.01), spec)["passes_all"] is False


@pytest.mark.parametrize("spec", [
    {"ranges": {"qed": {"min": 0}}},                       # unknown property
    {"ranges": {"mol_weight": {"min": 2, "max": 1}}},      # min > max
    {"ranges": {"mol_weight": {"low": 1}}},                # unknown bound key
    {"ranges": {"mol_weight": {"min": True}}},             # bool is not a number
    {"ranges": {"mol_weight": {"min": float("nan")}}},
    {"ranges": {"mol_weight": {"max": float("inf")}}},
    {"ranges": {"mol_weight": {"min": "1"}}},
    {"pains_exclude": 1},
    {"ranges": [], "pains_exclude": False},
    {"other": 1},
    [],
])
def test_filter_spec_rejects_invalid_input(spec):
    with pytest.raises(ToolFailure) as caught:
        normalize_filter_spec(spec)
    assert caught.value.cls is FailureClass.input_invalid


@pytest.mark.parametrize("bad", [None, "1", True, float("nan")])
def test_rows_with_missing_or_null_property_are_rejected(bad):
    row = _row(0)
    row["properties"]["hba"] = bad
    with pytest.raises(ToolFailure):
        evaluate_row(row, normalize_filter_spec({}))
    row = _row(0)
    del row["properties"]["tpsa"]
    with pytest.raises(ToolFailure):
        evaluate_row(row, normalize_filter_spec({}))


def test_query_sorts_pages_and_shows_passes_only():
    rows = [_row(0, mol_weight=300.0), _row(1, mol_weight=150.0, pains=["x"]), _row(2, mol_weight=200.0),
            _row(3, mol_weight=150.0)]
    spec = normalize_filter_spec({"ranges": {"mol_weight": {"min": 150, "max": 250}}})
    page = query_candidates(rows, spec, sort="mol_weight", direction="asc", offset=0, limit=10)
    assert [r["generation_order"] for r in page["rows"]] == [1, 3, 2, 0]   # ties keep generation order
    assert page["total"] == 4 and page["passing"] == 3 and page["hidden_by_filter"] == 0
    assert page["filter_pass_counts"] == {"mol_weight": 3}
    assert page["rows"][0]["candidate"] is rows[1] and page["rows"][3]["passes_all"] is False
    desc = query_candidates(rows, spec, sort="mol_weight", direction="desc", offset=0, limit=10)
    assert [r["generation_order"] for r in desc["rows"]] == [0, 2, 1, 3]
    only = query_candidates(rows, spec, sort="generation_order", direction="desc", offset=1, limit=1,
                            passes_only=True)
    assert only["matched"] == 3 and only["hidden_by_filter"] == 1
    assert [r["generation_order"] for r in only["rows"]] == [2]
    default = query_candidates(rows, normalize_filter_spec({}), offset=2, limit=5)
    assert default["sort"] == "generation_order" and default["direction"] == "asc"
    assert [r["generation_order"] for r in default["rows"]] == [2, 3]
    assert default["passing"] is None and default["filter_pass_counts"] == {}
    # passes_only with no active filter hides nothing (there is no filter to pass).
    assert query_candidates(rows, normalize_filter_spec({}), passes_only=True)["matched"] == 4
    beyond = query_candidates(rows, spec, offset=10, limit=5)
    assert beyond["rows"] == [] and beyond["matched"] == 4
    pains = query_candidates(rows, normalize_filter_spec({"pains_exclude": True}), passes_only=True)
    assert [r["generation_order"] for r in pains["rows"]] == [0, 2, 3]


@pytest.mark.parametrize("kwargs", [
    {"sort": "qed"}, {"direction": "up"}, {"offset": -1}, {"limit": 0}, {"limit": 1001},
    {"offset": True}, {"limit": 1.5}, {"passes_only": "yes"},
])
def test_query_rejects_invalid_arguments(kwargs):
    with pytest.raises(ToolFailure) as caught:
        query_candidates([_row(0)], normalize_filter_spec({}), **kwargs)
    assert caught.value.cls is FailureClass.input_invalid


def test_sort_keys_and_property_names_are_the_closed_set():
    assert C.PROPERTY_NAMES == ("mol_weight", "crippen_logp", "hbd", "hba", "tpsa", "rotatable_bonds",
                                "heavy_atoms", "formal_charge")
    assert C.SORT_KEYS == ("generation_order", *C.PROPERTY_NAMES)
    assert C.STEREO_FLAGS == ("none", "parent_stereo_lost", "new_unspecified_center")
    assert len(C.LIMITATIONS) == 5 and C.LIMITATIONS[0].startswith("속성값은 RDKit 추정값")


# ---------------------------------------------------------------- isolation


@pytest.mark.parametrize("name", ["ligand_constants.py", "ligand_inputs.py", "ligand_site.py",
                                  "ligand_filters.py", "chemical_inputs.py"])
def test_server_modules_do_not_import_rdkit(name):
    tree = ast.parse((MW / name).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(module == "rdkit" or module.startswith("rdkit.") for module in imported)
    assert "__import__" not in (MW / name).read_text() and "importlib" not in (MW / name).read_text()


def test_importing_server_modules_does_not_load_rdkit():
    import subprocess
    import sys
    code = ("import sys; import mw.ligand_inputs, mw.ligand_site, mw.ligand_filters, mw.chemical_inputs, "
            "mw.api.app; print(any(m == 'rdkit' or m.startswith('rdkit.') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
