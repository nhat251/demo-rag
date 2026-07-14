import re
import math
import pandas as pd
from config import Config
from src.extract import read_excel_raw


LOGIC_RULES = [
    ("CT03", "<=", "CT01", "Số hộ nghèo > tổng số hộ dân"),
    ("CT04", "<=", "CT01", "Số hộ cận nghèo > tổng số hộ dân"),
    ("CT09", "<=", "CT01", "Số hộ GĐVH > tổng số hộ dân"),
    ("CT07", "<=", "CT02", "Trẻ em <16t > tổng nhân khẩu"),
    ("CT08", "<=", "CT07", "Trẻ em khó khăn > tổng trẻ em"),
    ("CT10", "<=", "CT02", "Người trong độ tuổi LĐ > tổng nhân khẩu"),
    ("CT11", "<=", "CT02", "Người BHYT > tổng nhân khẩu"),
]


def _find_header_row(df: pd.DataFrame) -> int:
    for i in range(min(len(df), 20)):
        row = df.iloc[i].astype(str).str.strip().tolist()
        text = " ".join(row)
        ct_count = len(re.findall(r"CT\d{2}", text))
        if ct_count >= 3:
            return i
        if "thôn" in text.lower() and ("stt" in text.lower() or "số điện thoại" in text.lower()):
            return i
    return 0


def find_indicator_columns(header: list) -> dict:
    result = {}
    for i, h in enumerate(header):
        h_str = str(h).strip()
        m = re.search(r"(CT\d{2})", h_str)
        if m:
            code = m.group(1).upper()
            result[code] = i
    return result


def find_thon_column(header: list) -> int | None:
    for i, h in enumerate(header):
        if "thôn" in str(h).strip().lower():
            return i
    return None


def _find_col(header: list, keywords: list) -> int | None:
    for i, h in enumerate(header):
        h_str = str(h).strip().lower()
        if any(kw in h_str for kw in keywords):
            return i
    return None


def normalize_records(workbook: dict[str, pd.DataFrame], cfg: Config) -> list[dict]:
    records = []
    for sheet_name, df in workbook.items():
        if df.empty:
            continue
        header_row_idx = _find_header_row(df)
        header = df.iloc[header_row_idx].astype(str).str.strip().tolist()
        data_df = df.iloc[header_row_idx + 1:]

        indicator_cols = find_indicator_columns(header)
        thon_col = find_thon_column(header)

        if indicator_cols and thon_col is not None:
            for _, row in data_df.iterrows():
                thon_val = str(row.iloc[thon_col]).strip() if thon_col < len(row) else ""
                if not thon_val or thon_val.lower() in ("nan", "tổng cộng", ""):
                    continue
                ct_values = {}
                for code, col_idx in indicator_cols.items():
                    if col_idx < len(row):
                        val = str(row.iloc[col_idx]).strip()
                        ct_values[code] = val
                records.append({
                    "thon": thon_val,
                    "ct": ct_values,
                    "raw": {str(header[i]): str(row.iloc[i]).strip() if i < len(row) else ""
                           for i in range(len(header))},
                    "file": "",
                    "sheet": sheet_name,
                })
        else:
            ma_ct_col = _find_col(header, ["mã ct", "ma ct", "mã chỉ tiêu"])
            so_lieu_col = _find_col(header, ["số liệu", "so lieu", "giá trị"])
            if ma_ct_col is not None and so_lieu_col is not None:
                ct_values = {}
                for _, row in data_df.iterrows():
                    code = str(row.iloc[ma_ct_col]).strip() if ma_ct_col < len(row) else ""
                    val = str(row.iloc[so_lieu_col]).strip() if so_lieu_col < len(row) else ""
                    m = re.match(r"(CT\d{2})", code)
                    if m:
                        ct_values[m.group(1)] = val
                thon_label = ""
                for _, row in data_df.iterrows():
                    t = str(row.iloc[0]).strip() if len(row) > 0 else ""
                    if "thôn" in t.lower():
                        thon_label = t
                        break
                records.append({
                    "thon": thon_label,
                    "ct": ct_values,
                    "raw": {},
                    "file": "",
                    "sheet": sheet_name,
                })
            else:
                thon_col_generic = find_thon_column(header)
                for _, row in data_df.iterrows():
                    thon_val = ""
                    if thon_col_generic is not None and thon_col_generic < len(row):
                        thon_val = str(row.iloc[thon_col_generic]).strip()
                    records.append({
                        "thon": thon_val,
                        "ct": {},
                        "raw": {str(header[i]): str(row.iloc[i]).strip() if i < len(row) else ""
                               for i in range(len(header))},
                        "file": "",
                        "sheet": sheet_name,
                    })
    return records


