#!/usr/bin/env python3
"""Validate case identity, nested output-contract fields and all-record screening coverage."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from screen_literature import MISSING, find_unsupported_schema_features, load_json, normalize_schema


def issue(code, path, message):
    return {"code": code, "path": path or "/", "message": message}


def type_matches(value, expected):
    expected = str(expected).casefold()
    checks = {
        "string": lambda: isinstance(value, str),
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "list": lambda: isinstance(value, list),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "bool": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }
    return checks[expected]() if expected in checks else True


def validate_schema(schema_node, value, path, errors, warnings, null_fields):
    schema = normalize_schema(schema_node)
    expected = schema.get("type")
    if isinstance(expected, list):
        if value is not None and not any(type_matches(value, item) for item in expected):
            errors.append(issue("contract_type_mismatch", path, "Expected one of %s" % expected))
    elif expected and value is not None and not type_matches(value, expected):
        errors.append(issue("contract_type_mismatch", path, "Expected %s, got %s" % (expected, type(value).__name__)))
    if value is None:
        null_fields.append(path or "/")
        return
    properties = schema.get("properties") or {}
    if properties:
        if not isinstance(value, dict):
            errors.append(issue("contract_object_required", path, "Nested contract fields require an object"))
            return
        for field, child in properties.items():
            child_path = path + "/" + str(field).replace("~", "~0").replace("/", "~1")
            if field not in value:
                errors.append(issue("missing_contract_field", child_path, "Original output_contract field name is absent; aliases are not substitutes"))
            else:
                validate_schema(child, value[field], child_path, errors, warnings, null_fields)
    if schema.get("items") is not None and isinstance(value, list):
        for index, item in enumerate(value):
            validate_schema(schema["items"], item, path + "/" + str(index), errors, warnings, null_fields)


def validate_case(case, result):
    errors = []
    warnings = []
    null_fields = []
    if not isinstance(case, dict):
        return [issue("invalid_case", "/", "case.json must be an object")], warnings, null_fields
    if not isinstance(result, dict):
        return [issue("invalid_result", "/", "result.json must be an object")], warnings, null_fields
    if "case_id" not in case:
        errors.append(issue("missing_input_case_id", "/case_id", "Input case_id is absent"))
    if "case_id" not in result:
        errors.append(issue("missing_result_case_id", "/case_id", "Result case_id is absent"))
    elif result.get("case_id") != case.get("case_id"):
        errors.append(issue("case_id_mismatch", "/case_id", "Result case_id must exactly match input"))
    if "output_contract" not in case:
        errors.append(issue("missing_output_contract", "/output_contract", "Cannot verify original required fields when output_contract is absent"))
    else:
        contract = case["output_contract"]
        schema = normalize_schema(contract)
        if not schema:
            warnings.append(issue("empty_output_contract", "/output_contract", "Present but empty; only generic result invariants can be checked"))
        unsupported = find_unsupported_schema_features(contract)
        if unsupported:
            labels = ["%s at %s" % (item["feature"], item["path"]) for item in unsupported]
            errors.append(issue("unsupported_output_contract_features", "/output_contract", "Composition/reference features require explicit task-grounded handling; refusing silent projection: " + ", ".join(labels)))
        validate_schema(contract, result, "", errors, warnings, null_fields)
    unmapped = result.get("contract_status", {}).get("unmapped_fields") if isinstance(result.get("contract_status"), dict) else None
    if unmapped:
        errors.append(issue("unmapped_contract_fields", "/contract_status/unmapped_fields", "Unresolved fields require honest partial results or task-grounded completion: %s" % unmapped))
    if null_fields:
        warnings.append(issue("null_contract_values", "/", "Null is retained as an honest missing value, not fabricated content: %s" % null_fields))

    rows = result.get("screening_results", MISSING)
    if rows is not MISSING:
        if not isinstance(rows, list):
            errors.append(issue("invalid_screening_results", "/screening_results", "Must be a list"))
            rows = []
        keys = []
        for index, row in enumerate(rows):
            path = "/screening_results/%d" % index
            if not isinstance(row, dict):
                errors.append(issue("invalid_screening_row", path, "Every row must be an object"))
                continue
            key = row.get("record_key")
            if key in (None, ""):
                errors.append(issue("missing_record_key", path + "/record_key", "Every record needs a stable key"))
            else:
                keys.append(str(key))
            if not isinstance(row.get("source_record"), dict):
                errors.append(issue("missing_source_record", path + "/source_record", "Original metadata must be retained"))
            if row.get("rank") != index + 1:
                errors.append(issue("noncontiguous_rank", path + "/rank", "Ranks must be 1..N in result order"))
            score = row.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
                errors.append(issue("invalid_score", path + "/score", "Score must be finite and numeric"))
            if row.get("decision") not in {"keep", "review", "exclude"}:
                errors.append(issue("invalid_decision", path + "/decision", "Use keep, review or exclude"))
            if row.get("relevance") not in {"direct", "indirect", "uncertain", "not_relevant", "irrelevant"}:
                errors.append(issue("invalid_relevance", path + "/relevance", "Unknown relevance label"))
            if not isinstance(row.get("evidence"), list) or not isinstance(row.get("score_components"), dict):
                errors.append(issue("missing_explanation", path, "Evidence list and score_components are required"))
        if len(keys) != len(set(keys)):
            errors.append(issue("duplicate_record_key", "/screening_results", "record_key values must be unique"))
        summary = result.get("summary")
        if isinstance(summary, dict):
            for field in ("input_records", "screened_records"):
                if field in summary and summary[field] != len(rows):
                    errors.append(issue("record_count_mismatch", "/summary/" + field, "Count must equal all retained screening rows"))
        else:
            errors.append(issue("missing_summary", "/summary", "All-record counts are required"))
        ranking = result.get("ranking")
        if not isinstance(ranking, list) or len(ranking) != len(keys) or set(ranking) != set(keys) or len(ranking) != len(set(ranking)):
            errors.append(issue("ranking_coverage", "/ranking", "Ranking must contain every record_key exactly once"))
    return errors, warnings, null_fields


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="/input/case.json")
    parser.add_argument("--result", default="/app/output/result.json")
    parser.add_argument("--output", default="/app/work/result_validation.json")
    args = parser.parse_args(argv)
    try:
        case = load_json(args.case)
        result = load_json(args.result)
        errors, warnings, null_fields = validate_case(case, result)
        report = {
            "valid": not errors,
            "case_id": case.get("case_id") if isinstance(case, dict) else None,
            "errors": errors,
            "warnings": warnings,
            "null_contract_field_count": len(null_fields),
            "official_cases_run": False,
            "boundary": "Structure and all-record invariants only; scientific labels, official whiteboards and server admission are not verified.",
        }
        exit_code = 1 if errors else 0
    except Exception as exc:
        report = {"valid": False, "errors": [issue("read_or_parse_failure", "/", type(exc).__name__ + ": " + str(exc))], "official_cases_run": False}
        exit_code = 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
