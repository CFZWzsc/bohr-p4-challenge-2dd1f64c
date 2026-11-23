# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-2dd1f64c` (track: `literature-search`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `traceable-literature-screening`
- Summary: Use when a research task supplies candidate papers and requires all-record relevance labels, explainable stable ranking, duplicate/version handling, conflict review, or a contract-preserving /app/output/result.json; retain every source record and dynamically validate case_id plus all original output_contract fields.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/screen_literature.py` |
| `scripts/validate_result.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
