# Contracts

Shapes that cross module or process boundaries. Code is the implementation; this file is the spec.
Change a contract only together with: `backend/mw/...`, `frontend/src/lib/contracts.ts`, and this file.

## Handle  (`mw/core/handles.py`)

```json
{ "handle": "obj://run_20260923_a91/interaction_set/9f3c55e0b7120ba1",
  "kind": "interaction_set", "schema": "interaction_set@1",
  "summary": { "n_edges": 47, "n_hbond": 12 },
  "preview": [ { "...": "≤ 5 rows" } ],
  "produced_by": "call_0007",
  "null_result": false }
```
- `sha16 = sha256(kind \0 schema \0 canonical_content)[:16]`. canonical_content = sorted-key compact JSON, or raw bytes.
- Storage: `runs/<run_id>/objects/<sha16>.<fmt>` (`json | parquet | pdb | cif`), index `runs/<run_id>/index.sqlite` (derived).
- `materialize(handle, columns, offset, limit)` → rows. The only way full content is read.

### Kinds (v1)
| kind | schema | content |
|---|---|---|
| structure / prepared_structure / relaxed_structure | structure@1 | raw file bytes (pdb/cif). Never the original file name. |
| preparation_manifest | preparation_manifest@1 | `{altloc, waters, hydrogens, protonation{ph,engine,applied}, missing_residues, symmetry_mates, model_index, removed{}, input, notes[]}` |
| interaction_set | interaction_set@1 | rows `{residue: ResidueRef, type, distance_A, protein_atom, ligand_atom, engine}` |
| pocket_set | pocket_set@1 | rows `{id, residues: ResidueRef[], volume_A3, score, engine}` |
| mutation_set | mutation_set@1 | rows `{chain_auth, seq_auth, icode?, from?, to}` |
| energy_table | energy_table@1 | rows `{mutation, chain_auth, ddg_REU, sd_REU, rounds_REU[], iterations}` + summary `{unit:"REU", protocol, scorefxn, rosetta_version, seed, stub?}` |
| interface_scores | interface_scores@1 | `{interface, dG_separated, dSASA_int, dG_separated_per_dSASAx100, packstat, delta_unsatHbonds, hbonds_int}` |
| residue_energy_table | residue_energy_table@1 | rows `{residue, term, value_REU}` |
| selection | selection@1 | `{residues: ResidueRef[], source: "viewer"|"sequence"|"pae"}` |
| compact_state | compact_state@1 | `{items: [{handle, kind, schema, summary, preview}], token_budget}` — no coords, no sequence |
| viewer_state | viewer_state@1 | Mol* snapshot JSON (camera, reps, selection) |

## ResidueRef  (`mw/core/residue.py`)
```json
{ "chain_auth": "A", "seq_auth": 100, "icode": "A", "chain_label": "B", "seq_label": 97, "resname": "ASP" }
```
Display `uid = "A/100A"` (never parse). Join key = `(chain_label, seq_label, resname)`. Every adapter
(gemmi, Mol*, ProLIF, PLIP, PyRosetta) needs a round-trip test.

## ToolFailure  (`mw/core/errors.py`)
```json
{ "error": "precondition", "message": "energy_table requires relaxed structure",
  "fix": { "tool": "relax_structure", "args": { "structure": "obj://..." } }, "detail": {} }
```
`error ∈ transient | input_invalid | precondition | resource_exceeded | fatal`.
`scientific_null` is NOT here: it's `Handle.null_result = true`.

| class | orchestrator does | agent may |
|---|---|---|
| transient | retries ×3 with 2s,4s,8s backoff | — |
| input_invalid | raises | change args, retry once |
| precondition | raises (with `fix`) | run `fix`, retry once |
| resource_exceeded | raises | propose smaller params (no retry) |
| fatal | raises | stop, ask human |

## ToolSpec  (`config/tools.yaml`, `mw/core/contracts.py`)
`name, level(L1–L5), version, accepts{arg: [kinds]}, params{name: {type, enum?, min?, max?, default?, required?}},
emits, cost_class(cheap|moderate|expensive), idempotent, read_only, typical_runtime_s, description`.
`idempotency_key = sha256({tool, v: version, args: normalized})`.

## Events  (`runs/<run_id>/events.jsonl`, `mw/core/events.py`)
One JSON object per line: `{seq, ts, type, ...}`.

| type | fields |
|---|---|
| run_started | run_id, dry_run, seed |
| goal | text, context[handles], egress |
| tool_called | tool, key, call_id, args, decided_by, attempt, version |
| tool_succeeded | tool, key, call_id, output(Handle), duration_s, null_result, cached? |
| tool_failed | tool, key, call_id, error, message, fix, detail |
| decision | source(rule/jev/frontier/human), question, answer, …meta |
| approval_requested / approval_resolved | gate, tool/args · approved, by |
| checkpoint | reason, axis?, budget? |
| llm_call (M3) | role, prompt_ref, prompt_sha, requested_model, served_model, tokens, usd, cached |
| egress (M3, mirror of egress.jsonl summary) | destination, blocked_fields |
| run_finished | — |

Approval gates: `expensive_first_call | write_outside_run_dir | egress_l2_plus | final_selection | budget`.

## Egress log  (`runs/<run_id>/egress.jsonl`)
`{ts, destination, purpose, mode, sent, blocked_fields[], payload(sanitized) | kind:"fetch"}`.

## OpenRouter request body  (`mw/llm/openrouter.py`)
```json
{ "model": "<pinned>", "messages": [...], "temperature": 0, "max_tokens": 512,
  "provider": { "data_collection": "deny", "zdr": true, "require_parameters": true, "allow_fallbacks": false },
  "usage": { "include": true },
  "response_format": { "type": "json_schema", "json_schema": { "name": "...", "strict": true, "schema": {...} } } }
```
`models: [...]` only when `allow_fallbacks: true`. Response → `LLMResult{content, parsed, requested_model, served_model, served_matches_pin, usage, cached}`.

## HTTP API  (`mw/api/app.py`, proxied at `/api` by Next)
| method | path | body / query | returns |
|---|---|---|---|
| GET | /tools | levels=L5 | ToolSpec[] |
| POST | /runs | {goal, context[], dry_run, egress} | {run_id} |
| POST | /runs/{id}/commands | {tool, args, decided_by} | {ok, handle} \| {ok:false, error…} \| {ok:false, approval} \| {ok:false, loop_stop} |
| POST | /runs/{id}/approvals/{gate} | — | {ok} |
| GET | /runs/{id}/events | after | RunEvent[] |
| GET | /runs/{id}/budget | — | BudgetSnapshot |
| GET | /runs/{id}/objects | handle, columns, offset, limit | {meta, rows} |
