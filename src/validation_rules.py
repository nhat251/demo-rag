import math
import re
from dataclasses import dataclass
from typing import Callable

from config import Config
from src.schema_infer import norm_text


LOGIC_RULES = [
    ("CT03", "<=", "CT01", "Số hộ nghèo > tổng số hộ dân"),
    ("CT04", "<=", "CT01", "Số hộ cận nghèo > tổng số hộ dân"),
    ("CT09", "<=", "CT01", "Số hộ GĐVH > tổng số hộ dân"),
    ("CT07", "<=", "CT02", "Trẻ em <16t > tổng nhân khẩu"),
    ("CT08", "<=", "CT07", "Trẻ em khó khăn > tổng trẻ em"),
    ("CT10", "<=", "CT02", "Người trong độ tuổi LĐ > tổng nhân khẩu"),
    ("CT11", "<=", "CT02", "Người BHYT > tổng nhân khẩu"),
]


@dataclass(frozen=True)
class ValidationRule:
    rule_id: str
    description: str
    severity: str
    check: Callable[[list[dict], Config], list[dict]]


def is_phone_column(header: str, cfg: Config) -> bool:
    h = norm_text(header)
    return any(norm_text(kw) in h for kw in cfg.phone_header_keywords)


def is_blank_value(val: str | None) -> bool:
    return val is None or str(val).strip() in ("", "nan", "NaN", "None")


def to_float(val: str) -> float | None:
    if is_thousand_separator_value(val):
        return None
    try:
        return float(str(val).replace(",", "."))
    except (ValueError, AttributeError):
        return None


def is_thousand_separator_value(val: str) -> bool:
    return bool(re.match(r"^\d{1,3}([.,]\d{3})+$", str(val).strip()))


def finding_context(rec: dict) -> dict:
    return {
        "sheet": rec.get("sheet", ""),
        "schema_kind": rec.get("schema_kind", ""),
        "schema_confidence": round(float(rec.get("schema_confidence", 0.0)), 3),
    }


def check_missing(records: list[dict], cfg: Config) -> list[dict]:
    findings = []
    seen_thon_blanks = set()
    for rec in records:
        if rec.get("record_type") != "indicator" or not rec.get("thon"):
            continue
        thon = rec["thon"]
        ct_values = rec.get("ct", {})
        has_any = any(not is_blank_value(v) for v in ct_values.values())
        if not has_any:
            findings.append({
                "vi_tri": f"Thôn '{thon}'",
                "loai_loi": "CHUA_NOP",
                "mo_ta": f"Thôn '{thon}' chưa nộp (toàn bộ ô trống)",
                "muc_do": "cao",
                **finding_context(rec),
            })
            continue

        empty_cts = [code for code, val in ct_values.items() if is_blank_value(val)]
        if empty_cts and thon not in seen_thon_blanks:
            seen_thon_blanks.add(thon)
            for code in empty_cts:
                findings.append({
                    "vi_tri": f"Thôn '{thon}', {code}",
                    "loai_loi": "BLANK",
                    "mo_ta": f"Ô số liệu trống tại {code}",
                    "muc_do": "cao",
                    **finding_context(rec),
                })
    return findings


def check_type(records: list[dict], cfg: Config) -> list[dict]:
    findings = []
    for rec in records:
        if rec.get("record_type") != "indicator":
            continue
        for code, val in rec["ct"].items():
            if is_blank_value(val):
                continue
            if is_thousand_separator_value(val):
                continue
            if to_float(val) is None:
                findings.append({
                    "vi_tri": f"Thôn '{rec['thon']}', {code}",
                    "loai_loi": "TEXT",
                    "mo_ta": f"Giá trị '{val}' không phải số tại cột {code}",
                    "muc_do": "cao",
                    **finding_context(rec),
                })
    return findings


def check_separator(records: list[dict], cfg: Config) -> list[dict]:
    findings = []
    pattern = re.compile(cfg.thousand_sep_pattern)
    for rec in records:
        if rec.get("record_type") != "indicator":
            continue
        for code, val in rec["ct"].items():
            if val and pattern.match(str(val).strip()):
                findings.append({
                    "vi_tri": f"Thôn '{rec['thon']}', {code}",
                    "loai_loi": "SEP",
                    "mo_ta": f"Giá trị '{val}' có dấu phân cách nghìn (không đúng định dạng số thuần)",
                    "muc_do": "vua",
                    **finding_context(rec),
                })
    return findings


