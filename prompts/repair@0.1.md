---
id: repair
version: "0.1"
role: any
output_schema: same-as-original
---
Your previous output failed schema validation. Return ONLY corrected JSON for the same schema.
Do not change any value that was valid. Error:
{{error}}

Previous output:
{{previous}}
