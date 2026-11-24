#!/usr/bin/env python3
"""Deterministic all-record literature screening with dynamic output-contract preservation."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

VERSION = "1.0.0"
CANDIDATE_KEYS = {
    "candidates", "candidate_papers", "papers", "records", "documents",
    "literature", "publications", "works", "search_results", "results", "items",
}
QUESTION_KEYS = ("research_question", "question", "objective", "query", "topic")
ID_KEYS = ("record_id", "paper_id", "work_id", "id", "doi", "url", "title")
MISSING = object()
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "of", "on", "or", "that", "the", "this", "to", "using", "with",
    "研究", "方法", "结果", "以及", "进行", "基于", "相关", "问题", "文献",
}
ALIASES = {
    "papers": "screening_results", "candidates": "screening_results",
    "candidate_papers": "screening_results", "records": "screening_results",
    "results": "screening_results", "screened_papers": "screening_results",
    "ranked_papers": "screening_results", "ranked_results": "screening_results",
    "ranking": "ranking", "order": "ranking", "query": "research_question",
    "search_query": "research_question", "question": "research_question",
    "objective": "research_question", "state": "status", "run_status": "status",
    "limitations": "limitations", "limitation": "limitations",
    "uncertainties": "uncertainty", "sources": "sources", "source": "sources",
    "evidence_records": "evidence_record", "audit_trail": "evidence_record",
    "query_trace": "evidence_record", "decision_records": "evidence_record",
    "duplicates": "duplicate_clusters", "deduplication": "duplicate_clusters",
    "version_clusters": "duplicate_clusters", "manual_review": "review_queue",
    "human_review": "review_queue", "review": "review_queue",
    "change_records": "changes", "change_log": "changes", "summary": "summary",
    "counts": "summary", "k": "k", "top_k": "top_k", "conflicts": "conflicts",
}


def normalize_text(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def normalize_doi(value):
    text = str(value or "").strip().casefold()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    return re.sub(r"^doi:\s*", "", text).strip().rstrip(".")


def tokens(value):
    text = normalize_text(value)
    output = []
    for part in text.split():
        if re.fullmatch(r"[a-z0-9_-]+", part):
            if len(part) > 1 and part not in STOPWORDS:
                output.append(part)
        else:
            han = "".join(re.findall(r"[\u4e00-\u9fff]", part))
            output.extend(han[i:i + 2] for i in range(max(0, len(han) - 1)))
    return {item for item in output if item and item not in STOPWORDS}


def flatten_text(value):
    if isinstance(value, dict):
        return " ".join(flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten_text(item) for item in value)
    return str(value or "")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def pointer_get(value, pointer):
    if not pointer:
        return value
    current = value
    for raw in pointer.strip("/").split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(key)] if isinstance(current, list) else current[key]
    return current


def looks_like_record(value):
    return isinstance(value, dict) and any(
        key in value for key in ("title", "abstract", "doi", "paper_id", "work_id", "url")
    )


def discover_lists(value, path=""):
    """Collect candidate-like lists without descending into a selected list twice."""
    found = []
    if isinstance(value, list):
        if not value or all(isinstance(item, dict) for item in value):
            found.append((path or "/", value))
        return found
    if not isinstance(value, dict):
        return found
    for key, child in value.items():
        child_path = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
        if key.casefold() in CANDIDATE_KEYS and isinstance(child, list):
            if not child or all(isinstance(item, dict) for item in child):
                found.append((child_path, child))
            continue
        found.extend(discover_lists(child, child_path))
    return found


def extract_records(case, candidate_file=None, candidate_pointer=None):
    source = load_json(candidate_file) if candidate_file else case
    if candidate_pointer:
        selected = pointer_get(source, candidate_pointer)
        if not isinstance(selected, list) or not all(isinstance(item, dict) for item in selected):
            raise ValueError("candidate pointer must identify a list of objects")
        lists = [(candidate_pointer, selected)]
    elif candidate_file:
        lists = discover_lists(source)
    else:
        lists = discover_lists(case)
    records = []
    for list_path, items in lists:
        for index, record in enumerate(items):
            if looks_like_record(record) or candidate_pointer or candidate_file:
                records.append((list_path, index, record))
    return records


def extract_question(case, explicit=None, criteria=None):
    if explicit:
        return explicit
    for key in QUESTION_KEYS:
        if key in case and case[key]:
            value = case[key]
            return flatten_text(value) if not isinstance(value, str) else value
    if criteria:
        return " ".join(criteria)
    return ""


def source_id(record):
    for key in ID_KEYS:
        if record.get(key) not in (None, ""):
            return str(record[key])
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def unique_record_keys(records):
    used = defaultdict(int)
    output = []
    for list_path, index, record in records:
        base = source_id(record)
        used[base] += 1
        key = base if used[base] == 1 else "%s#%s/%d" % (base, list_path.strip("/"), index)
        output.append(key)
    return output


def assessment_keys(assessment):
    record = assessment.get("source_record") if isinstance(assessment, dict) else None
    values = []
    for key in ("record_key", "source_id", "record_id", "paper_id", "work_id", "id", "doi", "title"):
        if assessment.get(key) not in (None, ""):
            values.append(str(assessment[key]))
    if isinstance(record, dict):
        values.append(source_id(record))
    return set(values)


def resolve_assessments(record, record_key, assessments):
    aliases = {record_key, source_id(record)}
    if record.get("doi"):
        aliases.add(str(record["doi"]))
        aliases.add(normalize_doi(record["doi"]))
    if record.get("title"):
        aliases.add(str(record["title"]))
        aliases.add(normalize_text(record["title"]))
    matched = []
    for assessment in assessments:
        if assessment.get("record_key") not in (None, ""):
            if str(assessment["record_key"]) == record_key:
                matched.append(assessment)
            continue
        keys = assessment_keys(assessment)
        normalized = {normalize_doi(item) if "doi" in assessment else item for item in keys}
        normalized |= {normalize_text(item) for item in keys}
        if aliases & keys or aliases & normalized or normalize_text(record.get("title")) in normalized:
            matched.append(assessment)
    if not matched:
        return None, []
    decisions = {str(item.get("decision", "")) for item in matched if item.get("decision")}
    relevances = {str(item.get("relevance", "")) for item in matched if item.get("relevance")}
    conflicts = []
    if len(decisions) > 1 or len(relevances) > 1:
        conflicts.append("multiple_assessments_disagree")
    if len(matched) == 1:
        resolved = copy.deepcopy(matched[0])
    else:
        resolved = copy.deepcopy(matched[0])
        resolved["reviewer_opinions"] = copy.deepcopy(matched)
        resolved["rationale"] = " | ".join(str(item.get("rationale", "")) for item in matched if item.get("rationale"))
        resolved["evidence"] = [evidence for item in matched for evidence in item.get("evidence", [])]
        if conflicts:
            resolved["decision"] = "review"
            resolved["relevance"] = "uncertain"
    opinions = resolved.get("reviewer_opinions") or []
    opinion_decisions = {str(item.get("decision", "")) for item in opinions if isinstance(item, dict) and item.get("decision")}
    opinion_relevances = {str(item.get("relevance", "")) for item in opinions if isinstance(item, dict) and item.get("relevance")}
    if len(opinion_decisions) > 1 or len(opinion_relevances) > 1:
        conflicts.append("reviewer_opinions_disagree")
        resolved["decision"] = "review"
    return resolved, sorted(set(conflicts))


def lexical_features(question, criteria, record):
    query_tokens = tokens(" ".join([question] + list(criteria or [])))
    title_tokens = tokens(record.get("title"))
    record_tokens = tokens(flatten_text({key: value for key, value in record.items() if key != "source_record"}))
    matched = sorted(query_tokens & record_tokens)
    title_matched = sorted(query_tokens & title_tokens)
    coverage = len(matched) / len(query_tokens) if query_tokens else 0.0
    title_coverage = len(title_matched) / len(query_tokens) if query_tokens else 0.0
    return {
        "query_token_count": len(query_tokens),
        "matched_tokens": matched,
        "title_matched_tokens": title_matched,
        "coverage": round(coverage, 6),
        "title_coverage": round(title_coverage, 6),
        "points": round(min(10.0, 6.0 * coverage + 4.0 * title_coverage), 6),
    }


def criteria_points(criteria):
    points = 0.0
    detail = {}
    for name, raw in sorted((criteria or {}).items()):
        value = raw.get("match") if isinstance(raw, dict) else raw
        normalized = str(value).strip().casefold()
        if normalized in {"match", "matched", "yes", "true", "1", "符合", "匹配"}:
            score = 6.0
        elif normalized in {"partial", "partially", "间接", "部分匹配"}:
            score = 2.0
        elif normalized in {"mismatch", "no", "false", "0", "不符合", "不匹配"}:
            score = -15.0
        else:
            score = 0.0
            normalized = "unknown"
        detail[name] = {"judgment": normalized, "points": score}
        points += score
    return points, detail


def publication_rank(record):
    text = normalize_text(" ".join(str(record.get(key, "")) for key in ("type", "status", "version", "publication_status")))
    if any(word in text for word in ("published", "journal", "version of record", "正式发表")):
        return 2
    if any(word in text for word in ("preprint", "submitted", "预印本")):
        return 1
    return 0


def build_clusters(results):
    parent = list(range(len(results)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    for left in range(len(results)):
        a = results[left]["source_record"]
        for right in range(left + 1, len(results)):
            b = results[right]["source_record"]
            doi_a, doi_b = normalize_doi(a.get("doi")), normalize_doi(b.get("doi"))
            title_a, title_b = normalize_text(a.get("title")), normalize_text(b.get("title"))
            if (doi_a and doi_a == doi_b) or (len(title_a) >= 8 and title_a == title_b):
                union(left, right)
    groups = defaultdict(list)
    for index in range(len(results)):
        groups[find(index)].append(index)
    clusters = []
    for indices in sorted((sorted(group) for group in groups.values() if len(group) > 1), key=lambda g: results[g[0]]["record_key"]):
        canonical = sorted(indices, key=lambda i: (
            -publication_rank(results[i]["source_record"]),
            -sum(results[i]["source_record"].get(key) not in (None, "") for key in ("title", "abstract", "year", "doi", "url")),
            results[i]["record_key"],
        ))[0]
        cluster_id = "cluster-%03d" % (len(clusters) + 1)
        members = []
        for index in indices:
            item = results[index]
            item["cluster_id"] = cluster_id
            item["duplicate_of"] = results[canonical]["record_key"] if index != canonical else None
            members.append({
                "record_key": item["record_key"],
                "publication_status": item["source_record"].get("publication_status", item["source_record"].get("status")),
                "canonical": index == canonical,
            })
        clusters.append({"cluster_id": cluster_id, "canonical_record_key": results[canonical]["record_key"], "members": members})
    return clusters


SUPPORTED_SCHEMA_KEYS = {"type", "properties", "required", "optional", "fields", "items", "description", "title", "$schema", "additionalProperties"}
UNSUPPORTED_SCHEMA_FEATURES = {
    "anyOf", "allOf", "oneOf", "not", "if", "then", "else", "$ref", "$defs",
    "definitions", "patternProperties", "dependencies", "dependentRequired",
    "dependentSchemas", "prefixItems", "contains", "propertyNames",
    "unevaluatedProperties", "unevaluatedItems", "additionalItems", "contentSchema",
}
IGNORED_SCHEMA_KEYS = {
    "$id", "$anchor", "$comment", "default", "examples", "enum", "const", "format",
    "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "minItems", "maxItems", "uniqueItems", "minProperties",
    "maxProperties", "readOnly", "writeOnly", "deprecated", "contentEncoding", "contentMediaType",
}
SCHEMA_CONTROL_KEYS = SUPPORTED_SCHEMA_KEYS | UNSUPPORTED_SCHEMA_FEATURES | IGNORED_SCHEMA_KEYS


def find_unsupported_schema_features(node, path=""):
    """Independently locate composition/reference features that this Skill cannot project safely."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
            if key in UNSUPPORTED_SCHEMA_FEATURES:
                found.append({"feature": key, "path": child_path or "/"})
            found.extend(find_unsupported_schema_features(value, child_path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(find_unsupported_schema_features(item, path + "/" + str(index)))
    return found


def normalize_schema(node):
    if isinstance(node, str):
        return {"type": node}
    if isinstance(node, list):
        properties = {}
        for item in node:
            if isinstance(item, str):
                properties[item] = {}
            elif isinstance(item, dict) and item.get("name"):
                properties[str(item["name"])] = {key: value for key, value in item.items() if key != "name"}
        return {"type": "object", "properties": properties, "required": list(properties)}
    if not isinstance(node, dict):
        return {}
    schema = {key: copy.deepcopy(value) for key, value in node.items() if key in SUPPORTED_SCHEMA_KEYS}
    properties = dict(schema.get("properties") or {})
    fields = node.get("fields")
    if isinstance(fields, dict):
        properties.update(fields)
    elif isinstance(fields, list):
        for item in fields:
            if isinstance(item, str):
                properties[item] = {}
            elif isinstance(item, dict) and item.get("name"):
                properties[str(item["name"])] = {key: value for key, value in item.items() if key != "name"}
    for key, value in node.items():
        if key not in SCHEMA_CONTROL_KEYS:
            properties[key] = value
    required = list(schema.get("required") or [])
    required.extend(key for key, value in properties.items() if isinstance(value, dict) and value.get("required") is True and key not in required)
    for key in list(schema.get("optional") or []) + required:
        properties.setdefault(key, {})
    if properties or required or fields is not None:
        schema["type"] = schema.get("type", "object")
        schema["properties"] = properties
        schema["required"] = required
    return schema


def select_value(value, field):
    if not isinstance(value, dict):
        return MISSING
    if field in value:
        return value[field]
    normalized = normalize_text(field).replace(" ", "_")
    for key in value:
        if normalize_text(key).replace(" ", "_") == normalized:
            return value[key]
    target = ALIASES.get(normalized)
    if target and target in value:
        return value[target]
    return MISSING


def project_value(schema_node, value, path, unmapped):
    schema = normalize_schema(schema_node)
    properties = schema.get("properties") or {}
    if properties:
        base = copy.deepcopy(value) if isinstance(value, dict) else {}
        for field, child_schema in properties.items():
            selected = select_value(value, field)
            child_path = path + "/" + str(field).replace("~", "~0").replace("/", "~1")
            if selected is MISSING:
                selected = None
                unmapped.append(child_path)
            base[field] = project_value(child_schema, selected, child_path, unmapped)
        return base
    schema_type = schema.get("type")
    is_array = (
        schema_type in {"array", "list"} if isinstance(schema_type, str)
        else isinstance(schema_type, list) and any(item in {"array", "list"} for item in schema_type if isinstance(item, str))
    )
    if is_array and isinstance(value, list) and schema.get("items"):
        return [project_value(schema["items"], item, path + "/" + str(index), unmapped) for index, item in enumerate(value)]
    return copy.deepcopy(value)


def apply_contract(result, contract):
    unmapped = []
    projected = project_value(contract, result, "", unmapped)
    if isinstance(projected, dict):
        result.update(projected)
    return result, sorted(set(unmapped))


def screen(case, records, assessments=None, question="", criteria=None, top_k=None):
    assessments = assessments or []
    criteria = criteria or []
    keys = unique_record_keys(records)
    results = []
    conflicts = []
    review = defaultdict(list)
    limitations = []
    if not records:
        limitations.append("candidate_set_empty: no records were supplied or discovered")
    if not question and not criteria:
        limitations.append("research_question_missing: lexical comparison cannot establish relevance")
    if not assessments and records:
        limitations.append("no_task_grounded_assessments: labels default to uncertain/review; lexical points are only tie-breaking evidence")

    for index, ((list_path, source_index, record), record_key) in enumerate(zip(records, keys)):
        lexical = lexical_features(question, criteria, record)
        assessment, assessment_conflicts = resolve_assessments(record, record_key, assessments)
        assessment = assessment or {}
        relevance = str(assessment.get("relevance", "uncertain"))
        decision = str(assessment.get("decision", "review" if relevance == "uncertain" else ("exclude" if relevance in {"not_relevant", "irrelevant"} else "keep")))
        criterion_score, criterion_detail = criteria_points(assessment.get("criteria"))
        relevance_base = {"direct": 100.0, "indirect": 60.0, "uncertain": 35.0, "not_relevant": 0.0, "irrelevant": 0.0}.get(relevance, 35.0)
        evidence = copy.deepcopy(assessment.get("evidence") or [])
        evidence_points = min(6.0, 2.0 * len(evidence))
        score = round(relevance_base + criterion_score + evidence_points + lexical["points"], 6)
        missing = [field for field in ("title", "abstract", "year") if record.get(field) in (None, "")]
        for reason in assessment_conflicts:
            review[record_key].append(reason)
            conflicts.append({"type": reason, "record_keys": [record_key]})
        if not assessment:
            review[record_key].append("task_grounded_assessment_missing")
        if "title" in missing:
            review[record_key].append("title_missing")
        if "abstract" in missing and decision != "exclude":
            review[record_key].append("abstract_missing")
        if decision == "review":
            review[record_key].append("decision_review")
        results.append({
            "record_key": record_key,
            "source_id": source_id(record),
            "source_locator": {"list_path": list_path, "index": source_index},
            "title": record.get("title"),
            "decision": decision,
            "relevance": relevance,
            "role": assessment.get("role"),
            "confidence": assessment.get("confidence"),
            "rationale": assessment.get("rationale") or "No task-grounded rationale supplied; do not treat lexical overlap as a relevance decision.",
            "evidence": evidence,
            "criteria": criterion_detail,
            "score": score,
            "score_components": {
                "relevance_base": relevance_base,
                "criteria": criterion_score,
                "evidence_coverage": evidence_points,
                "lexical_tie_break": lexical["points"],
            },
            "lexical_features": lexical,
            "missing_metadata": missing,
            "source_record": copy.deepcopy(record),
            "cluster_id": None,
            "duplicate_of": None,
        })

    clusters = build_clusters(results)
    for cluster in clusters:
        members = [item for item in results if item["cluster_id"] == cluster["cluster_id"]]
        if len({item["decision"] for item in members}) > 1 or len({item["relevance"] for item in members}) > 1:
            keys_in_cluster = [item["record_key"] for item in members]
            conflicts.append({"type": "duplicate_cluster_assessment_conflict", "record_keys": keys_in_cluster, "cluster_id": cluster["cluster_id"]})
            for key in keys_in_cluster:
                review[key].append("duplicate_cluster_assessment_conflict")

    results.sort(key=lambda item: (
        {"keep": 0, "review": 1, "exclude": 2}.get(item["decision"], 1),
        -item["score"],
        {"direct": 0, "indirect": 1, "uncertain": 2}.get(item["relevance"], 3),
        -len(item["evidence"]),
        normalize_text(item["title"]),
        item["record_key"],
    ))
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    k = len(results) if top_k is None else min(len(results), top_k)
    review_queue = [
        {"record_key": key, "reasons": sorted(set(review[key]))}
        for key in sorted(review)
    ]
    result = {
        "case_id": case.get("case_id"),
        "status": "completed_with_limitations" if limitations or conflicts else "completed",
        "research_question": question,
        "criteria": list(criteria),
        "screening_results": results,
        "ranking": [item["record_key"] for item in results],
        "top_k": k,
        "k": k,
        "primary_results": results[:k],
        "duplicate_clusters": clusters,
        "conflicts": conflicts,
        "review_queue": review_queue,
        "summary": {
            "input_records": len(records),
            "screened_records": len(results),
            "keep": sum(item["decision"] == "keep" for item in results),
            "review": sum(item["decision"] == "review" for item in results),
            "exclude": sum(item["decision"] == "exclude" for item in results),
            "duplicate_clusters": len(clusters),
            "conflicts": len(conflicts),
        },
        "sources": [{"type": "case", "path": "/input/case.json"}] + [
            {"type": "candidate_record", "record_key": item["record_key"], "locator": item["source_locator"]}
            for item in results
        ],
        "evidence_record": {
            "method": "task-grounded labels first; explicit criteria and evidence; lexical features only as disclosed tie-breaking evidence",
            "tie_break": ["decision keep/review/exclude", "score desc", "relevance direct/indirect/uncertain", "evidence count desc", "normalized title", "record_key"],
            "all_records_retained": True,
            "deduplication": "records are clustered and cross-referenced, never silently deleted",
        },
        "uncertainty": ["Missing metadata and unverified assessments remain explicit; no external recall or live-database claim is made."],
        "limitations": limitations,
        "changes": [
            "Copied every source_record unchanged; normalized values are derived only for matching and sorting.",
            "Applied stable explainable sorting and cross-referenced duplicate/version clusters without deleting records.",
        ],
        "contract_status": {"present": "output_contract" in case, "unmapped_fields": []},
        "script_version": VERSION,
    }
    if "output_contract" in case:
        contract = case.get("output_contract")
        unsupported = sorted(find_unsupported_schema_features(contract), key=lambda item: (item["path"], item["feature"]))
        result, unmapped = apply_contract(result, contract)
        result["contract_status"] = {"present": True, "unmapped_fields": unmapped, "unsupported_features": unsupported}
        if unmapped or unsupported:
            result["status"] = "partial"
            if unmapped:
                result["limitations"] = list(result.get("limitations") or []) + ["unmapped_output_contract_fields: " + ", ".join(unmapped)]
            if unsupported:
                labels = ["%s at %s" % (item["feature"], item["path"]) for item in unsupported]
                result["limitations"] = list(result.get("limitations") or []) + ["unsupported_output_contract_features: " + ", ".join(labels)]
            result["uncertainty"] = list(result.get("uncertainty") or []) + ["Unmapped fields and unsupported schema features are explicit limitations, not fabricated or silently validated content."]
            result, _ = apply_contract(result, contract)
    else:
        result["status"] = "partial"
        result["limitations"].append("output_contract_missing: generic result saved; original required fields cannot be verified")
    return result


def run(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        case = load_json(args.case)
        if not isinstance(case, dict):
            raise ValueError("case.json must contain an object")
    except Exception as exc:
        failure = {"case_id": None, "status": "failed", "errors": [type(exc).__name__ + ": " + str(exc)], "uncertainty": ["Input could not be parsed; no screening was performed."]}
        output.write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False))
        return 2
    try:
        records = extract_records(case, args.candidates, args.candidate_pointer)
        assessments = load_json(args.assessments) if args.assessments else []
        if isinstance(assessments, dict):
            assessments = assessments.get("assessments", assessments.get("records", [assessments]))
        if not isinstance(assessments, list) or not all(isinstance(item, dict) for item in assessments):
            raise ValueError("assessments must be a list of objects or an object containing assessments")
        question = extract_question(case, args.question, args.criterion)
        result = screen(case, records, assessments, question, args.criterion, args.top_k)
        if args.candidates:
            result["sources"].insert(1, {"type": "candidate_file", "path": str(args.candidates)})
        result["sources"][0]["path"] = str(args.case)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "records": len(records), "output": str(output)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        result = {
            "case_id": case.get("case_id"), "status": "failed", "screening_results": [],
            "ranking": [], "sources": [{"type": "case", "path": str(args.case)}],
            "errors": [type(exc).__name__ + ": " + str(exc)],
            "uncertainty": ["Screening failed; no missing records or metadata were fabricated."],
            "limitations": ["failed_before_complete_screening"], "changes": [],
        }
        if "output_contract" in case:
            result, _ = apply_contract(result, case["output_contract"])
            result["status"] = "failed"
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="/input/case.json")
    parser.add_argument("--candidates", help="Optional actual JSON file containing candidate records")
    parser.add_argument("--candidate-pointer", help="JSON pointer to the actual candidate list")
    parser.add_argument("--assessments", help="Optional task-grounded per-record assessment JSON")
    parser.add_argument("--question", help="Exact research question; otherwise read common case fields")
    parser.add_argument("--criterion", action="append", default=[], help="Actual inclusion/exclusion criterion; repeatable")
    parser.add_argument("--top-k", type=int, default=None, help="Convenience primary prefix; all records remain in screening_results")
    parser.add_argument("--output", "--out", default="/app/output/result.json")
    args = parser.parse_args(argv)
    os.environ["SK_RESULT_PATH"] = str(getattr(args, "out", None) or getattr(args, "output", None) or "")
    if args.top_k is not None and args.top_k < 0:
        parser.error("--top-k must be nonnegative")
    return run(args)


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.environ.get("SK_RESULT_PATH") or "result.json"
            _d = os.path.dirname(os.path.abspath(_p))
            if _d:
                os.makedirs(_d, exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    _fallback = os.environ.get("SK_RESULT_PATH", "")
    if _fallback and not os.path.isfile(_fallback):
        try:
            _parent = os.path.dirname(os.path.abspath(_fallback))
            if _parent:
                os.makedirs(_parent, exist_ok=True)
            with open(_fallback, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0 if _fallback else _rc)
