import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import Config


@dataclass
class SheetSchema:
    sheet_name: str
    kind: str
    confidence: float
    header_row_idx: int | None = None
    entity_col: int | None = None
    metric_cols: dict[str, int] = field(default_factory=dict)
    code_col: int | None = None
    value_col: int | None = None
    phone_cols: list[int] = field(default_factory=list)
    status_col: int | None = None
    submitted_at_col: int | None = None
    header: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def norm_text(text: Any) -> str:
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text).strip()


def is_blankish(value: Any) -> bool:
    text = norm_text(value)
    return not text or text in ("nan", "none")


def is_total_row(value: Any) -> bool:
    text = norm_text(value)
    return is_blankish(value) or "tong cong" in text or text.startswith("tong ")


def infer_sheet_schema(sheet_name: str, df: pd.DataFrame, cfg: Config) -> SheetSchema:
    candidates = []
    max_scan = min(len(df), 30)
    for row_idx in range(max_scan):
        header = [str(v).strip() for v in df.iloc[row_idx].tolist()]
        if not any(not is_blankish(v) for v in header):
            continue
        candidates.extend(_score_header_candidate(sheet_name, row_idx, header, df, cfg))

    if not candidates:
        return SheetSchema(sheet_name=sheet_name, kind="unclassified", confidence=0.0)

    candidates.sort(key=lambda s: s.confidence, reverse=True)
    best = candidates[0]
    if best.confidence < 0.55:
        return SheetSchema(
            sheet_name=sheet_name,
            kind="unclassified",
            confidence=best.confidence,
            header_row_idx=best.header_row_idx,
            header=best.header,
            reasons=best.reasons,
        )
    return best


def infer_workbook_schemas(workbook: dict[str, pd.DataFrame], cfg: Config) -> list[SheetSchema]:
    return [infer_sheet_schema(name, df, cfg) for name, df in workbook.items()]


def records_from_workbook(workbook: dict[str, pd.DataFrame], cfg: Config) -> tuple[list[dict], list[SheetSchema]]:
    schemas = infer_workbook_schemas(workbook, cfg)
    records = []
    for schema in schemas:
        if schema.kind == "unclassified":
            continue
        df = workbook[schema.sheet_name]
        if schema.kind == "indicator_wide":
            records.extend(_records_from_indicator_wide(df, schema))
        elif schema.kind == "indicator_long":
            record = _record_from_indicator_long(df, schema)
            if record:
                records.append(record)
        elif schema.kind == "progress":
            records.extend(_records_from_progress(df, schema))
    return records, schemas


def _score_header_candidate(sheet_name: str, row_idx: int, header: list[str], df: pd.DataFrame, cfg: Config) -> list[SheetSchema]:
    schemas = []
    entity_col = _find_entity_col(header)
    metric_cols = _find_metric_cols(header)
    code_col = _find_code_col(header)
    value_col = _find_value_col(header)
    phone_cols = _find_phone_cols(header, cfg)
    status_col = _find_status_col(header)
    submitted_at_col = _find_submitted_at_col(header)

    if entity_col is not None and len(metric_cols) >= 2:
        confidence = min(0.99, 0.55 + len(metric_cols) * 0.03 + _data_rows_score(df, row_idx, entity_col))
        schemas.append(SheetSchema(
            sheet_name=sheet_name,
            kind="indicator_wide",
            confidence=confidence,
            header_row_idx=row_idx,
            entity_col=entity_col,
            metric_cols=metric_cols,
            header=header,
            reasons=[f"có cột đơn vị/thôn và {len(metric_cols)} cột CT"],
        ))

    if code_col is not None and value_col is not None:
        ct_count = _count_ct_values_below(df, row_idx, code_col)
        confidence = min(0.95, 0.58 + ct_count * 0.03)
        schemas.append(SheetSchema(
            sheet_name=sheet_name,
            kind="indicator_long",
            confidence=confidence,
            header_row_idx=row_idx,
            code_col=code_col,
            value_col=value_col,
            header=header,
            reasons=[f"có cột mã chỉ tiêu và số liệu, {ct_count} mã CT"],
        ))

    if entity_col is not None and (phone_cols or status_col is not None or submitted_at_col is not None):
        confidence = 0.62
        if phone_cols:
            confidence += 0.18
        if status_col is not None:
            confidence += 0.08
        if submitted_at_col is not None:
            confidence += 0.08
        schemas.append(SheetSchema(
            sheet_name=sheet_name,
            kind="progress",
            confidence=min(confidence, 0.96),
            header_row_idx=row_idx,
            entity_col=entity_col,
            phone_cols=phone_cols,
            status_col=status_col,
            submitted_at_col=submitted_at_col,
            header=header,
            reasons=["có cột đơn vị/thôn và cột liên hệ/trạng thái"],
        ))

    return schemas


def _find_entity_col(header: list[str]) -> int | None:
    for i, h in enumerate(header):
        h_norm = norm_text(h)
        if h_norm in ("thon", "xa", "don vi", "don vi bao cao", "dia ban"):
            return i
    for i, h in enumerate(header):
        h_norm = norm_text(h)
        if any(term in h_norm for term in ("ten thon", "ten xa", "don vi bao cao")):
            return i
    return None


def _find_metric_cols(header: list[str]) -> dict[str, int]:
    result = {}
    for i, h in enumerate(header):
        match = re.search(r"\b(CT\d{2})\b", str(h), flags=re.IGNORECASE)
        if match:
            result[match.group(1).upper()] = i
    return result


