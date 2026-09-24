# M1 partial independent review

Reviewer: GPT-6 Astra. Date: 2026-09-24. This report currently covers the completed backend implementation only. The frontend worker/browser validation is still pending; no full M1 approval is implied.

## Inspected backend files

- backend/mw/api/app.py
- backend/mw/core/handles.py
- backend/mw/core/contracts.py
- backend/mw/tools/structural.py
- config/tools.yaml
- backend/tests/test_api.py
- backend/tests/test_structural.py
- backend/tests/test_core.py
- backend/tests/fixtures/mini_complex.pdb

## Independent checks and accepted evidence

- .venv/bin/python -m pytest backend/tests/test_api.py backend/tests/test_structural.py -q: **15 passed in 0.54s**, one upstream TestClient deprecation warning.
- .venv/bin/python -m pytest backend/tests/test_core.py -q: **9 passed in 0.26s**.
- .venv/bin/python -m ruff check backend/mw/api backend/mw/core backend/mw/tools backend/tests/test_api.py: **passed**.
- Confirmed interaction_set now hashes an envelope of input structure, explicit ligand selection, cutoff/types/method and rows. Tests cover equal rows under different cutoffs, empty rows and different preparation policies. Materialization and compact previews read envelope rows consistently.
- Confirmed explicit same-name ligand instance selection, author/label/insertion-code preservation in mmCIF, bounded object materialization, local bytes endpoints and reopened objects after upload originals are removed.
- Inspected parent-created /tmp/protview-qa/m1-api-evidence.json. It records real HTTP 1HSG import (source SHA-256 d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268), cutoff 4.0: 97 atom contacts across 26 residues; cutoff 4.5: 226/30; minimum distance 2.6264474104767457 angstrom. These are parent-observed HTTP results, independently matched by the parent's direct geometric calculation, not invented design data.

## Changes required

1. **Run-root write/read confinement:** _run_path rejects a symlinked run directory, but upload and load_structure do not reject a symlinked uploads parent. Independently created a run/uploads symlink into another temporary directory: upload returned HTTP 201 and wrote one file outside the run; load_structure through its upload_id returned 200. Validate the upload directory and resolved parent boundary for both reads and writes; ensure file creation cannot follow an unexpected parent link. Add a regression proving no outside file is written/read.
2. **Public argument shape validation:** prepare_structure with structure=[valid_handle] passes per-element kind checks, then crashes at a scalar-handle operation. Independently observed HTTP 500. Enforce scalar/list cardinality before execution (including empty and nested lists), retaining compile_state's list contract; malformed commands should return typed 422 and invoke no implementation.
3. **Author-chain summary clarity:** 1HSG currently reports chains_auth=[A,B,A,B] because Gemmi chain segments are listed. If this field represents author-chain names for a UI count, deduplicate it or expose segment count separately. Verify the completed frontend does not display four author chains for this structure.

Frontend/browser gate still requires actual local structure rendering, representation change, accurate residue focus with mmCIF/insertion identity, data-backed counts, empty/error/loading handling, reopen behavior and no third-party runtime resources. This report will be rewritten around final integrated evidence once those checks and the backend corrections are complete.

## Backend corrections independently verified

Inspected the terminal Sol result at /tmp/protview-qa/m1-backend-fixes-result.md and current api/app.py, core/handles.py, core/contracts.py, tools/structural.py, tools/registry.py, runtime/orchestrator.py, config/tools.yaml and the corresponding API/core/structural regression tests. Independently executed all three suites together: **29 passed in 0.81s**, with the same upstream TestClient deprecation warning. Ruff for API/core/tools and test_api.py passed.

The upload code now opens the run and uploads directory with O_DIRECTORY/O_NOFOLLOW and uses directory-relative file descriptors for reading/creation. It verifies regular files and hashes before passing source_bytes/source_format into Run.call and ToolContext, so the scientific importer does not reopen a redirectable upload path. Repeated legitimate uploads and loads remain idempotent. Object blob access uses corresponding nested-directory/file protections.

Independent repetitions of the original exploits now pass: symlinked upload-parent write and read both return 422 without an outside write; scalar handle arrays, empty arrays and nested arrays return 422; malformed collection shapes also return 422 before tool execution. The declared handle_cardinality defaults to scalar, with compile_state.inputs explicitly collection.

Unique author-chain summaries preserve order, while residue counts still include every segment. load_structure version 0.1.1 and structure_selection@2 separate the updated summary from old cached outputs; the regression retains the legacy metadata and shares the immutable source object correctly. Earlier M0 preparation-policy identity, model number/auth-label/insertion-code handling, sparse Parquet and events-only recovery tests remain passing. The interaction semantic-envelope follow-up is implemented and covered by equal/empty-row tests.

All backend findings in this report are resolved. This approval is only for the M1 backend slice and shared M0 regression preservation. Full step1 approval still requires terminal frontend review and actual browser evidence; no phase index or reviewed-file hashes were changed by this reviewer.

Backend-scope verdict: APPROVED

