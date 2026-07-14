import pandas as pd

from config import Config
from src.ai_validator import ai_audit_findings
from src.extract import read_excel_raw
from src.schema_infer import SheetSchema, records_from_workbook
from src.validation_rules import VALIDATION_RULES


def normalize_records(workbook: dict[str, pd.DataFrame], cfg: Config) -> list[dict]:
    records, _schemas = records_from_workbook(workbook, cfg)
    return records


def infer_schemas(path_or_workbook, cfg: Config) -> list[SheetSchema]:
    workbook = read_excel_raw(path_or_workbook) if isinstance(path_or_workbook, str) else path_or_workbook
    _records, schemas = records_from_workbook(workbook, cfg)
    return schemas


def validate(path_or_workbook, cfg: Config) -> list[dict]:
    workbook = read_excel_raw(path_or_workbook) if isinstance(path_or_workbook, str) else path_or_workbook
    records, schemas = records_from_workbook(workbook, cfg)

    all_findings = []
    for rule in VALIDATION_RULES:
        for finding in rule.check(records, cfg):
            finding.setdefault("rule_id", rule.rule_id)
            all_findings.append(finding)

    all_findings.extend(ai_audit_findings(records, all_findings, cfg))

    unique = _dedupe_findings(all_findings)
    _attach_schema_context(unique, records, schemas)

    severity_order = {"cao": 0, "vua": 1, "thap": 2}
    unique.sort(key=lambda item: severity_order.get(item["muc_do"], 9))
    return unique


def _dedupe_findings(findings: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for finding in findings:
        key = (finding.get("vi_tri"), finding.get("loai_loi"), finding.get("rule_id"))
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def _attach_schema_context(findings: list[dict], records: list[dict], schemas: list[SheetSchema]) -> None:
    schema_by_sheet = {schema.sheet_name: schema for schema in schemas}
    for finding in findings:
        sheet = finding.get("sheet", "")
        matched_record = None
        if sheet:
            matched_record = next(
                (
                    r for r in records
                    if r.get("sheet") == sheet and r.get("thon") and r["thon"] in finding.get("vi_tri", "")
                ),
                None,
            )
        if not matched_record:
            matched_record = next((r for r in records if r.get("thon") and r["thon"] in finding.get("vi_tri", "")), None)
        if not matched_record and not sheet:
            continue
        sheet = sheet or matched_record.get("sheet", "")
        schema = schema_by_sheet.get(sheet)
        finding.setdefault("sheet", sheet)
        if matched_record:
            finding.setdefault("schema_kind", matched_record.get("schema_kind", ""))
            finding.setdefault("schema_confidence", round(float(matched_record.get("schema_confidence", 0.0)), 3))
        if schema:
            finding.setdefault("schema_reason", "; ".join(schema.reasons))


def summarize_with_ai(findings: list[dict], cfg: Config) -> str:
    if not cfg.ai_explain or not findings:
        return ""

    counts = {}
    for finding in findings:
        loai = finding["loai_loi"]
        counts[loai] = counts.get(loai, 0) + 1

    summary_parts = [f"Tìm thấy {len(findings)} vấn đề:"]
    for loai, count in sorted(counts.items(), key=lambda x: -x[1]):
        severity = next((f["muc_do"] for f in findings if f["loai_loi"] == loai), "thap")
        summary_parts.append(f"- {loai} ({count} lỗi, mức {severity})")

    return "\n".join(summary_parts)
