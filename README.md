# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-2dd1f64c` (track: `literature-search`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `traceable-literature-screening`
- Summary: Use when a research task supplies candidate papers and requires all-record relevance labels, explainable stable ranking, duplicate/version handling, conflict review, or a contract-preserving /app/output/result.json; retain every source record and dynamically validate case_id plus all original output_contract fields.

## Contents

| File |
|------|
| `SKILL.md` |
| `examples/demo-case/assessments.json` |
| `examples/demo-case/case.json` |
| `scripts/deliver.py` |
| `scripts/screen_literature.py` |
| `scripts/validate_result.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
