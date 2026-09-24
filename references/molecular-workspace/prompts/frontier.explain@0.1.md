---
id: frontier.explain
version: "0.1"
role: frontier
output_schema: null
---
Explain the result to a structural biologist in Korean, 3–6 sentences, plain declarative style.
Every sentence that contains a number MUST end with the short id of the handle it came from, in
square brackets, e.g. "[9f3c]". Copy numbers exactly as they appear in EVIDENCE, with units
(Å, Å², REU). Energies are REU; do not convert to kcal/mol. Negative ΔΔG means stabilizing.
If evidence is missing for a claim, do not make the claim.

GOAL: {{goal}}

EVIDENCE (handle short id -> rows):
{{evidence}}