def check_phone(records: list[dict], cfg: Config) -> list[dict]:
    findings = []
    phone_pattern = re.compile(cfg.phone_regex)
    for rec in records:
        phone_fields = rec.get("phone_fields") or {
            col_name: val
            for col_name, val in rec.get("raw", {}).items()
            if is_phone_column(str(col_name), cfg)
        }
        for col_name, val in phone_fields.items():
            cleaned = str(val).strip()
            if cleaned and norm_text(cleaned) not in ("nan", "none") and not phone_pattern.match(cleaned):
                findings.append({
                    "vi_tri": f"Thôn '{rec['thon']}', cột '{col_name}'",
                    "loai_loi": "BADPHONE",
                    "mo_ta": f"Số điện thoại '{cleaned}' không đúng định dạng",
                    "muc_do": "cao",
                    **finding_context(rec),
                })
    return findings


def check_outlier(records: list[dict], cfg: Config) -> list[dict]:
    findings = []
    grouped = {}
    for rec in records:
        if rec.get("record_type") != "indicator":
            continue
        for code, val in rec["ct"].items():
            fval = to_float(val)
            if fval is not None:
                grouped.setdefault(code, []).append((rec, fval))

    for code, values in grouped.items():
        nums = [v[1] for v in values]
        if len(nums) < 3:
            continue
        if cfg.outlier_method == "iqr":
            sorted_nums = sorted(nums)
            q1 = sorted_nums[len(sorted_nums) // 4]
            q3 = sorted_nums[3 * len(sorted_nums) // 4]
            iqr = q3 - q1
            lower = q1 - cfg.outlier_k * iqr
            upper = q3 + cfg.outlier_k * iqr
            for rec, val in values:
                if val < lower or val > upper:
                    findings.append({
                        "vi_tri": f"Thôn '{rec['thon']}', {code}",
                        "loai_loi": "OUTLIER",
                        "mo_ta": f"Giá trị '{val}' bất thường (IQR)",
                        "muc_do": "thap",
                        **finding_context(rec),
                    })
        elif cfg.outlier_method == "zscore":
            mean = sum(nums) / len(nums)
            var = sum((x - mean) ** 2 for x in nums) / len(nums)
            std = math.sqrt(var) if var > 0 else 0
            for rec, val in values:
                if std > 0 and abs(val - mean) / std > cfg.outlier_k:
                    findings.append({
                        "vi_tri": f"Thôn '{rec['thon']}', {code}",
                        "loai_loi": "OUTLIER",
                        "mo_ta": f"Giá trị '{val}' bất thường (z-score)",
                        "muc_do": "thap",
                        **finding_context(rec),
                    })
    return findings


def check_logic(records: list[dict], cfg: Config) -> list[dict]:
    findings = []
    for rec in records:
        if rec.get("record_type") != "indicator":
            continue
        for code_a, op, code_b, desc in LOGIC_RULES:
            val_a = to_float(rec["ct"].get(code_a, ""))
            val_b = to_float(rec["ct"].get(code_b, ""))
            if val_a is None or val_b is None:
                continue
            if op == "<=" and val_a > val_b:
                findings.append({
                    "vi_tri": f"Thôn '{rec['thon']}', {code_a}/{code_b}",
                    "loai_loi": "LOGIC",
                    "mo_ta": f"{desc} ({code_a}={val_a}, {code_b}={val_b})",
                    "muc_do": "cao",
                    **finding_context(rec),
                })
    return findings


VALIDATION_RULES = [
    ValidationRule(
        rule_id="CHUA_NOP_BLANK",
        description="Phát hiện thôn chưa nộp hoặc ô chỉ tiêu bị trống.",
        severity="cao",
        check=check_missing,
    ),
    ValidationRule(
        rule_id="NUMERIC_TEXT",
        description="Phát hiện chữ trong trường số liệu chỉ tiêu.",
        severity="cao",
        check=check_type,
    ),
    ValidationRule(
        rule_id="THOUSAND_SEPARATOR",
        description="Phát hiện dấu phân cách nghìn trong trường cần số thuần.",
        severity="vua",
        check=check_separator,
    ),
    ValidationRule(
        rule_id="BAD_PHONE",
        description="Phát hiện số điện thoại/SĐT sai định dạng.",
        severity="cao",
        check=check_phone,
    ),
    ValidationRule(
        rule_id="OUTLIER",
        description="Phát hiện số liệu bất thường theo thống kê.",
        severity="thap",
        check=check_outlier,
    ),
    ValidationRule(
        rule_id="CROSS_FIELD_LOGIC",
        description="Phát hiện mâu thuẫn logic giữa các chỉ tiêu.",
        severity="cao",
        check=check_logic,
    ),
]