def _to_float(val: str) -> float | None:
    try:
        return float(val.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def check_missing(records: list, cfg: Config) -> list:
    findings = []
    seen_thon_blanks = set()
    for rec in records:
        if not rec.get("thon"):
            continue
        thon = rec["thon"]
        empty_cts = [code for code, val in rec["ct"].items() if val in ("", "nan", "NaN", "None") or val is None]
        if empty_cts and thon not in seen_thon_blanks:
            seen_thon_blanks.add(thon)
            for code in empty_cts:
                findings.append({
                    "vi_tri": f"Thôn '{thon}', {code}",
                    "loai_loi": "BLANK",
                    "mo_ta": f"Ô số liệu trống tại {code}",
                    "muc_do": "cao",
                })
        has_any = any(v.strip() not in ("", "nan", "NaN", "None") for v in rec["ct"].values() if v)
        if not has_any:
            findings.append({
                "vi_tri": f"Thôn '{thon}'",
                "loai_loi": "CHUA_NOP",
                "mo_ta": f"Thôn '{thon}' chưa nộp (toàn bộ ô trống)",
                "muc_do": "cao",
            })
    return findings


def check_type(records: list, cfg: Config) -> list:
    findings = []
    for rec in records:
        for code, val in rec["ct"].items():
            if val in ("", "nan", "NaN", "None") or val is None:
                continue
            if _to_float(val) is None:
                findings.append({
                    "vi_tri": f"Thôn '{rec['thon']}', {code}",
                    "loai_loi": "TEXT",
                    "mo_ta": f"Giá trị '{val}' không phải số tại cột {code}",
                    "muc_do": "cao",
                })
    return findings


def check_separator(records: list, cfg: Config) -> list:
    findings = []
    pattern = re.compile(cfg.thousand_sep_pattern)
    for rec in records:
        for code, val in rec["ct"].items():
            if val and pattern.match(str(val)):
                cleaned = val.replace(".", "").replace(",", "")
                try:
                    int(cleaned)
                    findings.append({
                        "vi_tri": f"Thôn '{rec['thon']}', {code}",
                        "loai_loi": "SEP",
                        "mo_ta": f"Giá trị '{val}' có dấu phân cách nghìn (không đúng định dạng số thuần)",
                        "muc_do": "vua",
                    })
                except ValueError:
                    pass
    return findings


def is_phone_column(header: str, cfg: Config) -> bool:
    h = header.lower().strip()
    return any(kw in h for kw in cfg.phone_header_keywords)


def check_phone(records: list, cfg: Config) -> list:
    findings = []
    phone_pattern = re.compile(cfg.phone_regex)
    for rec in records:
        raw = rec.get("raw", {})
        for col_name, val in raw.items():
            if is_phone_column(str(col_name), cfg):
                cleaned = val.strip()
                if cleaned and not phone_pattern.match(cleaned):
                    findings.append({
                        "vi_tri": f"Thôn '{rec['thon']}', cột '{col_name}'",
                        "loai_loi": "BADPHONE",
                        "mo_ta": f"Số điện thoại '{cleaned}' không đúng định dạng",
                        "muc_do": "cao",
                    })
        # Also check numeric columns for phone-like values
        for code, val in rec["ct"].items():
            if val and val.strip() and not phone_pattern.match(val.strip()):
                if len(val.strip()) == 7 and val.strip()[0].isalpha():
                    cleaned = val.strip()
                    col_name = code
                    findings.append({
                        "vi_tri": f"Thôn '{rec['thon']}', {code}",
                        "loai_loi": "BADPHONE",
                        "mo_ta": f"Giá trị '{cleaned}' không đúng định dạng số điện thoại",
                        "muc_do": "cao",
                    })
    return findings


def check_outlier(records: list, cfg: Config) -> list:
    findings = []
    grouped = {}
    for rec in records:
        for code, val in rec["ct"].items():
            fval = _to_float(val)
            if fval is not None:
                grouped.setdefault(code, []).append((rec["thon"], fval))
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
            for thon, val in values:
                if val < lower or val > upper:
                    findings.append({
                        "vi_tri": f"Thôn '{thon}', {code}",
                        "loai_loi": "OUTLIER",
                        "mo_ta": f"Giá trị '{val}' bất thường (IQR)",
                        "muc_do": "thap",
                    })
        elif cfg.outlier_method == "zscore":
            mean = sum(nums) / len(nums)
            var = sum((x - mean) ** 2 for x in nums) / len(nums)
            std = math.sqrt(var) if var > 0 else 0
            for thon, val in values:
                if std > 0 and abs(val - mean) / std > cfg.outlier_k:
                    findings.append({
                        "vi_tri": f"Thôn '{thon}', {code}",
                        "loai_loi": "OUTLIER",
                        "mo_ta": f"Giá trị '{val}' bất thường (z-score)",
                        "muc_do": "thap",
                    })
    return findings


def check_logic(records: list, cfg: Config) -> list:
    findings = []
    for rec in records:
        for code_a, op, code_b, desc in LOGIC_RULES:
            val_a = _to_float(rec["ct"].get(code_a, ""))
            val_b = _to_float(rec["ct"].get(code_b, ""))
            if val_a is None or val_b is None:
                continue
            if op == "<=" and val_a > val_b:
                findings.append({
                    "vi_tri": f"Thôn '{rec['thon']}', {code_a}/{code_b}",
                    "loai_loi": "LOGIC",
                    "mo_ta": f"{desc} ({code_a}={val_a}, {code_b}={val_b})",
                    "muc_do": "cao",
                })
    return findings


def validate(path_or_workbook, cfg: Config) -> list:
    wb = read_excel_raw(path_or_workbook) if isinstance(path_or_workbook, str) else path_or_workbook
    records = normalize_records(wb, cfg)

    all_findings = []
    all_findings.extend(check_missing(records, cfg))
    all_findings.extend(check_type(records, cfg))
    all_findings.extend(check_separator(records, cfg))
    all_findings.extend(check_phone(records, cfg))
    all_findings.extend(check_outlier(records, cfg))
    all_findings.extend(check_logic(records, cfg))

    seen = set()
    unique = []
    for f in all_findings:
        key = (f["vi_tri"], f["loai_loi"])
        if key not in seen:
            seen.add(key)
            unique.append(f)

    severity_order = {"cao": 0, "vua": 1, "thap": 2}
    unique.sort(key=lambda x: severity_order.get(x["muc_do"], 9))

    return unique


def summarize_with_ai(findings: list, cfg: Config) -> str:
    if not cfg.ai_explain or not findings:
        return ""

    counts = {}
    for f in findings:
        loai = f["loai_loi"]
        counts[loai] = counts.get(loai, 0) + 1

    summary_parts = [f"Tìm thấy {len(findings)} vấn đề:"]
    for loai, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        severity = next((f["muc_do"] for f in findings if f["loai_loi"] == loai), "thap")
        summary_parts.append(f"- {loai} ({cnt} lỗi, mức {severity})")

    return "\n".join(summary_parts)
