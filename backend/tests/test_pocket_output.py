"""M12 fpocket 4.2.3 output parser, result classification and native output evidence.

Fixtures under ``fixtures/pockets/synthetic-*`` are SYNTHETIC (hand-built in the fpocket
writer format, see SYNTHETIC-PROVENANCE.md); they are never engine output. The real-engine
tests run the pinned installed fpocket with the fixed spec argv on projections produced by
``mw.pocket_input.project`` and must fail (not skip) when the engine is absent. They assert no
specific pocket count or descriptor value.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from mw.pocket_output import (
    DETECTOR_SPECIFIC_NOTE,
    DISPLAY_CENTER_METHOD,
    PARSER_VERSION,
    PocketOutputFailure,
    classify,
    display_center,
    native_output_evidence,
)

FIXTURES = Path(__file__).parent / "fixtures"
POCKETS = FIXTURES / "pockets"
REPO = Path(__file__).resolve().parents[2]
FPOCKET = REPO / ".deps" / "fpocket" / "env" / "bin" / "fpocket"
# Fixed argv from spec §5 (the executable path is prepended at run time).
ARGV = ["-f", "protein.pdb", "-m", "3.4", "-M", "6.2", "-D", "2.4", "-C", "s", "-e", "e", "-i", "15", "-p", "0.0",
        "--number_apol_asph_pocket", "3", "-v", "300", "-w", "p"]
BANNER = b"***** POCKET HUNTING BEGINS ***** \n***** POCKET HUNTING ENDS ***** \n"
EMPTY_STDERR = b"! No Pockets Found while refining\n! No pocket to reindex.\n! No pocket to reindex.\n"
READ_FILES = {"protein_info.txt", "protein_pockets.pqr"}
MiB = 1024 * 1024


# ----------------------------------------------------------------- helpers
def _copy(tmp_path: Path, name: str) -> Path:
    root = tmp_path / "job"
    shutil.copytree(POCKETS / name / "protein_out", root / "protein_out")
    (root / "protein_out" / "pockets").mkdir(exist_ok=True)
    return root


def _streams(name: str) -> tuple[bytes, bytes]:
    return (POCKETS / name / "stdout.bin").read_bytes(), (POCKETS / name / "stderr.bin").read_bytes()


def _atoms() -> list[dict]:
    return json.loads((POCKETS / "synthetic-valid" / "transport_atoms.json").read_text())


def _run(root: Path, atoms=None, fixture: str = "synthetic-valid", **overrides):
    stdout, stderr = _streams(fixture)
    kwargs = {"exit_code": 0, "stdout": stdout, "stderr": stderr, "killed": False, **overrides}
    return classify(root, _atoms() if atoms is None else atoms, **kwargs)


def _fails(root: Path, cls: str, code: str, fixture: str = "synthetic-valid", **overrides) -> PocketOutputFailure:
    with pytest.raises(PocketOutputFailure) as caught:
        _run(root, fixture=fixture, **overrides)
    assert (caught.value.failure_class, caught.value.reason_code) == (cls, code), caught.value.message
    return caught.value


def _edit(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text()
    assert text.count(old) >= count, old
    path.write_text(text.replace(old, new, count))


def _independent_pqr(path: Path) -> list[dict]:
    """Fixed-column PQR reader independent of the module (x,y,z %8.3f at 30/38/46, radius %6.2f at 65)."""
    out = []
    for line in path.read_text().splitlines():
        if line.startswith("ATOM"):
            out.append({"x_A": float(line[30:38]), "y_A": float(line[38:46]), "z_A": float(line[46:54]),
                        "radius_A": float(line[65:71]), "resid": int(line[22:26])})
    return out


def _independent_atm(path: Path) -> list[tuple]:
    out = []
    for line in path.read_text().splitlines():
        if line.startswith("ATOM"):
            out.append(((line[21], int(line[22:26]), line[12:16].strip(), line[76:78].strip()),
                        [float(line[30:38]), float(line[38:46]), float(line[46:54])]))
    return out


# ----------------------------------------------------------------- synthetic success
def test_synthetic_valid_output_parses_every_pocket(tmp_path: Path) -> None:
    root = _copy(tmp_path, "synthetic-valid")
    result, _native = _run(root)
    assert result["classification"] == "success" and result["null_result"] is False
    assert result["parser_version"] == PARSER_VERSION == "fpocket_4_2_3_output@1"
    assert result["total_count"] == 2 and [p["rank"] for p in result["pockets"]] == [1, 2]
    first, second = result["pockets"]
    d = first["descriptors"]
    assert d["score"] == {"native_name": "Score", "native_text": "0.412", "value": 0.412, "unit": "dimensionless"}
    assert d["druggability_score"] == {"native_name": "Druggability Score", "native_text": "0.037", "value": 0.037,
                                       "unit": "dimensionless", "detector_specific_note": DETECTOR_SPECIFIC_NOTE}
    assert d["alpha_sphere_count"] == {"native_name": "Number of Alpha Spheres", "native_text": "3", "value": 3,
                                       "unit": "count"}
    assert d["total_sasa_A2"]["native_name"] == "Total SASA" and d["total_sasa_A2"]["unit"] == "A2"
    assert d["total_sasa_A2"]["value"] == 112.345
    assert d["volume_A3"] == {"native_name": "Volume", "native_text": "402.118", "value": 402.118, "unit": "A3"}
    assert "fpocket" in DETECTOR_SPECIFIC_NOTE
    # The other 14 native fields are opaque strings in native order, verbatim (no units guessed).
    assert list(first["native_fields"]) == [
        "Polar SASA", "Apolar SASA", "Mean local hydrophobic density", "Mean alpha sphere radius",
        "Mean alp. sph. solvent access", "Apolar alpha sphere proportion", "Hydrophobicity score", "Volume score",
        "Polarity score", "Charge score", "Proportion of polar atoms", "Alpha sphere density",
        "Cent. of mass - Alpha Sphere max dist", "Flexibility"]
    assert first["native_fields"]["Charge score"] == "-1" and first["native_fields"]["Volume score"] == "3.000"
    assert second["native_fields"]["Flexibility"] == "nan"
    # Spheres come from the PQR in file order; radius is the PQR radius column, not a B-factor.
    assert first["spheres"] == [{"x_A": 12.5, "y_A": 10.5, "z_A": 12.0, "radius_A": 3.62},
                                {"x_A": 12.0, "y_A": 11.0, "z_A": 13.1, "radius_A": 4.05},
                                {"x_A": 13.2, "y_A": 9.8, "z_A": 12.4, "radius_A": 5.01}]
    # Lining atoms: unique per transport atom (first native occurrence), native record count preserved.
    atoms = _atoms()
    assert first["lining_atoms"]["transport_indices"] == [1, 4, 5]
    assert first["lining_atoms"]["native_record_count"] == 4
    assert first["lining_atoms"]["atoms"] == [atoms[i]["ref"] for i in (1, 4, 5)]
    assert first["lining_residues"] == [atoms[1]["ref"]["residue"], atoms[5]["ref"]["residue"]]
    assert first["lining_residues"][1]["resname"] == "HID"  # original name, not the transport HIS
    assert second["lining_atoms"]["transport_indices"] == [7, 8]
    assert second["lining_residues"][0]["chain_label"] is None
    for pocket in result["pockets"]:
        spheres = pocket["spheres"]
        expected = {axis: math.fsum(s[axis] for s in spheres) / len(spheres) for axis in ("x_A", "y_A", "z_A")}
        assert pocket["display_center"] == {**expected, "method": DISPLAY_CENTER_METHOD}
    assert DISPLAY_CENTER_METHOD == "arithmetic_mean_of_stored_sphere_centers"
    read = {"protein_info.txt", "protein_pockets.pqr", "pockets/pocket1_vert.pqr", "pockets/pocket1_atm.pdb",
            "pockets/pocket2_vert.pqr", "pockets/pocket2_atm.pdb"}
    out = root / "protein_out"
    assert result["raw_file_hashes"] == {p: hashlib.sha256((out / p).read_bytes()).hexdigest() for p in sorted(read)}
    joined = " ".join(result["limitations"])
    assert "normalised" in joined and "same execution" in joined
    assert "not binding-site, affinity or druggability evidence" in joined
    assert "Monte Carlo" in joined
    assert result["units"]["volume_A3"] == "A3" and result["total_sphere_count"] == 5


def test_display_center_is_plain_mean_and_rejects_empty() -> None:
    center = display_center([{"x_A": 0.0, "y_A": 1.0, "z_A": 2.0, "radius_A": 4.0},
                             {"x_A": 2.0, "y_A": 3.0, "z_A": -2.0, "radius_A": 3.5}])
    assert center == {"x_A": 1.0, "y_A": 2.0, "z_A": 0.0, "method": "arithmetic_mean_of_stored_sphere_centers"}
    with pytest.raises(ValueError):
        display_center([])


def test_native_output_evidence_keeps_bytes_only_for_read_files(tmp_path: Path) -> None:
    root = _copy(tmp_path, "synthetic-valid")
    stdout, stderr = _streams("synthetic-valid")
    result, native = _run(root)
    evidence = native_output_evidence(native, stdout, stderr)
    out = root / "protein_out"
    files = {entry["path"]: entry for entry in evidence["files"]}
    all_files = {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()}
    assert set(files) == all_files
    retained = 0
    for path, entry in files.items():
        raw = (out / path).read_bytes()
        assert entry["size"] == len(raw) and entry["sha256"] == hashlib.sha256(raw).hexdigest()
        if path in READ_FILES or path.startswith("pockets/"):
            assert entry["retained"] is True and base64.b64decode(entry["content_b64"]) == raw
            retained += len(raw)
        else:
            assert entry["retained"] is False and "content_b64" not in entry
    assert base64.b64decode(evidence["stdout"]["content_b64"]) == stdout
    assert evidence["stderr"]["size"] == 0
    assert evidence["retained_bytes"] == retained + len(stdout) + len(stderr)
    assert evidence["parser_version"] == PARSER_VERSION
    assert "protein_out.pdb" not in json.dumps({k: v for k, v in files.items() if v["retained"]})
    assert result["raw_file_hashes"] == {p: files[p]["sha256"] for p in result["raw_file_hashes"]}


def test_synthetic_supported_empty_is_scientific_null(tmp_path: Path) -> None:
    root = _copy(tmp_path, "synthetic-empty")
    result, native = _run(root, fixture="synthetic-empty")
    assert result["classification"] == "scientific_null" and result["null_result"] is True
    assert result["total_count"] == 0 and result["pockets"] == [] and result["total_sphere_count"] == 0
    assert result["empty_diagnostics"] == ["! No Pockets Found while refining", "! No pocket to reindex.",
                                           "! No pocket to reindex."]
    evidence = native_output_evidence(native, *_streams("synthetic-empty"))
    assert {e["path"] for e in evidence["files"] if e["retained"]} == READ_FILES


# ----------------------------------------------------------------- synthetic failures
def _rm(rel: str):
    def mutate(root: Path) -> None:
        target = root / "protein_out" / rel
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    return mutate


def _rename_rank2_to(rank: int):
    def mutate(root: Path) -> None:
        out = root / "protein_out"
        _edit(out / "protein_info.txt", "Pocket 2 :", f"Pocket {rank} :")
        if rank != 1:
            for suffix in ("vert.pqr", "atm.pdb"):
                (out / "pockets" / f"pocket2_{suffix}").rename(out / "pockets" / f"pocket{rank}_{suffix}")
    return mutate


def _replace(rel: str, old: str, new: str, count: int = 1):
    return lambda root: _edit(root / "protein_out" / rel, old, new, count)


def _write(rel: str, data: bytes):
    def mutate(root: Path) -> None:
        path = root / "protein_out" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return mutate


def _symlink_outside(rel: str):
    def mutate(root: Path) -> None:
        target = root.parent / "outside.txt"
        target.write_bytes((root / "protein_out" / rel).read_bytes())
        (root / "protein_out" / rel).unlink()
        os.symlink(target, root / "protein_out" / rel)
    return mutate


def _symlink_inside(root: Path) -> None:
    out = root / "protein_out"
    (out / "protein.tcl").unlink()
    os.symlink(out / "protein.pml", out / "protein.tcl")


def _hardlink_outside(root: Path) -> None:
    os.link(root / "protein_out" / "protein_out.pdb", root.parent / "escape.pdb")


def _symlink_outdir(root: Path) -> None:
    (root / "protein_out").rename(root / "real_out")
    os.symlink(root / "real_out", root / "protein_out")


def _fifo(root: Path) -> None:
    (root / "protein_out" / "protein.tcl").unlink()
    os.mkfifo(root / "protein_out" / "protein.tcl")


def _extra_rank_files(root: Path) -> None:
    pockets = root / "protein_out" / "pockets"
    shutil.copy(pockets / "pocket2_vert.pqr", pockets / "pocket3_vert.pqr")
    shutil.copy(pockets / "pocket2_atm.pdb", pockets / "pocket3_atm.pdb")


FAILURES = {
    "missing_outdir": (_rm(""), "fatal", "missing_output_directory"),
    "missing_info": (_rm("protein_info.txt"), "fatal", "missing_output_file"),
    "missing_all_pqr": (_rm("protein_pockets.pqr"), "fatal", "missing_output_file"),
    "missing_unread_known_file": (_rm("protein_PYMOL.sh"), "fatal", "missing_output_file"),
    "missing_pockets_dir": (_rm("pockets"), "fatal", "missing_output_file"),
    "partial_rank_files": (_rm("pockets/pocket2_atm.pdb"), "fatal", "missing_pocket_file"),
    "extra_rank_files": (_extra_rank_files, "fatal", "unexpected_pocket_file"),
    "duplicate_rank": (_rename_rank2_to(1), "fatal", "duplicate_rank"),
    "rank_gap": (_rename_rank2_to(3), "fatal", "rank_sequence"),
    "malformed_pqr_record": (_replace("pockets/pocket1_vert.pqr", "    0.00     3.62", "    0.00    3.62"),
                             "fatal", "malformed_record"),
    "malformed_pqr_structure": (_replace("pockets/pocket1_vert.pqr", "TER\nEND\n", "END\n"),
                                "fatal", "malformed_record"),
    "pqr_nonzero_charge": (_replace("pockets/pocket1_vert.pqr", "    0.00     3.62", "    1.00     3.62"),
                           "fatal", "malformed_record"),
    "malformed_atm_record": (_replace("pockets/pocket1_atm.pdb", "           C 0\n", "          C 0\n"),
                             "fatal", "malformed_record"),
    "malformed_info_value": (_replace("protein_info.txt", "\tScore : \t0.412", "\tScore : \t0.41"),
                             "fatal", "malformed_field"),
    "malformed_info_separator": (_replace("protein_info.txt", "\tVolume : \t402.118", "\tVolume :\t402.118"),
                                 "fatal", "malformed_field"),
    "non_ascii_info": (_replace("protein_info.txt", "Pocket 1 :", "Pocket 1 é:"), "fatal", "malformed_file"),
    "info_missing_trailing_blank": (_write("protein_info.txt", b"Pocket 1 :\n"), "fatal", "missing_field"),
    "nonfinite_sphere_coordinate": (_replace("pockets/pocket1_vert.pqr", "  12.500  10.500", "     nan  10.500"),
                                    "fatal", "nonfinite_coordinate"),
    "nonfinite_atm_coordinate": (_replace("pockets/pocket1_atm.pdb", "  11.988", "    -inf"),
                                 "fatal", "nonfinite_coordinate"),
    "nonfinite_descriptor": (_replace("protein_info.txt", "\tTotal SASA : \t112.345", "\tTotal SASA : \tnan"),
                             "fatal", "nonfinite_descriptor"),
    "radius_out_of_range": (_replace("pockets/pocket1_vert.pqr", "     5.01", "     7.50"),
                            "fatal", "sphere_radius_out_of_range"),
    "unknown_field": (_replace("protein_info.txt", "\tFlexibility : \t0.250", "\tFlexibility : \t0.250\n\tMystery : \t1.0"),
                      "fatal", "unknown_field"),
    "duplicate_field": (_replace("protein_info.txt", "\tFlexibility : \t0.250",
                                 "\tFlexibility : \t0.250\n\tFlexibility : \t0.250"), "fatal", "duplicate_field"),
    "missing_field": (_replace("protein_info.txt", "\tFlexibility : \t0.250\n", ""), "fatal", "missing_field"),
    "count_mismatch": (_replace("protein_info.txt", "\tNumber of Alpha Spheres : \t3", "\tNumber of Alpha Spheres : \t4"),
                       "fatal", "sphere_count_mismatch"),
    "all_pockets_pqr_mismatch": (_replace("protein_pockets.pqr", "  13.200", "  13.201"),
                                 "fatal", "pocket_sphere_mismatch"),
    "all_pockets_pqr_extra_resid": (_replace("protein_pockets.pqr", "STP     2", "STP     3"),
                                    "fatal", "pocket_sphere_mismatch"),
    "zero_alpha_spheres": (_replace("protein_info.txt", "\tNumber of Alpha Spheres : \t2", "\tNumber of Alpha Spheres : \t0"),
                           "fatal", "empty_pocket"),
    "vert_file_without_atoms": (_write("pockets/pocket2_vert.pqr", b"HEADER\nTER\nEND\n"), "fatal", "empty_pocket"),
    "atm_file_without_atoms": (_write("pockets/pocket2_atm.pdb", b"HEADER\nTER\nEND\n"), "fatal", "empty_pocket"),
    "unmapped_lining_atom": (_replace("pockets/pocket2_atm.pdb", "GLY B   3", "GLY B   9"),
                             "fatal", "unmapped_lining_atom"),
    "lining_element_mismatch": (_replace("pockets/pocket2_atm.pdb", "           N 0", "           O 0"),
                                "fatal", "unmapped_lining_atom"),
    "lining_resname_mismatch": (_replace("pockets/pocket2_atm.pdb", "GLY B   3", "ALA B   3", 2),
                                "fatal", "lining_atom_mismatch"),
    "lining_coordinate_mismatch": (_replace("pockets/pocket2_atm.pdb", "  -5.250", "  -5.252"),
                                   "fatal", "lining_atom_coordinate_mismatch"),
    "unexpected_file": (_write("notes.txt", b"x"), "fatal", "unexpected_output_file"),
    "unexpected_pocket_name": (_write("pockets/pocket1_atm.cif", b"x"), "fatal", "unexpected_output_file"),
    "recursive_directory": (_write("pockets/sub/pocket1_atm.pdb", b"x"), "fatal", "unexpected_directory"),
    "top_level_directory": (_write("extra/x", b"x"), "fatal", "unexpected_directory"),
    "symlink_escape": (_symlink_outside("protein_info.txt"), "fatal", "link_rejected"),
    "symlink_pocket_file": (_symlink_outside("pockets/pocket1_vert.pqr"), "fatal", "link_rejected"),
    "symlink_inside": (_symlink_inside, "fatal", "link_rejected"),
    "symlink_outdir": (_symlink_outdir, "fatal", "link_rejected"),
    "hardlink_escape": (_hardlink_outside, "fatal", "hardlink_rejected"),
    "special_file": (_fifo, "fatal", "special_file"),
}


@pytest.mark.parametrize("case", sorted(FAILURES))
def test_synthetic_malformed_outputs_fail(tmp_path: Path, case: str) -> None:
    mutate, cls, code = FAILURES[case]
    root = _copy(tmp_path, "synthetic-valid")
    mutate(root)
    _fails(root, cls, code)


def test_process_outcomes_fail_before_reading(tmp_path: Path) -> None:
    root = _copy(tmp_path, "synthetic-valid")
    _fails(root, "fatal", "nonzero_exit", exit_code=1)
    _fails(root, "fatal", "engine_killed", exit_code=-9)
    _fails(root, "fatal", "engine_killed", killed=True)
    _fails(root, "fatal", "engine_killed", exit_code=None)
    empty = _copy(tmp_path / "e", "synthetic-empty")
    _fails(empty, "fatal", "nonzero_exit", fixture="synthetic-empty", exit_code=2)
    _fails(empty, "fatal", "engine_killed", fixture="synthetic-empty", killed=True)


def _pocket_block(rank: int, spheres: int) -> str:
    values = ["0.100", "0.000", str(spheres), *["1.000"] * 9, " 1.000", " 1", " 0", *["1.000"] * 4]
    prefixes = ["\tScore : \t", "\tDruggability Score : \t", "\tNumber of Alpha Spheres : \t", "\tTotal SASA : \t",
                "\tPolar SASA : \t", "\tApolar SASA : \t", "\tVolume : \t", "\tMean local hydrophobic density : \t",
                "\tMean alpha sphere radius :\t", "\tMean alp. sph. solvent access : \t",
                "\tApolar alpha sphere proportion : \t", "\tHydrophobicity score:\t", "\tVolume score: \t",
                "\tPolarity score:\t", "\tCharge score :\t", "\tProportion of polar atoms: \t",
                "\tAlpha sphere density : \t", "\tCent. of mass - Alpha Sphere max dist: \t", "\tFlexibility : \t"]
    return f"Pocket {rank} :\n" + "".join(p + v + "\n" for p, v in zip(prefixes, values, strict=True)) + "\n"


def test_block_helper_matches_fixture_format() -> None:
    text = (POCKETS / "synthetic-valid" / "protein_out" / "protein_info.txt").read_text()
    shape = lambda block: [line.split("\t")[1] if "\t" in line else line for line in block.splitlines()]
    assert shape(_pocket_block(1, 3))[1:20] == shape(text.split("\n\n")[0])[1:20]


def test_resource_caps_are_resource_exceeded(tmp_path: Path) -> None:
    root = _copy(tmp_path / "stdout", "synthetic-valid")
    _fails(root, "resource_exceeded", "stdout_limit", stdout=b"x" * (MiB + 1))
    _fails(root, "resource_exceeded", "stderr_limit", stderr=b"x" * (MiB + 1))
    # Streams are capped even when the process failed.
    _fails(root, "resource_exceeded", "stdout_limit", stdout=b"x" * (MiB + 1), exit_code=1)

    big = _copy(tmp_path / "bytes", "synthetic-valid")
    with open(big / "protein_out" / "protein_out.pdb", "r+b") as handle:  # sparse: size is what counts
        handle.truncate(30 * MiB + 1)
    _fails(big, "resource_exceeded", "output_bytes_limit")

    many = _copy(tmp_path / "files", "synthetic-valid")
    for i in range(3, 3 + 1000):
        (many / "protein_out" / "pockets" / f"pocket{i}_vert.pqr").write_bytes(b"")
    _fails(many, "resource_exceeded", "output_file_limit")

    pockets = _copy(tmp_path / "pockets", "synthetic-valid")
    (pockets / "protein_out" / "protein_info.txt").write_text("".join(_pocket_block(r, 20) for r in range(1, 202)))
    _fails(pockets, "resource_exceeded", "pocket_count_limit")

    spheres = _copy(tmp_path / "spheres", "synthetic-valid")
    (spheres / "protein_out" / "protein_info.txt").write_text(_pocket_block(1, 30000) + _pocket_block(2, 20001))
    _fails(spheres, "resource_exceeded", "sphere_count_limit")


def test_exactly_at_caps_is_not_resource_exceeded(tmp_path: Path) -> None:
    root = _copy(tmp_path, "synthetic-valid")
    result, _ = _run(root, stdout=b"x" * MiB, stderr=b"y" * MiB)
    assert result["classification"] == "success"
    pockets = _copy(tmp_path / "p", "synthetic-valid")
    (pockets / "protein_out" / "protein_info.txt").write_text("".join(_pocket_block(r, 250) for r in range(1, 201)))
    # 200 pockets / 50000 spheres are within the caps; the parse then fails on the missing rank files.
    _fails(pockets, "fatal", "missing_pocket_file")


def _empty_variant(mutate, **overrides):
    return mutate, overrides


EMPTY_VARIANTS = {
    "legacy_no_pockets_text": (_write("protein_info.txt", b"No pockets found\n"), {}),
    "no_diagnostic": (lambda root: None, {"stderr": b""}),
    "arbitrary_empty_streams": (lambda root: None, {"stdout": b"", "stderr": b""}),
    "diagnostic_on_stdout_only": (lambda root: None, {"stdout": BANNER + EMPTY_STDERR, "stderr": b""}),
    "only_refining_diagnostic": (lambda root: None, {"stderr": b"! No Pockets Found while refining\n"}),
    "only_reindex_diagnostic": (lambda root: None, {"stderr": b"! No pocket to reindex.\n"}),
    "extra_stderr_line": (lambda root: None, {"stderr": EMPTY_STDERR + b"! Empty Pocket...something might be wrong\n"}),
    # src/refine.c: dropSmallNpolarPockets prints the refining line once, then two reIndexPockets calls
    # print one reindex line each. Any other count or order is an unreviewed form.
    "reordered_diagnostics": (lambda root: None, {"stderr": b"! No pocket to reindex.\n! No Pockets Found while "
                                                            b"refining\n! No pocket to reindex.\n"}),
    "duplicated_refining_line": (lambda root: None, {"stderr": b"! No Pockets Found while refining\n" + EMPTY_STDERR}),
    "one_reindex_line": (lambda root: None, {"stderr": b"! No Pockets Found while refining\n! No pocket to reindex.\n"}),
    "three_reindex_lines": (lambda root: None, {"stderr": EMPTY_STDERR + b"! No pocket to reindex.\n"}),
    "empty_before_refining_path": (lambda root: None, {"stderr": b"! No pocket to reindex.\n" * 3}),
    "stderr_missing_final_newline": (lambda root: None, {"stderr": EMPTY_STDERR[:-1]}),
    "stdout_not_banner": (lambda root: None, {"stdout": b"***** POCKET HUNTING BEGINS ***** \n"}),
    "pqr_with_atom_record": (_write("protein_pockets.pqr", b"HEADER\nATOM      1    C STP     1      12.500  10.500  "
                                                          b"12.000    0.00     3.62\nTER\nEND\n"), {}),
    "pqr_zero_bytes": (_write("protein_pockets.pqr", b""), {}),
    "pqr_without_end": (_write("protein_pockets.pqr", b"HEADER\nTER\n"), {}),
    "pocket_files_present": (_write("pockets/pocket1_vert.pqr", b"HEADER\nTER\nEND\n"), {}),
    "info_whitespace_only": (_write("protein_info.txt", b"\n"), {}),
    "info_is_symlink": (_symlink_outside("protein_info.txt"), {}),
    "missing_script": (_rm("protein_VMD.sh"), {}),
    "nonzero_exit": (lambda root: None, {"exit_code": 1}),
}


@pytest.mark.parametrize("case", sorted(EMPTY_VARIANTS))
def test_unsupported_empty_variants_fail_not_null(tmp_path: Path, case: str) -> None:
    mutate, overrides = EMPTY_VARIANTS[case]
    root = _copy(tmp_path, "synthetic-empty")
    mutate(root)
    with pytest.raises(PocketOutputFailure) as caught:
        _run(root, fixture="synthetic-empty", **overrides)
    assert caught.value.failure_class == "fatal"


def test_duplicate_transport_key_is_rejected(tmp_path: Path) -> None:
    root = _copy(tmp_path, "synthetic-valid")
    atoms = _atoms()
    atoms.append({**atoms[1], "transport_index": len(atoms)})
    with pytest.raises(PocketOutputFailure) as caught:
        _run(root, atoms=atoms)
    assert caught.value.reason_code == "transport_key_not_unique"


# ----------------------------------------------------------------- real engine
def _execute(tmp_path: Path, pdb_bytes: bytes) -> tuple[Path, subprocess.CompletedProcess]:
    assert FPOCKET.is_file(), f"pinned fpocket missing at {FPOCKET}; run scripts/setup_fpocket.py (no skip)"
    root = tmp_path / "job"
    private_tmp = tmp_path / "private_tmp"
    root.mkdir()
    private_tmp.mkdir()
    (root / "protein.pdb").write_bytes(pdb_bytes)
    env = {"TMPDIR": str(private_tmp), "PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    done = subprocess.run([str(FPOCKET), *ARGV], cwd=root, env=env, capture_output=True, timeout=120, check=False)
    return root, done


def _project(tmp_path: Path, raw: bytes) -> dict:
    from test_pockets import _load

    from mw.pocket_input import project

    run, _, prepared = _load(tmp_path / "runs", raw, "cif")
    return project(run.store, prepared)


def test_real_engine_1hsg_output_is_fully_parsed_and_mapped(tmp_path: Path) -> None:
    projection = _project(tmp_path, (FIXTURES / "public_1hsg.cif").read_bytes())
    root, done = _execute(tmp_path, projection["pdb_bytes"])
    assert done.returncode == 0, done.stderr
    result, native = classify(root, projection["atoms"], exit_code=done.returncode, stdout=done.stdout,
                              stderr=done.stderr, killed=False)
    out = root / "protein_out"
    assert result["classification"] == "success" and result["total_count"] >= 1
    blocks = [line for line in (out / "protein_info.txt").read_text().splitlines() if line.startswith("Pocket ")]
    assert [p["rank"] for p in result["pockets"]] == list(range(1, len(blocks) + 1))
    assert sorted(p.name for p in (out / "pockets").iterdir()) == sorted(
        f"pocket{r}_{s}" for r in range(1, len(blocks) + 1) for s in ("atm.pdb", "vert.pqr"))
    by_key = {(a["synthetic_chain"], a["synthetic_resseq"], a["atom_name"], a["element"]): a
              for a in projection["atoms"]}
    all_spheres = _independent_pqr(out / "protein_pockets.pqr")
    assert result["total_sphere_count"] == len(all_spheres)
    for pocket in result["pockets"]:
        rank = pocket["rank"]
        spheres = _independent_pqr(out / "pockets" / f"pocket{rank}_vert.pqr")
        assert len(pocket["spheres"]) == len(spheres) == pocket["descriptors"]["alpha_sphere_count"]["value"]
        assert pocket["spheres"] == [{k: s[k] for k in ("x_A", "y_A", "z_A", "radius_A")} for s in spheres]
        assert all(3.4 - 0.005 <= s["radius_A"] <= 6.2 + 0.005 for s in spheres)
        assert sorted((s["x_A"], s["y_A"], s["z_A"], s["radius_A"]) for s in spheres) == sorted(
            (s["x_A"], s["y_A"], s["z_A"], s["radius_A"]) for s in all_spheres if s["resid"] == rank)
        center = {axis: math.fsum(s[axis] for s in spheres) / len(spheres) for axis in ("x_A", "y_A", "z_A")}
        assert pocket["display_center"] == {**center, "method": "arithmetic_mean_of_stored_sphere_centers"}
        records = _independent_atm(out / "pockets" / f"pocket{rank}_atm.pdb")
        assert pocket["lining_atoms"]["native_record_count"] == len(records) >= 1
        unique = []
        for key, xyz in records:
            atom = by_key[key]
            assert all(abs(a - b) <= 0.0005 + 1e-9 for a, b in zip(xyz, atom["projected_coordinate_A"]))
            if atom["transport_index"] not in unique:
                unique.append(atom["transport_index"])
        assert pocket["lining_atoms"]["transport_indices"] == unique
        assert pocket["lining_atoms"]["atoms"] == [projection["atoms"][i]["ref"] for i in unique]
        for key in ("score", "druggability_score", "alpha_sphere_count", "total_sasa_A2", "volume_A3"):
            descriptor = pocket["descriptors"][key]
            assert math.isfinite(descriptor["value"]) and float(descriptor["native_text"]) == descriptor["value"]
    evidence = native_output_evidence(native, done.stdout, done.stderr)
    retained = {e["path"] for e in evidence["files"] if e["retained"]}
    assert retained == {"protein_info.txt", "protein_pockets.pqr",
                        *(f"pockets/pocket{r}_{s}" for r in range(1, len(blocks) + 1) for s in ("atm.pdb", "vert.pqr"))}
    for entry in evidence["files"]:
        raw = (out / entry["path"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
        assert ("content_b64" in entry) is entry["retained"]
    unread = sum((out / e["path"]).stat().st_size for e in evidence["files"] if not e["retained"])
    assert unread > 0  # protein_out.pdb etc. are hashed, not retained
    assert evidence["retained_bytes"] == sum(
        (out / p).stat().st_size for p in retained) + len(done.stdout) + len(done.stderr)


def test_real_engine_derived_small_fixture_empty_result(tmp_path: Path) -> None:
    from test_pockets import DERIVED

    projection = _project(tmp_path, DERIVED.read_bytes())
    assert len(projection["atoms"]) == 88
    root, done = _execute(tmp_path, projection["pdb_bytes"])
    assert done.returncode == 0, done.stderr
    result, native = classify(root, projection["atoms"], exit_code=done.returncode, stdout=done.stdout,
                              stderr=done.stderr, killed=False)
    if (root / "protein_out" / "protein_info.txt").stat().st_size != 0:
        # A legitimate positive run is preserved and surfaced, never forced to the desired empty result.
        assert result["classification"] == "success" and result["total_count"] >= 1
        warnings.warn(f"derived small fixture produced {result['total_count']} pocket(s); investigate", stacklevel=1)
        return
    assert result["classification"] == "scientific_null" and result["null_result"] is True
    assert result["total_count"] == 0 and result["pockets"] == []
    # Exact observed streams of the pinned 4.2.3 build: banner on stdout, diagnostics on stderr
    # (src/refine.c writes both diagnostics with fprintf(stderr, ...)).
    assert done.stdout == BANNER
    assert done.stderr == EMPTY_STDERR
    evidence = native_output_evidence(native, done.stdout, done.stderr)
    assert {e["path"] for e in evidence["files"] if e["retained"]} == READ_FILES
    assert not list((root / "protein_out" / "pockets").iterdir())
