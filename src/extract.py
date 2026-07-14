import os
import re

import pandas as pd
import pdfplumber


def read_excel_raw(path: str) -> dict[str, pd.DataFrame]:
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    return {name: df.fillna("") for name, df in sheets.items()}


def excel_to_text_records(path: str) -> list[dict]:
    sheets = read_excel_raw(path)
    base = os.path.basename(path)
    records = []

    for sheet_name, df in sheets.items():
        df = _trim_empty_edges(df)
        if df.empty:
            continue

        non_empty = [
            (idx, [_clean_cell(cell) for cell in row])
            for idx, row in df.iterrows()
            if any(_clean_cell(cell) for cell in row)
        ]
        if not non_empty:
            continue

        sheet_context = _sheet_context(non_empty)
        header_pos = _detect_header_row([row for _, row in non_empty])

        if sheet_context:
            records.append({
                "noi_dung": f"File: {base} | Sheet: {sheet_name} | " + " | ".join(sheet_context),
                "nguon_file": base,
                "loai": "metadata",
                "sheet": sheet_name,
                "row": 0,
            })

        if header_pos is not None:
            header_excel_idx, header = non_empty[header_pos]
            data_rows = non_empty[header_pos + 1:]
        else:
            header_excel_idx = -1
            header = [f"Cột {i + 1}" for i in range(len(non_empty[0][1]))]
            data_rows = non_empty

        headers = [_clean_cell(h) or f"Cột {i + 1}" for i, h in enumerate(header)]
        for excel_idx, row in data_rows:
            if excel_idx == header_excel_idx or _looks_like_section_title(row):
                continue

            parts = [f"File: {base}", f"Sheet: {sheet_name}", f"Dòng Excel: {excel_idx + 1}"]
            parts.extend(sheet_context)

            for col_idx, cell in enumerate(row):
                cell_str = _clean_cell(cell)
                if not cell_str:
                    continue

                col_name = headers[col_idx] if col_idx < len(headers) else f"Cột {col_idx + 1}"
                parts.append(f"{col_name}: {cell_str}")

            if len(parts) > 3 + len(sheet_context):
                records.append({
                    "noi_dung": " | ".join(parts),
                    "nguon_file": base,
                    "loai": "so_lieu",
                    "sheet": sheet_name,
                    "row": excel_idx + 1,
                })

    return records


def _detect_header_row(rows: list[list]) -> int | None:
    for i, row in enumerate(rows):
        text_cells = [str(c).strip() for c in row if str(c).strip()]
        if len(text_cells) < 2:
            continue

        text = " ".join(text_cells).lower()
        ct_count = len(re.findall(r"\bct\d{2}\b", text, flags=re.IGNORECASE))
        table_keywords = ("stt", "thôn", "mã ct", "tên chỉ tiêu", "số liệu", "chỉ số", "giá trị")
        keyword_count = sum(1 for kw in table_keywords if kw in text)
        if ct_count >= 2 or keyword_count >= 2:
            return i
    return None


def _trim_empty_edges(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    mask_rows = df.apply(lambda row: any(_clean_cell(v) for v in row), axis=1)
    mask_cols = df.apply(lambda col: any(_clean_cell(v) for v in col), axis=0)
    if not mask_rows.any() or not mask_cols.any():
        return pd.DataFrame()

    return df.loc[mask_rows, mask_cols]


def _clean_cell(value) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def _sheet_context(non_empty: list[tuple[int, list[str]]]) -> list[str]:
    context = []
    for _, row in non_empty[:12]:
        cells = [_clean_cell(c) for c in row if _clean_cell(c)]
        if len(cells) >= 2 and cells[0].endswith(":"):
            context.append(f"{cells[0]} {cells[1]}")
        elif len(cells) == 1 and (
            "kỳ báo cáo" in cells[0].lower()
            or "hạn nộp" in cells[0].lower()
            or "thời điểm tổng hợp" in cells[0].lower()
        ):
            context.append(cells[0])
    return context


def _looks_like_section_title(row: list[str]) -> bool:
    filled = [c for c in row if c.strip()]
    if len(filled) != 1:
        return False
    text = filled[0]
    return len(text) > 20 and not re.search(r"\d", text)


def read_pdf_text(path: str) -> list[dict]:
    base = os.path.basename(path)
    records = []
    try:
        with pdfplumber.open(path) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                if text and text.strip():
                    records.append({
                        "noi_dung": f"File: {base} | Trang: {page_idx}\n{text.strip()}",
                        "nguon_file": base,
                        "loai": "van_ban",
                        "page": page_idx,
                    })
        if not records:
            print(f"Cảnh báo: PDF '{base}' không có text layer (có thể là scan).")
    except Exception as e:
        print(f"Lỗi đọc PDF '{base}': {e}")
    return records


def extract_file(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return excel_to_text_records(path)
    if ext == ".pdf":
        return read_pdf_text(path)
    raise ValueError(f"Không hỗ trợ định dạng '{ext}'. Chỉ chấp nhận .xlsx và .pdf")
