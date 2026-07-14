import pandas as pd
import pdfplumber
import os


def read_excel_raw(path: str) -> dict[str, pd.DataFrame]:
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    return {name: df.fillna("") for name, df in sheets.items()}


def excel_to_text_records(path: str) -> list[dict]:
    sheets = read_excel_raw(path)
    base = os.path.basename(path)
    records = []

    for sheet_name, df in sheets.items():
        rows_data = df.values.tolist()
        if not rows_data:
            continue
        non_empty = [r for r in rows_data if any(cell.strip() for cell in r if isinstance(cell, str))]
        if not non_empty:
            continue
        header_row_idx = _detect_header_row(non_empty)
        if header_row_idx is not None:
            header = non_empty[header_row_idx]
            data_rows = non_empty[header_row_idx + 1:]
        else:
            header = [f"Cột_{i+1}" for i in range(len(non_empty[0]))]
            data_rows = non_empty

        for row_idx, row in enumerate(data_rows):
            parts = []
            for col_idx, cell in enumerate(row):
                cell_str = str(cell).strip()
                if cell_str:
                    col_name = str(header[col_idx]).strip() if col_idx < len(header) else f"Cột_{col_idx+1}"
                    parts.append(f"{col_name}: {cell_str}")
            if parts:
                noi_dung = f"[Sheet: {sheet_name}] " + " | ".join(parts)
                records.append({"noi_dung": noi_dung, "nguon_file": base, "loai": "so_lieu"})

    return records


def _detect_header_row(rows: list[list]) -> int | None:
    for i, row in enumerate(rows):
        text_cells = [str(c).strip() for c in row if isinstance(c, str) and c.strip()]
        if not text_cells:
            continue
        alpha_count = sum(1 for c in text_cells if any(ch.isalpha() for ch in c))
        if alpha_count >= len(text_cells) * 0.5:
            return i
    return None


def read_pdf_text(path: str) -> list[dict]:
    base = os.path.basename(path)
    records = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text and text.strip():
                    records.append({"noi_dung": text.strip(), "nguon_file": base, "loai": "van_ban"})
        if not records:
            print(f"Cảnh báo: PDF '{base}' không có text layer (có thể là scan).")
    except Exception as e:
        print(f"Lỗi đọc PDF '{base}': {e}")
    return records


def extract_file(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return excel_to_text_records(path)
    elif ext == ".pdf":
        return read_pdf_text(path)
    else:
        raise ValueError(f"Không hỗ trợ định dạng '{ext}'. Chỉ chấp nhận .xlsx và .pdf")