def _find_code_col(header: list[str]) -> int | None:
    for i, h in enumerate(header):
        h_norm = norm_text(h)
        if h_norm in ("ma ct", "ma chi tieu", "ma"):
            return i
    return None


def _find_value_col(header: list[str]) -> int | None:
    for i, h in enumerate(header):
        h_norm = norm_text(h)
        if h_norm in ("so lieu", "gia tri", "value"):
            return i
    return None


def _find_phone_cols(header: list[str], cfg: Config) -> list[int]:
    keywords = [norm_text(k) for k in cfg.phone_header_keywords]
    result = []
    for i, h in enumerate(header):
        h_norm = norm_text(h)
        if any(keyword in h_norm for keyword in keywords):
            result.append(i)
    return result


def _find_status_col(header: list[str]) -> int | None:
    for i, h in enumerate(header):
        h_norm = norm_text(h)
        if "trang thai" in h_norm:
            return i
    return None


def _find_submitted_at_col(header: list[str]) -> int | None:
    for i, h in enumerate(header):
        h_norm = norm_text(h)
        if "thoi diem nop" in h_norm or "ngay nop" in h_norm:
            return i
    return None


def _data_rows_score(df: pd.DataFrame, row_idx: int, entity_col: int) -> float:
    score = 0.0
    sample = df.iloc[row_idx + 1: row_idx + 8]
    for _, row in sample.iterrows():
        if entity_col < len(row) and not is_total_row(row.iloc[entity_col]):
            score += 0.03
    return min(score, 0.12)


def _count_ct_values_below(df: pd.DataFrame, row_idx: int, code_col: int) -> int:
    count = 0
    for _, row in df.iloc[row_idx + 1:].iterrows():
        if code_col < len(row) and re.match(r"CT\d{2}", str(row.iloc[code_col]).strip(), flags=re.IGNORECASE):
            count += 1
    return count


def _records_from_indicator_wide(df: pd.DataFrame, schema: SheetSchema) -> list[dict]:
    records = []
    assert schema.header_row_idx is not None
    assert schema.entity_col is not None
    for _, row in df.iloc[schema.header_row_idx + 1:].iterrows():
        thon_val = str(row.iloc[schema.entity_col]).strip() if schema.entity_col < len(row) else ""
        if is_total_row(thon_val):
            continue
        ct_values = {}
        for code, col_idx in schema.metric_cols.items():
            if col_idx < len(row):
                ct_values[code] = str(row.iloc[col_idx]).strip()
        records.append({
            "thon": thon_val,
            "ct": ct_values,
            "raw": _raw_row(schema.header, row),
            "file": "",
            "sheet": schema.sheet_name,
            "record_type": "indicator",
            "schema_kind": schema.kind,
            "schema_confidence": schema.confidence,
        })
    return records


def _record_from_indicator_long(df: pd.DataFrame, schema: SheetSchema) -> dict | None:
    assert schema.header_row_idx is not None
    assert schema.code_col is not None
    assert schema.value_col is not None
    ct_values = {}
    for _, row in df.iloc[schema.header_row_idx + 1:].iterrows():
        code = str(row.iloc[schema.code_col]).strip() if schema.code_col < len(row) else ""
        val = str(row.iloc[schema.value_col]).strip() if schema.value_col < len(row) else ""
        match = re.match(r"(CT\d{2})", code, flags=re.IGNORECASE)
        if match:
            ct_values[match.group(1).upper()] = val
    if not ct_values:
        return None
    return {
        "thon": _extract_prefill_value(df, schema.header_row_idx, ["thôn", "đơn vị báo cáo"]),
        "ct": ct_values,
        "raw": {},
        "file": "",
        "sheet": schema.sheet_name,
        "record_type": "indicator",
        "schema_kind": schema.kind,
        "schema_confidence": schema.confidence,
    }


def _records_from_progress(df: pd.DataFrame, schema: SheetSchema) -> list[dict]:
    records = []
    assert schema.header_row_idx is not None
    assert schema.entity_col is not None
    for _, row in df.iloc[schema.header_row_idx + 1:].iterrows():
        thon_val = str(row.iloc[schema.entity_col]).strip() if schema.entity_col < len(row) else ""
        if is_total_row(thon_val):
            continue
        raw = _raw_row(schema.header, row)
        phone_fields = {}
        for col_idx in schema.phone_cols:
            if col_idx < len(row):
                phone_fields[schema.header[col_idx]] = str(row.iloc[col_idx]).strip()
        records.append({
            "thon": thon_val,
            "ct": {},
            "raw": raw,
            "phone_fields": phone_fields,
            "file": "",
            "sheet": schema.sheet_name,
            "record_type": "progress",
            "schema_kind": schema.kind,
            "schema_confidence": schema.confidence,
        })
    return records


def _raw_row(header: list[str], row: pd.Series) -> dict[str, str]:
    return {
        str(header[i]): str(row.iloc[i]).strip() if i < len(row) else ""
        for i in range(len(header))
        if str(header[i]).strip()
    }


def _extract_prefill_value(df: pd.DataFrame, header_row_idx: int | None, keywords: list[str]) -> str:
    if header_row_idx is None:
        return ""
    norm_keywords = [norm_text(k) for k in keywords]
    for i in range(0, max(header_row_idx, 0)):
        row = df.iloc[i].astype(str).str.strip().tolist()
        row_text = norm_text(" ".join(row))
        if any(keyword in row_text for keyword in norm_keywords):
            values = [v for v in row if v and not is_blankish(v)]
            if len(values) >= 2:
                return values[1]
    return ""
